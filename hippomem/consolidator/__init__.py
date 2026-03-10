"""Consolidator — decay, demotion, and background maintenance."""
from hippomem.consolidator.service import ConsolidationService, ConsolidationConfig
from hippomem.consolidator.background import BackgroundConsolidationTask

__all__ = [
    "ConsolidationService",
    "ConsolidationConfig",
    "BackgroundConsolidationTask",
]
