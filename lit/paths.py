#!/usr/bin/env python3
"""Where things are in a collection.

A collection is a directory. Each paper held in full is a directory inside it
named by the paper's slug, holding `INDEX.md` and a `chapters/` directory. The
files at the root and the pages under `references/` are rendered from the
reference store on every run, and nothing else writes them.

Every module that asks "which papers are here" or "which files may hold a
citation" asks it here, so one answer covers them all.
"""

from __future__ import annotations

import os
from pathlib import Path

INDEX_NAME = "INDEX.md"
CHAPTERS_DIR = "chapters"

# The pages rendered from the store, one per cited work. Named here rather than
# imported from `reference_store`, which reads this module.
RECORDS_DIR = "references"


def default_root() -> Path:
    """Where the collection is: `$LITERATURE_ROOT`, or `literature` beside you.

    One collection can serve many projects. A paper costs a download, a
    conversion and a place in the reference store, and paying that again in
    the next project buys nothing. The variable names a directory that outlives
    any one project; without it the collection belongs to the project, as the
    path in every skill says.

    Every command reads this as the default of `--literature-root`, so the flag
    still wins where a caller names a root of its own.
    """
    return Path(os.environ.get("LITERATURE_ROOT") or "literature")


def index_path(root: Path, slug: str) -> Path:
    return root / slug / INDEX_NAME


def papers_on_disk(root: Path) -> list[str]:
    """The slug of every paper this root holds in full.

    A directory with an `INDEX.md` is a paper. A root that does not exist holds
    nothing, which is an answer rather than an error: a project may have no
    collection yet.
    """
    return sorted(path.parent.name for path in root.glob("*/" + INDEX_NAME))


def index_files(root: Path) -> list[Path]:
    """The `INDEX.md` of each paper held in full."""
    return sorted(root.glob("*/" + INDEX_NAME))


def chapters_of(root: Path, slug: str) -> list[Path]:
    """The chapter files of one paper, in the order their names give."""
    return sorted((root / slug / CHAPTERS_DIR).glob("*.md"))


def slug_of(root: Path, path: Path) -> str:
    """Which paper a file belongs to: the first part of its path under the root."""
    try:
        return path.relative_to(root).parts[0]
    except ValueError:
        return ""


def written_files(root: Path, slug: str = "") -> list[Path]:
    """The Markdown of the papers: what a citation can appear in.

    The files at the root and the pages under `references/` are left out. Both
    are rendered from the store on every run, so a citation cannot go stale in
    them and rewriting them here would be undone immediately. `slug` narrows
    the answer to one paper.
    """
    if slug:
        return sorted((root / slug).rglob("*.md"))
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.parent != root and path.parent.name != RECORDS_DIR
    )
