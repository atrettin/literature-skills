"""The driver, end to end, against the collection fixture.

Nothing here calls a network: the `small_paper` fixture answers both arXiv
requests from `tests/data/small_paper.tar.gz`, and `FakeInspire` answers
INSPIRE. What is under test is the order of the steps and what each one leaves
on disk, which is the part no single script can check for itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import add_paper
import check_references
import inspire_lookup
from conftest import DATA, FakeInspire

ARXIV_ID = "2501.00001"
SLUG = "lovelace_2025_small_paper"


def run(collection: Path, *arguments: str) -> tuple[int, list[dict]]:
    """The driver, with its reports parsed. One JSON object per line."""
    import contextlib
    import io

    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        status = add_paper.main(
            [*arguments, "--literature-root", str(collection)]
        )
    reports = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    return status, reports


@pytest.fixture
def inspire_silent(monkeypatch: pytest.MonkeyPatch) -> FakeInspire:
    """INSPIRE holds nothing. The paper is then a preprint, which is an answer."""
    fake = FakeInspire({})
    monkeypatch.setattr(inspire_lookup, "fetch_record", fake)
    return fake


def test_one_run_ingests_the_paper(collection: Path, small_paper: dict,
                                   inspire_silent: FakeInspire) -> None:
    status, reports = run(collection, "--auto", ARXIV_ID)

    assert status == 0
    assert len(reports) == 1
    report = reports[0]
    assert report["status"] == "ingested"
    assert report["slug"] == SLUG
    assert report["exception"] is None

    paper_dir = collection / SLUG
    assert (paper_dir / "INDEX.md").is_file()
    assert (paper_dir / add_paper.MANIFEST_NAME).is_file()
    assert sorted(path.name for path in (paper_dir / "chapters").glob("*.md"))


def test_the_index_holds_the_counts(
    collection: Path, small_paper: dict, inspire_silent: FakeInspire
) -> None:
    run(collection, "--auto", ARXIV_ID)
    text = (collection / SLUG / "INDEX.md").read_text(encoding="utf-8")

    assert "| # | File | Words | Named anchors | Subsections |" in text
    # A preprint: INSPIRE answered nothing, so nothing invented a journal.
    assert "| Published | preprint |" in text


def test_the_collection_row_is_written(collection: Path, small_paper: dict,
                                       inspire_silent: FakeInspire) -> None:
    status, reports = run(collection, "--auto", ARXIV_ID)

    assert reports[0]["collection_row"] == "added"
    text = (collection / "README.md").read_text(encoding="utf-8")
    assert "[A Small Paper on Quasielastic Scattering](%s/INDEX.md)" % SLUG in text


def test_the_store_learns_the_paper(collection: Path, small_paper: dict,
                                    inspire_silent: FakeInspire) -> None:
    status, reports = run(collection, "--auto", ARXIV_ID)

    assert status == 0
    assert reports[0]["references"]["cited"] == 2
    # The fixture already holds both works this paper cites, so the merge
    # updates two records rather than adding two.
    assert reports[0]["references"]["updated"] + reports[0]["references"]["added"] == 2


def test_a_directory_that_exists_is_an_exception(
    collection: Path, small_paper: dict, inspire_silent: FakeInspire
) -> None:
    run(collection, "--auto", ARXIV_ID)
    status, reports = run(collection, "--auto", ARXIV_ID)

    assert status == 2
    assert reports[0]["status"] == "exception"
    assert reports[0]["exception"]["code"] == "SLUG_EXISTS"
    assert reports[0]["exception"]["slug"] == SLUG
    assert reports[0]["next_action"] == "handle_exception"


def test_force_replaces_it(collection: Path, small_paper: dict,
                           inspire_silent: FakeInspire) -> None:
    run(collection, "--auto", ARXIV_ID)
    status, reports = run(collection, "--auto", ARXIV_ID, "--force")

    assert status == 0
    assert reports[0]["collection_row"] == "present"


def test_a_source_with_no_section_fails_the_parse(
    collection: Path, small_paper: dict, inspire_silent: FakeInspire,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    import arxiv_fetch

    def bare(arxiv_id: str, work_dir: Path) -> Path:
        source_dir = work_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "main.tex").write_text(
            "\\documentclass{article}\\begin{document}\\end{document}",
            encoding="utf-8",
        )
        return source_dir

    monkeypatch.setattr(arxiv_fetch, "download_source", bare)
    status, reports = run(collection, "--auto", ARXIV_ID)

    assert status == 2
    assert reports[0]["exception"]["code"] == "PARSER_FAILURE"
    assert "main_tex" in reports[0]["exception"]


def test_no_source_is_its_own_exception(
    collection: Path, small_paper: dict, inspire_silent: FakeInspire,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    import arxiv_fetch

    def pdf_only(arxiv_id: str, work_dir: Path) -> Path:
        raise arxiv_fetch.NoSource("arXiv served a PDF for %s" % arxiv_id, http_status=403)

    monkeypatch.setattr(arxiv_fetch, "download_source", pdf_only)
    status, reports = run(collection, "--auto", ARXIV_ID)

    assert status == 2
    assert reports[0]["exception"]["code"] == "NO_ARXIV_SOURCE"
    assert reports[0]["exception"]["http_status"] == 403


def test_a_metadata_failure_is_reported_and_writes_nothing(
    collection: Path, small_paper: dict, inspire_silent: FakeInspire,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lookup that failed once put a paper on disk as `anon_nd`.

    The title, the authors and the year build the slug, the index and the
    collection row. A lookup that answered `{}` gave a paper with none of them,
    a meaningless directory name, and an exit code of 0.
    """
    import arxiv_fetch

    def refuse(arxiv_id: str) -> dict:
        raise arxiv_fetch.MetadataUnavailable("arXiv did not answer for %s" % arxiv_id)

    monkeypatch.setattr(arxiv_fetch, "fetch_metadata_by_id", refuse)
    status, reports = run(collection, "--auto", ARXIV_ID)

    assert status == 2
    assert reports[0]["exception"]["code"] == "NETWORK_UNAVAILABLE"
    assert reports[0]["exception"]["host"] == "export.arxiv.org"
    assert not (collection / "anon_nd").exists()
    assert not list(collection.glob("*_nd"))


def test_an_identifier_arxiv_does_not_know_is_not_ingestable(
    gate_off: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty feed means arXiv holds no such paper. It never means `{}`."""
    import arxiv_fetch

    monkeypatch.setattr(
        arxiv_fetch, "read_feed",
        lambda params: (DATA / "feed_empty.xml").read_text(encoding="utf-8"),
    )

    with pytest.raises(arxiv_fetch.NoSource):
        arxiv_fetch.fetch_metadata_by_id("2501.99999")


def test_an_arxiv_that_does_not_answer_raises(
    gate_off: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import arxiv_fetch

    def refuse(params: dict) -> str:
        raise RuntimeError("arXiv API request failed: timed out")

    monkeypatch.setattr(arxiv_fetch, "read_feed", refuse)

    with pytest.raises(arxiv_fetch.MetadataUnavailable):
        arxiv_fetch.fetch_metadata_by_id("2501.00001")


def test_metadata_comes_back_whole(gate_off: None, monkeypatch: pytest.MonkeyPatch) -> None:
    import arxiv_fetch

    monkeypatch.setattr(
        arxiv_fetch, "read_feed",
        lambda params: (DATA / "feed_quasielastic.xml").read_text(encoding="utf-8"),
    )

    found = arxiv_fetch.fetch_metadata_by_id("nothing-in-particular")

    assert found["title"]
    assert found["authors"]
    assert found["year"]


def test_a_citation_the_store_cannot_answer_fails_the_check(
    collection: Path, small_paper: dict, inspire_silent: FakeInspire
) -> None:
    # --no-references leaves the chapters citing the paper's own LaTeX keys,
    # and no record answers those.
    status, reports = run(collection, "--auto", ARXIV_ID, "--no-references")

    assert status == 2
    assert reports[0]["exception"]["code"] == "REFERENCE_CHECK_FAILED"
    assert reports[0]["exception"]["unresolved"]
    # The paper is on disk, and the collection lists it. The citations are what
    # failed, and the next run repairs those.
    assert (collection / SLUG / "INDEX.md").is_file()
    assert reports[0]["collection_row"] == "added"


def test_a_defect_of_another_paper_stays_elsewhere(
    collection: Path, small_paper: dict, inspire_silent: FakeInspire,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture's own paper cites a key nothing answers. That is not ours."""
    calls = []
    real = check_references.check

    def counted(root, paper=None):
        calls.append(paper)
        return real(root, paper)

    monkeypatch.setattr(check_references, "check", counted)
    status, reports = run(collection, "--auto", ARXIV_ID)

    assert status == 0
    assert reports[0]["checks"]["ok"] is True
    assert reports[0]["checks"]["elsewhere"]["unresolved"] >= 1
    assert reports[0]["checks"]["pre_existing"] >= 1
    # One scoped call, and never a second pass to subtract from.
    assert calls == [SLUG]


def test_residue_comes_from_the_check_and_not_from_a_scan(
    collection: Path, small_paper: dict, inspire_silent: FakeInspire,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    import arxiv_fetch

    original = arxiv_fetch.sanitise

    def with_residue(text: str) -> str:
        return original(text).replace("chi-square", "PH4")

    monkeypatch.setattr(arxiv_fetch, "sanitise", with_residue)
    status, reports = run(collection, "--auto", ARXIV_ID)

    codes = [entry["code"] for entry in reports[0]["warnings"]]
    assert "PLACEHOLDER_RESIDUE" in codes
    entry = next(item for item in reports[0]["warnings"]
                 if item["code"] == "PLACEHOLDER_RESIDUE")
    assert entry["count"] == len(reports[0]["checks"]["residue"])
    assert reports[0]["checks"]["residue"][0]["in"].startswith(SLUG + "/")


def test_index_only_rebuilds_the_counts(collection: Path, small_paper: dict,
                                        inspire_silent: FakeInspire) -> None:
    run(collection, "--auto", ARXIV_ID)
    index = collection / SLUG / "INDEX.md"
    index.write_text("# damaged\n", encoding="utf-8")

    status, reports = run(collection, "--index-only", SLUG)

    assert status == 0
    assert "| # | File | Words |" in index.read_text(encoding="utf-8")
    assert reports[0]["collection_row"] == "present"
