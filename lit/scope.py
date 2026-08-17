#!/usr/bin/env python3
"""What a command is asked to look at, in one grammar.

Every command that reads the papers takes the same `--scope`, and a scope token
is the citation contract without its `lit:` prefix, cut off at whichever level
the caller wants:

    disk                          every paper the collection holds
    <slug>                        one paper
    <slug>/<stem>                 one chapter
    <slug>/<stem>#<anchor>        one section, or one block
    <slug>/<stem>#<from>..#<to>   a span of blocks, both ends included
    <slug>#<anchor>               the anchor, in whichever chapter carries it

That last form is a convenience with a guard: an anchor a paper writes once —
`#sec-methods`, `#fig-3` — needs no chapter, and an anchor that repeats across
chapters, as `#p5` does, is refused with the list of chapters that carry it. A
caller then chooses rather than guesses.

The grammar is closed on itself. `location()` below builds exactly the form
these parse, so the address an answer reports is an address the next command
accepts, and an agent narrows a search by handing back what it just read.

A span exists because an argument in a paper is not one block. Prose is
interleaved with mathematics — paragraph, equation, paragraph — and each of
those is addressed separately, so `#p5..#p8` is how a caller asks for the
argument rather than for one of its pieces.

Nothing here reads a scope's meaning. It says which blocks a command was
pointed at, and the command decides what to do with them.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from lit import blocks, paths

# The token that means the whole collection. Spelled out rather than implied by
# an absent flag, so a scan of everything is something a caller typed.
DISK = "disk"

# What separates the two ends of a span. Two dots read as a range in every
# language a reader of this is likely to know, and no slug or anchor holds them.
SPAN = ".."


class ScopeError(Exception):
    """A scope that cannot be resolved, with the fields the report carries.

    Raised rather than returned so that parsing a list of tokens stops at the
    first bad one. Every caller turns it into `cli.fail`, so the message and the
    fields here are what an agent reads.
    """

    def __init__(self, message: str, **fields: object) -> None:
        super().__init__(message)
        self.fields = fields


@dataclass(frozen=True)
class Scope:
    """One parsed token. An empty tail means "everything below this".

    `slug` empty is `disk`. `until` is set by a span alone, and never without
    `anchor`, because a span is two anchors and not two chapters.
    """

    slug: str = ""
    stem: str = ""
    anchor: str = ""
    until: str = ""

    @property
    def whole_collection(self) -> bool:
        return not self.slug


@dataclass
class Selection:
    """The blocks one scope points at, inside the file that holds them.

    `blocks` is the whole chapter and never the narrowed part. The span is
    `start:end`, and the rest stays reachable because a caller asking for
    context around a block has to step outside the span to find it — which is
    the whole reason a selection is not just a list.
    """

    path: Path
    slug: str
    stem: str
    blocks: list[dict]
    start: int
    end: int

    def location(self, index: int) -> str:
        """The address of the block at `index`, in the citation form."""
        return location(self.slug, self.stem, self.blocks[index].get("anchor") or "")


def location(slug: str, stem: str, anchor: str = "") -> str:
    """The address of a paper, a chapter or a block.

    The one place the form is built. `parse` reads what this writes.
    """
    address = slug
    if stem:
        address += "/" + stem
    if anchor:
        address += "#" + anchor
    return address


# --------------------------------------------------------------------------
# the token
# --------------------------------------------------------------------------


def parse(token: str) -> Scope:
    """One token, as syntax alone. Nothing here touches the disk.

    Existence is `resolve`'s question, and keeping the two apart means a
    malformed token is reported as malformed rather than as an absent paper.
    """
    text = (token or "").strip()
    if not text:
        raise ScopeError("an empty scope says nothing; write %s for the whole "
                         "collection" % DISK, scope=token)
    if text == DISK:
        return Scope()

    path, marked, tail = text.partition("#")
    parts = [part for part in path.split("/") if part]

    if not parts:
        raise ScopeError("a scope needs a paper before its anchor: "
                         "<slug>#<anchor> or <slug>/<stem>#<anchor>", scope=token)
    if len(parts) > 2:
        raise ScopeError(
            "a scope names a paper and at most one chapter, as <slug>/<stem>",
            scope=token, read_as=parts,
        )

    slug = parts[0]
    stem = parts[1] if len(parts) == 2 else ""

    if not marked:
        return Scope(slug=slug, stem=stem)

    anchor, span, until = tail.partition(SPAN)
    anchor = anchor.strip()
    # The second end is written `#p8`, matching how the first is written, so the
    # `#` is part of the form rather than a mistake to reject.
    until = until.lstrip("#").strip()

    if not anchor:
        raise ScopeError("a scope's `#` needs an anchor after it", scope=token)
    if span and not until:
        raise ScopeError("a span needs both ends: <slug>/<stem>#<from>..#<to>",
                         scope=token)

    return Scope(slug=slug, stem=stem, anchor=anchor, until=until)


def parse_all(tokens: list[str] | None) -> list[Scope]:
    """Every token of a `--scope`, or the whole collection when none was given."""
    if not tokens:
        return [Scope()]
    return [parse(token) for token in tokens]


# --------------------------------------------------------------------------
# the span a scope covers inside one chapter
# --------------------------------------------------------------------------


def index_of(chapter: list[dict], anchor: str) -> int:
    for position, block in enumerate(chapter):
        if block.get("anchor") == anchor:
            return position
    return -1


def span(chapter: list[dict], anchor: str, until: str = "") -> tuple[int, int]:
    """The half-open range of blocks one anchor addresses.

    A heading addresses its section: itself, and everything up to the next
    heading that is its equal or its senior. That is what makes
    `show <slug>/<stem>#sec-methods` return the section rather than one line of
    title, and what lets a caller ask for a chapter's parts by asking for its
    headings.

    A span addresses both its ends and everything between them. Any other
    anchor addresses its own block alone.
    """
    start = index_of(chapter, anchor)
    if start < 0:
        raise ScopeError("no block carries this anchor", anchor=anchor,
                         anchors=blocks.anchors(chapter))

    if until:
        finish = index_of(chapter, until)
        if finish < 0:
            raise ScopeError("no block carries the second anchor of the span",
                             anchor=until, anchors=blocks.anchors(chapter))
        if finish < start:
            raise ScopeError(
                "a span runs forwards: %s comes after %s in this chapter"
                % (anchor, until), start=anchor, until=until,
            )
        return start, finish + 1

    block = chapter[start]
    if block.get("kind") != "heading":
        return start, start + 1

    # A heading with no level closes at the next heading of any level: nothing
    # says which headings are under it, so claiming any of them would be a
    # guess, and a guess here silently returns the wrong section.
    level = block.get("level") or 0
    for position in range(start + 1, len(chapter)):
        later = chapter[position]
        if later.get("kind") != "heading":
            continue
        if (later.get("level") or 0) <= level:
            return start, position
    return start, len(chapter)


# --------------------------------------------------------------------------
# the files, and the blocks inside them
# --------------------------------------------------------------------------


def chapters_carrying(root: Path, slug: str, anchor: str) -> list[Path]:
    """Every chapter of one paper that holds this anchor."""
    return [
        path for path in paths.text_of(root, slug)
        if index_of(blocks.read(path), anchor) >= 0
    ]


def files_of(root: Path, one: Scope, held: set[str]) -> list[Path]:
    """The stored chapters one scope reaches, before any anchor narrows them."""
    if one.whole_collection:
        return paths.stored_files(root)

    if one.slug not in held:
        raise ScopeError("no such paper in the collection", unknown_paper=one.slug,
                         papers=sorted(held))

    if not one.stem:
        if not one.anchor:
            return paths.text_of(root, one.slug)
        # No chapter, but an anchor: find the chapter that carries it. An
        # anchor a paper wrote once needs no chapter from the caller; `#p5`
        # exists in every file and must not be resolved by picking the first.
        found = chapters_carrying(root, one.slug, one.anchor)
        if not found:
            raise ScopeError("no chapter of this paper carries the anchor",
                             paper=one.slug, anchor=one.anchor)
        if len(found) > 1:
            raise ScopeError(
                "this anchor is in more than one chapter; name the chapter as "
                "<slug>/<stem>#<anchor>",
                paper=one.slug, anchor=one.anchor,
                chapters=[path.stem for path in found],
            )
        return found

    path = paths.text_path(root, one.slug, one.stem)
    if not path.is_file():
        raise ScopeError(
            "no such chapter in this paper", paper=one.slug, chapter=one.stem,
            chapters=[other.stem for other in paths.text_of(root, one.slug)],
        )
    return [path]


def resolve(root: Path, scopes: list[Scope]) -> list[Selection]:
    """Every chapter in scope, each with the range of blocks it was narrowed to.

    A chapter named by two scopes is read once. The order follows the order the
    files sort in, and not the order the tokens were written: a caller reading a
    span expects the paper's order, and a report over several papers reads
    better in one.
    """
    held = set(paths.papers_on_disk(root))
    selections: dict[Path, Selection] = {}

    for one in scopes:
        for path in files_of(root, one, held):
            chapter = blocks.read(path)
            slug = paths.slug_of(root, path)
            start, end = 0, len(chapter)
            if one.anchor:
                start, end = span(chapter, one.anchor, one.until)
            existing = selections.get(path)
            if existing is None:
                selections[path] = Selection(
                    path=path, slug=slug, stem=path.stem, blocks=chapter,
                    start=start, end=end,
                )
            else:
                # Two scopes over one chapter cover what either covers. Reading
                # a block twice would repeat it in the answer, and reporting the
                # narrower of the two would drop what the caller asked for.
                existing.start = min(existing.start, start)
                existing.end = max(existing.end, end)

    return [selections[path] for path in sorted(selections)]


# --------------------------------------------------------------------------
# the flag
# --------------------------------------------------------------------------


def papers(root: Path, scopes: list[Scope], known: list[str] | None = None) -> list[str]:
    """The slugs in scope, for a command that works a paper at a time.

    A bibliography and a vocabulary belong to a paper and not to one of its
    sections, so a scope naming a chapter or an anchor is refused rather than
    widened to the paper around it. Silently reading it as the whole paper would
    answer a question the caller did not ask, and the report would say it had
    done what was asked.

    `known` is what the caller counts as a paper. A command reading the text
    means the papers on disk; one reading the reference store means the papers
    that store has a bibliography for, which is not always the same set.
    """
    held = paths.papers_on_disk(root) if known is None else sorted(known)
    named: list[str] = []
    for one in scopes:
        if one.stem or one.anchor:
            raise ScopeError(
                "this command reads a paper at a time; give <slug> or %s, and "
                "not a chapter or an anchor" % DISK,
                scope=location(one.slug, one.stem, one.anchor),
            )
        if one.whole_collection:
            return held
        if one.slug not in held:
            raise ScopeError("no such paper in the collection",
                             unknown_paper=one.slug, papers=held)
        named.append(one.slug)
    return sorted(set(named))


def add_scope_argument(target: argparse.ArgumentParser, required: bool = False) -> None:
    """`--scope`, in the one form every command takes it.

    Multi-valued and repeatable both, so `--scope a b c` and `--scope a
    --scope b` say the same thing. A command whose positional argument follows
    the flag would lose it to `nargs="+"`, so every usage line writes the
    positional first.

    `required` is the command's judgement and not this module's. A search over
    the whole collection is a fair question; a terminology scan over it is not,
    because the collection holds the papers of other tasks and their words would
    answer for yours.
    """
    target.add_argument(
        "--scope",
        nargs="+",
        action="extend",
        default=None,
        required=required,
        metavar="TARGET",
        help="what to read: %s, <slug>, <slug>/<stem>, <slug>/<stem>#<anchor>, "
             "or <slug>/<stem>#<from>..#<to>; repeat or list several" % DISK,
    )


def described(scopes: list[Scope], selections: list[Selection]) -> dict:
    """The `scope` block of a report: what was asked for, and what it reached.

    Every command reports this. A scope that a reader cannot see is a scope that
    a reader cannot check, and the papers a scan covered decide what its answer
    means.
    """
    return {
        "asked": [location(one.slug, one.stem, one.anchor) or DISK for one in scopes],
        "papers": sorted({selection.slug for selection in selections}),
        "chapters": len(selections),
        "blocks": sum(selection.end - selection.start for selection in selections),
    }
