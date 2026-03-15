"""
hippomem demo — decode / encode / consolidate / retrieve.

Usage:
    export LLM_API_KEY=sk-...
    python examples/demo.py

This demo simulates a 3-turn conversation and exercises all four core API calls.

Core API:
    memory.decode(user_id, message, ...)           → retrieve and synthesize memory context
    memory.encode(user_id, msg, reply, result, ...) → store the completed turn
    memory.consolidate(user_id)                    → periodic maintenance (compression, persona)
    memory.retrieve(user_id, query, ...)           → raw structured search, no LLM synthesis
"""
import asyncio
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, rely on environment variables

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from hippomem import MemoryService, MemoryConfig


CONVERSATION = [
    ("I'm building a FastAPI app with JWT auth.", "Sounds great! JWT is a solid choice for stateless auth."),
    ("I'm having trouble with token expiry handling.", "You can use a refresh token pattern — short-lived access tokens + long-lived refresh tokens."),
    ("Can you remind me what auth approach I chose?", None),  # Last message — no response yet
]


async def main():
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        print("Set LLM_API_KEY environment variable.")
        sys.exit(1)

    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("LLM_MODEL")

    _here = os.path.dirname(os.path.abspath(__file__))
    config = MemoryConfig(
        db_url=f"sqlite:///{os.path.join(_here, 'demo_memory.db')}",
        vector_dir=os.path.join(_here, "demo_vectors"),
    )
    if model:
        config.llm_model = model

    user_id = "demo_user_001"

    async with MemoryService(llm_api_key=api_key, llm_base_url=base_url, config=config) as memory:
        print("=== hippomem demo ===\n")

        # Callers own conversation_history — build it turn by turn.
        history: list = []

        # Simulate first two turns (encode only, no decode needed yet)
        for user_msg, assistant_msg in CONVERSATION[:2]:
            print(f"User: {user_msg}")
            print(f"Assistant: {assistant_msg}\n")

            # Decode before each turn (empty at start)
            result = await memory.decode(user_id, user_msg, conversation_history=history)
            if result.context:
                print(f"[Memory context passed to LLM]\n{result.context}\n")

            # Encode after each turn; pass the same history so updater has context
            await memory.encode(
                user_id, user_msg, assistant_msg, result,
                conversation_history=history,
            )
            history.append((user_msg, assistant_msg))

        # Third turn — demonstrate decode with real memory
        user_msg = CONVERSATION[2][0]
        print(f"User: {user_msg}\n")
        result = await memory.decode(user_id, user_msg, conversation_history=history)

        if result.context:
            print("=== Memory retrieved ===")
            print(result.context)
            print(f"\n[Reasoning: {result.reasoning}]")
            print(f"[Events used: {result.used_engram_ids}]")
        else:
            print("[No memory context — either LLM keys are not set or memory is empty]")

        # retrieve() — raw structured search, independent of the decode/encode lifecycle.
        # No LLM calls are made; returns episodes with linked entities and graph neighbours.
        # Use this to power search UIs or query memory outside of a conversation turn.
        print("\n=== retrieve(): raw structured search ===")
        search = await memory.retrieve(user_id, "JWT authentication approach", mode="hybrid", top_k=3)
        print(f"Found {search.total_primary} primary episode(s).\n")
        for ep in search.episodes:
            print(f"  [{ep.source}  score={ep.score:.2f}]  {ep.core_intent}")
            if ep.updates:
                for fact in ep.updates[:3]:
                    print(f"    • {fact}")
            if ep.entities:
                names = ", ".join(e.core_intent for e in ep.entities)
                print(f"    entities: {names}")
            if ep.related_episodes:
                related = ", ".join(r.core_intent for r in ep.related_episodes)
                print(f"    related:  {related}")
            print()

        # consolidate() — periodic maintenance: compresses episode facts, enriches entity
        # profiles, prunes stale self-traits, and regenerates the persona engram.
        # Call on a schedule (e.g. daily) or after a fixed number of turns.
        print("=== consolidate(): periodic maintenance ===")
        await memory.consolidate(user_id)
        print("Consolidation complete.")

        print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
