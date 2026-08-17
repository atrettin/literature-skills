"""Finding a phrase in the text of the papers.

Every failure this covers is a false negative: text that is present and that a
plain search reports as absent. A false negative here becomes a report that says
a paper does not hold a claim it does hold, and the reader of that report cannot
see the error.

Each test stores the chapter it needs in its own copy of the fixture collection,
so the phrase under test is the only thing that matches it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lit import blocks
from lit import arxiv_fetch, search_literature

PAPER = "jeong_2023_shallow_deep_inelastic"
OTHER = "juszczak_2003_recoil_nucleon_spectrum"


def write_chapter(collection: Path, slug: str, stem: str, *stored: dict) -> Path:
    """Store one chapter, as a list of blocks. Returns the file.

    Every block leaves the ingest with an address, so a chapter written for a
    test has them too: a fixture whose blocks cannot be addressed would test a
    store the conversion never produces.
    """
    chapter = arxiv_fetch.fallback_anchors(
        arxiv_fetch.paragraph_anchors([dict(block) for block in stored])
    )
    return blocks.write(collection / slug / "text" / (stem + ".jsonl"), chapter)


def prose(text: str, anchor: str = "") -> dict:
    return {"kind": "paragraph", "anchor": anchor, "text": text}


def run(collection: Path, *arguments: str, capsys=None) -> tuple[int, dict]:
    """The script as a caller runs it: an exit status and the JSON it printed."""
    status = search_literature.main(
        [*arguments, "--literature-root", str(collection)]
    )
    assert capsys is not None
    return status, json.loads(capsys.readouterr().out)


def test_a_line_break_inside_the_phrase_does_not_stop_the_match(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The failure this tool exists for: chapter text wraps, and a phrase spans lines."""
    write_chapter(collection, PAPER, "09_wrapped", prose(
        "The anomalies are not sufficient to explain the entirety of the "
        "observed excess."
    ))

    # The phrase as a reader copied it out of a preview, which wrapped it.
    status, report = run(
        collection, "not sufficient to explain the\nentirety", capsys=capsys
    )

    assert status == 0
    assert report["matches"] == 1
    assert report["results"][0]["location"].startswith("%s/09_wrapped#" % PAPER)


def test_a_nul_byte_does_not_hide_the_file(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`grep` prints nothing at all for such a file, and says nothing about why."""
    path = write_chapter(collection, PAPER, "09_binary",
                         prose("The axial mass is measured in deuterium."))
    # Inside the stored string, which is where a bad conversion would put it.
    path.write_bytes(path.read_bytes().replace(b"axial", b"a\x00xial"))

    status, report = run(collection, "axial mass is measured", capsys=capsys)

    assert status == 0
    assert report["matches"] == 1
    assert any("09_binary" in warning for warning in report["warnings"])


def test_the_result_gives_the_anchor_above_the_match(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_chapter(
        collection, PAPER, "09_anchored",
        prose("Text before any anchor names the resonance region."),
        {"kind": "heading", "level": 2, "number": "9", "title": "Transition",
         "anchor": "sec-transition"},
        prose("The transition region begins at two GeV.", "p1"),
    )

    _, report = run(collection, "transition region begins", capsys=capsys)
    assert report["results"][0]["anchor"] == "p1"
    assert report["results"][0]["location"] == "%s/09_anchored#p1" % PAPER

    # A block the paper gave no label of its own is still addressed. Nothing in
    # a chapter is reachable only by naming the chapter around it.
    _, above = run(collection, "before any anchor", capsys=capsys)
    assert above["results"][0]["anchor"]
    assert above["results"][0]["location"].startswith("%s/09_anchored#" % PAPER)


def test_no_result_carries_a_line_number(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The anchor is the one address. A line number describes the file, not the paper:
    it moves whenever the paper is ingested again, and a reader cannot see that it has.
    """
    write_chapter(collection, PAPER, "09_lines",
                  prose("one"), prose("two"), prose("three"),
                  prose("the phrase to find"), prose("five"))

    _, report = run(collection, "the phrase to find", capsys=capsys)

    found = report["results"][0]
    assert "line" not in found and "line_location" not in found
    # `b4`, not `p4`: these blocks are shorter than a paragraph anchor is given
    # for, and the fallback addresses what the paragraph count leaves.
    assert found["location"] == "%s/09_lines#b4" % PAPER


def test_the_sentence_stops_at_the_sentence_boundary(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_chapter(collection, PAPER, "09_sentences", prose(
        "A sentence before it. The phrase to find stands here. A sentence after it."
    ))

    _, report = run(collection, "the phrase to find", capsys=capsys)

    assert report["results"][0]["sentence"] == "The phrase to find stands here."


def test_a_long_sentence_is_cut_at_context_chars(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    filler = "word " * 200
    write_chapter(collection, PAPER, "09_long",
                  prose("%s the phrase to find %s." % (filler, filler)))

    _, report = run(collection, "the phrase to find", capsys=capsys)
    sentence = report["results"][0]["sentence"]

    assert len(sentence) <= search_literature.CONTEXT_CHARS
    assert "the phrase to find" in sentence
    assert sentence.startswith(search_literature.ELLIPSIS)


def test_the_match_ignores_case_unless_it_is_told_not_to(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_chapter(collection, PAPER, "09_case", prose("The Axial Mass of the nucleon."))

    _, ignoring = run(collection, "axial mass of the nucleon", capsys=capsys)
    assert ignoring["matches"] == 1

    status, exact = run(
        collection, "axial mass of the nucleon", "--case-sensitive", capsys=capsys
    )
    assert status == 1
    assert exact["matches"] == 0


def test_a_phrase_that_matches_nothing_reports_the_part_that_does(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """"Absent" is a claim, and this is the evidence for it."""
    write_chapter(collection, PAPER, "09_partial",
                  prose("The axial mass extracted from deuterium data."))

    status, report = run(
        collection, "the axial mass extracted from muon capture", capsys=capsys
    )

    assert status == 1
    assert report["matches"] == 0
    assert report["partial_matches"][0]["phrase"] == "the axial mass extracted from"
    assert any(
        result["chapter"] == "09_partial"
        for result in report["partial_matches"][0]["results"]
    )


def test_the_default_scope_is_the_text_of_the_papers(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only the store is read: no rendered file of any flavor can match."""
    (collection / "README.md").write_text("a rendered phrase\n", encoding="utf-8")
    pages = collection / "references"
    pages.mkdir(exist_ok=True)
    (pages / "some_tag.md").write_text("a rendered phrase\n", encoding="utf-8")
    chapters = collection / PAPER / "chapters"
    chapters.mkdir(parents=True, exist_ok=True)
    (chapters / "09_rendered.md").write_text("a rendered phrase\n", encoding="utf-8")
    write_chapter(collection, PAPER, "09_scope", prose("a rendered phrase"))

    _, report = run(collection, "a rendered phrase", capsys=capsys)

    assert report["matches"] == 1
    assert report["results"][0]["paper"] == PAPER


def test_a_regex_matches_against_the_flat_text(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plain space in the pattern matches a run of whitespace of any length."""
    write_chapter(collection, PAPER, "09_regex", prose("The axial mass is 1.03 GeV."))

    _, report = run(collection, r"axial mass is 1\.03", "--regex", capsys=capsys)

    assert report["matches"] == 1


def test_max_results_caps_the_results_and_says_so(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_chapter(collection, PAPER, "09_many",
                  *[prose("the phrase to find.") for _ in range(10)])

    _, report = run(collection, "the phrase to find", "--max-results", "3",
                    capsys=capsys)

    assert report["matches"] == 10
    assert len(report["results"]) == 3
    assert report["truncated"] is True


def test_paper_hides_a_hit_in_a_paper_of_another_task(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The collection outlives the query: a hit can come from someone else's subject."""
    write_chapter(collection, PAPER, "09_mine", prose("the phrase to find"))
    write_chapter(collection, OTHER, "09_theirs", prose("the phrase to find"))

    _, everywhere = run(collection, "the phrase to find", capsys=capsys)
    assert everywhere["matches"] == 2

    _, mine = run(collection, "the phrase to find", "--scope", PAPER, capsys=capsys)
    assert mine["matches"] == 1
    assert mine["scope"]["papers"] == [PAPER]


def test_an_unknown_slug_exits_rather_than_reporting_no_match(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Status 1 means the phrase is absent, and this phrase was never searched for."""
    status, report = run(collection, "the axial mass", "--scope", "no_such_paper",
                         capsys=capsys)

    assert status == 2
    assert report["unknown_paper"] == "no_such_paper"


def test_the_report_names_its_own_scope(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A reader can then see that a search covered one paper of two."""
    write_chapter(collection, PAPER, "09_scoped", prose("the phrase to find"))

    _, whole = run(collection, "the phrase to find", capsys=capsys)
    assert whole["scope"]["asked"] == ["disk"]
    assert whole["scope"]["papers"] == sorted([PAPER, OTHER])

    _, one = run(collection, "the phrase to find", "--scope", PAPER, capsys=capsys)
    assert one["scope"]["asked"] == [PAPER]
    assert one["scope"]["papers"] == [PAPER]
    assert one["scope"]["chapters"] < whole["scope"]["chapters"]
