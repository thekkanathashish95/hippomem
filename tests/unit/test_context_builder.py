"""
Test: get_conversation_window([]) returns ""
Test: get_conversation_window(history, 2) returns last 2 turns formatted
Test: requesting more turns than available returns all available
Test: format_recent_turns formats as "User: ...\nAssistant: ..."
"""
from hippomem.decoder.context_builder import get_conversation_window, format_recent_turns


def test_get_conversation_window_empty():
    result = get_conversation_window([])
    assert result == ""


def test_get_conversation_window_last_two():
    # history = prior completed turns only (no current turn — it's passed separately to decode())
    history = [
        ("Hello", "Hi there"),
        ("How are you?", "I'm good"),
        ("What's up?", "Not much"),
    ]
    result = get_conversation_window(history, 2)
    expected = "User: How are you?\nAssistant: I'm good\nUser: What's up?\nAssistant: Not much"
    assert result == expected


def test_get_conversation_window_more_than_available():
    history = [
        ("Hello", "Hi"),
        ("Bye", "See you"),
    ]
    result = get_conversation_window(history, 5)
    expected = "User: Hello\nAssistant: Hi\nUser: Bye\nAssistant: See you"
    assert result == expected


def test_format_recent_turns():
    history = [
        ("First", "Response1"),
        ("Second", "Response2"),
        ("Third", "Response3"),  # current
    ]
    result = format_recent_turns(history, 3)  # should return 2 prior
    expected = "User: First\nAssistant: Response1\nUser: Second\nAssistant: Response2"
    assert result == expected


def test_format_recent_turns_no_previous():
    history = [("Current", "Response")]  # only current
    result = format_recent_turns(history, 2)
    assert result == "(No previous turns)"
