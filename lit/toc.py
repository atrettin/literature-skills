#!/usr/bin/env python3
"""What a paper is, and what is in it, in one answer.

This is the first thing to run on a paper and often the last. It says what the
paper is — title, authors, year, where it appeared, its abstract — and then
every chapter with its sections, each with an address and a word count.

That makes it the whole answer to "should I read this, and where". A section's
title says whether it bears on the question; its word count says whether to read
it whole or search inside it; its address opens it with `litdb show`. A review
organised by the axis a question asks about is often answered by its chapter
titles alone, for the cost of one call.

Nothing here reads `paper.json`'s chapter list. It walks the stored text, so it
reports the addresses that exist rather than the ones a manifest recorded.

A paper can be very large — a manual runs to sixty-six chapters — so `--depth`
bounds the listing, and `truncated_at_depth` says when there is more. Deeper
goes one chapter at a time:

    litdb show <slug>/<stem> --anchors-only

Prints JSON on stdout. Reads only; nothing is written or downloaded.

Exit status is 0 when the paper was read, 1 when it holds no text, and 2 when
there is no such paper.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lit import cli, paths, scope, show_text
from lit.text import display_authors

# How many authors the header names before it gives the count instead. A paper
# of this field can carry several thousand, and listing them answers nothing.
AUTHORS_SHOWN = 3


def identity(root: Path, slug: str) -> dict:
    """What the paper is, from the manifest, and no part of what it says."""
    paper = paths.read_paper(root, slug)
    publication = paper.get("publication") or {}
    authors = paper.get("authors") or []
    return {
        "slug": slug,
        "title": paper.get("title", ""),
        "authors": display_authors(authors, AUTHORS_SHOWN),
        "authors_total": len(authors),
        "submitted_year": paper.get("submitted_year"),
        "published_year": publication.get("published_year"),
        "journal": publication.get("journal") or "",
        "doi": paper.get("doi") or publication.get("doi") or "",
        "arxiv_id": paper.get("arxiv_id", ""),
        "abs_url": paper.get("abs_url", ""),
        # The paper's own summary of itself. It is the cheapest thing that can
        # rule a paper in or out, so it belongs in the answer that decides that.
        "abstract": paper.get("abstract", ""),
    }


def contents(root: Path, slug: str, depth: int | None,
             headings_only: bool) -> tuple[list[dict], bool, int]:
    """Each chapter with the addresses inside it. Returns (chapters, deeper, words)."""
    chapters = []
    deeper = False
    total = 0
    for path in paths.text_of(root, slug):
        selection = scope.resolve(root, [scope.parse("%s/%s" % (slug, path.stem))])[0]
        rows, more = show_text.read_anchors([selection], depth, headings_only)
        deeper = deeper or more
        words = show_text.words_in(selection.blocks, 0, len(selection.blocks))
        total += words
        heading = next(
            (block for block in selection.blocks if block.get("kind") == "heading"),
            {},
        )
        # A chapter's own heading says what the chapter row already says. Listing
        # both spends a row per chapter to repeat a title, and on a manual of
        # this size that is the difference between a listing worth its cost and
        # one a caller regrets asking for.
        if rows and heading.get("anchor") and rows[0]["location"].endswith(
            "#" + heading["anchor"]
        ):
            rows = rows[1:]
        chapters.append({
            "location": scope.location(slug, path.stem),
            "stem": path.stem,
            "number": heading.get("number") or "",
            "title": heading.get("title") or path.stem,
            "words": words,
            "blocks": len(selection.blocks),
            "sections": rows,
        })
    return chapters, deeper, total


def build_parser() -> argparse.ArgumentParser:
    parser = cli.parser(__doc__)
    parser.add_argument("slug", help="the paper to describe")
    parser.add_argument("--depth", type=int, default=show_text.TOC_DEPTH, metavar="N",
                        help="how many ranks of heading to list; 0 for the "
                             "chapters alone (default %d)" % show_text.TOC_DEPTH)
    parser.add_argument("--all-anchors", action="store_true",
                        help="list every address, not the headings alone: "
                             "figures, tables, equations and paragraphs")
    cli.add_root_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = cli.parse(build_parser(), argv)
    root = args.literature_root

    if not root.is_dir():
        return cli.fail("%s does not exist" % root, cli.JUDGEMENT, chapters=[])

    held = paths.papers_on_disk(root)
    if args.slug not in held:
        return cli.fail("no such paper in the collection", cli.JUDGEMENT,
                        unknown_paper=args.slug, papers=held, chapters=[])

    depth = None if args.all_anchors else max(args.depth, 0)
    chapters, deeper, words = contents(root, args.slug, depth, not args.all_anchors)

    cli.emit({
        "paper": identity(root, args.slug),
        "literature_root": str(root),
        "chapters": chapters,
        "chapter_count": len(chapters),
        "words": words,
        # The listing is a view of the structure, not the whole of it. A caller
        # that cannot see this would read an absent section as one that is not
        # there.
        "truncated_at_depth": deeper,
    })
    return 0 if chapters else cli.ABSENT


if __name__ == "__main__":
    sys.exit(main())
