#!/usr/bin/env python3
"""Read what stands at an address, without opening the file that holds it.

`litdb search` answers where a phrase is. This answers what is there. Between
them a caller never has to read a whole chapter to reach one paragraph, and
never has to write a loop over the store to find out what a paper contains.

The address is the scope grammar, so everything a search reported is something
this opens:

    litdb show <slug>/<stem>#<anchor>          one section, or one block
    litdb show <slug>/<stem>#p5..#p8           an argument, both ends included
    litdb show <slug>/<stem>#p7 --context 2    that block, and two either side
    litdb show <slug>/<stem>                   a whole chapter
    litdb show <slug>#<anchor>                 without naming the chapter

A heading addresses its section: the heading and everything under it, down to
the next heading of its own rank or higher. So the anchors a table of contents
lists are the anchors that open the parts it names.

`--anchors-only` answers with the addresses inside the target and none of its
words. That is how a caller reads what is there before deciding what to spend a
context window on, and it is what `litdb toc` runs over a whole paper.

Two caps hold the answer down, because the point of the command is to protect a
context window rather than to fill one. `--max-words` cuts at a block boundary
and says where it stopped, so the caller resumes from that anchor.

Prints JSON on stdout. Reads only; nothing is written or downloaded.

Exit status is 0 when the address was read, 1 when nothing is there, and 2 when
the address itself cannot be resolved — an unknown paper, a chapter that is not
in it, or an anchor that is in more than one chapter.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lit import blocks, cli, scope

# The default cap on the words one answer carries. About 2700 tokens, which a
# caller can spend two or three times on one paper without crowding the work it
# is doing. It sits above the length at which the research loop stops reading a
# section whole, so a section that loop cleared arrives whole and this cap fires
# only as a backstop.
MAX_WORDS = 2000

# How many ranks of heading a table of contents shows. Chapters and the
# sections directly under them: enough to choose what to read, and bounded on a
# paper with sixty-six chapters, where every heading would be hundreds of rows.
# Deeper goes per chapter, with `show <slug>/<stem> --anchors-only`.
TOC_DEPTH = 2

# The first words of a block, where a row has to say what the block is and the
# block has no title of its own.
PREVIEW_CHARS = 90


def word_count(value: str) -> int:
    return len(value.split())


# --------------------------------------------------------------------------
# how deep a heading sits
# --------------------------------------------------------------------------


def ranks(chapter: list[dict]) -> dict[int, int]:
    """Map each heading level the chapter uses to its rank, counting from 1.

    A paper's heading levels are not contiguous. This manual writes a chapter
    at level 1 and its sections at level 3, with nothing at level 2, so
    filtering on the raw level would drop every section of it. Rank asks the
    question a reader means — how deep is this under the chapter — and answers
    it from the levels the chapter actually uses.
    """
    levels = sorted({
        block.get("level") or 0
        for block in chapter if block.get("kind") == "heading"
    })
    return {level: position for position, level in enumerate(levels, 1)}


def describe(chapter: list[dict], index: int, selection: scope.Selection,
             rank: dict[int, int]) -> dict:
    """One row of an `--anchors-only` answer: what is here, and how big it is."""
    block = chapter[index]
    # `location` carries the anchor, so the row does not repeat it. On a paper
    # of sixty-six chapters a field repeated per row is the difference between a
    # listing a caller can afford and one it cannot.
    row: dict[str, object] = {"location": selection.location(index)}

    if block.get("kind") == "heading":
        start, end = scope.span(chapter, block["anchor"]) if block.get("anchor") \
            else (index, index + 1)
        row["rank"] = rank.get(block.get("level") or 0, 1)
        if block.get("number"):
            row["number"] = block["number"]
        row["title"] = block.get("title", "")
        # The words of the section, and not of the heading. That is the number a
        # caller weighs when deciding whether to read it or search inside it.
        row["words"] = words_in(chapter, start, end)
    else:
        text = blocks.display(block)
        row["kind"] = block.get("kind", "")
        row["words"] = word_count(blocks.words(block))
        row["preview"] = (text[:PREVIEW_CHARS] + "…") if len(text) > PREVIEW_CHARS \
            else text
        if block.get("number"):
            row["number"] = block["number"]
    return row


def words_in(chapter: list[dict], start: int, end: int) -> int:
    """The readable words of a range of blocks.

    `blocks.words` is the one measure, so a chapter's count and the count of the
    section that fills it agree. Counting a paragraph's `text` alone would leave
    out every caption and report two different sizes for one thing.
    """
    return sum(word_count(blocks.words(chapter[position]))
               for position in range(start, end))


# --------------------------------------------------------------------------
# the blocks themselves
# --------------------------------------------------------------------------


def widened(selection: scope.Selection, width: int) -> tuple[int, int]:
    """The span, opened by `width` blocks on each side, inside the chapter."""
    if width <= 0:
        return selection.start, selection.end
    return (max(0, selection.start - width),
            min(len(selection.blocks), selection.end + width))


def rendered(selection: scope.Selection, index: int, root: Path) -> dict:
    """One block, as a caller reads it.

    A figure answers with the path to its image. The store keeps the file name
    alone, and a caller wanting to look at the figure would otherwise have to
    build the path itself out of the root, the slug and a directory name — which
    is the hand-assembly this command exists to remove.
    """
    block = selection.blocks[index]
    shown = {
        "location": selection.location(index),
        "anchor": block.get("anchor") or "",
        "kind": block.get("kind", ""),
        "text": blocks.display(block),
    }
    for field in ("level", "number", "title", "env", "numbers", "language"):
        if block.get(field):
            shown[field] = block[field]
    if block.get("kind") == "figure" and block.get("file"):
        shown["path"] = str(root / selection.slug / "figures" / block["file"])
    return shown


def read_blocks(selections: list[scope.Selection], root: Path, width: int,
                max_words: int) -> tuple[list[dict], bool, str | None]:
    """Every block in scope, up to the word cap. Returns (blocks, cut, resume).

    `resume` is the address the answer stopped at, so a caller that wants the
    rest asks for it directly instead of guessing how much it missed.
    """
    shown: list[dict] = []
    spent = 0
    for selection in selections:
        start, end = widened(selection, width)
        for index in range(start, end):
            block = rendered(selection, index, root)
            cost = word_count(block["text"])
            if shown and spent + cost > max_words:
                return shown, True, block["location"]
            shown.append(block)
            spent += cost
    return shown, False, None


def read_anchors(selections: list[scope.Selection], depth: int | None,
                 headings_only: bool) -> tuple[list[dict], bool]:
    """Every address in scope, with no words. Returns (rows, deeper).

    `deeper` says that the paper holds headings below the depth asked for, so a
    caller knows the listing is a view and not the whole structure.
    """
    rows: list[dict] = []
    deeper = False
    for selection in selections:
        rank = ranks(selection.blocks)
        for index in range(selection.start, selection.end):
            block = selection.blocks[index]
            if not block.get("anchor"):
                continue
            is_heading = block.get("kind") == "heading"
            if headings_only and not is_heading:
                continue
            if depth is not None and is_heading:
                if rank.get(block.get("level") or 0, 1) > depth:
                    deeper = True
                    continue
            rows.append(describe(selection.blocks, index, selection, rank))
    return rows, deeper


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------


def show(root: Path, target: str, anchors_only: bool, width: int,
         max_words: int) -> dict:
    scopes = [scope.parse(target)]
    selections = scope.resolve(root, scopes)

    report = {
        "target": target,
        "literature_root": str(root),
        "scope": scope.described(scopes, selections),
    }

    if anchors_only:
        rows, _ = read_anchors(selections, None, headings_only=False)
        report["anchors"] = rows
        report["count"] = len(rows)
        return report

    shown, cut, resume = read_blocks(selections, root, width, max_words)
    report["blocks"] = shown
    report["count"] = len(shown)
    report["words"] = sum(word_count(block["text"]) for block in shown)
    report["truncated"] = cut
    if cut:
        report["resume_at"] = resume
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = cli.parser(__doc__)
    parser.add_argument(
        "target",
        help="what to read: <slug>/<stem>#<anchor>, a span, a chapter or a paper",
    )
    parser.add_argument("--anchors-only", action="store_true",
                        help="report the addresses inside the target, and no words")
    parser.add_argument("--context", type=int, default=0, metavar="N",
                        help="report N blocks either side of the target")
    parser.add_argument("--max-words", type=int, default=MAX_WORDS, metavar="N",
                        help="report at most N words (default %d)" % MAX_WORDS)
    cli.add_root_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = cli.parse(build_parser(), argv)
    root = args.literature_root

    if not root.is_dir():
        return cli.fail("%s does not exist" % root, cli.JUDGEMENT, blocks=[])

    try:
        report = show(root, args.target, args.anchors_only,
                      max(args.context, 0), max(args.max_words, 1))
    except scope.ScopeError as error:
        return cli.fail(str(error), cli.JUDGEMENT, blocks=[], **error.fields)

    cli.emit(report)
    return 0 if report["count"] else cli.ABSENT


if __name__ == "__main__":
    sys.exit(main())
