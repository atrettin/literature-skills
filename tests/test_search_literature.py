"""Finding a phrase in the text of the papers.

Every failure this covers is a false negative: text that is present and that a
plain search reports as absent. A false negative here becomes a report that says
a paper does not hold a claim it does hold, and the reader of that report cannot
see the error.

Each test writes the chapter it needs into its own copy of the fixture
collection, so the phrase under test is the only thing that matches it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lit import search_literature

PAPER = "jeong_2023_shallow_deep_inelastic"
OTHER = "juszczak_2003_recoil_nucleon_spectrum"


def write_chapter(collection: Path, slug: str, name: str, text: str) -> Path:
    path = collection / slug / "chapters" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


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
    write_chapter(collection, PAPER, "09_wrapped.md", (
        "The anomalies are not sufficient to explain the\n"
        "entirety of the observed excess.\n"
    ))

    status, report = run(
        collection, "not sufficient to explain the entirety", capsys=capsys
    )

    assert status == 0
    assert report["matches"] == 1
    assert report["results"][0]["file"] == "%s/chapters/09_wrapped.md" % PAPER


def test_a_nul_byte_does_not_hide_the_file(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`grep` prints nothing at all for such a file, and says nothing about why."""
    write_chapter(collection, PAPER, "09_binary.md",
                  "\x00\nThe axial mass is measured in deuterium.\n")

    status, report = run(collection, "axial mass is measured", capsys=capsys)

    assert status == 0
    assert report["matches"] == 1
    assert any("09_binary.md" in warning for warning in report["warnings"])


def test_the_result_gives_the_anchor_above_the_match(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_chapter(collection, PAPER, "09_anchored.md", (
        "Text before any anchor names the resonance region.\n"
        "\n"
        '<a id="sec-transition"></a>\n'
        "\n"
        "## 9. Transition\n"
        "\n"
        "The transition region begins at two GeV.\n"
    ))

    _, report = run(collection, "transition region begins", capsys=capsys)
    assert report["results"][0]["anchor"] == "sec-transition"
    assert report["results"][0]["location"].endswith(
        "09_anchored.md#sec-transition"
    )

    _, above = run(collection, "before any anchor", capsys=capsys)
    assert above["results"][0]["anchor"] is None
    assert above["results"][0]["location"] == "%s/chapters/09_anchored.md" % PAPER


def test_the_line_number_is_the_line_of_the_match(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_chapter(collection, PAPER, "09_lines.md",
                  "one\ntwo\nthree\nthe phrase to find\nfive\n")

    _, report = run(collection, "the phrase to find", capsys=capsys)

    assert report["results"][0]["line"] == 4


def test_the_sentence_stops_at_the_sentence_boundary(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_chapter(collection, PAPER, "09_sentences.md", (
        "A sentence before it. The phrase to find stands here. A sentence after it.\n"
    ))

    _, report = run(collection, "the phrase to find", capsys=capsys)

    assert report["results"][0]["sentence"] == "The phrase to find stands here."


def test_a_long_sentence_is_cut_at_context_chars(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    filler = "word " * 200
    write_chapter(collection, PAPER, "09_long.md",
                  "%s the phrase to find %s.\n" % (filler, filler))

    _, report = run(collection, "the phrase to find", capsys=capsys)
    sentence = report["results"][0]["sentence"]

    assert len(sentence) <= search_literature.CONTEXT_CHARS
    assert "the phrase to find" in sentence
    assert sentence.startswith(search_literature.ELLIPSIS)


def test_the_match_ignores_case_unless_it_is_told_not_to(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_chapter(collection, PAPER, "09_case.md", "The Axial Mass of the nucleon.\n")

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
    write_chapter(collection, PAPER, "09_partial.md",
                  "The axial mass extracted from deuterium data.\n")

    status, report = run(
        collection, "the axial mass extracted from muon capture", capsys=capsys
    )

    assert status == 1
    assert report["matches"] == 0
    assert report["partial_matches"][0]["phrase"] == "the axial mass extracted from"
    assert any(
        result["file"].endswith("09_partial.md")
        for result in report["partial_matches"][0]["results"]
    )


def test_the_default_scope_is_the_text_of_the_papers(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Neither the rendered files at the root nor the reference pages count."""
    (collection / "README.md").write_text("a rendered phrase\n", encoding="utf-8")
    pages = collection / "references"
    pages.mkdir(exist_ok=True)
    (pages / "some_tag.md").write_text("a rendered phrase\n", encoding="utf-8")
    write_chapter(collection, PAPER, "09_scope.md", "a rendered phrase\n")

    _, report = run(collection, "a rendered phrase", capsys=capsys)

    assert report["matches"] == 1
    assert report["results"][0]["paper"] == PAPER


def test_a_regex_matches_against_the_flat_text(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plain space in the pattern therefore carries across a line break."""
    write_chapter(collection, PAPER, "09_regex.md", "The axial mass is\n1.03 GeV.\n")

    _, report = run(collection, r"axial mass is 1\.03", "--regex", capsys=capsys)

    assert report["matches"] == 1


def test_max_results_caps_the_results_and_says_so(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_chapter(collection, PAPER, "09_many.md",
                  "the phrase to find. " * 10)

    _, report = run(collection, "the phrase to find", "--max-results", "3",
                    capsys=capsys)

    assert report["matches"] == 10
    assert len(report["results"]) == 3
    assert report["truncated"] is True


def test_paper_hides_a_hit_in_a_paper_of_another_task(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The collection outlives the query: a hit can come from someone else's subject."""
    write_chapter(collection, PAPER, "09_mine.md", "the phrase to find\n")
    write_chapter(collection, OTHER, "09_theirs.md", "the phrase to find\n")

    _, everywhere = run(collection, "the phrase to find", capsys=capsys)
    assert everywhere["matches"] == 2

    _, mine = run(collection, "the phrase to find", "--paper", PAPER, capsys=capsys)
    assert mine["matches"] == 1
    assert mine["scope"]["papers"] == [PAPER]


def test_an_unknown_slug_exits_rather_than_reporting_no_match(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Status 1 means the phrase is absent, and this phrase was never searched for."""
    status, report = run(collection, "the axial mass", "--paper", "no_such_paper",
                         capsys=capsys)

    assert status == 2
    assert report["unknown_papers"] == ["no_such_paper"]


def test_the_report_names_its_own_scope(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A reader can then see that a search covered one paper of two."""
    write_chapter(collection, PAPER, "09_scoped.md", "the phrase to find\n")

    _, whole = run(collection, "the phrase to find", capsys=capsys)
    assert whole["scope"]["papers"] == sorted([PAPER, OTHER])
    assert whole["scope"]["papers_in_collection"] == 2
    assert whole["scope"]["files_read"] == len(
        search_literature.written_files(collection)
    )

    _, one = run(collection, "the phrase to find", "--paper", PAPER, capsys=capsys)
    assert one["scope"]["papers"] == [PAPER]
    assert one["scope"]["papers_in_collection"] == 2
    assert one["scope"]["files_read"] < whole["scope"]["files_read"]
