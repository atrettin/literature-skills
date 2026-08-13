#!/usr/bin/env python3
"""One gated request to an API, and the header that identifies us to it.

Every call to arXiv, INSPIRE-HEP and Crossref goes through `get`, so the pace
`rate_gate` holds covers all of them and one user agent names us everywhere.

What a failure means is left to the caller and is not decided here. A 404 from
INSPIRE means "no such record", a 404 from arXiv's e-print service means "this
submission carries no TeX", and a timeout at Crossref means "look it up
somewhere else". Those are three different answers to one HTTP status, so the
exception arrives at the caller intact.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from lit import rate_gate

USER_AGENT = "neutrino-factory-literature/0.1 (local research tooling)"


def get(url: str, host: str, timeout: float) -> bytes:
    """The body of one GET, sent while this process holds the gate for `host`.

    Exactly one request per call. Parsing the answer and deciding whether to
    retry belong outside, because the gate is held for as long as this runs and
    every other caller waits behind it.
    """
    query = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with rate_gate.request(host):
        with urllib.request.urlopen(query, timeout=timeout) as response:
            return response.read()


def get_text(url: str, host: str, timeout: float) -> str:
    return get(url, host, timeout).decode("utf-8", errors="replace")


def get_json(url: str, host: str, timeout: float) -> Any:
    return json.loads(get_text(url, host, timeout))


def retry_after(error: urllib.error.HTTPError, floor: float, ceiling: float) -> float:
    """How long to wait after a 429, never less than the rate-limit window.

    An API that says `Retry-After` knows better than we do, so its value wins
    where it is longer. The ceiling is there because a header saying "an hour"
    would hang a command that a person is waiting on.
    """
    delay = floor
    header = error.headers.get("Retry-After") if error.headers else None
    if header and str(header).strip().isdigit():
        delay = max(delay, float(str(header).strip()))
    return min(delay, ceiling)
