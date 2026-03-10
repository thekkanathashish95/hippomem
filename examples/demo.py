"""
hippomem demo — decode / encode / consolidate loop.

Usage:
    export LLM_API_KEY=sk-...
    python examples/demo.py

This demo simulates a 3-turn conversation and prints memory context at each turn.
No actual LLM calls — uses a mock response to demonstrate the memory update cycle.

Core API:
    memory.decode(user_id, message, ...)  → retrieve relevant memory context
    memory.encode(user_id, msg, reply, decode_result, ...)  → store the turn
    memory.consolidate(user_id)           → run decay / clustering maintenance
    memory.retrieve(user_id, query, ...)  → raw semantic search (optional)
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

    config = MemoryConfig(
        db_url="sqlite:///demo_memory.db",
        vector_dir="./demo_vectors",
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

            # Give background encode time to complete (not needed in production)
            await asyncio.sleep(3)

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

        # Run consolidation — decay stale events and cluster related ones.
        # Call this periodically in production (e.g. daily, or after N turns).
        print("\n=== Running consolidation ===")
        await memory.consolidate(user_id)
        print("Consolidation complete.")

        print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
