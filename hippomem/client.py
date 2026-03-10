"""
HippoMemClient — thin httpx wrapper for apps that connect to a running hippomem daemon.

Usage::

    from hippomem.client import HippoMemClient

    # As a context manager (recommended):
    async with HippoMemClient("http://localhost:8719") as mem:
        result = await mem.decode("user_123", "What was I working on?")
        # ... call your LLM with result.context ...
        await mem.encode("user_123", user_msg, assistant_msg, decode_result=result)

    # Or manage lifecycle manually:
    mem = HippoMemClient("http://localhost:8719")
    try:
        result = await mem.decode(...)
    finally:
        await mem.aclose()

Requires: pip install hippomem[server]  (includes httpx)
"""
from typing import Optional

from hippomem.decoder.schemas import DecodeResult
from hippomem.encoder.schemas import EncodeResult
from hippomem.retrieve.schemas import RetrieveResult, RetrievedEntity, RetrievedEpisode


def _get_httpx():
    try:
        import httpx
        return httpx
    except ImportError:
        raise ImportError(
            "httpx is required for HippoMemClient. "
            "Install it with: pip install hippomem[server]"
        ) from None


class HippoMemClient:
    """
    Async HTTP client for the hippomem daemon.

    Mirrors MemoryService's public API (decode, encode, consolidate) but
    delegates all calls to a running daemon over HTTP. Holds a persistent
    httpx.AsyncClient — use as a context manager or call aclose() when done.
    """

    def __init__(self, base_url: str = "http://localhost:8719", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        httpx = _get_httpx()
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()

    async def __aenter__(self) -> "HippoMemClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def decode(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
        conversation_history: Optional[list[tuple[str, str]]] = None,
    ) -> DecodeResult:
        """Retrieve memory context before LLM call. POST /decode."""
        raw = conversation_history or []
        payload = {
            "user_id": user_id,
            "message": message,
            "session_id": session_id,
            "conversation_history": [list(pair) for pair in raw],
        }
        r = await self._client.post("/decode", json=payload)
        r.raise_for_status()
        data = r.json()
        return DecodeResult(
            context=data["context"],
            used_engram_ids=data["used_engram_ids"],
            used_entity_ids=data.get("used_entity_ids", []),
            reasoning=data["reasoning"],
            synthesized_context=data["synthesized_context"],
            turn_id=data.get("turn_id", ""),
        )

    async def encode(
        self,
        user_id: str,
        user_message: str,
        assistant_response: str,
        decode_result: Optional[DecodeResult] = None,
        session_id: Optional[str] = None,
        conversation_history: Optional[list[tuple[str, str]]] = None,
    ) -> EncodeResult:
        """Update memory after LLM response. POST /encode."""
        raw = conversation_history or []
        payload: dict = {
            "user_id": user_id,
            "user_message": user_message,
            "assistant_response": assistant_response,
            "session_id": session_id,
            "conversation_history": [list(pair) for pair in raw],
        }
        if decode_result is not None:
            payload["decode_result"] = {
                "context": decode_result.context,
                "used_engram_ids": decode_result.used_engram_ids,
                "used_entity_ids": decode_result.used_entity_ids,
                "reasoning": decode_result.reasoning,
                "synthesized_context": decode_result.synthesized_context,
                "turn_id": decode_result.turn_id,
            }
        r = await self._client.post("/encode", json=payload)
        r.raise_for_status()
        data = r.json()
        return EncodeResult(turn_id=data.get("turn_id", ""))

    async def consolidate(self, user_id: str) -> None:
        """Run periodic memory maintenance. POST /consolidate."""
        r = await self._client.post("/consolidate", json={"user_id": user_id})
        r.raise_for_status()

    async def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        mode: str = "hybrid",
        top_k: int = 5,
        entity_count: int = 4,
        graph_count: int = 5,
        exclude_uuids: Optional[list[str]] = None,
        rrf_k: Optional[int] = None,
        bm25_index_ttl_seconds: Optional[int] = None,
        w_sem: Optional[float] = None,
        w_rel: Optional[float] = None,
        w_rec: Optional[float] = None,
    ) -> RetrieveResult:
        """Retrieve raw episodes by query. POST /retrieve."""
        payload: dict = {
            "user_id": user_id,
            "query": query,
            "mode": mode,
            "top_k": top_k,
            "entity_count": entity_count,
            "graph_count": graph_count,
        }
        if exclude_uuids is not None:
            payload["exclude_uuids"] = exclude_uuids
        if rrf_k is not None:
            payload["rrf_k"] = rrf_k
        if bm25_index_ttl_seconds is not None:
            payload["bm25_index_ttl_seconds"] = bm25_index_ttl_seconds
        if w_sem is not None:
            payload["w_sem"] = w_sem
        if w_rel is not None:
            payload["w_rel"] = w_rel
        if w_rec is not None:
            payload["w_rec"] = w_rec
        r = await self._client.post("/retrieve", json=payload)
        r.raise_for_status()
        data = r.json()
        return _dict_to_retrieve_result(data)


def _dict_to_entity(d: dict) -> RetrievedEntity:
    return RetrievedEntity(
        event_uuid=d["event_uuid"],
        core_intent=d["core_intent"],
        score=d.get("score"),
        source=d.get("source", "mention"),
        event_kind=d.get("event_kind", "entity"),
        entity_type=d.get("entity_type"),
        summary_text=d.get("summary_text"),
        updates=d.get("updates", []),
        cosine_score=d.get("cosine_score"),
        rrf_score=d.get("rrf_score"),
        graph_hop=d.get("graph_hop"),
    )


def _dict_to_episode(d: dict) -> RetrievedEpisode:
    return RetrievedEpisode(
        event_uuid=d["event_uuid"],
        core_intent=d["core_intent"],
        score=d["score"],
        source=d["source"],
        event_kind=d.get("event_kind", "episode"),
        summary_text=d.get("summary_text"),
        updates=d.get("updates", []),
        entity_type=d.get("entity_type"),
        cosine_score=d.get("cosine_score"),
        rrf_score=d.get("rrf_score"),
        graph_hop=d.get("graph_hop"),
        entities=[_dict_to_entity(e) for e in d.get("entities", [])],
        related_episodes=[_dict_to_episode(r) for r in d.get("related_episodes", [])],
    )


def _dict_to_retrieve_result(d: dict) -> RetrieveResult:
    return RetrieveResult(
        episodes=[_dict_to_episode(ep) for ep in d.get("episodes", [])],
        total_primary=d.get("total_primary", 0),
    )
