"""What each flavor writes, and what a re-render is allowed to change.

The store is the paper. A render is one reading of it, and the two flavors
differ where the tools differ: Obsidian resolves a fragment to a heading or to a
block ID and never to an HTML anchor, and its maths is MathJax rather than
KaTeX. Everything a reader is meant to be able to open has to survive both.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import conftest

from lit import blocks
from lit import paths
from lit import render

SLUG = "jeong_2023_shallow_deep_inelastic"
CHAPTER = "02_introduction"
LIPARI = "lipari_2002_neutrino_oscillation_neutrino_cross"


def rendered(root: Path, flavor: str, slug: str = SLUG, stem: str = CHAPTER) -> str:
    render.render_collection(root, flavor)
    return (root / slug / paths.CHAPTERS_DIR / (stem + ".md")).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# anchors
# --------------------------------------------------------------------------


def test_vscode_writes_an_html_anchor_above_the_block(stored_collection: Path) -> None:
    text = rendered(stored_collection, "vscode")

    assert '<a id="p1"></a>\n\n' in text
    assert "^p1" not in text


def test_obsidian_writes_a_block_id_at_the_end_of_the_block(
    stored_collection: Path
) -> None:
    """Obsidian resolves a block ID and never an HTML anchor."""
    text = rendered(stored_collection, "obsidian")

    assert "<a id=" not in text
    paragraph = next(line for line in text.splitlines() if line.endswith("^p1"))
    assert paragraph.endswith(" ^p1")


def test_obsidian_leaves_a_heading_its_own_words_as_its_address(
    stored_collection: Path
) -> None:
    """A block ID is not allowed on a heading, so the heading text is the address."""
    text = rendered(stored_collection, "obsidian")

    assert "## 2 Introduction" in text
    assert "^sec-introduction" not in text


# --------------------------------------------------------------------------
# the markers
# --------------------------------------------------------------------------


def test_a_citation_reads_the_same_in_both_flavors(stored_collection: Path) -> None:
    """A record page has no anchor, so nothing about it depends on the flavor."""
    link = "([Lipari, 2002](../../references/%s.md))" % LIPARI

    assert link in rendered(stored_collection, "vscode")
    assert link in rendered(stored_collection, "obsidian")


def test_a_cross_reference_takes_the_flavor_s_fragment(tmp_path: Path) -> None:
    conftest.write_paper(
        tmp_path, "brown_2019_cells",
        {"01_method": [
            {"kind": "math", "env": "equation", "tex": "E = mc^2", "numbers": ["1"],
             "anchor": "eq-mass"},
            {"kind": "paragraph", "anchor": "p1",
             "text": "The rate follows from eq. ([ref: eq:mass])."},
        ]},
        labels={"eq:mass": {"kind": "equation", "number": "1", "anchor": "eq-mass",
                            "chapter": "Method", "file": "01_method"}},
    )

    vscode = rendered(tmp_path, "vscode", "brown_2019_cells", "01_method")
    obsidian = rendered(tmp_path, "obsidian", "brown_2019_cells", "01_method")

    assert "eq. ([1](#eq-mass))" in vscode
    assert "eq. ([1](#^eq-mass))" in obsidian


def test_a_label_with_no_target_keeps_its_marker(tmp_path: Path) -> None:
    """That is how a reference the paper's own source never defined stays visible."""
    conftest.write_paper(
        tmp_path, "brown_2019_cells",
        {"01_method": [{"kind": "paragraph", "anchor": "p1",
                        "text": "See eq. ([ref: eq:absent])."}]},
    )

    assert "[ref: eq:absent]" in rendered(
        tmp_path, "vscode", "brown_2019_cells", "01_method"
    )


# --------------------------------------------------------------------------
# maths
# --------------------------------------------------------------------------


def numbered(env: str, tex: str, numbers: list[str]) -> dict:
    return {"kind": "math", "env": env, "tex": tex, "numbers": numbers, "anchor": ""}


def test_katex_gets_an_environment_it_knows(tmp_path: Path) -> None:
    """KaTeX has no eqnarray. `aligned` takes the same rows."""
    block = numbered("eqnarray", r"a &=& b \\ c &=& d", ["1", "2"])

    text = render.render_math(block, "vscode")

    assert r"\begin{aligned}" in text
    assert "eqnarray" not in text
    # KaTeX rejects \tag inside an environment, so a row prints its own number.
    assert r"\qquad (1)" in text and r"\qquad (2)" in text
    assert r"\tag{" not in text


def test_mathjax_keeps_what_the_paper_wrote(tmp_path: Path) -> None:
    block = numbered("eqnarray", r"a &=& b \\ c &=& d", ["1", "2"])

    text = render.render_math(block, "obsidian")

    assert r"\begin{eqnarray}" in text
    assert r"\tag{1}" in text and r"\tag{2}" in text


def test_a_single_number_sits_outside_the_environment(tmp_path: Path) -> None:
    """KaTeX rejects `\\tag` inside one, so it is appended after the body."""
    text = render.render_math(numbered("equation", "E = mc^2", ["7"]), "vscode")

    assert text == "$$\nE = mc^2 \\tag{7}\n$$"


def test_the_number_ends_the_last_row_rather_than_standing_under_it(
    tmp_path: Path
) -> None:
    """A source is free to end its maths with a newline; the number follows the text."""
    text = render.render_math(numbered("equation", "\n\\sigma = A E^2 .\n", ["1"]),
                              "vscode")

    assert text == "$$\n\\sigma = A E^2 . \\tag{1}\n$$"


def test_a_chapter_heading_prints_its_number_as_a_paper_does(
    stored_collection: Path
) -> None:
    conftest.write_paper(
        stored_collection, "brown_2019_cells",
        {"01_method": [
            {"kind": "heading", "level": 1, "number": "1", "title": "Method",
             "anchor": "sec-method"},
            {"kind": "heading", "level": 2, "number": "1.1", "title": "Fitting",
             "anchor": "sec-fitting"},
        ]},
    )

    text = rendered(stored_collection, "vscode", "brown_2019_cells", "01_method")

    assert "# 1. Method" in text
    assert "## 1.1 Fitting" in text


def test_an_unnumbered_block_gets_no_tag(tmp_path: Path) -> None:
    text = render.render_math(numbered("equation*", "E = mc^2", [""]), "vscode")

    assert r"\tag" not in text


def test_the_commands_neither_renderer_knows_are_rewritten(tmp_path: Path) -> None:
    """`\\alt` is a REVTeX shorthand, and KaTeX and MathJax both reject it."""
    for flavor in render.FLAVORS:
        text = render.render_math(numbered("equation", r"x \alt y", [""]), flavor)
        assert r"\lesssim" in text
        assert r"\alt" not in text


# --------------------------------------------------------------------------
# the collection, and what a re-render leaves behind
# --------------------------------------------------------------------------


def test_the_flavor_is_recorded_by_the_command(stored_collection: Path,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    status = render.main(["--flavor", "obsidian",
                          "--literature-root", str(stored_collection)])
    report = json.loads(capsys.readouterr().out)

    assert status == 0
    assert report["flavor"] == "obsidian"
    assert paths.flavor(stored_collection) == "obsidian"


def test_a_flavor_change_rewrites_every_chapter(stored_collection: Path) -> None:
    """The store is untouched, so the change is only ever in the render."""
    before = (stored_collection / SLUG / paths.TEXT_DIR / (CHAPTER + ".jsonl")).read_bytes()

    vscode = rendered(stored_collection, "vscode")
    obsidian = rendered(stored_collection, "obsidian")

    assert vscode != obsidian
    after = (stored_collection / SLUG / paths.TEXT_DIR / (CHAPTER + ".jsonl")).read_bytes()
    assert after == before


def test_the_sweep_removes_a_chapter_the_store_no_longer_holds(
    stored_collection: Path
) -> None:
    render.render_collection(stored_collection, "vscode")
    stale = stored_collection / SLUG / paths.CHAPTERS_DIR / "99_removed.md"
    stale.write_text("# a chapter no store holds\n", encoding="utf-8")

    render.render_collection(stored_collection, "vscode")

    assert not stale.exists()
    assert (stored_collection / SLUG / paths.INDEX_NAME).is_file()


def test_out_writes_elsewhere_and_records_nothing(stored_collection: Path) -> None:
    render.render_collection(stored_collection, "vscode")
    somewhere = stored_collection.parent / "vault"

    render.render_collection(stored_collection, "obsidian", somewhere)

    assert (somewhere / SLUG / paths.CHAPTERS_DIR / (CHAPTER + ".md")).is_file()
    # In place, the collection is still what it was recorded as.
    assert paths.flavor(stored_collection) == "vscode"
    assert "<a id=" in (
        stored_collection / SLUG / paths.CHAPTERS_DIR / (CHAPTER + ".md")
    ).read_text(encoding="utf-8")


def test_the_index_counts_what_the_store_holds(stored_collection: Path) -> None:
    render.render_collection(stored_collection, "vscode")

    index = (stored_collection / SLUG / paths.INDEX_NAME).read_text(encoding="utf-8")
    stored = blocks.read(stored_collection / SLUG / paths.TEXT_DIR / (CHAPTER + ".jsonl"))

    assert "[%s.md](chapters/%s.md)" % (CHAPTER, CHAPTER) in index
    assert "%d words." % sum(len(blocks.words(b).split()) for b in stored) in index
