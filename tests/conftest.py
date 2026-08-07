"""Fixtures shared by the tests.

The scripts are not a package. They import each other by name, relying on the
`sys.path.insert` that each one does at import time. The tests need the same
directory on the path before they can import anything at all, so it happens here
rather than in every test file.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "add-paper" / "scripts"
DATA = Path(__file__).resolve().parent / "data"

sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def collection(tmp_path: Path) -> Path:
    """A copy of the fixture collection, writable, one per test.

    A copy rather than the fixture itself: `mark_held` writes `held_as` back
    into the records it is given, and a test that saved the store would edit
    the fixture for every test after it.

    The directory on disk is not called `literature`. `.gitignore` holds
    `literature/` with no leading slash, which matches a directory of that name
    at any depth, so a fixture under that name would never be committed.
    """
    root = tmp_path / "collection"
    shutil.copytree(DATA / "collection_fixture", root)
    return root


@pytest.fixture
def feed_quasielastic() -> str:
    return (DATA / "feed_quasielastic.xml").read_text(encoding="utf-8")


@pytest.fixture
def feed_empty() -> str:
    return (DATA / "feed_empty.xml").read_text(encoding="utf-8")


def first_entry_only(feed_xml: str) -> str:
    """The same feed carrying one paper, for a rung that answered thinly."""
    import xml.etree.ElementTree as ET

    atom = "{http://www.w3.org/2005/Atom}"
    ET.register_namespace("", atom.strip("{}"))
    root = ET.fromstring(feed_xml)
    for extra in root.findall(atom + "entry")[1:]:
        root.remove(extra)
    return ET.tostring(root, encoding="unicode")


class FakeFetch:
    """Stands in for `arxiv_search.fetch_feed`, and records what it was asked.

    A test asserts on `queries` to check the query the ladder built, and sets
    `feeds` to choose what each successive rung gets back. The last feed repeats
    once the list runs out, so a test that cares about only the first rung need
    supply only one.
    """

    def __init__(self, feeds: list[str]) -> None:
        self.feeds = feeds
        self.queries: list[str] = []
        self.max_results: list[int] = []

    def __call__(self, search_query: str, max_results: int) -> str:
        self.queries.append(search_query)
        self.max_results.append(max_results)
        index = min(len(self.queries) - 1, len(self.feeds) - 1)
        return self.feeds[index]


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the courtesy delay between rungs. Nothing here calls arXiv."""
    import arxiv_discover

    monkeypatch.setattr(arxiv_discover.time, "sleep", lambda seconds: None)
