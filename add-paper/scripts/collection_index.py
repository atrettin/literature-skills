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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference_store  # noqa: E402
from arxiv_search import collapse_whitespace  # noqa: E402

INDEX_NAME = "README.md"

# How much of the abstract the row carries before a summary pass replaces it.
ROW_DESCRIPTION_CHARS = 160

COLUMNS = ("Title", "Authors", "Year", "Journal", "What it is about")
# Where the Journal column sits, for a table written before there was one.
JOURNAL_COLUMN = 3

EMPTY = "—"

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


def escape(text: str) -> str:
    """Make a value safe to sit in a Markdown table cell. Only the pipe has to go."""
    return collapse_whitespace(str(text or "")).replace("|", "\\|")


def cells(line: str) -> list[str]:
    """The cells of one table row, without the outer pipes.

    A pipe the writer escaped stays inside its cell: it is a character of the
    title, and splitting on it would give the row a column that is not there.
    """
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") else inner
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", inner)]


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
    """The opening of an abstract, as the description of a paper.

    It stands in until somebody writes a better one. The abstract's own first
    sentence says what the paper is about more often than not, and it is the
    only description available at ingest that nobody had to invent.
    """
    text = collapse_whitespace(text)
    if not text:
        return ""
    match = re.search(r"(?<=[.!?])\s", text)
    sentence = text[: match.start()] if match else text
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 1].rstrip() + "…"


def first_author(authors: list[str]) -> str:
    names = [collapse_whitespace(name) for name in authors or [] if collapse_whitespace(name)]
    if not names:
        return EMPTY
    return "%s et al." % names[0] if len(names) > 1 else names[0]


def build_row(report: dict, description: str) -> str:
    publication = report.get("publication") or {}
    return "| [%s](%s/INDEX.md) | %s | %s | %s | %s |" % (
        escape(report.get("title") or report.get("slug") or ""),
        report.get("slug", ""),
        escape(first_author(report.get("authors") or [])),
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
