"""
hippomem — Brain-inspired persistent memory for LLM chat applications.

Quick start::

    from hippomem import MemoryService, MemoryConfig, DecodeResult

    memory = MemoryService(llm_api_key="sk-...")
    async with memory:
        result = await memory.decode(user_id, message)
        # result.context → pass to your LLM
        response = await your_llm(result.context + user_message)
        await memory.encode(user_id, message, response, result)
"""
import logging

logging.getLogger(__name__).addHandler(logging.NullHandler())

from hippomem.service import MemoryService
from hippomem.decoder.schemas import DecodeResult
from hippomem.config import MemoryConfig
from hippomem.retrieve.schemas import RetrieveResult, RetrievedEpisode, RetrievedEntity

__version__ = "0.3.0"
__all__ = [
    "MemoryService",
    "DecodeResult",
    "MemoryConfig",
    "RetrieveResult",
    "RetrievedEpisode",
    "RetrievedEntity",
]
