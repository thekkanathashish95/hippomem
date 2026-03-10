"""
Conversation context helpers for the memory retrieval cascade.

Used by C1 (Continuation Check), C2 (Local Scan), and C3 (Long-Term Retrieval)
to format recent turns into strings suitable for LLM prompts.

hippomem is stateless: callers own conversation_history and pass it in.
No DB access occurs here — these are pure formatting utilities.
"""
from typing import List, Tuple


def get_conversation_window(
    conversation_history: List[Tuple[str, str]],
    num_turns: int = 2,
) -> str:
    """
    Get the last N turns formatted as 'User: ...\\nAssistant: ...'.

    Args:
        conversation_history: List of (user_message, assistant_response) pairs,
            oldest first. Do NOT include the current (unanswered) turn —
            the current message is passed separately to decode().
        num_turns: Number of prior turn pairs to include.

    Returns:
        Formatted string: 'User: ...\\nAssistant: ...\\n...'
    """
    if not conversation_history:
        return ""
    window = conversation_history[-num_turns:] if num_turns > 0 else []
    lines = []
    for user_msg, asst_msg in window:
        lines.append(f"User: {user_msg}")
        lines.append(f"Assistant: {asst_msg}")
    return "\n".join(lines)


def format_recent_turns(
    conversation_history: List[Tuple[str, str]],
    num_turns: int,
) -> str:
    """
    Format last (num_turns - 1) previous turns for LLM prompts.
    Current turn is always passed separately; this returns only prior context.

    Args:
        conversation_history: List of (user_message, assistant_response) pairs.
            The last element is the current turn.
        num_turns: Window size including current turn (so returns num_turns-1 prior).

    Returns:
        Formatted string or "(No previous turns)"
    """
    if not conversation_history or num_turns <= 1:
        return "(No previous turns)"
    previous = conversation_history[:-1]
    slice_ = previous[-(num_turns - 1):]
    if not slice_:
        return "(No previous turns)"
    lines = []
    for u, a in slice_:
        lines.append(f"User: {u}")
        lines.append(f"Assistant: {a}")
    return "\n".join(lines)
