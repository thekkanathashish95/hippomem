"""
Background Consolidation Task — periodic decay, demotion (v0.2).

Runs as an asyncio background task while MemoryService is active.
Enabled via MemoryConfig.enable_background_consolidation.
"""
import asyncio
import logging
from typing import Optional, TYPE_CHECKING

from hippomem.consolidator.service import ConsolidationService

if TYPE_CHECKING:
    from hippomem.infra.embeddings import EmbeddingService
    from hippomem.consolidator.llm_ops import ConsolidationLLMOps

logger = logging.getLogger(__name__)


class BackgroundConsolidationTask:
    """
    Asyncio background task for periodic memory maintenance.

    On each cycle (configurable interval):
    1. Apply decay + staleness demotion for all active user/session scopes.
    2. Optionally enrich entity profiles and refresh persona (if enabled).

    Usage::

        task = BackgroundConsolidationTask(session_factory, consolidation_svc, config=config)
        task.start()
        # ... later ...
        await task.stop()
    """

    def __init__(
        self,
        session_factory,
        consolidation_svc: ConsolidationService,
        interval_hours: float = 1.0,
        enable_entity_extraction: bool = False,
        consolidation_llm_ops: Optional["ConsolidationLLMOps"] = None,
        embedding_service: Optional["EmbeddingService"] = None,
        vector_dir: str = ".hippomem/vectors",
        enable_self_memory: bool = False,
        self_trait_min_confidence: float = 0.5,
    ) -> None:
        self._session_factory = session_factory
        self._svc = consolidation_svc
        self._interval_seconds = interval_hours * 3600
        self._enable_entity_extraction = enable_entity_extraction
        self._consolidation_llm_ops = consolidation_llm_ops
        self._embedding_service = embedding_service
        self._vector_dir = vector_dir
        self._enable_self_memory = enable_self_memory
        self._self_trait_min_confidence = self_trait_min_confidence
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Start the background loop."""
        self._task = asyncio.create_task(self._run())
        logger.info(
            "Background consolidation started (interval=%.1fh)",
            self._interval_seconds / 3600,
        )

    async def stop(self) -> None:
        """Cancel and await the background loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("background task stopped")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(None, self._run_sync)
            except Exception as e:
                logger.error("Background consolidation cycle failed: %s", e)

    def _run_sync(self) -> None:
        from hippomem.models.working_state import WorkingState
        from hippomem.consolidator.service import consolidate_user
        from hippomem.db.session import get_db_session

        db = next(get_db_session(self._session_factory))
        try:
            user_ids = [
                row.user_id
                for row in db.query(WorkingState.user_id).distinct().all()
            ]
            for user_id in user_ids:
                try:
                    consolidate_user(
                        user_id=user_id,
                        db=db,
                        consolidation_svc=self._svc,
                        enable_entity_extraction=self._enable_entity_extraction,
                        consolidation_llm_ops=self._consolidation_llm_ops,
                        embedding_service=self._embedding_service,
                        vector_dir=self._vector_dir,
                        enable_self_memory=self._enable_self_memory,
                        self_trait_min_confidence=self._self_trait_min_confidence,
                    )
                except Exception as e:
                    logger.warning("consolidation cycle failed user=%s: %s", user_id, e)
        finally:
            db.close()
