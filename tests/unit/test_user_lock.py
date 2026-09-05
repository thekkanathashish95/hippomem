"""Per-user encode lock serializes concurrent writes for the same user."""
import threading
import time

from hippomem.service import MemoryService


def _bare_service() -> MemoryService:
    svc = MemoryService.__new__(MemoryService)
    svc._user_locks = {}
    svc._user_locks_guard = threading.Lock()
    return svc


def test_same_user_encode_is_serialized():
    svc = _bare_service()
    started: list[float] = []

    def unlocked(*_args, **_kwargs):
        started.append(time.monotonic())
        time.sleep(0.08)

    svc._encode_sync_unlocked = unlocked  # type: ignore[method-assign]

    def run(turn: str) -> None:
        svc._encode_sync("u1", None, [], [], "", "", [], turn)

    t1 = threading.Thread(target=run, args=("t1",))
    t2 = threading.Thread(target=run, args=("t2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(started) == 2
    assert abs(started[1] - started[0]) >= 0.07


def test_different_users_can_overlap():
    svc = _bare_service()
    barrier = threading.Barrier(2)
    overlapping = threading.Event()

    def unlocked(*_args, **_kwargs):
        barrier.wait(timeout=1)
        overlapping.set()
        time.sleep(0.02)

    svc._encode_sync_unlocked = unlocked  # type: ignore[method-assign]

    t1 = threading.Thread(target=lambda: svc._encode_sync("a", None, [], [], "", "", [], "t1"))
    t2 = threading.Thread(target=lambda: svc._encode_sync("b", None, [], [], "", "", [], "t2"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert overlapping.is_set()
