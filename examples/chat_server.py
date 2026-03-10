"""
hippomem chat server — standalone FastAPI wrapper for testing hippomem with Studio.

Canonical server is hippomem.server.app (used by `hippomem serve`). This file is
kept as a standalone reference for development.

Usage:
    pip install "."                  # from hippomem root
    cp .env.example .env             # fill in your API key
    python examples/chat_server.py   # starts on http://localhost:8000

For Studio dev (cd studio && npm run dev), the Vite proxy expects port 8719.
Use: hippomem serve  (or uvicorn examples.chat_server:app --port 8719)

Environment variables (see .env.example):
    LLM_API_KEY     — required; your OpenAI-compatible API key
    LLM_BASE_URL    — default: https://api.openai.com/v1
    LLM_MODEL       — model used by hippomem internally (default: gpt-4o-mini)
    CHAT_MODEL      — model used for actual chat responses (default: same as LLM_MODEL)
    SYSTEM_PROMPT   — base system prompt injected before memory context
    DB_URL          — SQLite path (default: sqlite:///hippomem_chat.db)
    VECTOR_DIR      — FAISS index directory (default: ./hippomem_chat_vectors)
"""
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from pydantic import BaseModel

from hippomem import MemoryConfig, MemoryService

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
CHAT_MODEL = os.environ.get("CHAT_MODEL", LLM_MODEL)
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    "You are a helpful assistant with access to long-term memory about the user.",
)

if not LLM_API_KEY:
    raise RuntimeError("LLM_API_KEY environment variable is required.")

# ── In-memory state ────────────────────────────────────────────────────────────

# Per-user conversation history: list of (user_msg, assistant_msg) tuples.
# Passed to decode() and encode() so hippomem has short-term context.
conversation_histories: dict[str, list[tuple[str, str]]] = {}

# Per-user message log returned by GET /messages.
message_logs: dict[str, list[dict]] = {}

# ── Global service instances (initialised in lifespan) ────────────────────────

memory: Optional[MemoryService] = None
llm_client: Optional[AsyncOpenAI] = None

# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global memory, llm_client

    config = MemoryConfig(
        llm_model=LLM_MODEL,
        db_url=os.environ.get("DB_URL", "sqlite:///hippomem_chat.db"),
        vector_dir=os.environ.get("VECTOR_DIR", "./hippomem_chat_vectors"),
    )
    memory = MemoryService(
        llm_api_key=LLM_API_KEY,
        llm_base_url=LLM_BASE_URL,
        config=config,
    )
    await memory.setup()
    logger.info("MemoryService ready  memory_model=%s  chat_model=%s", LLM_MODEL, CHAT_MODEL)

    llm_client = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

    yield

    await memory.close()
    logger.info("MemoryService closed.")


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="hippomem chat server", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
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


# ── Helpers ────────────────────────────────────────────────────────────────────


def _log(user_id: str, role: str, content: str, memory_context: Optional[str] = None) -> MessageOut:
    msg = MessageOut(
        id=str(uuid.uuid4()),
        role=role,
        content=content,
        memory_context=memory_context,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    message_logs.setdefault(user_id, []).append(msg.model_dump())
    return msg


# ── Routes ─────────────────────────────────────────────────────────────────────


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if not memory or not llm_client:
        raise HTTPException(status_code=503, detail="Service not ready.")

    history = conversation_histories.get(req.user_id, [])

    # 1. Decode — retrieve relevant memory context before the LLM call
    decode_result = await memory.decode(
        req.user_id,
        req.message,
        conversation_history=history,
    )

    if decode_result.context:
        logger.info(
            "decode() retrieved context for user=%s  events=%s",
            req.user_id,
            decode_result.used_engram_ids,
        )

    # 2. Build messages for the chat LLM call
    #    Memory context is injected into the system prompt, exactly as hippomem intends.
    system = SYSTEM_PROMPT
    if decode_result.context:
        system = f"{system}\n\n{decode_result.context}"

    messages: list[dict] = [{"role": "system", "content": system}]
    # Include recent turns for conversational continuity (capped at 6 to stay lean)
    for user_turn, assistant_turn in history[-6:]:
        messages.append({"role": "user", "content": user_turn})
        messages.append({"role": "assistant", "content": assistant_turn})
    messages.append({"role": "user", "content": req.message})

    # 3. Chat LLM call
    completion = await llm_client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,  # type: ignore[arg-type]
    )
    assistant_content = completion.choices[0].message.content or ""

    # 4. Encode — update hippomem with this turn (fire-and-forget)
    await memory.encode(
        req.user_id,
        req.message,
        assistant_content,
        decode_result,
        conversation_history=history,
    )

    # 5. Update local history (callers own the history list per hippomem pattern)
    conversation_histories[req.user_id] = history + [(req.message, assistant_content)]

    # 6. Log both messages; expose synthesized_context (raw, no markdown header) to the UI
    _log(req.user_id, "user", req.message)
    assistant_msg = _log(
        req.user_id,
        "assistant",
        assistant_content,
        memory_context=decode_result.synthesized_context or None,
    )

    return ChatResponse(message=assistant_msg)


@app.get("/messages", response_model=list[MessageOut])
async def get_messages(user_id: str) -> list[dict]:
    return message_logs.get(user_id, [])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "memory_model": LLM_MODEL, "chat_model": CHAT_MODEL}


# ── Inspector (traces + stats) ───────────────────────────────────────────────────


@app.get("/traces")
async def list_traces(user_id: str, limit: int = 50) -> dict:
    """Return LLM interaction summaries for the Inspector tab."""
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    return {"interactions": memory.list_interactions(user_id, limit)}


@app.get("/traces/{interaction_id}")
async def get_trace(interaction_id: str) -> dict:
    """Return full interaction detail with call logs."""
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    detail = memory.get_interaction_detail(interaction_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return detail


@app.get("/stats")
async def get_stats(user_id: str) -> dict:
    """Return memory counts + usage aggregates for the Dashboard."""
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    return memory.get_stats(user_id)


# ── Memory Explorer (read-only) ─────────────────────────────────────────────────


@app.get("/memory/graph/{user_id}")
async def get_memory_graph(user_id: str) -> dict:
    """Return all nodes and edges for the memory explorer graph."""
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    return memory.get_graph_for_explorer(user_id)


@app.get("/memory/events/{user_id}/{event_uuid}")
async def get_event_detail(user_id: str, event_uuid: str) -> dict:
    """Return full event detail for the memory explorer."""
    if not memory:
        raise HTTPException(status_code=503, detail="Service not ready.")
    detail = memory.get_event_detail_for_explorer(user_id, event_uuid)
    if detail is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    return detail


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
