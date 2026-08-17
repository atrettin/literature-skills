"""`litdb show` and `litdb toc`: reading an address, and reading what addresses exist.

These two exist because an agent could find a passage and not walk around it.
The cases below are the walks: open a section, step either side of a block, take
a span, and read a paper's structure without opening the file that holds it.

Two of them are about size rather than content. A command whose whole purpose is
to protect a context window must not be the thing that fills one, so the answer
is capped and says where it stopped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lit import blocks, show_text, toc

PAPER = "jeong_2023_shallow_deep_inelastic"


def heading(anchor: str, level: int, title: str) -> dict:
    return {"kind": "heading", "level": level, "number": "", "title": title,
            "anchor": anchor}


def prose(anchor: str, text: str) -> dict:
    return {"kind": "paragraph", "anchor": anchor, "text": text}


def maths(anchor: str, tex: str) -> dict:
    return {"kind": "math", "env": "equation", "tex": tex, "anchor": anchor}


def write(collection: Path, stem: str, *stored: dict) -> Path:
    return blocks.write(collection / PAPER / "text" / (stem + ".jsonl"), list(stored))


def run(module, collection: Path, *arguments: str, capsys) -> tuple[int, dict]:
    status = module.main([*arguments, "--literature-root", str(collection)])
    return status, json.loads(capsys.readouterr().out)


def show(collection: Path, *arguments: str, capsys) -> tuple[int, dict]:
    return run(show_text, collection, *arguments, capsys=capsys)


# --------------------------------------------------------------------------
# reading an address
# --------------------------------------------------------------------------


def test_a_heading_returns_its_section_and_not_the_whole_chapter(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(collection, "90_sections",
          heading("sec-one", 1, "One"), prose("p1", "the first section"),
          heading("sec-two", 1, "Two"), prose("p2", "the second section"))

    status, report = show(collection, "%s/90_sections#sec-one" % PAPER, capsys=capsys)

    assert status == 0
    assert [block["anchor"] for block in report["blocks"]] == ["sec-one", "p1"]


def test_a_span_returns_both_ends_and_everything_between(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The case a physics paper needs: an argument runs prose, equation, prose."""
    write(collection, "90_span",
          prose("p1", "before the argument"),
          prose("p2", "we substitute the current into"),
          maths("b1", r"\sigma = \int f(x)\,dx"),
          prose("p3", "which gives the result"),
          prose("p4", "after the argument"))

    _, report = show(collection, "%s/90_span#p2..#p3" % PAPER, capsys=capsys)

    assert [block["anchor"] for block in report["blocks"]] == ["p2", "b1", "p3"]
    # The equation arrives as its TeX, which no search could have matched.
    assert r"\sigma" in report["blocks"][1]["text"]


def test_context_stops_at_the_edges_of_the_chapter(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Running off the end would put a block of another section into this one."""
    write(collection, "90_edge",
          prose("p1", "the first block"), prose("p2", "the second block"))

    _, first = show(collection, "%s/90_edge#p1" % PAPER, "--context", "5",
                    capsys=capsys)
    assert [block["anchor"] for block in first["blocks"]] == ["p1", "p2"]


def test_a_figure_answers_with_a_path_that_can_be_opened(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The store keeps a file name. Assembling the path is what a caller should not do."""
    write(collection, "90_figure",
          {"kind": "figure", "file": "spectrum.png", "number": "3",
           "caption": "The measured spectrum.", "anchor": "fig-spectrum"})

    _, report = show(collection, "%s/90_figure#fig-spectrum" % PAPER, capsys=capsys)

    path = Path(report["blocks"][0]["path"])
    assert path == collection / PAPER / "figures" / "spectrum.png"


def test_an_address_that_is_not_there_is_a_judgement_and_not_an_empty_answer(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(collection, "90_present", prose("p1", "the only block"))

    status, report = show(collection, "%s/90_present#p999" % PAPER, capsys=capsys)
    assert status == 2
    # It names the anchors that are there, so the caller corrects the address
    # rather than concluding the paper does not carry the passage.
    assert report["anchors"] == ["p1"]


# --------------------------------------------------------------------------
# the caps
# --------------------------------------------------------------------------


def test_max_words_cuts_at_a_block_and_says_where_to_resume(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(collection, "90_long",
          prose("p1", " ".join(["word"] * 40)),
          prose("p2", " ".join(["word"] * 40)),
          prose("p3", " ".join(["word"] * 40)))

    _, report = show(collection, "%s/90_long" % PAPER, "--max-words", "50",
                     capsys=capsys)

    assert report["truncated"] is True
    # Cut between blocks, never inside one, and the caller is told where.
    assert [block["anchor"] for block in report["blocks"]] == ["p1"]
    assert report["resume_at"] == "%s/90_long#p2" % PAPER


def test_one_block_over_the_cap_is_still_returned_whole(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty answer would say the address holds nothing, which is false."""
    write(collection, "90_huge", prose("p1", " ".join(["word"] * 500)))

    _, report = show(collection, "%s/90_huge#p1" % PAPER, "--max-words", "10",
                     capsys=capsys)

    assert report["count"] == 1
    assert report["truncated"] is False


# --------------------------------------------------------------------------
# what addresses exist
# --------------------------------------------------------------------------


def test_anchors_only_returns_rows_and_no_words(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(collection, "90_listing",
          heading("sec-one", 1, "One"), prose("p1", "a paragraph of prose"))

    _, report = show(collection, "%s/90_listing" % PAPER, "--anchors-only",
                     capsys=capsys)

    assert "blocks" not in report
    assert [row["location"].split("#")[-1] for row in report["anchors"]] == \
        ["sec-one", "p1"]
    # A heading's count is its section's, which is what decides whether to read it.
    assert report["anchors"][0]["words"] > report["anchors"][1]["words"]


def test_the_table_of_contents_says_what_the_paper_is(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """So that reading `paper.json` by hand is never the way to learn this."""
    status, report = run(toc, collection, PAPER, capsys=capsys)

    assert status == 0
    assert report["paper"]["slug"] == PAPER
    assert "title" in report["paper"] and "abstract" in report["paper"]
    assert report["chapter_count"] == len(report["chapters"])
    assert report["words"] > 0


def test_depth_bounds_a_deep_paper_and_says_that_it_did(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A listing that quietly stopped would read as a paper with no deeper sections."""
    write(collection, "90_deep",
          heading("sec-one", 1, "One"),
          heading("sec-sub", 2, "Under one"),
          heading("sec-deeper", 3, "Under that"),
          prose("p1", "the words"))

    _, shallow = run(toc, collection, PAPER, "--depth", "1", capsys=capsys)
    _, deep = run(toc, collection, PAPER, "--depth", "3", capsys=capsys)

    def sections(report):
        chapter = [row for row in report["chapters"] if row["stem"] == "90_deep"][0]
        return [row["location"].split("#")[-1] for row in chapter["sections"]]

    assert sections(shallow) == []
    assert sections(deep) == ["sec-sub", "sec-deeper"]
    assert shallow["truncated_at_depth"] is True


def test_the_chapter_row_does_not_repeat_its_own_heading(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One row per thing. On a manual of sixty-six chapters the repeat is the cost."""
    write(collection, "90_own",
          heading("sec-own", 1, "Its own title"), prose("p1", "the words"))

    _, report = run(toc, collection, PAPER, capsys=capsys)
    chapter = [row for row in report["chapters"] if row["stem"] == "90_own"][0]

    assert chapter["title"] == "Its own title"
    assert "sec-own" not in [row["location"] for row in chapter["sections"]]


def test_all_anchors_reaches_the_figures_and_the_equations(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(collection, "90_every",
          heading("sec-one", 1, "One"),
          maths("b1", r"E = mc^2"),
          {"kind": "figure", "file": "f.png", "number": "1", "caption": "A figure.",
           "anchor": "fig-one"})

    _, report = run(toc, collection, PAPER, "--all-anchors", capsys=capsys)
    chapter = [row for row in report["chapters"] if row["stem"] == "90_every"][0]
    found = [row["location"].split("#")[-1] for row in chapter["sections"]]

    assert "b1" in found and "fig-one" in found


def test_an_unknown_paper_is_a_judgement_and_names_the_ones_held(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, report = run(toc, collection, "no_such_paper", capsys=capsys)
    assert status == 2
    assert PAPER in report["papers"]
