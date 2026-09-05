"""delete_user / export_user remove rows and the FAISS file."""
from pathlib import Path

import pytest

from hippomem.config import MemoryConfig
from hippomem.models.engram import Engram
from hippomem.privacy import EXPORT_SCHEMA_VERSION  # registers inspector/privacy tables
from hippomem.service import MemoryService


@pytest.mark.asyncio
async def test_delete_user_removes_rows_and_faiss(tmp_path):
    vector_dir = tmp_path / "vectors"
    vector_dir.mkdir()
    db_path = tmp_path / "mem.db"
    cfg = MemoryConfig(
        db_url=f"sqlite:///{db_path}",
        vector_dir=str(vector_dir),
        enable_background_consolidation=False,
    )
    svc = MemoryService(llm_api_key="sk-test", llm_base_url="http://127.0.0.1", config=cfg)
    await svc.setup()
    try:
        db = svc._get_db()
        db.add(Engram(user_id="u1", engram_id="e1", core_intent="remember this"))
        db.add(Engram(user_id="u2", engram_id="e2", core_intent="keep this"))
        db.commit()
        db.close()

        idx = Path(vector_dir) / "u1.index"
        idx.write_bytes(b"fake-faiss")

        export = svc.export_user("u1")
        assert export["schema_version"] == EXPORT_SCHEMA_VERSION
        assert export["user_id"] == "u1"
        assert len(export["engrams"]) == 1

        counts = svc.delete_user("u1")
        assert counts["engrams"] == 1
        assert counts["faiss_index"] == 1
        assert not idx.exists()

        after = svc.export_user("u1")
        assert after["engrams"] == []

        leftover = svc.export_user("u2")
        assert len(leftover["engrams"]) == 1
    finally:
        await svc.close()
