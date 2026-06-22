from __future__ import annotations

import sqlite3
import threading

from vesper.storage import PreferenceStore


def test_start_and_stop_session_toggles_active(settings) -> None:
    store = PreferenceStore(settings.database_path)

    started = store.start_session(request_text="play some music")
    assert started["is_active"] is True
    assert store.get_active_session() is not None

    stopped = store.stop_active_session()
    assert stopped is not None
    assert stopped["is_active"] is False
    assert store.get_active_session() is None


def test_concurrent_start_session_leaves_exactly_one_active(settings) -> None:
    # Without lifecycle serialization, two concurrent start_session calls can
    # interleave deactivate-all-then-insert on separate connections and leave
    # more than one row with is_active = 1. The lifecycle lock must prevent that.
    store = PreferenceStore(settings.database_path)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(10):
                store.start_session(request_text="play some music")
        except BaseException as exc:  # pragma: no cover - records any failure
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    with sqlite3.connect(settings.database_path) as connection:
        active = connection.execute("SELECT COUNT(*) FROM sessions WHERE is_active = 1").fetchone()[0]
    assert active == 1
