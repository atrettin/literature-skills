#!/usr/bin/env python3
"""Take a paper out of the collection.

An ingest is cheap to start and, until this, impossible to undo. An identifier
recalled rather than read resolves to a real paper, every stage of the ingest
succeeds on it, and the collection then holds a paper nobody wanted — in the
index a reader browses, in the scope of every later search, and in the store
that decides what the field is built on. `add-paper --expect-title` is the guard
that catches such a mistake before it is made; this is the answer once it has
been.

What goes: the paper's directory, its row in `README.md`, and the `held_as` of
every record that pointed at it. What stays: the records themselves. A work this
paper cited is a work the collection knows about, and another paper may cite it
too; the record loses its "held here in full" and keeps everything else.

**A paper that another paper cites is not removed without `--force`.** Removing
it turns a citation of a held paper into a citation of a work the collection
only knows by name. That is a judgement, not a mechanical step, so the caller
makes it and the report says which papers are affected.

Prints JSON on stdout. Writes; sends no request.

Exit status is 0 when the paper was removed, 1 when there is no such paper, and
2 when removing it needs a judgement the caller has not made.

Usage:
    remove_paper.py andreopoulos_2015_genie_neutrino --dry-run
    remove_paper.py andreopoulos_2015_genie_neutrino
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from lit import cli, collection_index, paths, reference_store


def citers(records: list[dict], slug: str) -> list[str]:
    """The papers that cite the work this directory holds, other than itself."""
    found: set[str] = set()
    for record in records:
        if record.get("held_as") != slug:
            continue
        for entry in record.get("cited_by") or []:
            other = entry.get("slug") or ""
            if other and other != slug:
                found.add(other)
    return sorted(found)


def remove(root: Path, slug: str, dry_run: bool) -> dict:
    """Take the paper out, and say what that cost."""
    records = reference_store.load(root)
    cited_by = citers(records, slug)
    paper_dir = root / slug

    report = {
        "paper": slug,
        "literature_root": str(root),
        "paper_dir": str(paper_dir),
        "cited_by": cited_by,
        "dry_run": dry_run,
    }

    if dry_run:
        report.update({"removed": False, "index_row": "", "records_unheld": 0})
        return report

    shutil.rmtree(paper_dir)
    report["index_row"] = collection_index.drop_row(root, slug)

    # `mark_held` reads the papers on disk and writes what it finds, so the
    # record pointing at a directory that is now gone is corrected by the same
    # pass that would have set it. Nothing here has to know which records those
    # were, which is what keeps this from drifting away from the ingest.
    unheld = reference_store.mark_held(records, root)
    reference_store.save(root, records)

    report.update({"removed": True, "records_unheld": unheld})
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = cli.parser(__doc__)
    parser.add_argument("slug", help="the paper to remove")
    parser.add_argument("--dry-run", action="store_true",
                        help="say what would go, and remove nothing")
    parser.add_argument("--force", action="store_true",
                        help="remove the paper even though another paper cites it")
    cli.add_root_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = cli.parse(build_parser(), argv)
    root = args.literature_root

    if not root.is_dir():
        return cli.fail("%s does not exist" % root, cli.JUDGEMENT, removed=False)

    held = paths.papers_on_disk(root)
    if args.slug not in held:
        return cli.fail("no such paper in the collection", cli.ABSENT,
                        unknown_paper=args.slug, papers=held, removed=False)

    try:
        report = remove(root, args.slug, dry_run=True)
    except RuntimeError as error:
        return cli.fail(str(error), cli.ABSENT, removed=False)

    if report["cited_by"] and not args.force and not args.dry_run:
        return cli.fail(
            "%d paper(s) of the collection cite this one; removing it leaves "
            "those citations naming a work the collection no longer holds. "
            "Pass --force to remove it anyway." % len(report["cited_by"]),
            cli.JUDGEMENT, removed=False, paper=args.slug,
            cited_by=report["cited_by"],
        )

    if args.dry_run:
        cli.emit(report)
        return 0

    cli.emit(remove(root, args.slug, dry_run=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
