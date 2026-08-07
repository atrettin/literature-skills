#!/usr/bin/env python3
"""Fold a paper's references into the store, and render REFERENCES.md from it.

Run this after arxiv_fetch.py has written a paper. It reads the manifest,
merges each cited work into `literature/.references.jsonl` — one record per
work, however many papers cite it — and writes the table a reader sees.

The table is a *view*. It is rewritten in full from the store every time, so
editing it by hand achieves nothing; change the store instead. Rows come out
most-cited first, which turns the file into a map of what the field leans on
and shows at a glance which of those works this collection does not yet hold.

Merging is done here rather than by an agent because it has to be exact: one
work must end up in one row no matter which of its identifiers a citing paper
happened to print, and a second ingest of the same paper must change nothing.

Usage:
    update_references.py --manifest manifest.json
    update_references.py --render-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference_store  # noqa: E402
from arxiv_search import collapse_whitespace  # noqa: E402

# Beyond this many, the author list stops informing and starts wrapping.
MAX_AUTHORS = 3
MAX_CITED_BY = 8

HEADER = """# References

Every work cited by a paper in this collection, most cited first. One row per
work: a work three papers cite appears once, with all three under **Cited by**.

This table is for reading — what these papers are built on, and which of it this
collection already holds. A **linked title** is a work held here in full; follow
it and read the paper. The rest are known by their metadata only, and the DOI or
arXiv link reaches them.

**To resolve a citation, do not read this file.** A chapter cites
`[cite: some_tag]`, and the tag is looked up directly:

    reference_lookup.py some_tag

That answers from `.references.jsonl` with the publication the tag names, in
JSON, one work at a time. It also takes `--search`, `--doi`, `--arxiv` and
`--cited-by <paper>`.

A row marked ⚠ was not confirmed against INSPIRE-HEP or Crossref. Its fields
come from the citing paper's own bibliography, or from a match on title alone,
and may be wrong or incomplete. Do not quote a ⚠ row as a source without
checking it.

Generated from `.references.jsonl`. Editing this file changes nothing; it is
rewritten in full every time a paper is added.

"""

COLUMNS = ("Title", "Authors", "Year", "Journal", "DOI", "arXiv", "Cited", "Cited by")


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def escape(text: str) -> str:
    """Make a value safe to sit in a Markdown table cell.

    Only the pipe has to go: it splits the row into extra columns and every
    cell after it lands under the wrong heading, which stops the table being a
    lookup. Nothing else is touched. Titles in this field carry maths, and
    escaping `$` and `\\` turns a readable formula into backslash soup — worse
    to read than the emphasis it would prevent.
    """
    return collapse_whitespace(str(text or "")).replace("|", "\\|")


def display_name(author: str) -> str:
    """'Lipari, Paolo' -> 'P. Lipari', which is how a reader expects to see it."""
    author = collapse_whitespace(author)
    if "," not in author:
        return author
    family, _, given = author.partition(",")
    initials = " ".join(
        "%s." % part[0] for part in re.split(r"[\s.]+", given) if part and part[0].isalpha()
    )
    return collapse_whitespace("%s %s" % (initials, family))


def display_authors(authors: list[str]) -> str:
    names = [display_name(name) for name in authors or [] if collapse_whitespace(name)]
    if not names:
        return "—"
    if len(names) > MAX_AUTHORS:
        return "%s et al." % names[0]
    return ", ".join(names)


def display_cited_by(record: dict) -> str:
    slugs = sorted({entry.get("slug", "") for entry in record.get("cited_by") or [] if entry.get("slug")})
    if not slugs:
        return "—"
    shown = ["[%s](%s/INDEX.md)" % (slug, slug) for slug in slugs[:MAX_CITED_BY]]
    if len(slugs) > MAX_CITED_BY:
        shown.append("and %d more" % (len(slugs) - MAX_CITED_BY))
    return "<br>".join(shown)


def display_title(record: dict) -> str:
    """The title, marked when unconfirmed and linked when held here in full.

    The tag gets no column of its own. Tags run to fifty characters, which
    would make for a column wider than the title beside it, holding a string
    nobody reads — an identifier is looked up, not browsed.
    reference_lookup.py answers by tag; this table is for reading.
    """
    title = collapse_whitespace(record.get("title") or "")
    text = escape(title) if title else ""
    if not text:
        # A work no lookup confirmed has no title of its own. Its own
        # bibliography line is the only description of it there is.
        raw = collapse_whitespace(record.get("raw") or "")
        text = "*%s*" % escape(raw) if raw else "—"

    held = record.get("held_as")
    if held:
        text = "[%s](%s/INDEX.md)" % (text, held)
    return text if record.get("verified") else "⚠ " + text


def render_row(record: dict) -> str:
    doi = reference_store.normalize_doi(record.get("doi", ""))
    arxiv_id = reference_store.normalize_arxiv(record.get("arxiv_id", ""))
    citations = record.get("citation_count")
    return "| %s |" % " | ".join(
        (
            display_title(record),
            display_authors(record.get("authors") or []),
            str(record.get("year") or "—"),
            escape(record.get("journal") or "") or "—",
            "[%s](https://doi.org/%s)" % (escape(doi), doi) if doi else "—",
            "[%s](https://arxiv.org/abs/%s)" % (escape(arxiv_id), arxiv_id) if arxiv_id else "—",
            str(citations) if isinstance(citations, int) else "—",
            display_cited_by(record),
        )
    )


def sort_key(record: dict) -> tuple:
    citations = record.get("citation_count")
    return (-(citations if isinstance(citations, int) else -1), record.get("tag") or "")


def render_table(records: list[dict]) -> str:
    lines = [HEADER.rstrip("\n"), ""]
    if not records:
        lines.append("No paper in this collection has been read for its references yet.")
        return "\n".join(lines) + "\n"
    lines.append("| %s |" % " | ".join(COLUMNS))
    lines.append("|%s|" % "|".join("---" for _ in COLUMNS))
    lines.extend(render_row(record) for record in sorted(records, key=sort_key))
    unverified = sum(1 for record in records if not record.get("verified"))
    lines.append("")
    lines.append(
        "%d works, %d held here in full, %d unconfirmed (⚠)."
        % (
            len(records),
            sum(1 for record in records if record.get("held_as")),
            unverified,
        )
    )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# rewriting citations a merge moved
# --------------------------------------------------------------------------


def apply_rewrites(root: Path, slug: str, rewrites: dict[str, str]) -> int:
    """Repoint citations at the tag the store settled on for a work.

    A paper ingested before another paper's references were merged can be given
    a fresh tag for a work the store already knew under a different one. The
    merge says which; without this the citation names a row that is not there.
    """
    if not rewrites:
        return 0
    pattern = re.compile(
        r"(?<![\w-])(%s)(?![\w-])"
        % "|".join(re.escape(old) for old in sorted(rewrites, key=len, reverse=True))
    )
    touched = 0
    targets = list((root / slug).rglob("*.md")) if slug else list(root.rglob("*/*.md"))
    for path in targets:
        text = path.read_text(encoding="utf-8")
        replaced = pattern.sub(lambda match: rewrites[match.group(1)], text)
        if replaced != text:
            path.write_text(replaced, encoding="utf-8")
            touched += 1
    return touched


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--manifest", type=Path, help="the JSON arxiv_fetch.py printed")
    parser.add_argument("--literature-root", type=Path, default=Path("literature"))
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="rewrite REFERENCES.md from the store, merging nothing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="merge even when it would leave the store with fewer records",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.literature_root
    if not root.exists():
        print(json.dumps({"error": "%s does not exist" % root}, indent=2))
        return 1

    try:
        store = reference_store.load(root)
    except RuntimeError as error:
        print(json.dumps({"error": str(error)}, indent=2))
        return 1

    counts = {"added": 0, "updated": 0, "unchanged": 0}
    rewrites: dict[str, str] = {}
    slug = ""
    before = len(store)

    if args.manifest and not args.render_only:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        slug = manifest.get("slug", "")
        if not slug:
            print(json.dumps({"error": "the manifest names no slug"}, indent=2))
            return 1
        store, rewrites, counts = reference_store.merge(
            store, manifest.get("references") or [], slug
        )

    # literature/ is not in version control, so a store this run damaged cannot
    # be recovered from anywhere. Adding a paper only ever grows it.
    if len(store) < before and not args.force:
        print(json.dumps({
            "error": "this would leave the store with %d records instead of %d; "
                     "pass --force if that is meant" % (len(store), before),
        }, indent=2))
        return 1

    retagged = apply_rewrites(root, slug, rewrites)
    reference_store.mark_held(store, root)
    if not args.render_only:
        reference_store.save(root, store)
    (root / reference_store.VIEW_NAME).write_text(render_table(store), encoding="utf-8")

    print(json.dumps({
        "slug": slug,
        "records": len(store),
        "unverified": sum(1 for record in store if not record.get("verified")),
        "held": sum(1 for record in store if record.get("held_as")),
        **counts,
        "retagged": retagged,
        "store": str(reference_store.store_path(root)),
        "view": str(root / reference_store.VIEW_NAME),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
