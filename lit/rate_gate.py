#!/usr/bin/env python3
"""One request at a time to an API that limits its rate.

arXiv asks for three seconds between calls. INSPIRE-HEP allows 15 requests in
any five-second window. A script that sends two requests at once trips both,
and every request of that pair fails.

The old rule was "one agent at a time". That rule also stops work the limit
allows: a download of one paper and a reference lookup for another are two
requests, and the limit counts requests rather than agents. This module counts
requests. A caller holds the gate for the length of one request, and the gate
holds each host to its own minimum interval.

    with rate_gate.request("export.arxiv.org"):
        with urllib.request.urlopen(...) as response:
            ...

The gate works across processes. Two shells, or an agent beside a running
ingest, must not double the request rate, so the gate holds an exclusive lock
on `<literature-root>/.api-gate.json.lock` while `.api-gate.json` beside it
holds the time of the last request to each host.

A collection root that nothing can write gives a lock inside this process alone.
`local_only()` then answers true, and the caller reports it: two processes are
then paced independently, which is a weaker guarantee than the one above.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import filelock

from lit import paths

GATE_NAME = ".api-gate.json"

# The minimum interval between two requests to one host, in seconds. Each entry
# is registered by the module that owns the constant, so the pace an API asks
# for has one definition: `arxiv_search.COURTESY_DELAY_S`,
# `inspire_lookup.INSPIRE_PACE_S`, `references.CROSSREF_PACE_S`.
HOST_INTERVALS: dict[str, float] = {}

# What a host nobody registered gets. One second is slower than every pace
# registered below, so an unknown host is paced conservatively rather than not
# at all.
DEFAULT_INTERVAL_S = 1.0

# How long a caller waits for the lock before it gives up. It bounds a wait, and
# it makes nothing faster. A timeout means another process holds the gate and is
# not letting go, which the caller reports as a network failure.
GATE_WAIT_TIMEOUT_S = 120.0

class GateTimeout(RuntimeError):
    """Nobody released the gate within `GATE_WAIT_TIMEOUT_S`."""


def set_interval(host: str, seconds: float) -> None:
    """Register the pace one host asks for.

    The module that defines the constant calls this at import time. The gate
    imports nothing from its callers, which is what keeps it out of the import
    cycle they form among themselves.
    """
    HOST_INTERVALS[host] = seconds


def interval_for(host: str) -> float:
    return HOST_INTERVALS.get(host, DEFAULT_INTERVAL_S)


# --------------------------------------------------------------------------
# the fallback, for a root that cannot hold the gate file
# --------------------------------------------------------------------------

_process_lock = threading.Lock()
_local_times: dict[str, float] = {}
_local_only = False

# The collection this process works on. A script that takes `--literature-root`
# sets it after it parses its arguments, so the gate locks the collection the
# caller named rather than whichever one the working directory happens to hold.
_root: Path | None = None


def use_root(root: Path) -> None:
    """Name the collection whose gate file this process shares.

    Without this the gate falls back to `paths.default_root()`, which
    is relative to the working directory. Two processes on one collection,
    started from two directories, would then take two different locks and neither
    would hold the other back — which is the whole of what the gate promises.
    """
    global _root
    _root = root


def local_only() -> bool:
    """Whether any request so far fell back to a lock inside this process."""
    return _local_only


def reset() -> None:
    """Forget the fallback flag, the local times and the root. For the tests."""
    global _local_only, _root
    _local_only = False
    _root = None
    _local_times.clear()


def gate_path(root: Path | None = None) -> Path:
    if root is None:
        root = _root
    if root is None:
        root = paths.default_root()
    return root / GATE_NAME


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------


def _open_gate_file(root: Path | None):
    """The gate file, opened for reading and writing, or None.

    None means this machine cannot hold the shared state: a collection that is
    not there, or a root nothing may write. Either is a reason to pace inside
    this process instead of failing — the request itself is still worth
    sending.

    It never creates the collection directory. A gate that made one would leave
    an empty `literature/` behind in whatever directory a script ran from, and
    would take its lock there rather than on the collection the caller named.
    `init-literature` makes a collection; this only locks one.
    """
    path = gate_path(root)
    if not path.parent.is_dir():
        return None
    try:
        return open(path, "a+", encoding="utf-8")
    except OSError:
        return None


def _read_state(handle) -> dict:
    """The time of the last request to each host. A damaged file is an empty one.

    The gate is a pace, not a record. A file that cannot be parsed costs one
    request sent earlier than it should have been, and rewriting it is what
    repairs the pace for every request after this one.
    """
    try:
        handle.seek(0)
        loaded = json.loads(handle.read() or "{}")
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_state(handle, state: dict) -> None:
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(state, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
    except OSError:
        pass


def _wait(last: float, interval: float, now: float) -> None:
    """Sleep out the rest of the interval since the last request to this host.

    The times are wall clock, because two processes have to agree on them. A
    clock that moves backwards would otherwise ask for an unbounded wait, so the
    wait is never longer than the interval itself.
    """
    if not last:
        return
    delay = min(interval - (now - last), interval)
    if delay > 0:
        time.sleep(delay)


@contextlib.contextmanager
def request(host: str, root: Path | None = None) -> Iterator[None]:
    """Hold the gate for one request to `host`.

    The body of the `with` sends exactly one request. Everything else — parsing
    the answer, retrying, writing a file — belongs outside it, because the gate
    is held for as long as the body runs and every other caller waits.
    """
    global _local_only
    interval = interval_for(host)
    handle = _open_gate_file(root)

    if handle is None:
        _local_only = True
        with _process_lock:
            _wait(_local_times.get(host, 0.0), interval, time.time())
            try:
                yield
            finally:
                _local_times[host] = time.time()
        return

    lock = filelock.FileLock(str(gate_path(root)) + ".lock",
                             timeout=GATE_WAIT_TIMEOUT_S)
    # The threads of this process queue here, so only one of them competes for
    # the file lock and the others do not spin on it.
    with _process_lock:
        with handle:
            try:
                lock.acquire()
            except filelock.Timeout as error:
                raise GateTimeout(
                    "no API request slot within %.0f seconds; another process "
                    "holds %s" % (GATE_WAIT_TIMEOUT_S, lock.lock_file)
                ) from error
            try:
                state = _read_state(handle)
                last = state.get(host)
                _wait(float(last) if isinstance(last, (int, float)) else 0.0,
                      interval, time.time())
                try:
                    yield
                finally:
                    state[host] = time.time()
                    _write_state(handle, state)
            finally:
                lock.release()
