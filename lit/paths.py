#!/usr/bin/env python3
"""Where things are in a collection.

A collection is a directory. Each paper held in full is a directory inside it
named by the paper's slug, and that directory holds two kinds of thing:

    paper.json           what the paper is: metadata, chapters, labels    stored
    text/NN_title.jsonl  the words, one JSON block per line               stored
    figures/*.png        the figures                                      stored
    INDEX.md             chapters/NN_title.md   figures/FIGURES.md      rendered

Storage and render sit in separate directories on purpose. A `*.md` glob then
cannot reach the store and a `*.jsonl` glob cannot reach a render, so no pass
over the collection has to know which of two files holding the same words it
found. The chapter stem is shared between them, which is what lets one address
name both.

Every module that asks "which papers are here", "where is the text of this
chapter" or "which flavor is this collection rendered in" asks it here, so one
answer covers them all.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

INDEX_NAME = "INDEX.md"
CHAPTERS_DIR = "chapters"
TEXT_DIR = "text"
PAPER_NAME = "paper.json"
STATE_NAME = ".collection.json"

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


def paper_path(root: Path, slug: str) -> Path:
    return root / slug / PAPER_NAME


def text_path(root: Path, slug: str, stem: str) -> Path:
    return root / slug / TEXT_DIR / (stem + ".jsonl")


def read_paper(root: Path, slug: str) -> dict:
    """What the collection knows about one paper, as it is stored."""
    path = paper_path(root, slug)
    if not path.is_file():
        raise RuntimeError(
            "%s holds no %s. Fetch the paper again with --force." % (path.parent, PAPER_NAME)
        )
    return json.loads(path.read_text(encoding="utf-8"))


def papers_on_disk(root: Path) -> list[str]:
    """The slug of every paper this root holds in full.

    A directory with a `paper.json` is a paper. The render is asked about
    nothing here: a collection that has been stored but not yet rendered still
    holds its papers. A root that does not exist holds nothing, which is an
    answer rather than an error — a project may have no collection yet.
    """
    return sorted(path.parent.name for path in root.glob("*/" + PAPER_NAME))


def paper_files(root: Path) -> list[Path]:
    """The `paper.json` of each paper held in full."""
    return sorted(root.glob("*/" + PAPER_NAME))


def text_of(root: Path, slug: str) -> list[Path]:
    """The stored text of one paper, in the order the file names give."""
    return sorted((root / slug / TEXT_DIR).glob("*.jsonl"))


def stem_of(path: Path) -> str:
    """The chapter stem a stored or rendered chapter file shares."""
    return path.stem


# --------------------------------------------------------------------------
# the flavor the collection is rendered in
# --------------------------------------------------------------------------

FLAVORS = ("vscode", "obsidian")
DEFAULT_FLAVOR = "vscode"


def state_path(root: Path) -> Path:
    return root / STATE_NAME


def flavor(root: Path) -> str:
    """Which flavor this collection is rendered in.

    It is a property of the files on disk and not of the shell that reads them:
    the anchors a render writes differ per flavor, so a report written against
    the wrong one names anchors that are not there. `litdb init` records one
    when a collection starts, `litdb render --flavor` records it from then on,
    and `$LITERATURE_FLAVOR` answers for a collection that recorded no flavor.
    """
    path = state_path(root)
    if path.is_file():
        recorded = json.loads(path.read_text(encoding="utf-8")).get("flavor")
        if recorded:
            return recorded
    return os.environ.get("LITERATURE_FLAVOR") or DEFAULT_FLAVOR


def set_flavor(root: Path, name: str) -> Path:
    """Record the flavor the collection now holds."""
    from datetime import date

    path = state_path(root)
    state = {}
    if path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
    state["flavor"] = name
    state["rendered"] = date.today().isoformat()
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def chapters_of(root: Path, slug: str) -> list[Path]:
    """The rendered chapter files of one paper, in the order their names give."""
    return sorted((root / slug / CHAPTERS_DIR).glob("*.md"))


def slug_of(root: Path, path: Path) -> str:
    """Which paper a file belongs to: the first part of its path under the root."""
    try:
        return path.relative_to(root).parts[0]
    except ValueError:
        return ""


def stored_files(root: Path, slug: str = "") -> list[Path]:
    """The stored text of the papers: what a citation marker can appear in.

    This is what a pass that changes the collection writes to. Every rendered
    file is derived from these and from the reference store, so a marker is
    corrected here once and reaches every rendering of it. `slug` narrows the
    answer to one paper.
    """
    if slug:
        return text_of(root, slug)
    return sorted(root.glob("*/" + TEXT_DIR + "/*.jsonl"))


def written_files(root: Path, slug: str = "") -> list[Path]:
    """The Markdown a render wrote: what a sweep may delete.

    The files at the root and the pages under `references/` are left out. Both
    are rendered from the reference store rather than from any one paper, and
    a pass over the papers has no business deleting them.
    """
    if slug:
        return sorted((root / slug).rglob("*.md"))
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.parent != root and path.parent.name != RECORDS_DIR
    )
