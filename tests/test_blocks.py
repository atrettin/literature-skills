"""The stored form of a chapter: what one line is, and what it carries.

Everything downstream reads this. A block that parses wrong sends a citation to
the wrong place, and nothing later can tell.
"""

from __future__ import annotations

from pathlib import Path

from lit import blocks

PARAGRAPH = (
    "The measured cross section rises with the energy of the beam, and the "
    "model reproduces that rise over the whole range considered here."
)


def test_one_block_is_one_line(tmp_path: Path) -> None:
    """A `Read` gives a line number per block and a `Grep` matches one block."""
    path = blocks.write(tmp_path / "01.jsonl", [
        {"kind": "paragraph", "anchor": "p1", "text": "one\ntwo"},
        {"kind": "paragraph", "anchor": "p2", "text": PARAGRAPH},
    ])

    lines = path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    assert blocks.read(path)[0]["text"] == "one\ntwo"


def test_an_anchor_names_what_comes_after_it() -> None:
    found = blocks.parse('<a id="p1"></a>\n\n%s\n' % PARAGRAPH)

    assert found == [{"kind": "paragraph", "text": PARAGRAPH, "anchor": "p1"}]


def test_a_chapter_anchor_names_the_heading_above_it() -> None:
    """The conversion writes it under the heading; every other anchor precedes."""
    found = blocks.parse(
        '# 1. Introduction\n\n<a id="sec-intro"></a>\n\n%s\n' % PARAGRAPH
    )

    assert found[0] == {"kind": "heading", "level": 1, "number": "1",
                        "title": "Introduction", "anchor": "sec-intro"}
    assert found[1]["anchor"] == ""


def test_a_subsection_anchor_still_names_its_own_heading() -> None:
    found = blocks.parse('<a id="sec-method"></a>\n\n## 1.1 Method\n\nprose here.\n')

    assert found[0]["anchor"] == "sec-method"
    assert found[0]["title"] == "Method"
    assert found[0]["number"] == "1.1"


def test_a_sentinel_comes_back_as_the_block_it_carried() -> None:
    text = blocks.sentinel({"kind": "math", "env": "equation",
                            "tex": "E = mc^2", "numbers": ["1"]})

    found = blocks.parse('<a id="eq-mass"></a>\n%s' % text)

    assert found == [{"kind": "math", "env": "equation", "tex": "E = mc^2",
                      "numbers": ["1"], "anchor": "eq-mass"}]


def test_a_sentinel_never_spans_two_lines() -> None:
    """Every pass that splits the intermediate on blank lines leaves it whole."""
    text = blocks.sentinel({"kind": "table", "tex": "a\nb\nc", "caption": "",
                            "number": "1"})

    assert len([line for line in text.strip().splitlines() if line]) == 1
    assert blocks.parse(text)[0]["tex"] == "a\nb\nc"


def test_a_fence_keeps_its_language() -> None:
    found = blocks.parse("```tex\n\\begin{tabular}{c}\n1\n\\end{tabular}\n```\n")

    assert found[0]["kind"] == "code"
    assert found[0]["language"] == "tex"
    assert found[0]["text"] == "\\begin{tabular}{c}\n1\n\\end{tabular}"


def test_the_words_of_a_block_are_what_a_search_matches() -> None:
    """Maths and the raw TeX of a table are not words. A caption is."""
    assert blocks.words({"kind": "paragraph", "text": PARAGRAPH}) == PARAGRAPH
    assert blocks.words({"kind": "math", "tex": "E = mc^2"}) == ""
    assert blocks.words({"kind": "table", "tex": "x", "caption": "The rates."}) == (
        "The rates."
    )
    assert blocks.words({"kind": "figure", "file": "f.png", "caption": "A plot."}) == (
        "A plot."
    )


def test_a_line_that_is_not_json_names_itself(tmp_path: Path) -> None:
    """A paper that reads one block short is worse than one that refuses to read."""
    path = tmp_path / "01.jsonl"
    path.write_text('{"kind": "paragraph"}\nnot json at all\n', encoding="utf-8")

    try:
        blocks.read(path)
    except ValueError as error:
        assert "line 2" in str(error)
    else:
        raise AssertionError("a line that is not JSON must raise")


# --------------------------------------------------------------------------
# stepping from one block to the next
# --------------------------------------------------------------------------


def near(anchor: str, level: int = 0, kind: str = "paragraph") -> dict:
    if kind == "heading":
        return {"kind": "heading", "level": level, "title": anchor, "anchor": anchor}
    return {"kind": kind, "anchor": anchor, "text": "the words"}


def test_neighbours_step_to_the_blocks_either_side() -> None:
    chapter = [near("p1"), near("p2"), near("p3")]
    assert blocks.neighbours(chapter, 1) == {
        "prev": "p1", "next": "p3", "parent": None,
    }


def test_neighbours_are_none_at_the_ends_of_a_chapter() -> None:
    chapter = [near("p1"), near("p2")]
    assert blocks.neighbours(chapter, 0)["prev"] is None
    assert blocks.neighbours(chapter, 1)["next"] is None


def test_neighbours_step_over_a_block_with_no_anchor() -> None:
    """A block ingested before every block had an address cannot be opened,
    so naming it would send a caller to a place it cannot reach."""
    chapter = [near("p1"), {"kind": "math", "anchor": "", "tex": "x"}, near("p2")]
    assert blocks.neighbours(chapter, 2)["prev"] == "p1"


def test_the_parent_of_a_block_is_the_heading_above_it() -> None:
    chapter = [near("sec-one", 1, "heading"), near("p1"), near("p2")]
    assert blocks.neighbours(chapter, 2)["parent"] == "sec-one"


def test_the_parent_of_a_heading_skips_its_own_equals() -> None:
    """Two sections at one level are siblings. A sibling is not a parent."""
    chapter = [
        near("sec-top", 1, "heading"),
        near("sec-a", 2, "heading"), near("p1"),
        near("sec-b", 2, "heading"), near("p2"),
    ]
    assert blocks.neighbours(chapter, 3)["parent"] == "sec-top"
    # A block under the second sibling still belongs to that sibling.
    assert blocks.neighbours(chapter, 4)["parent"] == "sec-b"
