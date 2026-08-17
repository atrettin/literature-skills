#!/usr/bin/env python3
"""Put one paper into the table of `literature/README.md`.

That table is the collection at a glance: one row per paper held here, in order
of the year the preprint went to arXiv, newest last. The year is the submission
year rather than the journal year, so the order of the table and the directory
names agree with each other.

The step is safe to repeat. A second run on one slug writes the Journal cell —
a preprint that has since been published is exactly what makes a re-run worth
doing — and changes nothing else. It never touches a description somebody wrote.

Usage:
    collection_index.py literature --report report.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lit import reference_store
from lit import text as lit_text
from lit.text import EMPTY, escape_cell as escape, split_cells as cells

INDEX_NAME = "README.md"

# How much of the abstract the row carries before a summary pass replaces it.
ROW_DESCRIPTION_CHARS = 160

COLUMNS = ("Title", "Authors", "Year", "Journal", "What it is about")
# Where the Journal column sits.
JOURNAL_COLUMN = 3

# How many authors the row names before "et al.". One: the column is narrow,
# and the row is a pointer to INDEX.md rather than a citation.
ROW_AUTHORS_SHOWN = 1

# A separator row: `|---|---|---|`, in any of the shapes Markdown allows.
SEPARATOR = re.compile(r"^\|(?:\s*:?-{2,}:?\s*\|)+\s*$")

HEADING = "## Papers"

EMPTY_INDEX = """# Literature

Papers are stored as plain text for humans and agents to read. Each paper has
its own directory, and `INDEX.md` inside it is where to start.

This directory is **not tracked by git**. The papers are copyrighted, so their
text must not go to a remote. Never commit a file of this collection.

## Papers

| %s |
|%s|
""" % (" | ".join(COLUMNS), "|".join("---" for _ in COLUMNS))


class CollectionIndexUnreadable(RuntimeError):
    """`README.md` holds no table this can add a row to."""

    def __init__(self, message: str, path: Path) -> None:
        super().__init__(message)
        self.path = str(path)
        self.reason = message


# --------------------------------------------------------------------------
# finding the table
# --------------------------------------------------------------------------


def find_table(lines: list[str], path: Path) -> tuple[int, int]:
    """(index of the header row, index just past the last data row).

    The header is the first row naming both Title and Year, and the separator
    under it is what proves it is a table rather than a sentence with pipes in
    it.
    """
    for number, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        names = [cell.lower() for cell in cells(line)]
        if "title" not in names or "year" not in names:
            continue
        if number + 1 >= len(lines) or not SEPARATOR.match(lines[number + 1]):
            continue
        end = number + 2
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        return number, end
    raise CollectionIndexUnreadable(
        "no table with a Title and a Year column, under a separator row", path
    )


def row_slug(line: str) -> str:
    """The slug a row's title links to, or an empty string."""
    match = re.search(r"\]\(([^)/]+)/INDEX\.md\)", line)
    return match.group(1) if match else ""


def row_year(line: str) -> int:
    """The year cell of a row. A row with no readable year sorts first."""
    parts = cells(line)
    if len(parts) > 2 and parts[2].isdigit():
        return int(parts[2])
    return 0


# --------------------------------------------------------------------------
# writing a row
# --------------------------------------------------------------------------


def first_sentence(text: str, limit: int = ROW_DESCRIPTION_CHARS) -> str:
    return lit_text.first_sentence(text, limit)


def build_row(report: dict, description: str) -> str:
    publication = report.get("publication") or {}
    return "| [%s](%s/INDEX.md) | %s | %s | %s | %s |" % (
        escape(report.get("title") or report.get("slug") or ""),
        report.get("slug", ""),
        lit_text.display_authors(report.get("authors") or [], ROW_AUTHORS_SHOWN,
                                initials=False),
        report.get("submitted_year") or EMPTY,
        escape(publication.get("journal") or "") or EMPTY,
        escape(description) or EMPTY,
    )


def set_journal(line: str, journal: str) -> str:
    """Write the Journal cell of an existing row, and leave every other cell.

    This is the whole of a repeat run. The description in the last cell may be
    somebody's own sentence, and a re-ingest must not overwrite it with the
    abstract again.
    """
    parts = cells(line)
    if len(parts) <= JOURNAL_COLUMN:
        return line
    parts[JOURNAL_COLUMN] = escape(journal) or EMPTY
    return "| %s |" % " | ".join(parts)


def drop_row(root: Path, slug: str) -> str:
    """Take this paper's row out of the table. Returns `removed` or `absent`.

    The index lists what the collection holds, so a row for a directory that is
    not there sends a reader to a page that does not open.
    """
    path = root / INDEX_NAME
    if not path.exists():
        return "absent"

    lines = path.read_text(encoding="utf-8").splitlines()
    header, end = find_table(lines, path)
    for number in range(header + 2, end):
        if row_slug(lines[number]) == slug:
            del lines[number]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return "removed"
    return "absent"


def add_row(root: Path, report: dict, description: str = "") -> str:
    """Put this paper's row into the table. Returns `added` or `present`.

    Raises `CollectionIndexUnreadable` when the file holds no table to add to.
    A collection with no `README.md` at all gets one: an index nothing wrote is
    a collection nobody can browse.
    """
    path = root / INDEX_NAME
    if not path.exists():
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(EMPTY_INDEX, encoding="utf-8")

    lines = path.read_text(encoding="utf-8").splitlines()
    header, end = find_table(lines, path)

    slug = report.get("slug", "")
    publication = report.get("publication") or {}
    for number in range(header + 2, end):
        if row_slug(lines[number]) == slug:
            lines[number] = set_journal(lines[number], publication.get("journal") or "")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return "present"

    row = build_row(report, description)
    year = int(report.get("submitted_year") or 0)
    # Newest last: the row goes after every row of its year or earlier.
    position = end
    for number in range(header + 2, end):
        if row_year(lines[number]) > year:
            position = number
            break
    lines.insert(position, row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "added"
