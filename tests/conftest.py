"""Fixtures shared by the tests.

`pytest.ini` puts the repository root on the path, so `litdb` imports here from
the working tree rather than from wherever it happens to be installed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent / "data"


@pytest.fixture
def collection(tmp_path: Path) -> Path:
    """A copy of the fixture collection, rendered and writable, one per test.

    A copy rather than the fixture itself: `mark_held` writes `held_as` back
    into the records it is given, and a test that saved the store would edit
    the fixture for every test after it.

    The fixture on disk holds only what is stored — `paper.json`, `text/` and
    the reference store. The render is written here rather than committed, so
    the two can never drift apart and every test that reads a rendered file
    reads one this renderer wrote.

    The directory on disk is not called `literature`. `.gitignore` holds
    `literature/` with no leading slash, which matches a directory of that name
    at any depth, so a fixture under that name would never be committed.
    """
    from lit import paths, render

    root = tmp_path / "collection"
    shutil.copytree(DATA / "collection_fixture", root)
    render.render_collection(root, paths.flavor(root))
    return root


@pytest.fixture
def stored_collection(tmp_path: Path) -> Path:
    """The fixture collection as it is stored, with nothing rendered.

    For a test about the store itself, and for one that renders the collection
    and asserts on what the render wrote.
    """
    root = tmp_path / "collection"
    shutil.copytree(DATA / "collection_fixture", root)
    return root


def write_paper(root: Path, slug: str, chapters: dict[str, list[dict]], **fields) -> Path:
    """Store a paper made up for one test. Returns its directory.

    `chapters` maps a chapter stem to its blocks. Every count `paper.json`
    carries is measured here rather than passed in, so a test never states a
    number that the store then contradicts.
    """
    import json

    from lit import blocks

    paper_dir = root / slug
    entries = []
    for stem, chapter_blocks in chapters.items():
        path = blocks.write(paper_dir / "text" / (stem + ".jsonl"), chapter_blocks)
        entries.append({
            "stem": stem,
            "number": str(len(entries) + 1),
            "title": stem.split("_", 1)[-1].replace("_", " ").title(),
            "subsections": [],
            "bytes": path.stat().st_size,
            "blocks": len(chapter_blocks),
            "words": sum(len(blocks.words(block).split()) for block in chapter_blocks),
            "anchors": blocks.anchors(chapter_blocks),
        })
    paper = {
        "arxiv_id": "", "slug": slug, "paper_dir": str(paper_dir),
        "title": slug, "authors": [], "year": None, "submitted_year": None,
        "abs_url": "", "journal_ref": "", "doi": "",
        "publication": {"source": "none", "journal": "", "published_year": None,
                        "doi": "", "errata": [], "inspire_url": ""},
        "abstract": "", "ingested": "2026-08-07", "parser": "texsoup",
        "chapters": entries, "figures": [], "labels": {},
        "unresolved_refs": [], "references": [], "warnings": [],
    }
    paper.update(fields)
    (paper_dir / "paper.json").write_text(
        json.dumps(paper, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return paper_dir


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
def gate_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Open the request gate for every host, so the suite never waits.

    The gate paces real API calls. Nothing in the offline suite calls an API, so
    every wait it would impose is a wait for nothing. It also writes a lock file
    under the collection root, which a test running against a read-only fixture
    has no use for.
    """
    import contextlib

    from lit import rate_gate

    @contextlib.contextmanager
    def open_gate(host: str, root=None):
        yield

    monkeypatch.setattr(rate_gate, "request", open_gate)
    rate_gate.reset()


@pytest.fixture
def no_sleep(gate_off: None) -> None:
    """The name the search tests ask for. The gate is what waited."""


class FakeInspire:
    """Stands in for `inspire_lookup.fetch_record`, and records what it was asked.

    Every request to INSPIRE in these scripts goes through that one function,
    whether it fetches a record by identifier or runs a search, so replacing it
    replaces the whole API. A test sets `answers`, keyed by a substring of the
    path, and reads `paths` to check what was asked for. A path no key matches
    answers 404, the same as a record INSPIRE does not hold.
    """

    def __init__(self, answers: dict[str, dict] | None = None) -> None:
        self.answers = answers or {}
        self.paths: list[str] = []

    def __call__(self, path: str) -> dict | None:
        self.paths.append(path)
        for key, payload in self.answers.items():
            if key in path:
                return payload
        return None

    def query(self, index: int = 0) -> str:
        """The `q=` of the index-th search, as it was sent."""
        import urllib.parse

        searches = [path for path in self.paths if path.startswith("literature?")]
        parsed = urllib.parse.parse_qs(searches[index].split("?", 1)[1])
        return parsed["q"][0]

    def params(self, index: int = 0) -> dict[str, str]:
        """Every parameter of the index-th search."""
        import urllib.parse

        searches = [path for path in self.paths if path.startswith("literature?")]
        parsed = urllib.parse.parse_qs(searches[index].split("?", 1)[1])
        return {name: values[0] for name, values in parsed.items()}


SMALL_PAPER_METADATA = {
    "arxiv_id": "2501.00001",
    "version": "v1",
    "title": "A Small Paper on Quasielastic Scattering",
    "authors": ["Ada Lovelace", "Grace Hopper"],
    "year": 2025,
    "published": "2025-01-02T00:00:00Z",
    "summary": "This paper measures a cross section. It then compares that "
               "measurement with a model.",
    "doi": "",
    "journal_ref": "",
    "comment": "",
    "pdf_url": "",
    "abs_url": "https://arxiv.org/abs/2501.00001",
}


@pytest.fixture
def small_paper(monkeypatch: pytest.MonkeyPatch, gate_off: None) -> dict:
    """arXiv, replaced by the small TeX archive in `tests/data`.

    Both requests the conversion sends are answered from disk: the metadata of
    the paper, and its source archive. Nothing here reaches a network, and the
    archive holds what the conversion has to handle — two sections, a labelled
    equation, a figure and a bibliography of two entries.
    """
    import tarfile

    from lit import arxiv_fetch
    from lit import arxiv_search

    def metadata(arxiv_id: str) -> dict:
        return dict(SMALL_PAPER_METADATA, arxiv_id=arxiv_id)

    def source(arxiv_id: str, work_dir: Path) -> Path:
        source_dir = work_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(DATA / "small_paper.tar.gz") as archive:
            archive.extractall(source_dir)
        return source_dir

    def empty_feed(params: dict) -> str:
        # arXiv knows none of the identifiers this paper's bibliography prints.
        # An empty answer rather than a raise: a raise would fail the whole
        # bibliography, and what is under test is a bibliography that resolves
        # to unconfirmed records, which is the common case.
        return (DATA / "feed_empty.xml").read_text(encoding="utf-8")

    monkeypatch.setattr(arxiv_fetch, "fetch_metadata_by_id", metadata)
    monkeypatch.setattr(arxiv_fetch, "download_source", source)
    # Both bindings, because `arxiv_fetch` imported the name for itself.
    monkeypatch.setattr(arxiv_search, "read_feed", empty_feed)
    monkeypatch.setattr(arxiv_fetch, "read_feed", empty_feed)
    return dict(SMALL_PAPER_METADATA)


@pytest.fixture
def inspire_payloads() -> dict[str, dict]:
    """The canned INSPIRE answers, read from tests/data."""
    import json

    return {
        name: json.loads((DATA / ("%s.json" % name)).read_text(encoding="utf-8"))
        for name in ("inspire_record", "inspire_refersto", "inspire_references", "inspire_recids")
    }


@pytest.fixture
def no_pace(gate_off: None) -> None:
    """The name the reference tests ask for. The gate is what paced them."""


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Refuse a real INSPIRE request in a test that did not ask for one.

    A search now describes its shortlist from INSPIRE. Without this, every test
    of the search would call the API, and the suite would answer differently on
    a machine with no network than on one with it. A test that means to reach
    INSPIRE replaces `fetch_record` itself, and its patch wins over this one.
    `references.search_payload` reads the failure as "INSPIRE said nothing",
    which is the case this guards.
    """
    if "network" in request.keywords:
        return

    from lit import arxiv_fetch
    from lit import arxiv_search
    from lit import inspire_lookup

    def refuse(path: str) -> dict | None:
        raise RuntimeError(
            "the offline tests do not call INSPIRE; patch inspire_lookup.fetch_record (%s)"
            % path
        )

    monkeypatch.setattr(inspire_lookup, "fetch_record", refuse)

    def refuse_arxiv(params: dict) -> str:
        raise RuntimeError(
            "the offline tests do not call arXiv; patch read_feed or fetch_feed (%s)"
            % params
        )

    # Both bindings. `arxiv_fetch` does `from arxiv_search import read_feed`, so
    # it holds a name of its own, and a patch of one module leaves the other
    # calling the real API. That is how a test came to wait on arXiv for three
    # seconds a retry while it believed it was offline.
    monkeypatch.setattr(arxiv_search, "read_feed", refuse_arxiv)
    monkeypatch.setattr(arxiv_fetch, "read_feed", refuse_arxiv)
