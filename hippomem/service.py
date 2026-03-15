"""
MemoryService - Public API for hippomem.

Three-line integration:
    memory = MemoryService(llm_api_key="sk-...")
    context = await memory.decode(user_id, message)
    await memory.encode(user_id, message, response, context)
"""
import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Dict, Any, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from hippomem.infra.call_collector import LLMCallCollector

from sqlalchemy.orm import Session

from hippomem.config import MemoryConfig
from hippomem.db.base import Base
from hippomem.db.session import create_db_engine, create_session_factory, get_db_session
from hippomem.infra.llm import LLMService
from hippomem.infra.embeddings import EmbeddingService
from hippomem.memory.episodic.llm_ops import EpisodicLLMOps
from hippomem.decoder.synthesizer import ContextSynthesizer
from hippomem.decoder.schemas import DecodeResult
from hippomem.retrieve.service import RetrieveService
from hippomem.retrieve.schemas import RetrieveResult
from hippomem.encoder.updater import MemoryEncoder
from hippomem.memory.entity.llm_ops import EntityLLMOps
from hippomem.memory.self.extractor import SelfExtractor
from hippomem.memory.self.llm_ops import SelfLLMOps
from hippomem.consolidator import BackgroundConsolidationTask, ConsolidationService, ConsolidationConfig
from hippomem.consolidator.llm_ops import ConsolidationLLMOps
from hippomem.models.working_state import WorkingState  # noqa: F401 — registers table
from hippomem.models.engram import Engram  # noqa: F401 — registers table
from hippomem.models.engram_link import EngramLink  # noqa: F401 — registers table
from hippomem.models.trace import Trace  # noqa: F401 — registers table
from hippomem.models.self_trait import SelfTrait  # noqa: F401 — registers table
from hippomem.models.turn_status import TurnStatus  # noqa: F401 — registers table
from hippomem.models.conversation_turn import ConversationTurn
from hippomem.models.conversation_turn_engram import ConversationTurnEngram
from hippomem import explorer, sessions

logger = logging.getLogger(__name__)

_DECODE_CACHE_MAX = 500  # max (user_id, session_id) entries; oldest evicted when exceeded


class MemoryService:
    """
    Brain-inspired persistent memory for LLM chat applications.

    Quick start::

        memory = MemoryService(llm_api_key="sk-...")
        async with memory:
            result = await memory.decode("user_123", "What was I working on?")
            response = await your_llm(result.context + user_message)
            await memory.encode("user_123", user_message, response, result)

    Or explicit setup/close::

        memory = MemoryService(llm_api_key="sk-...")
        await memory.setup()
        # ... use memory ...
        await memory.close()
    """

    def __init__(
        self,
        llm_api_key: str,
        llm_base_url: str,
        llm_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        config: Optional[MemoryConfig] = None,
    ) -> None:
        """
        Args:
            llm_api_key: API key for your LLM provider (OpenAI-compatible).
            llm_base_url: Base URL for your LLM provider (default: OpenAI).
            llm_model: Model name override (default: from config).
            embedding_model: Embedding model name override (default: from config).
            config: MemoryConfig instance to override any defaults.
        """
        self.config = config or MemoryConfig()
        if llm_model:
            self.config.llm_model = llm_model
        if embedding_model:
            self.config.embedding_model = embedding_model

        self._llm_svc = LLMService(
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=self.config.llm_model,
            max_retries=self.config.llm_max_retries,
            retry_delay=self.config.llm_retry_delay,
            timeout=self.config.llm_timeout,
        )
        self._emb_svc = EmbeddingService(
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=self.config.embedding_model,
        )
        self._episodic_llm = EpisodicLLMOps(self._llm_svc)
        self._synthesizer = ContextSynthesizer(
            llm_service=self._llm_svc,
            embedding_service=self._emb_svc,
            config=self.config,
        )
        self._retrieve_svc = RetrieveService(
            embedding_service=self._emb_svc,
            config=self.config,
        )
        _entity_llm_ops: Optional[EntityLLMOps] = None
        if self.config.enable_entity_extraction:
            _entity_llm_ops = EntityLLMOps(self._llm_svc)
        _self_extractor: Optional[SelfExtractor] = None
        if self.config.enable_self_memory:
            _self_extractor = SelfExtractor(llm_ops=SelfLLMOps(self._llm_svc))
        self._updater = MemoryEncoder(
            llm_ops=self._episodic_llm,
            embedding_service=self._emb_svc,
            config=self.config,
            entity_llm_ops=_entity_llm_ops,
            self_extractor=_self_extractor,
        )
        logger.info(
            "MemoryService init: entity_extraction=%s self_memory=%s bg_consolidation=%s",
            self.config.enable_entity_extraction,
            self.config.enable_self_memory,
            self.config.enable_background_consolidation,
        )

        self._engine = None
        self._session_factory = None
        self._bg_consolidation: Optional[BackgroundConsolidationTask] = None
        # Tracks fire-and-forget encode tasks so they are not garbage-collected
        # before completion (asyncio drops unreferenced tasks).
        self._background_tasks: Set[asyncio.Task] = set()
        # Maps (user_id, session_id) → (turn_id, used_engram_ids) for Tier 2 resolution.
        # Bounded to _DECODE_CACHE_MAX entries; oldest key evicted on overflow.
        self._last_decode_cache: OrderedDict[Tuple[str, Optional[str]], Tuple[str, List[str]]] = OrderedDict()

    def update_llm_config(
        self,
        api_key: str,
        base_url: str,
        llm_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
    ) -> None:
        """
        Update LLM/embedding credentials and models in place (warm reload).
        Call when llm_api_key, llm_base_url, llm_model, or embedding_model change.
        """
        self._llm_svc.api_key = api_key
        self._llm_svc.base_url = base_url.rstrip("/")
        if llm_model is not None:
            self.config.llm_model = llm_model
            self._llm_svc.model = llm_model
        if embedding_model is not None:
            self.config.embedding_model = embedding_model
            self._emb_svc.model = embedding_model
        self._emb_svc.api_key = api_key
        self._emb_svc.base_url = base_url.rstrip("/")

    def update_feature_flags(self) -> None:
        """
        Re-sync all runtime sub-components that hold copies of MemoryConfig values.
        Call after any hot-field patch so changes take effect immediately.

        Covers:
        - entity_llm_ops / self_extractor on the encoder
        - ConsolidationService inside MemoryEncoder (recreated from current config)
        - BackgroundConsolidationTask cached flag scalars (if task is running)
        """
        # ── encoder feature objects ───────────────────────────────────────────
        if self.config.enable_entity_extraction:
            if self._updater.entity_llm_ops is None:
                self._updater.entity_llm_ops = EntityLLMOps(self._llm_svc)
        else:
            self._updater.entity_llm_ops = None

        if self.config.enable_self_memory:
            if self._updater.self_extractor is None:
                self._updater.self_extractor = SelfExtractor(llm_ops=SelfLLMOps(self._llm_svc))
        else:
            self._updater.self_extractor = None

        # ── Recreate ConsolidationService from current config ─────────────────
        self._updater.consolidation = self._get_consolidation_svc()

        # ── BackgroundConsolidationTask cached scalars ────────────────────────
        if self._bg_consolidation is not None:
            self._bg_consolidation._enable_entity_extraction = self.config.enable_entity_extraction
            self._bg_consolidation._enable_self_memory = self.config.enable_self_memory

    async def setup(self) -> None:
        """Create DB engine, tables, and session factory. Start background tasks."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._setup_sync)
        if self.config.enable_background_consolidation:
            self._start_background_consolidation()

    def _setup_sync(self) -> None:
        from pathlib import Path
        from hippomem.db.migrations import run_migrations
        Path(self.config.db_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_db_engine(self.config.db_url)
        Base.metadata.create_all(self._engine)
        run_migrations(self._engine)
        self._session_factory = create_session_factory(self._engine)

    def _start_background_consolidation(self) -> None:
        self._bg_consolidation = BackgroundConsolidationTask(
            session_factory=self._session_factory,
            interval_hours=self.config.consolidation_interval_hours,
            enable_episode_consolidation=self.config.enable_episode_consolidation,
            enable_entity_extraction=self.config.enable_entity_extraction,
            consolidation_llm_ops=ConsolidationLLMOps(self._llm_svc),
            embedding_service=self._emb_svc,
            vector_dir=self.config.vector_dir,
            enable_self_memory=self.config.enable_self_memory,
        )
        self._bg_consolidation.start()

    async def close(self) -> None:
        """Stop background tasks and dispose DB engine."""
        if self._background_tasks:
            logger.info("close: waiting for %d in-flight encode task(s)", len(self._background_tasks))
            await asyncio.wait(self._background_tasks, timeout=10)
        if self._bg_consolidation:
            await self._bg_consolidation.stop()
        if self._engine:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._engine.dispose)

    async def __aenter__(self) -> "MemoryService":
        await self.setup()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    def _get_db(self) -> Session:
        if self._session_factory is None:
            raise RuntimeError("MemoryService not initialized. Call setup() or use 'async with'.")
        return next(get_db_session(self._session_factory))

    def _get_consolidation_svc(self) -> ConsolidationService:
        return ConsolidationService(
            config=ConsolidationConfig(
                max_active_events=self.config.max_active_events,
                max_dormant_events=self.config.max_dormant_events,
                relevance_decay_rate=self.config.decay_rate_per_hour,
            )
        )

    async def consolidate(self, user_id: str) -> None:
        """
        Run periodic memory maintenance for a user.

        Call this at session end, on a schedule, or whenever appropriate.
        Handles: entity enrichment, trait pruning, self memory snapshot.
        Decay and demotion run in the encoder on each turn.

        Args:
            user_id: The user to consolidate.
        """
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._consolidate_sync, user_id)
        except Exception as e:
            logger.error("consolidate() failed for user %s: %s", user_id, e)

    def _consolidate_sync(self, user_id: str) -> None:
        from hippomem.consolidator.service import consolidate_user
        from hippomem.infra.call_collector import _current_collector, LLMCallCollector

        collector = LLMCallCollector()
        token = _current_collector.set(collector)
        db = self._get_db()
        try:
            consolidate_user(
                user_id=user_id,
                db=db,
                enable_episode_consolidation=self.config.enable_episode_consolidation,
                enable_entity_extraction=self.config.enable_entity_extraction,
                consolidation_llm_ops=ConsolidationLLMOps(self._llm_svc),
                embedding_service=self._emb_svc,
                vector_dir=self.config.vector_dir,
                enable_self_memory=self.config.enable_self_memory,
            )
            logger.info("consolidate: user=%s", user_id)
            self._persist_interaction("consolidate", user_id, collector, db)
        finally:
            _current_collector.reset(token)
            db.close()

    async def decode(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
        conversation_history: Optional[List[Tuple[str, str]]] = None,
        on_step: Optional[Callable[[str], None]] = None,
        turn_id: Optional[str] = None,
    ) -> DecodeResult:
        """
        Pre-inference: retrieve and synthesize relevant memory context.

        Args:
            user_id: Unique identifier for the user.
            message: The current user message.
            session_id: Optional session identifier (e.g. chat window ID).
            conversation_history: Prior (user, assistant) turn pairs, oldest first.
                Do NOT include the current turn — hippomem appends it during encode().
                Callers own and maintain this list across turns.
            on_step: Optional callback called with a human-readable step label as each
                decode phase begins. Called from the thread-pool executor; use
                loop.call_soon_threadsafe if you need to bridge to async code.
            turn_id: Optional pre-generated turn UUID. If omitted one is generated internally.

        Returns:
            DecodeResult with .context (pass to LLM) and internal state for encode().
        """
        history = conversation_history or []

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._decode_sync,
            user_id, session_id, message, history, on_step, turn_id,
        )
        return result

    def _decode_sync(
        self,
        user_id: str,
        session_id: Optional[str],
        message: str,
        conversation_history: List[Tuple[str, str]],
        on_step: Optional[Callable[[str], None]] = None,
        turn_id: Optional[str] = None,
    ) -> DecodeResult:
        from hippomem.infra.call_collector import _current_collector, LLMCallCollector

        turn_id = turn_id or str(uuid.uuid4())
        collector = LLMCallCollector()
        token = _current_collector.set(collector)
        t0 = time.perf_counter()
        db = self._get_db()
        try:
            try:
                synthesis = self._synthesizer.synthesize(
                    user_id=user_id,
                    session_id=session_id,
                    user_message=message,
                    conversation_history=conversation_history,
                    db=db,
                    on_step=on_step,
                )
            except Exception as e:
                logger.error("decode: synthesize() failed for user %s: %s", user_id, e)
                synthesis = {"synthesized_context": "", "used_engram_ids": [], "used_entity_ids": [], "reasoning": "", "cascade": "C2"}
            context = synthesis.get("synthesized_context", "")
            formatted = f"## Memory Context\n\n{context}" if context else ""
            used = synthesis.get("used_engram_ids", [])
            used_entities = synthesis.get("used_entity_ids", [])
            cascade = synthesis.get("cascade", "C2")  # synthesizer will set this
            ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "decode: user=%s cascade=%s engrams=%d ms=%d turn_id=%s",
                user_id, cascade, len(used), ms, turn_id,
            )
            self._last_decode_cache[(user_id, session_id)] = (turn_id, used)
            self._last_decode_cache.move_to_end((user_id, session_id))
            if len(self._last_decode_cache) > _DECODE_CACHE_MAX:
                self._last_decode_cache.popitem(last=False)
            result = DecodeResult(
                context=formatted,
                used_engram_ids=used,
                used_entity_ids=used_entities,
                reasoning=synthesis.get("reasoning", ""),
                synthesized_context=context,
                turn_id=turn_id,
            )
            self._persist_interaction(
                "decode", user_id, collector, db,
                turn_id=turn_id,
                session_id=session_id,
                output={
                    "used_engram_ids": used,
                    "used_entity_ids": used_entities,
                    "context": context,
                    "reasoning": synthesis.get("reasoning", ""),
                },
            )
            return result
        finally:
            _current_collector.reset(token)
            db.close()

    async def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        mode: str = "hybrid",
        top_k: int = 5,
        entity_count: int = 4,
        graph_count: int = 5,
        exclude_uuids: Optional[List[str]] = None,
        rrf_k: Optional[int] = None,
        bm25_index_ttl_seconds: Optional[int] = None,
        w_sem: Optional[float] = None,
        w_rel: Optional[float] = None,
        w_rec: Optional[float] = None,
    ) -> RetrieveResult:
        """
        Retrieve raw episodes by query. Mode-driven: faiss | bm25 | hybrid.
        Each episode has entities[] and related_episodes[].
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._retrieve_sync,
            user_id,
            query,
            mode,
            top_k,
            entity_count,
            graph_count,
            exclude_uuids,
            rrf_k,
            bm25_index_ttl_seconds,
            w_sem,
            w_rel,
            w_rec,
        )

    def _retrieve_sync(
        self,
        user_id: str,
        query: str,
        mode: str,
        top_k: int,
        entity_count: int,
        graph_count: int,
        exclude_uuids: Optional[List[str]],
        rrf_k: Optional[int],
        bm25_index_ttl_seconds: Optional[int],
        w_sem: Optional[float],
        w_rel: Optional[float],
        w_rec: Optional[float],
    ) -> RetrieveResult:
        db = self._get_db()
        try:
            return self._retrieve_svc.retrieve(
                user_id=user_id,
                query=query,
                db=db,
                mode=mode,
                top_k=top_k,
                entity_count=entity_count,
                graph_count=graph_count,
                exclude_uuids=exclude_uuids,
                rrf_k=rrf_k,
                bm25_index_ttl_seconds=bm25_index_ttl_seconds,
                w_sem=w_sem,
                w_rel=w_rel,
                w_rec=w_rec,
            )
        finally:
            db.close()

    async def encode(
        self,
        user_id: str,
        user_message: str,
        assistant_response: str,
        decode_result: Optional[DecodeResult] = None,
        session_id: Optional[str] = None,
        conversation_history: Optional[List[Tuple[str, str]]] = None,
        on_step: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Post-inference: update memory with the completed turn.

        Call this after your LLM responds. Awaits completion before returning.

        Args:
            user_id: Unique identifier for the user.
            user_message: The user's message from this turn.
            assistant_response: Your LLM's response.
            decode_result: The DecodeResult returned by decode() for this turn.
                Pass None if decode() was not called (memory update only, no linking).
            session_id: Optional session identifier.
            conversation_history: Prior (user, assistant) turn pairs, same list passed
                to decode(). hippomem appends the current turn internally before updating.
                Callers own and maintain this list across turns.
            on_step: Optional callback called with a human-readable step label as each
                encode phase begins. Called from the thread-pool executor; use
                loop.call_soon_threadsafe if you need to bridge to async code.

        Returns:
            turn_id: UUID linking this encode to its corresponding decode row.
        """
        # Tier 1: caller passed decode_result with turn_id
        if decode_result and decode_result.turn_id:
            turn_id = decode_result.turn_id
            used_engram_ids = decode_result.used_engram_ids
            used_entity_ids = decode_result.used_entity_ids or []
        # Tier 2: cache hit for (user_id, session_id)
        elif (user_id, session_id) in self._last_decode_cache:
            turn_id, used_engram_ids = self._last_decode_cache[(user_id, session_id)]
            used_entity_ids = []
        # Provisional — tiers 3+4 resolved inside _encode_sync
        else:
            turn_id = str(uuid.uuid4())
            used_engram_ids = []  # sentinel: signals DB fallback needed
            used_entity_ids = []

        await self._encode_async(
            user_id, user_message, assistant_response,
            decode_result, session_id, conversation_history or [],
            turn_id=turn_id, used_engram_ids=used_engram_ids,
            used_entity_ids=used_entity_ids,
            on_step=on_step,
        )
        return turn_id

    async def _encode_async(
        self,
        user_id: str,
        user_message: str,
        assistant_response: str,
        decode_result: Optional[DecodeResult],
        session_id: Optional[str],
        conversation_history: List[Tuple[str, str]],
        turn_id: str = "",
        used_engram_ids: Optional[List[str]] = None,
        used_entity_ids: Optional[List[str]] = None,
        on_step: Optional[Callable[[str], None]] = None,
    ) -> None:
        history = (conversation_history + [(user_message, assistant_response)])[
            -self.config.updater_history_turns:
        ]

        reasoning = decode_result.reasoning if decode_result else ""
        synthesized_context = decode_result.synthesized_context if decode_result else ""
        used_entity_ids = (decode_result.used_entity_ids if decode_result else None) or used_entity_ids or []

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                self._encode_sync,
                user_id, session_id, history,
                used_engram_ids, reasoning, synthesized_context,
                used_entity_ids, turn_id, on_step,
            )
        except Exception as e:
            logger.error("encode() failed for user %s: %s", user_id, e)

    def _encode_sync(
        self,
        user_id: str,
        session_id: Optional[str],
        conversation_history: List[Tuple[str, str]],
        used_engram_ids: List[str],
        reasoning: str,
        synthesized_context: str,
        used_entity_ids: List[str],
        turn_id: str = "",
        on_step: Optional[Callable[[str], None]] = None,
    ) -> None:
        from hippomem.infra.call_collector import _current_collector, LLMCallCollector
        from hippomem.models.llm_interaction import LLMInteraction

        collector = LLMCallCollector()
        token = _current_collector.set(collector)
        db = self._get_db()
        try:
            # Tier 3: DB fallback — find latest decode within recency threshold
            if not used_engram_ids:
                row = (
                    db.query(LLMInteraction)
                    .filter_by(user_id=user_id, session_id=session_id, operation="decode")
                    .order_by(LLMInteraction.created_at.desc())
                    .first()
                )
                threshold = self.config.turn_link_max_age_seconds
                if (
                    row
                    and row.turn_id
                    and row.created_at
                    and (datetime.now(timezone.utc).replace(tzinfo=None) - row.created_at.replace(tzinfo=None)).total_seconds() <= threshold
                ):
                    turn_id = row.turn_id
                    used_engram_ids = (row.output or {}).get("used_engram_ids", [])
                # Tier 4: provisional turn_id stands, used_engram_ids stays [] → Path B encode

            result = self._updater.update(
                user_id=user_id,
                session_id=session_id,
                conversation_history=conversation_history,
                db=db,
                used_engram_ids=used_engram_ids,
                reasoning=reasoning,
                synthesized_context=synthesized_context,
                used_entity_ids=used_entity_ids,
                on_step=on_step,
            )
            action = result.get("action", "skip")
            engram_id = result.get("event_id") or "none"
            logger.info(
                "encode: user=%s action=%s engram=%s turn_id=%s",
                user_id, action, engram_id, turn_id,
            )
            self._persist_interaction(
                "encode", user_id, collector, db,
                turn_id=turn_id,
                session_id=session_id,
                output={
                    "action": action,
                    "event_uuid": engram_id,
                },
            )
            self._save_conversation_turn(
                db=db,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                user_message=conversation_history[-1][0],
                assistant_response=conversation_history[-1][1],
                memory_context=synthesized_context,
                used_engram_ids=used_engram_ids,
                encoded_engram_id=result.get("event_id"),
            )
        finally:
            _current_collector.reset(token)
            db.close()

    # ── Conversation turn storage ───────────────────────────────────────────────

    def _save_conversation_turn(
        self,
        db: "Session",
        user_id: str,
        session_id: Optional[str],
        turn_id: str,
        user_message: str,
        assistant_response: str,
        memory_context: str,
        used_engram_ids: List[str],
        encoded_engram_id: Optional[str],
    ) -> None:
        """Persist raw conversation turn and its engram associations. Non-fatal on error."""
        try:
            turn = ConversationTurn(
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id or None,
                user_message=user_message,
                assistant_response=assistant_response,
                memory_context=memory_context or None,
            )
            db.add(turn)
            db.flush()  # get turn.id without committing

            seen_engram_ids: set = set()
            for engram_id in (used_engram_ids or []):
                if engram_id and engram_id not in seen_engram_ids:
                    db.add(ConversationTurnEngram(
                        turn_id=turn.id,
                        engram_id=engram_id,
                        link_type="decoded",
                        user_id=user_id,
                    ))
                    seen_engram_ids.add(engram_id)

            if encoded_engram_id and encoded_engram_id not in seen_engram_ids:
                db.add(ConversationTurnEngram(
                    turn_id=turn.id,
                    engram_id=encoded_engram_id,
                    link_type="encoded",
                    user_id=user_id,
                ))

            db.commit()
        except Exception as e:
            logger.error("_save_conversation_turn failed for user %s: %s", user_id, e)
            try:
                db.rollback()
            except Exception as rollback_err:
                logger.warning("rollback failed: %s", rollback_err)

    def get_messages(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Return conversation history as a flat list of message dicts for Studio.
        Each turn is expanded into two entries: user then assistant.
        """
        db = self._get_db()
        try:
            q = db.query(ConversationTurn).filter(ConversationTurn.user_id == user_id)
            if session_id is not None:
                q = q.filter(ConversationTurn.session_id == session_id)
            turns = q.order_by(ConversationTurn.created_at.asc()).limit(limit).all()
            result = []
            for turn in turns:
                ts = turn.created_at.isoformat() if turn.created_at else ""
                result.append({
                    "id": f"{turn.id}_u",
                    "role": "user",
                    "content": turn.user_message,
                    "memory_context": None,
                    "timestamp": ts,
                })
                result.append({
                    "id": f"{turn.id}_a",
                    "role": "assistant",
                    "content": turn.assistant_response,
                    "memory_context": turn.memory_context,
                    "timestamp": ts,
                })
            return result
        finally:
            db.close()

    def get_turns_for_engram(
        self,
        user_id: str,
        engram_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Return all raw conversation turns associated with an engram or entity UUID.
        Ordered oldest-first. Each entry includes link_type (decoded | encoded).
        """
        db = self._get_db()
        try:
            rows = (
                db.query(ConversationTurn, ConversationTurnEngram)
                .join(
                    ConversationTurnEngram,
                    ConversationTurnEngram.turn_id == ConversationTurn.id,
                )
                .filter(
                    ConversationTurnEngram.engram_id == engram_id,
                    ConversationTurnEngram.user_id == user_id,
                )
                .order_by(ConversationTurn.created_at.asc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "turn_id": turn.turn_id,
                    "session_id": turn.session_id,
                    "user_message": turn.user_message,
                    "assistant_response": turn.assistant_response,
                    "memory_context": turn.memory_context,
                    "link_type": cte.link_type,
                    "created_at": turn.created_at.isoformat() if turn.created_at else None,
                }
                for turn, cte in rows
            ]
        finally:
            db.close()

    # ── Explorer (delegated to hippomem.explorer) ──────────────────────────────

    def get_graph_for_explorer(self, user_id: str) -> Dict[str, Any]:
        """Return nodes and edges for the memory explorer graph."""
        db = self._get_db()
        try:
            return explorer.get_graph_for_explorer(user_id, db)
        finally:
            db.close()

    def get_event_detail_for_explorer(
        self, user_id: str, event_uuid: str
    ) -> Optional[Dict[str, Any]]:
        """Return full event detail for the memory explorer."""
        db = self._get_db()
        try:
            return explorer.get_event_detail_for_explorer(user_id, event_uuid, db)
        finally:
            db.close()

    def get_self_traits_for_explorer(self, user_id: str) -> Dict[str, Any]:
        """Return all self traits for the self memory explorer view."""
        db = self._get_db()
        try:
            return explorer.get_self_traits_for_explorer(user_id, db)
        finally:
            db.close()

    def get_entities_for_explorer(self, user_id: str) -> Dict[str, Any]:
        """Return all entity engrams for the persona explorer view."""
        db = self._get_db()
        try:
            return explorer.get_entities_for_explorer(user_id, db)
        finally:
            db.close()

    # ── Session management (delegated to hippomem.sessions) ───────────────────

    def initialize_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create empty working state for a new user/session scope.
        Returns existing state if already initialized.
        """
        db = self._get_db()
        try:
            return sessions.initialize_session(user_id, session_id, db)
        finally:
            db.close()

    def snapshot_to_session(
        self,
        user_id: str,
        new_session_id: str,
    ) -> None:
        """
        Copy global (session_id=None) memory state to a new session at session start.
        This seeds the new session with the user's existing long-term context.
        """
        db = self._get_db()
        try:
            sessions.snapshot_to_session(user_id, new_session_id, db)
        finally:
            db.close()

    # ── Inspector (delegated to hippomem.inspector) ─────────────────────────────

    def list_interactions(self, user_id: str, limit: int = 50) -> list[dict]:
        """Return LLM interaction summaries for the Inspector tab."""
        db = self._get_db()
        try:
            from hippomem import inspector

            return inspector.list_interactions(user_id, db, limit)
        finally:
            db.close()

    def get_interaction_detail(self, interaction_id: str) -> Optional[dict]:
        """Return full interaction detail with call logs for the Inspector."""
        db = self._get_db()
        try:
            from hippomem import inspector

            return inspector.get_interaction_detail(interaction_id, db)
        finally:
            db.close()

    def get_stats(self, user_id: str) -> dict:
        """Return memory counts + usage aggregates for the Dashboard."""
        db = self._get_db()
        try:
            from hippomem import inspector

            return inspector.get_stats(user_id, db)
        finally:
            db.close()

    def _persist_interaction(
        self,
        operation: str,
        user_id: str,
        collector: "LLMCallCollector",
        db: Session,
        turn_id: Optional[str] = None,
        session_id: Optional[str] = None,
        output: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write LLMInteraction + LLMCallLog rows. Called inside existing db session."""
        if not collector.records:
            return
        try:
            from hippomem.models.llm_interaction import LLMInteraction, LLMCallLog

            usage = collector.usage
            interaction = LLMInteraction(
                id=str(uuid.uuid4()),
                user_id=user_id,
                operation=operation,
                call_count=len(collector.records),
                total_input_tokens=usage.input_token_count,
                total_output_tokens=usage.output_token_count,
                total_cost=usage.cost,
                total_latency_ms=collector.total_latency_ms,
                turn_id=turn_id or None,
                session_id=session_id,
                output=output,
            )
            db.add(interaction)
            db.flush()
            for record in collector.records:
                db.add(
                    LLMCallLog(
                        id=str(uuid.uuid4()),
                        interaction_id=interaction.id,
                        user_id=user_id,
                        op=record.op,
                        model=record.model,
                        messages=record.messages,
                        raw_response=record.raw_response,
                        input_tokens=record.input_tokens,
                        output_tokens=record.output_tokens,
                        cost=record.cost,
                        latency_ms=record.latency_ms,
                        step_order=record.step_order,
                    )
                )
            db.commit()
        except Exception as e:
            logger.error("_persist_interaction failed: %s", e)
            db.rollback()

    def get_interaction_by_turn_id(self, turn_id: str) -> Optional[dict]:
        """Return all interaction detail rows that share the given turn_id."""
        db = self._get_db()
        try:
            from hippomem import inspector
            return inspector.get_by_turn_id(turn_id, db)
        finally:
            db.close()
