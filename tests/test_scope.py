"""The scope grammar: what a token means, and which blocks it reaches.

One grammar serves every command that reads the papers, and it is the citation
contract without its `lit:` prefix. So these cases assert two things together:
that each form parses, and that the address a search reports is an address the
next command accepts. A grammar that is not closed on itself would send an agent
back to assembling paths by hand, which is what it exists to stop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lit import blocks, scope

PAPER = "jeong_2023_shallow_deep_inelastic"
OTHER = "juszczak_2003_recoil_nucleon_spectrum"


def heading(anchor: str, level: int, title: str) -> dict:
    return {"kind": "heading", "level": level, "number": "", "title": title,
            "anchor": anchor}


def prose(anchor: str, text: str = "some words of the paper") -> dict:
    return {"kind": "paragraph", "anchor": anchor, "text": text}


def write(collection: Path, slug: str, stem: str, *stored: dict) -> Path:
    return blocks.write(collection / slug / "text" / (stem + ".jsonl"), list(stored))


# --------------------------------------------------------------------------
# the token
# --------------------------------------------------------------------------


def test_every_form_of_the_grammar_parses() -> None:
    assert scope.parse("disk") == scope.Scope()
    assert scope.parse("slug") == scope.Scope(slug="slug")
    assert scope.parse("slug/01_intro") == scope.Scope(slug="slug", stem="01_intro")
    assert scope.parse("slug/01_intro#p3") == scope.Scope(
        slug="slug", stem="01_intro", anchor="p3")
    assert scope.parse("slug/01_intro#p3..#p8") == scope.Scope(
        slug="slug", stem="01_intro", anchor="p3", until="p8")
    # Without a chapter: the anchor names itself, wherever it is.
    assert scope.parse("slug#sec-methods") == scope.Scope(
        slug="slug", anchor="sec-methods")


def test_a_location_a_search_reports_is_a_scope_the_next_call_accepts() -> None:
    """The loop that keeps an agent from assembling an address by hand."""
    reported = scope.location(PAPER, "03_results", "p9")
    assert reported == "%s/03_results#p9" % PAPER
    assert scope.parse(reported) == scope.Scope(
        slug=PAPER, stem="03_results", anchor="p9")


@pytest.mark.parametrize("token", ["", "   ", "a/b/c", "slug/01#", "slug/01#p1..",
                                   "#p1"])
def test_a_malformed_token_is_refused_as_syntax(token: str) -> None:
    """Before anything touches the disk, so a typo is not reported as an absent paper."""
    with pytest.raises(scope.ScopeError):
        scope.parse(token)


# --------------------------------------------------------------------------
# the span
# --------------------------------------------------------------------------


def test_a_heading_addresses_its_section_down_to_its_equal() -> None:
    chapter = [
        heading("sec-one", 1, "One"), prose("p1"),
        heading("sec-sub", 2, "Under one"), prose("p2"), prose("p3"),
        heading("sec-two", 1, "Two"), prose("p4"),
    ]
    # The senior heading takes its subsection with it.
    assert scope.span(chapter, "sec-one") == (0, 5)
    # The junior one stops where the next heading of any senior rank begins.
    assert scope.span(chapter, "sec-sub") == (2, 5)
    # The last section runs to the end of the chapter.
    assert scope.span(chapter, "sec-two") == (5, 7)


def test_a_block_that_is_not_a_heading_addresses_itself_alone() -> None:
    chapter = [heading("sec-one", 1, "One"), prose("p1"), prose("p2")]
    assert scope.span(chapter, "p1") == (1, 2)


def test_a_span_covers_both_ends_and_everything_between() -> None:
    chapter = [prose("p1"), prose("p2"), prose("p3"), prose("p4")]
    assert scope.span(chapter, "p2", "p4") == (1, 4)
    # One block either way is still a span.
    assert scope.span(chapter, "p2", "p2") == (1, 2)


def test_a_span_that_runs_backwards_is_refused() -> None:
    """Silently swapping the ends would answer a question nobody asked."""
    chapter = [prose("p1"), prose("p2"), prose("p3")]
    with pytest.raises(scope.ScopeError):
        scope.span(chapter, "p3", "p1")


def test_an_anchor_no_block_carries_names_the_ones_that_are_there() -> None:
    chapter = [prose("p1"), prose("p2")]
    with pytest.raises(scope.ScopeError) as raised:
        scope.span(chapter, "p9")
    assert raised.value.fields["anchors"] == ["p1", "p2"]


# --------------------------------------------------------------------------
# resolving against a collection
# --------------------------------------------------------------------------


def test_an_unknown_paper_names_the_papers_that_are_there(collection: Path) -> None:
    with pytest.raises(scope.ScopeError) as raised:
        scope.resolve(collection, [scope.parse("no_such_paper")])
    assert raised.value.fields["unknown_paper"] == "no_such_paper"
    assert PAPER in raised.value.fields["papers"]


def test_an_unknown_chapter_names_the_chapters_of_that_paper(collection: Path) -> None:
    with pytest.raises(scope.ScopeError) as raised:
        scope.resolve(collection, [scope.parse("%s/99_nothing" % PAPER)])
    assert raised.value.fields["paper"] == PAPER
    assert raised.value.fields["chapters"]


def test_an_anchor_in_two_chapters_asks_the_caller_which(collection: Path) -> None:
    """`p1` is in every file. Picking the first would be a guess presented as an answer."""
    write(collection, PAPER, "90_first", prose("p1", "the first chapter"))
    write(collection, PAPER, "91_second", prose("p1", "the second chapter"))

    with pytest.raises(scope.ScopeError) as raised:
        scope.resolve(collection, [scope.parse("%s#p1" % PAPER)])
    assert "90_first" in raised.value.fields["chapters"]
    assert "91_second" in raised.value.fields["chapters"]


def test_an_anchor_in_one_chapter_needs_no_chapter(collection: Path) -> None:
    write(collection, PAPER, "90_only", prose("sec-unique-here", "the words"))

    found = scope.resolve(collection, [scope.parse("%s#sec-unique-here" % PAPER)])
    assert len(found) == 1
    assert found[0].stem == "90_only"


def test_the_selection_keeps_the_whole_chapter_around_the_span(collection: Path) -> None:
    """Context has to reach outside the span, so the span cannot be all that is read."""
    write(collection, PAPER, "90_span",
          prose("p1"), prose("p2"), prose("p3"), prose("p4"))

    found = scope.resolve(collection, [scope.parse("%s/90_span#p2..#p3" % PAPER)])[0]
    assert (found.start, found.end) == (1, 3)
    assert len(found.blocks) == 4


def test_two_scopes_over_one_chapter_cover_what_either_covers(collection: Path) -> None:
    write(collection, PAPER, "90_twice",
          prose("p1"), prose("p2"), prose("p3"), prose("p4"))

    found = scope.resolve(collection, [
        scope.parse("%s/90_twice#p1" % PAPER),
        scope.parse("%s/90_twice#p4" % PAPER),
    ])
    # One chapter is read once, and the range holds both blocks asked for.
    assert len(found) == 1
    assert (found[0].start, found[0].end) == (0, 4)


def test_a_command_that_works_per_paper_refuses_a_chapter(collection: Path) -> None:
    """A bibliography belongs to a paper, and widening the scope would answer wrongly."""
    with pytest.raises(scope.ScopeError):
        scope.papers(collection, [scope.parse("%s/01_intro#p1" % PAPER)])


def test_the_whole_collection_absorbs_the_papers_named_beside_it(
    collection: Path,
) -> None:
    every = scope.papers(collection, [scope.parse("disk"), scope.parse(PAPER)])
    assert PAPER in every and OTHER in every
