"""
hippomem server — FastAPI daemon with Studio UI.

Serves the bundled Studio UI at / and exposes memory API endpoints.
Started via: hippomem serve [--port 8719] [--host 127.0.0.1]

Environment variables (see .env.example):
    LLM_API_KEY     — required (or in hippomem_config.json)
    LLM_BASE_URL    — default: https://api.openai.com/v1
    LLM_MODEL       — model used by hippomem internally (default: gpt-4o-mini)
    CHAT_MODEL      — model used for actual chat responses (default: same as LLM_MODEL)
    SYSTEM_PROMPT   — base system prompt injected before memory context
    DB_URL          — SQLite path (default: sqlite:///hippomem_chat.db)
    VECTOR_DIR      — FAISS index directory (default: .hippomem/vectors)
"""
import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from hippomem import MemoryConfig, MemoryService
from hippomem.decoder.schemas import DecodeResult
from hippomem.models.turn_status import TurnStatus
from hippomem.server.config_store import load_config_overlay, save_config

logger = logging.getLogger(__name__)

_RESET = "\033[0m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"

# Fields that require client swap (warm) — everything else is hot (mutate MemoryConfig)
WARM_FIELDS = {"llm_api_key", "llm_base_url", "llm_model", "chat_model", "embedding_model"}

# ── Config loading ─────────────────────────────────────────────────────────────


def _memory_config_to_dict(cfg: MemoryConfig) -> dict[str, Any]:
    """Serialize MemoryConfig fields that are exposed in the settings UI."""
    return {
        "max_active_events": cfg.max_active_events,
        "max_dormant_events": cfg.max_dormant_events,
        "ephemeral_trace_capacity": cfg.ephemeral_trace_capacity,
        "decay_rate_per_hour": cfg.decay_rate_per_hour,
        "continuation_threshold": cfg.continuation_threshold,
        "local_scan_threshold": cfg.local_scan_threshold,
        "retrieval_semantic_weight": cfg.retrieval_semantic_weight,
        "retrieval_relevance_weight": cfg.retrieval_relevance_weight,
        "retrieval_recency_weight": cfg.retrieval_recency_weight,
        "enable_background_consolidation": cfg.enable_background_consolidation,
        "consolidation_interval_hours": cfg.consolidation_interval_hours,
        "enable_entity_extraction": cfg.enable_entity_extraction,
        "enable_self_memory": cfg.enable_self_memory,
    }


def _apply_overlay_to_config(cfg: MemoryConfig, overlay: dict[str, Any]) -> None:
    """Apply overlay dict to MemoryConfig (only known fields)."""
    mc_fields = {
        "max_active_events", "max_dormant_events", "ephemeral_trace_capacity",
        "decay_rate_per_hour", "continuation_threshold", "local_scan_threshold",
        "retrieval_semantic_weight", "retrieval_relevance_weight", "retrieval_recency_weight",
        "enable_background_consolidation", "consolidation_interval_hours",
        "enable_entity_extraction", "enable_self_memory",
        "llm_model", "embedding_model",
    }
    for k, v in overlay.items():
        if k in mc_fields and hasattr(cfg, k):
            setattr(cfg, k, v)


def load_app_config() -> tuple[dict[str, Any], MemoryConfig, str, str, str, str, str]:
    """
    Load config: MemoryConfig defaults → .env → hippomem_config.json.
    Returns (full_config_dict, memory_config, llm_api_key, llm_base_url, llm_model, chat_model, system_prompt).
    """
    db_url = os.environ.get("DB_URL", "sqlite:///.hippomem/hippomem.db")
    vector_dir = os.environ.get("VECTOR_DIR", ".hippomem/vectors")

    overlay = load_config_overlay(db_url)

    llm_api_key = overlay.get("llm_api_key") or os.environ.get("LLM_API_KEY", "")
    llm_base_url = overlay.get("llm_base_url") or os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    llm_model = overlay.get("llm_model") or os.environ.get("LLM_MODEL", "x-ai/grok-4.1-fast")
    chat_model = overlay.get("chat_model") or os.environ.get("CHAT_MODEL", llm_model)
    system_prompt = overlay.get("system_prompt") or os.environ.get(
        "SYSTEM_PROMPT",
        "You are a helpful assistant with access to long-term memory about the user.",
    )

    config = MemoryConfig(
        llm_model=llm_model,
        db_url=db_url,
        vector_dir=vector_dir,
    )
    _apply_overlay_to_config(config, overlay)

    full = {
        "llm_api_key": llm_api_key,
        "llm_base_url": llm_base_url,
        "llm_model": config.llm_model,
        "chat_model": chat_model,
        "system_prompt": system_prompt,
        "embedding_model": config.embedding_model,
        **_memory_config_to_dict(config),
    }
    return full, config, llm_api_key, llm_base_url, config.llm_model, chat_model, system_prompt


# ── In-memory state ────────────────────────────────────────────────────────────

conversation_histories: dict[str, list[tuple[str, str]]] = {}

# ── Global service instances (set in lifespan) ────────────────────────────────────

memory: Optional[MemoryService] = None
llm_client: Optional[AsyncOpenAI] = None
app_config: dict[str, Any] = {}  # Mutable full config; updated by PATCH
db_url: str = "sqlite:///.hippomem/hippomem.db"

# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global memory, llm_client, app_config, db_url

    full, mem_config, api_key, base_url, llm_model, chat_model, system_prompt = load_app_config()
    db_url = mem_config.db_url
    app_config = full

    if api_key:
        memory = MemoryService(
            llm_api_key=api_key,
            llm_base_url=base_url,
            config=mem_config,
        )
        await memory.setup()
        llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        print(f"  {_GREEN}✓{_RESET}  Memory ready — model={llm_model}")
    else:
        settings_url = "http://127.0.0.1:8719/settings"
        _settings_link = f"\033]8;;{settings_url}\033\\Settings\033]8;;\033\\"
        print(f"  {_YELLOW}⚠  No API key configured.{_RESET}")
        print(f"  {_DIM}Open {_RESET}\033[36m{_settings_link}\033[0m{_DIM} in Studio  or  add {_RESET}\033[1mLLM_API_KEY\033[0m{_DIM} to a {_RESET}\033[1m.env\033[0m{_DIM} file and restart.{_RESET}")

    yield

    if memory:
        await memory.close()


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="hippomem", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # allow_origins=["*"] is acceptable for a localhost-bound daemon; if you
    # ever expose hippomem on 0.0.0.0 (e.g. in Docker), restrict this to
    # specific origins to prevent cross-origin requests from arbitrary websites.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Schemas ────────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    user_id: str
    message: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    memory_context: Optional[str] = None
    timestamp: str


class ChatResponse(BaseModel):
    message: MessageOut


# Decode/encode API for HippoMemClient
class DecodeRequest(BaseModel):
    user_id: str
    message: str
    session_id: Optional[str] = None
    conversation_history: Optional[list[list[str]]] = None  # [[user, assistant], ...]


class DecodeResponse(BaseModel):
    context: str
    used_engram_ids: list[str]
    used_entity_ids: list[str] = []
    reasoning: str
    synthesized_context: str
    turn_id: str = ""


class EncodeResponse(BaseModel):
    status: str
    turn_id: str


class EncodeRequest(BaseModel):
    user_id: str
    user_message: str
    assistant_response: str
    decode_result: Optional[DecodeResponse] = None
    session_id: Optional[str] = None
    conversation_history: Optional[list[list[str]]] = None  # [[user, assistant], ...]


class ConsolidateRequest(BaseModel):
    user_id: str


class RetrieveRequest(BaseModel):
    user_id: str
    query: str
    mode: str = "hybrid"
    top_k: int = 5
    entity_count: int = 4
    graph_count: int = 5
    exclude_uuids: Optional[list[str]] = None
    rrf_k: Optional[int] = None
    bm25_index_ttl_seconds: Optional[int] = None
    w_sem: Optional[float] = None
    w_rel: Optional[float] = None
    w_rec: Optional[float] = None


class ConfigPatch(BaseModel):
    """Partial config update. Only present fields are applied."""
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    chat_model: Optional[str] = None
    system_prompt: Optional[str] = None
    embedding_model: Optional[str] = None
    max_active_events: Optional[int] = None
    max_dormant_events: Optional[int] = None
    ephemeral_trace_capacity: Optional[int] = None
    decay_rate_per_hour: Optional[float] = None
    continuation_threshold: Optional[float] = None
    local_scan_threshold: Optional[float] = None
    retrieval_semantic_weight: Optional[float] = None
    retrieval_relevance_weight: Optional[float] = None
    retrieval_recency_weight: Optional[float] = None
    enable_background_consolidation: Optional[bool] = None
    consolidation_interval_hours: Optional[float] = None
    enable_entity_extraction: Optional[bool] = None
    enable_self_memory: Optional[bool] = None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _decode_response_to_result(d: DecodeResponse | None) -> DecodeResult | None:
    if d is None:
        return None
    return DecodeResult(
        context=d.context,
        used_engram_ids=d.used_engram_ids,
        used_entity_ids=d.used_entity_ids,
        reasoning=d.reasoning,
        synthesized_context=d.synthesized_context,
        turn_id=d.turn_id,
    )


def _result_to_decode_response(r: DecodeResult) -> DecodeResponse:
    return DecodeResponse(
        context=r.context,
        used_engram_ids=r.used_engram_ids,
        used_entity_ids=r.used_entity_ids,
        reasoning=r.reasoning,
        synthesized_context=r.synthesized_context,
        turn_id=r.turn_id,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────


def _ts_write(session_factory, turn_id: str, user_id: str, phase: str) -> Optional[str]:
    """Write a 'running' TurnStatus row. Returns the row id, or None on failure."""
    if session_factory is None:
        return None
    try:
        db = session_factory()
        try:
            now = datetime.now(timezone.utc)
            ts = TurnStatus(
                turn_id=turn_id, user_id=user_id, phase=phase, status="running",
                started_at=now, updated_at=now,
            )
            db.add(ts)
            db.commit()
            return ts.id
        finally:
            db.close()
    except Exception as exc:
        logger.warning("TurnStatus write failed (%s/%s): %s", phase, turn_id, exc)
        return None


def _ts_done(session_factory, ts_id: Optional[str]) -> None:
    """Mark a TurnStatus row as done."""
    if not ts_id or session_factory is None:
        return
    try:
        db = session_factory()
        try:
            ts = db.query(TurnStatus).filter_by(id=ts_id).first()
            if ts:
                now = datetime.now(timezone.utc)
                ts.status = "done"
                ts.updated_at = now
                ts.completed_at = now
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("TurnStatus done update failed (%s): %s", ts_id, exc)


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    if not memory or not llm_client:
        raise HTTPException(status_code=503, detail="Service not ready.")

    history = conversation_histories.get(req.user_id, [])
    # Pre-generate turn_id so we can write the decode status row before decode starts
    turn_id = str(uuid.uuid4())

    async def generate():
        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue = asyncio.Queue()
        _DONE = object()
        sf = memory._session_factory  # session factory for TurnStatus writes

        def push(event: dict) -> None:
            loop.call_soon_threadsafe(progress_queue.put_nowait, event)

        def mark_done(_task: asyncio.Task) -> None:
            loop.call_soon_threadsafe(progress_queue.put_nowait, _DONE)

        async def drain(task: asyncio.Task, heartbeat_secs: float = 15.0):
            """Yield SSE lines from progress_queue until task completion sentinel."""
            task.add_done_callback(mark_done)
            while True:
                try:
                    item = await asyncio.wait_for(progress_queue.get(), timeout=heartbeat_secs)
                    if item is _DONE:
                        break
                    yield f"data: {json.dumps(item)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

        # ── Decode phase ─────────────────────────────────────────────────────
        yield f"data: {json.dumps({'type': 'decode_start'})}\n\n"
        ts_decode_id = _ts_write(sf, turn_id, req.user_id, "decode")

        decode_task = asyncio.create_task(
            memory.decode(
                req.user_id, req.message,
                conversation_history=history,
                on_step=lambda s: push({"type": "decode_step", "step": s}),
                turn_id=turn_id,
            )
        )
        try:
            async for sse_line in drain(decode_task):
                yield sse_line
            decode_result = await decode_task
        except Exception as exc:
            logger.error("Decode failed for user=%s: %s", req.user_id, exc)
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Memory decode failed'})}\n\n"
            return

        _ts_done(sf, ts_decode_id)
        if decode_result.context:
            logger.info("decode: user=%s events=%s", req.user_id, decode_result.used_engram_ids)
        yield f"data: {json.dumps({'type': 'decode_done', 'used_events': len(decode_result.used_engram_ids)})}\n\n"

        # ── Build LLM messages ───────────────────────────────────────────────
        system = app_config.get("system_prompt", "")
        if decode_result.context:
            system = f"{system}\n\n{decode_result.context}"
        messages: list[dict] = [{"role": "system", "content": system}]
        for user_turn, assistant_turn in history[-6:]:
            messages.append({"role": "user", "content": user_turn})
            messages.append({"role": "assistant", "content": assistant_turn})
        messages.append({"role": "user", "content": req.message})

        # ── LLM token streaming ──────────────────────────────────────────────
        assistant_content = ""
        try:
            stream = await llm_client.chat.completions.create(
                model=app_config.get("chat_model", "gpt-4o-mini"),
                messages=messages,  # type: ignore[arg-type]
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else ""
                if delta:
                    assistant_content += delta
                    yield f"data: {json.dumps({'type': 'token', 'delta': delta})}\n\n"
        except Exception as exc:
            logger.error("Streaming error for user=%s: %s", req.user_id, exc)
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
            return

        # Update history immediately so next decode sees current turn
        conversation_histories[req.user_id] = history + [(req.message, assistant_content)]

        assistant_msg = MessageOut(
            id=str(uuid.uuid4()),
            role="assistant",
            content=assistant_content,
            memory_context=decode_result.synthesized_context or None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        yield f"data: {json.dumps({'type': 'done', 'message': assistant_msg.model_dump()})}\n\n"

        # ── Encode phase ─────────────────────────────────────────────────────
        yield f"data: {json.dumps({'type': 'encode_start'})}\n\n"
        ts_encode_id = _ts_write(sf, turn_id, req.user_id, "encode")

        encode_task = asyncio.create_task(
            memory.encode(
                req.user_id, req.message, assistant_content,
                decode_result,
                conversation_history=history,
                on_step=lambda s: push({"type": "encode_step", "step": s}),
            )
        )
        try:
            async for sse_line in drain(encode_task):
                yield sse_line
            await encode_task
        except Exception as exc:
            logger.error("Encode failed for user=%s: %s", req.user_id, exc)

        _ts_done(sf, ts_encode_id)
        yield f"data: {json.dumps({'type': 'encode_done', 'turn_id': turn_id})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/decode", response_model=DecodeResponse)
async def decode_endpoint(req: DecodeRequest) -> DecodeResponse:
    """Decode endpoint for HippoMemClient — retrieve memory context before LLM call."""
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    raw = req.conversation_history or []
    history = [tuple(pair) for pair in raw]  # type: ignore[misc]
    result = await memory.decode(
        req.user_id,
        req.message,
        session_id=req.session_id,
        conversation_history=history,
    )
    return _result_to_decode_response(result)


@app.post("/encode", response_model=EncodeResponse)
async def encode_endpoint(req: EncodeRequest) -> EncodeResponse:
    """Encode endpoint for HippoMemClient — update memory after LLM response."""
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    raw = req.conversation_history or []
    history = [tuple(pair) for pair in raw]  # type: ignore[misc]
    decode_result = _decode_response_to_result(req.decode_result)
    turn_id = await memory.encode(
        req.user_id,
        req.user_message,
        req.assistant_response,
        decode_result=decode_result,
        session_id=req.session_id,
        conversation_history=history,
    )
    return EncodeResponse(status="ok", turn_id=turn_id)


@app.post("/consolidate")
async def consolidate_endpoint(req: ConsolidateRequest) -> dict:
    """Consolidate endpoint for HippoMemClient — run periodic memory maintenance."""
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    await memory.consolidate(req.user_id)
    return {"status": "ok"}


@app.post("/retrieve")
async def retrieve_endpoint(req: RetrieveRequest) -> dict:
    """Retrieve raw episodes by query. Mode: faiss | bm25 | hybrid."""
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    from hippomem.retrieve.schemas import retrieve_result_to_dict

    result = await memory.retrieve(
        req.user_id,
        req.query,
        mode=req.mode,
        top_k=req.top_k,
        entity_count=req.entity_count,
        graph_count=req.graph_count,
        exclude_uuids=req.exclude_uuids,
        rrf_k=req.rrf_k,
        bm25_index_ttl_seconds=req.bm25_index_ttl_seconds,
        w_sem=req.w_sem,
        w_rel=req.w_rel,
        w_rec=req.w_rec,
    )
    return retrieve_result_to_dict(result)


@app.get("/turn-status/{turn_id}")
async def get_turn_status(turn_id: str) -> list[dict]:
    """Polling fallback for encode/decode status when SSE connection drops."""
    if not memory or memory._session_factory is None:
        raise HTTPException(status_code=503, detail="Service not ready.")
    db = memory._get_db()
    try:
        rows = db.query(TurnStatus).filter_by(turn_id=turn_id).all()
        return [
            {
                "phase": r.phase,
                "status": r.status,
                "current_step": r.current_step,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()


@app.get("/messages", response_model=list[MessageOut])
async def get_messages(user_id: str, session_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    if memory is None:
        return []
    return memory.get_messages(user_id, session_id=session_id, limit=limit)


@app.get("/engrams/{engram_id}/turns")
async def get_turns_for_engram(engram_id: str, user_id: str, limit: int = 50) -> list[dict]:
    if memory is None:
        raise HTTPException(status_code=503, detail="Memory service not initialized")
    return memory.get_turns_for_engram(user_id, engram_id, limit=limit)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "setup_required": memory is None,
        "memory_model": app_config.get("llm_model", ""),
        "chat_model": app_config.get("chat_model", ""),
    }


# ── Config API ──────────────────────────────────────────────────────────────────


def _config_for_response() -> dict[str, Any]:
    """Current config with API key masked."""
    out = dict(app_config)
    if out.get("llm_api_key"):
        out["llm_api_key"] = "sk-****"
    return out


@app.get("/config")
async def get_config() -> dict[str, Any]:
    """Return current config with API key masked."""
    return _config_for_response()


@app.patch("/config")
async def patch_config(patch: ConfigPatch) -> dict[str, Any]:
    """Apply partial config update. Hot fields apply immediately; warm fields swap clients."""
    global memory, llm_client, app_config

    # Build patch dict from non-None fields
    patch_dict: dict[str, Any] = {}
    for k, v in patch.model_dump(exclude_none=True).items():
        if k == "llm_api_key" and (not v or v == "sk-****"):
            continue
        patch_dict[k] = v

    if not patch_dict:
        return {"status": "applied", "config": _config_for_response()}

    # ── Setup mode: cold init ─────────────────────────────────────────────────
    if memory is None:
        api_key = patch_dict.get("llm_api_key") or app_config.get("llm_api_key", "")
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="LLM_API_KEY is required to activate hippomem.",
            )

        base_url = patch_dict.get("llm_base_url") or app_config.get("llm_base_url", "https://api.openai.com/v1")
        llm_model = patch_dict.get("llm_model") or app_config.get("llm_model", "gpt-4o-mini")

        app_config.update(patch_dict)

        mem_config = MemoryConfig(
            llm_model=llm_model,
            db_url=db_url,
            vector_dir=app_config.get("vector_dir", ".hippomem/vectors"),
        )
        _apply_overlay_to_config(mem_config, app_config)

        try:
            svc = MemoryService(llm_api_key=api_key, llm_base_url=base_url, config=mem_config)
            await svc.setup()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to initialise memory service: {exc}")

        memory = svc
        llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        save_config(db_url, app_config)
        print(f"  {_GREEN}✓{_RESET}  Memory service activated.")
        return {"status": "applied", "config": _config_for_response()}

    # ── Normal mode: hot/warm swap ────────────────────────────────────────────

    # Apply hot fields to MemoryConfig
    hot_fields = {k for k in patch_dict if k not in WARM_FIELDS}
    for k in hot_fields:
        if hasattr(memory.config, k):
            setattr(memory.config, k, patch_dict[k])
        app_config[k] = patch_dict[k]

    # Re-sync all derived runtime state (encoder sub-components, ConsolidationConfig
    # copy, BackgroundConsolidationTask cached scalars) from the updated config.
    if hot_fields:
        memory.update_feature_flags()

    # Apply warm fields
    warm_updates = {k: patch_dict[k] for k in WARM_FIELDS if k in patch_dict}
    if warm_updates:
        api_key = warm_updates.get("llm_api_key") or app_config["llm_api_key"]
        base_url = warm_updates.get("llm_base_url") or app_config["llm_base_url"]
        llm_model = warm_updates.get("llm_model") or app_config.get("llm_model")
        chat_model = warm_updates.get("chat_model") or app_config.get("chat_model")
        embedding_model = warm_updates.get("embedding_model") or app_config.get("embedding_model")

        memory.update_llm_config(
            api_key=api_key,
            base_url=base_url,
            llm_model=llm_model,
            embedding_model=embedding_model,
        )
        llm_client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        app_config["llm_api_key"] = api_key
        app_config["llm_base_url"] = base_url
        if llm_model is not None:
            app_config["llm_model"] = llm_model
        if chat_model is not None:
            app_config["chat_model"] = chat_model
        if embedding_model is not None:
            app_config["embedding_model"] = embedding_model

    # Persist full config
    save_config(db_url, app_config)

    return {"status": "applied", "config": _config_for_response()}


@app.get("/config/models")
async def get_config_models(api_key: Optional[str] = None, base_url: Optional[str] = None) -> dict[str, Any]:
    """
    Proxy GET models from OpenRouter (or base URL). Uses stored key/url unless query params supplied.
    For validation flow: pass api_key (and optionally base_url) to test before saving.
    """
    key = api_key or app_config.get("llm_api_key", "")
    base_url = (base_url or app_config.get("llm_base_url") or "https://openrouter.ai/api/v1").rstrip("/")

    if not key:
        return {"valid": False, "error": "No API key configured"}

    models_url = f"{base_url}/models"
    if "openrouter.ai" in base_url:
        models_url = "https://openrouter.ai/api/v1/models"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                models_url,
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.RequestError:
        host = base_url.split("/")[2] if "/" in base_url else "API"
        return {"valid": False, "error": f"Could not reach {host}"}

    if resp.status_code == 401:
        return {"valid": False, "error": "Invalid API key"}

    if resp.status_code == 404:
        return {"valid": False, "error": "Models endpoint not available"}

    resp.raise_for_status()
    data = resp.json()

    items = data.get("data", []) if isinstance(data, dict) else []
    models = sorted(
        [{"id": m.get("id", ""), "name": m.get("name", m.get("id", ""))} for m in items if isinstance(m, dict)],
        key=lambda x: (x["name"] or x["id"]).lower(),
    )
    return {"valid": True, "models": models}


# ── Inspector (traces + stats) ───────────────────────────────────────────────────


@app.get("/traces")
async def list_traces(user_id: str, limit: int = 50) -> dict:
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    return {"interactions": memory.list_interactions(user_id, limit)}


@app.get("/traces/{interaction_id}")
async def get_trace(interaction_id: str) -> dict:
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    detail = memory.get_interaction_detail(interaction_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return detail


@app.get("/stats")
async def get_stats(user_id: str) -> dict:
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    return memory.get_stats(user_id)


# ── Memory Explorer ────────────────────────────────────────────────────────────


@app.get("/memory/graph/{user_id}")
async def get_memory_graph(user_id: str) -> dict:
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    return memory.get_graph_for_explorer(user_id)


@app.get("/memory/events/{user_id}/{event_uuid}")
async def get_event_detail(user_id: str, event_uuid: str) -> dict:
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    detail = memory.get_event_detail_for_explorer(user_id, event_uuid)
    if detail is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    return detail


@app.get("/memory/self/{user_id}")
async def get_self_traits(user_id: str) -> dict:
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    return memory.get_self_traits_for_explorer(user_id)


@app.get("/memory/entities/{user_id}")
async def get_entities(user_id: str) -> dict:
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    return memory.get_entities_for_explorer(user_id)


# ── Studio UI (static files) ─────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"

# Top-level path segments that belong to the API — the SPA catch-all must not
# swallow requests to these paths and silently return index.html.
_API_PREFIXES = frozenset({
    "chat", "decode", "encode", "consolidate",
    "messages", "health", "traces", "stats", "memory", "config", "turn-status",
})


def _setup_static_routes(app: FastAPI) -> None:
    """Mount Studio UI static files. Skip if static/ not yet built."""
    if not STATIC_DIR.exists():
        logger.warning(
            "Studio static dir not found at %s — run scripts/build_studio.sh before serving UI",
            STATIC_DIR,
        )
        return

    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        logger.warning("index.html not found in %s", STATIC_DIR)
        return

    # Serve assets (js, css, etc.) from static/
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    async def root():
        return FileResponse(str(index_path))

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        # Return 404 for unknown API paths so typos don't silently serve index.html.
        if path.split("/")[0] in _API_PREFIXES:
            raise HTTPException(status_code=404, detail="Not found")
        # SPA fallback: serve the file if it exists, otherwise serve index.html.
        full_path = STATIC_DIR / path
        if full_path.is_file():
            return FileResponse(str(full_path))
        return FileResponse(str(index_path))


_setup_static_routes(app)
