"""The request gate: one request at a time, and one pace per host."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

import rate_gate


@pytest.fixture(autouse=True)
def clean_gate() -> Iterator[None]:
    rate_gate.reset()
    yield
    rate_gate.reset()


def test_two_threads_do_not_overlap(tmp_path: Path) -> None:
    """Two callers of one host hold the gate one after the other, never together."""
    rate_gate.set_interval("test.example", 0.0)
    inside = []
    overlapped = []
    lock = threading.Lock()

    def call() -> None:
        with rate_gate.request("test.example", root=tmp_path):
            with lock:
                inside.append(1)
                if len(inside) > 1:
                    overlapped.append(1)
            time.sleep(0.02)
            with lock:
                inside.pop()

    threads = [threading.Thread(target=call) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not overlapped


def test_the_second_request_waits_the_interval(tmp_path: Path) -> None:
    rate_gate.set_interval("slow.example", 0.3)

    with rate_gate.request("slow.example", root=tmp_path):
        pass
    started = time.monotonic()
    with rate_gate.request("slow.example", root=tmp_path):
        pass
    waited = time.monotonic() - started

    assert waited >= 0.25


def test_another_host_does_not_wait(tmp_path: Path) -> None:
    """The pace is per host. A slow API never holds up a fast one."""
    rate_gate.set_interval("slow.example", 0.5)
    rate_gate.set_interval("fast.example", 0.0)

    with rate_gate.request("slow.example", root=tmp_path):
        pass
    started = time.monotonic()
    with rate_gate.request("fast.example", root=tmp_path):
        pass

    assert time.monotonic() - started < 0.2


def test_an_unknown_host_gets_the_default(tmp_path: Path) -> None:
    assert rate_gate.interval_for("nobody.example") == rate_gate.DEFAULT_INTERVAL_S


def test_the_file_holds_the_time_of_each_host(tmp_path: Path) -> None:
    rate_gate.set_interval("noted.example", 0.0)
    with rate_gate.request("noted.example", root=tmp_path):
        pass

    state = json.loads((tmp_path / rate_gate.GATE_NAME).read_text(encoding="utf-8"))
    assert "noted.example" in state
    assert state["noted.example"] > 0


def test_a_lock_another_process_holds_makes_this_one_wait(tmp_path: Path) -> None:
    """A second process holding the file is what the cross-process lock is for."""
    fcntl = pytest.importorskip("fcntl")
    rate_gate.set_interval("locked.example", 0.0)
    path = tmp_path / rate_gate.GATE_NAME
    path.write_text("{}", encoding="utf-8")

    holder = open(path, "a+", encoding="utf-8")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)

    released = threading.Event()

    def let_go() -> None:
        time.sleep(0.25)
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
        released.set()

    threading.Thread(target=let_go).start()
    started = time.monotonic()
    with rate_gate.request("locked.example", root=tmp_path):
        pass
    waited = time.monotonic() - started

    assert released.is_set()
    assert waited >= 0.2


def test_a_timeout_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fcntl = pytest.importorskip("fcntl")
    rate_gate.set_interval("stuck.example", 0.0)
    path = tmp_path / rate_gate.GATE_NAME
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rate_gate, "GATE_WAIT_TIMEOUT_S", 0.2)

    holder = open(path, "a+", encoding="utf-8")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    try:
        with pytest.raises(rate_gate.GateTimeout):
            with rate_gate.request("stuck.example", root=tmp_path):
                pass
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()


def test_a_root_nothing_can_write_falls_back_and_says_so(tmp_path: Path) -> None:
    """A read-only collection still gets a pace, and the report names the weaker one."""
    rate_gate.set_interval("readonly.example", 0.0)
    root = tmp_path / "readonly"
    root.mkdir()
    os.chmod(root, 0o500)
    try:
        assert rate_gate.local_only() is False
        with rate_gate.request("readonly.example", root=root):
            pass
        assert rate_gate.local_only() is True
        assert not (root / rate_gate.GATE_NAME).exists()
    finally:
        os.chmod(root, 0o700)


def test_a_damaged_gate_file_is_an_empty_one(tmp_path: Path) -> None:
    rate_gate.set_interval("damaged.example", 0.0)
    (tmp_path / rate_gate.GATE_NAME).write_text("not json at all", encoding="utf-8")

    with rate_gate.request("damaged.example", root=tmp_path):
        pass

    state = json.loads((tmp_path / rate_gate.GATE_NAME).read_text(encoding="utf-8"))
    assert "damaged.example" in state


def test_every_api_this_repository_calls_has_a_pace() -> None:
    """Each host a script sends a request to is registered by the module owning it."""
    import arxiv_search  # noqa: F401
    import inspire_lookup  # noqa: F401
    import references  # noqa: F401

    for host in ("export.arxiv.org", "arxiv.org", "inspirehep.net", "api.crossref.org"):
        assert host in rate_gate.HOST_INTERVALS
