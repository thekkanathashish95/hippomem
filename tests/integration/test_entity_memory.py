"""
Integration tests for EntityExtractor (via MemoryEncoder) and enrich_entity_profiles().
"""
from unittest.mock import MagicMock

from hippomem.encoder.updater import MemoryEncoder
from hippomem.memory.episodic.llm_ops import EpisodicLLMOps
from hippomem.memory.entity.llm_ops import EntityLLMOps
from hippomem.memory.entity.schemas import EntityExtractionResult, ExtractedEntity
from hippomem.consolidator.service import enrich_entity_profiles
from hippomem.consolidator.llm_ops import ConsolidationLLMOps
from hippomem.models.engram import Engram, EngramKind
from hippomem.models.engram_link import EngramLink, LinkKind
from hippomem.config import MemoryConfig


def test_encode_creates_entity_engram_for_new_entity(db, mock_llm, mock_embeddings, vector_dir):
    """enable_entity_extraction=True, LLM extracts one entity, Engram with kind=entity created."""
    config = MemoryConfig(
        vector_dir=str(vector_dir),
        max_active_events=3,
        max_dormant_events=3,
    )

    episode = Engram(
        user_id="user1",
        engram_id="ep1",
        core_intent="discussed Alice",
        updates=[],
        relevance_score=1.0,
    )
    db.add(episode)
    db.commit()

    episodic_llm = MagicMock(spec=EpisodicLLMOps)
    episodic_llm.detect_drift.return_value = ("update_existing", "no drift")
    episodic_llm.extract_event_update.return_value = [{"add_update": False}]

    entity_llm = MagicMock(spec=EntityLLMOps)
    entity_llm.extract_entities.return_value = EntityExtractionResult(
        entities=[
            ExtractedEntity(
                canonical_name="Alice",
                entity_type="person",
                mention_type="protagonist",
                facts=["works at Acme"],
                significant=True,
            ),
        ]
    )

    encoder = MemoryEncoder(
        episodic_llm,
        mock_embeddings,
        config=config,
        entity_llm_ops=entity_llm,
    )

    encoder.update(
        "user1",
        "session1",
        [("I met Alice at Acme", "Nice")],
        db,
        used_engram_ids=["ep1"],
    )

    entity = db.query(Engram).filter(
        Engram.user_id == "user1",
        Engram.engram_kind == EngramKind.ENTITY.value,
    ).first()
    assert entity is not None
    assert entity.core_intent == "Alice"
    assert entity.entity_type == "person"
    # encoder writes new facts to pending_facts; updates is the consolidated baseline (empty until consolidation runs)
    assert "works at Acme" in (entity.pending_facts or [])


def test_encode_reuses_existing_entity_above_similarity_threshold(
    db, mock_embeddings, vector_dir, faiss_svc
):
    """Exact name match in DB → existing entity node reused, facts appended."""
    config = MemoryConfig(
        vector_dir=str(vector_dir),
        max_active_events=3,
        max_dormant_events=3,
    )

    entity_uuid = "entity-alice-001"
    entity = Engram(
        user_id="user1",
        engram_id=entity_uuid,
        engram_kind=EngramKind.ENTITY.value,
        entity_type="person",
        core_intent="Alice",
        updates=["original fact"],
        relevance_score=1.0,
    )
    db.add(entity)

    episode = Engram(
        user_id="user1",
        engram_id="ep1",
        core_intent="discussed Alice",
        relevance_score=1.0,
    )
    db.add(episode)
    db.commit()

    index = faiss_svc.get_or_create_index("user1")
    vec = mock_embeddings.embed("Alice")
    faiss_svc.add_vector(entity_uuid, vec, index)
    faiss_svc.save_index("user1", index)

    episodic_llm = MagicMock(spec=EpisodicLLMOps)
    episodic_llm.detect_drift.return_value = ("update_existing", "no drift")
    episodic_llm.extract_event_update.return_value = [{"add_update": False}]

    entity_llm = MagicMock(spec=EntityLLMOps)
    entity_llm.extract_entities.return_value = EntityExtractionResult(
        entities=[
            ExtractedEntity(
                canonical_name="Alice",
                entity_type="person",
                mention_type="protagonist",
                facts=["new fact from second mention"],
                significant=True,
            ),
        ]
    )

    encoder = MemoryEncoder(
        episodic_llm,
        mock_embeddings,
        config=config,
        entity_llm_ops=entity_llm,
    )

    encoder.update(
        "user1",
        "session1",
        [("Alice told me more", "OK")],
        db,
        used_engram_ids=["ep1"],
    )

    entities = db.query(Engram).filter(
        Engram.user_id == "user1",
        Engram.engram_kind == EngramKind.ENTITY.value,
    ).all()
    assert len(entities) == 1
    # original fact stays in consolidated updates; new fact goes to pending_facts
    assert "original fact" in (entities[0].updates or [])
    assert "new fact from second mention" in (entities[0].pending_facts or [])


def test_encode_creates_mention_link_to_episode(db, mock_embeddings, vector_dir):
    """Entity extracted → EngramLink with link_kind=MENTION created between episode and entity."""
    config = MemoryConfig(
        vector_dir=str(vector_dir),
        max_active_events=3,
        max_dormant_events=3,
    )

    episode = Engram(
        user_id="user1",
        engram_id="ep1",
        core_intent="discussed Bob",
        relevance_score=1.0,
    )
    db.add(episode)
    db.commit()

    episodic_llm = MagicMock(spec=EpisodicLLMOps)
    episodic_llm.detect_drift.return_value = ("update_existing", "no drift")
    episodic_llm.extract_event_update.return_value = [{"add_update": False}]

    entity_llm = MagicMock(spec=EntityLLMOps)
    entity_llm.extract_entities.return_value = EntityExtractionResult(
        entities=[
            ExtractedEntity(
                canonical_name="Bob",
                entity_type="person",
                mention_type="subject",
                facts=[],
                significant=True,
            ),
        ]
    )

    encoder = MemoryEncoder(
        episodic_llm,
        mock_embeddings,
        config=config,
        entity_llm_ops=entity_llm,
    )

    encoder.update(
        "user1",
        "session1",
        [("Bob is my friend", "Nice")],
        db,
        used_engram_ids=["ep1"],
    )

    entity = db.query(Engram).filter(
        Engram.user_id == "user1",
        Engram.engram_kind == EngramKind.ENTITY.value,
    ).first()
    assert entity is not None

    link = db.query(EngramLink).filter(
        EngramLink.user_id == "user1",
        EngramLink.source_id == "ep1",
        EngramLink.target_id == entity.engram_id,
        EngramLink.link_kind == LinkKind.MENTION.value,
    ).first()
    assert link is not None
    assert link.mention_type == "subject"


def test_encode_entity_increments_reinforcement_count(db, mock_embeddings, vector_dir, faiss_svc):
    """Second mention of same entity (exact name match) → reinforcement_count goes from 1 to 2."""
    config = MemoryConfig(
        vector_dir=str(vector_dir),
        max_active_events=3,
        max_dormant_events=3,
    )

    entity_uuid = "entity-charlie-001"
    entity = Engram(
        user_id="user1",
        engram_id=entity_uuid,
        engram_kind=EngramKind.ENTITY.value,
        entity_type="person",
        core_intent="Charlie",
        updates=[],
        reinforcement_count=1,
        relevance_score=1.0,
    )
    db.add(entity)

    episode = Engram(
        user_id="user1",
        engram_id="ep1",
        core_intent="discussed Charlie",
        relevance_score=1.0,
    )
    db.add(episode)
    db.commit()

    index = faiss_svc.get_or_create_index("user1")
    vec = mock_embeddings.embed("Charlie")
    faiss_svc.add_vector(entity_uuid, vec, index)
    faiss_svc.save_index("user1", index)

    episodic_llm = MagicMock(spec=EpisodicLLMOps)
    episodic_llm.detect_drift.return_value = ("update_existing", "no drift")
    episodic_llm.extract_event_update.return_value = [{"add_update": False}]

    entity_llm = MagicMock(spec=EntityLLMOps)
    entity_llm.extract_entities.return_value = EntityExtractionResult(
        entities=[
            ExtractedEntity(
                canonical_name="Charlie",
                entity_type="person",
                mention_type="referenced",
                facts=["second mention"],
                significant=True,
            ),
        ]
    )

    encoder = MemoryEncoder(
        episodic_llm,
        mock_embeddings,
        config=config,
        entity_llm_ops=entity_llm,
    )

    encoder.update(
        "user1",
        "session1",
        [("Charlie again", "OK")],
        db,
        used_engram_ids=["ep1"],
    )

    db.refresh(entity)
    assert entity.reinforcement_count == 2


def test_enrich_entity_profiles_generates_summary_text(db, mock_llm, mock_embeddings, vector_dir):
    """Entity Engram without summary_text → update_entity_profile LLM called → summary_text populated."""
    entity = Engram(
        user_id="user1",
        engram_id="ent1",
        engram_kind=EngramKind.ENTITY.value,
        entity_type="person",
        core_intent="Diana",
        updates=["fact1"],
        pending_facts=["fact2"],
        needs_consolidation=True,
        summary_text=None,
        relevance_score=1.0,
    )
    db.add(entity)
    db.commit()

    mock_llm.chat_structured.return_value = MagicMock(
        merged_facts=["fact1", "fact2"],
        summary_text="Diana is a person with several known facts.",
    )

    llm_ops = ConsolidationLLMOps(mock_llm)
    count = enrich_entity_profiles(
        user_id="user1",
        db=db,
        llm_ops=llm_ops,
        embedding_service=mock_embeddings,
        vector_dir=str(vector_dir),
    )

    assert count == 1
    db.refresh(entity)
    assert entity.summary_text == "Diana is a person with several known facts."


def test_enrich_entity_profiles_skips_already_enriched(db, mock_llm, mock_embeddings, vector_dir):
    """Entity enriched after last update → LLM not called again."""
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    # updated_at before last_enriched_at (last_decay) → skip enrichment
    updated_earlier = now - timedelta(minutes=5)
    last_enriched = now - timedelta(minutes=1)
    entity = Engram(
        user_id="user1",
        engram_id="ent1",
        engram_kind=EngramKind.ENTITY.value,
        entity_type="person",
        core_intent="Eve",
        updates=["fact1"],
        summary_text="Already enriched",
        relevance_score=1.0,
        last_decay_applied_at=last_enriched,
        updated_at=updated_earlier,
    )
    db.add(entity)
    db.commit()

    mock_llm.chat_structured.return_value = MagicMock(
        merged_facts=["fact1"],
        summary_text="Would overwrite",
    )

    llm_ops = ConsolidationLLMOps(mock_llm)
    count = enrich_entity_profiles(
        user_id="user1",
        db=db,
        llm_ops=llm_ops,
        embedding_service=mock_embeddings,
        vector_dir=str(vector_dir),
    )

    assert count == 0
    db.refresh(entity)
    assert entity.summary_text == "Already enriched"
