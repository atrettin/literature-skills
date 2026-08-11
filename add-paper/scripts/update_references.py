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

It also writes the citations into the chapters, and a page per cited work for
them to link to. The conversion leaves a `[cite: tag]` marker behind; this turns
it into `([Lipari, 2002](../../references/<tag>.md))`, which reads as a citation
and opens that one work. It happens here because the author and year come from
the store, so a citation says what INSPIRE and Crossref confirmed rather than
what the citing paper's bibliography printed.

`references/` and `REFERENCES.md` are both views of the store and neither is
where anything lives: the table is the collection at once, a page is one work on
its own. An agent needs neither — `reference_lookup.py` answers a tag from the
store — and both are rewritten in full on every run.

Usage:
    update_references.py --manifest manifest.json
    update_references.py --render-only
"""

from __future__ import annotations

import argparse
import json
import os
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

A chapter cites a work as `([Lipari, 2002](../../references/lipari_2002_neutrino_oscillation_neutrino_cross.md))`,
which reads as (Lipari, 2002) and opens that one work's page. `references/`
holds one such page per row below, for a reader following a citation; this table
is the whole collection at once.

**An agent resolving a citation should read neither.** The tag names the file
the citation links to, and it is looked up directly:

    reference_lookup.py lipari_2002_neutrino_oscillation_neutrino_cross

That answers from `.references.jsonl` with the publication the tag names, in
JSON, one work at a time — where this file holds every work every paper cites
and grows without limit. It also takes `--search`, `--doi`, `--arxiv` and
`--cited-by <paper>`.

A row marked ⚠ was not confirmed against INSPIRE-HEP or Crossref. Its fields
come from the citing paper's own bibliography, or from a match on title alone,
and may be wrong or incomplete. Do not quote a ⚠ row as a source without
checking it.

Generated from `.references.jsonl`. Editing this file changes nothing; it is
rewritten in full every time a paper is added.

"""

COLUMNS = ("Title", "Authors", "Year", "Journal", "DOI", "arXiv", "Cited", "Cited by")

# One page per cited work, beside the table. A citation links to a file rather
# than to a row, because a link to a file lands where it says: the VS Code
# preview resolves a cross-file `#fragment` through the heading table of
# contents, so it cannot reach an anchor in a table cell, and a heading it could
# reach would have to be slugified to be linked to — which would take the tag
# out of the citation, and the tag is what an agent resolves.
RECORDS_DIR = reference_store.RECORDS_DIR

UNVERIFIED_NOTE = (
    "⚠ **Not confirmed.** Nothing at INSPIRE-HEP or Crossref matched this "
    "entry, so its fields come from the citing paper's own bibliography, or "
    "from a match on title alone, and may be wrong or incomplete. Do not quote "
    "it as a source without checking it."
)


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
    nobody reads — an identifier is looked up, not browsed. A citation reaches
    this work through its page in `references/`, not through this table, so the
    table needs no handle for one either.
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


def render_record(record: dict) -> str:
    """One work's page: what a reader wants after clicking a citation.

    The same fields as that work's row in the table, laid out down the page
    instead of across it, in the two-column shape a paper's INDEX.md already
    uses. Nothing here is a source of truth — `.references.jsonl` is — so this
    is free to say things twice if that is what reads well.
    """
    tag = record.get("tag") or ""
    title = collapse_whitespace(record.get("title") or "")
    raw = collapse_whitespace(record.get("raw") or "")
    doi = reference_store.normalize_doi(record.get("doi", ""))
    arxiv_id = reference_store.normalize_arxiv(record.get("arxiv_id", ""))
    citations = record.get("citation_count")

    lines = ["# %s" % citation_text(record), ""]
    if not record.get("verified"):
        lines += [UNVERIFIED_NOTE, ""]
    # A work no lookup confirmed has no title of its own. Its own bibliography
    # line is the only description of it there is.
    if title:
        lines += ["**%s**" % escape(title), ""]
    elif raw:
        lines += ["*%s*" % escape(raw), ""]

    rows = [
        ("Authors", display_authors(record.get("authors") or [])),
        ("Year", str(record.get("year") or "—")),
        ("Journal", escape(record.get("journal") or "") or "—"),
        ("DOI", "[%s](https://doi.org/%s)" % (escape(doi), doi) if doi else "—"),
        ("arXiv", "[%s](https://arxiv.org/abs/%s)" % (escape(arxiv_id), arxiv_id) if arxiv_id else "—"),
        ("Cited", "%d times" % citations if isinstance(citations, int) else "—"),
        ("Tag", "`%s`" % tag),
    ]
    lines += ["| Field | Value |", "|---|---|"]
    lines += ["| %s | %s |" % row for row in rows]
    lines.append("")

    held = record.get("held_as")
    if held:
        lines += ["Held here in full: [%s](../%s/INDEX.md)." % (held, held), ""]
    elif doi or arxiv_id:
        lines += ["Not held in this collection. The DOI or arXiv link above "
                  "reaches it, and `add-paper` can fetch it.", ""]
    else:
        # Nothing above is a way to reach it. Saying so is the honest end of
        # the page; sending a reader to a link that is not there is not.
        lines += ["Not held in this collection, and no DOI or arXiv identifier "
                  "was found for it. The line above is all that is known.", ""]

    citing = sorted({entry.get("slug", "") for entry in record.get("cited_by") or [] if entry.get("slug")})
    if citing:
        lines += ["Cited by %s." % ", ".join(
            "[%s](../%s/INDEX.md)" % (slug, slug) for slug in citing
        ), ""]

    lines.append("[All references](../%s)" % reference_store.VIEW_NAME)
    return "\n".join(lines) + "\n"


def write_records(root: Path, store: list[dict]) -> tuple[int, int]:
    """Write one page per record, and clear out the pages of works that went.

    The directory holds nothing but what this writes, so it is rebuilt rather
    than patched: a file whose record the store no longer has is a citation
    target nothing points at any more, and leaving it would let a stale page
    outlive the work it described.
    """
    directory = root / RECORDS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    tags = {record["tag"] for record in store if record.get("tag")}

    written = 0
    for record in store:
        tag = record.get("tag")
        if not tag:
            continue
        path = directory / ("%s.md" % tag)
        text = render_record(record)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            written += 1

    removed = 0
    for path in sorted(directory.glob("*.md")):
        if path.stem not in tags:
            path.unlink()
            removed += 1
    return written, removed


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
# writing citations into the chapters
# --------------------------------------------------------------------------


def citation_text(record: dict) -> str:
    """How a citation reads in a sentence: 'Lipari, 2002', 'Bloom et al., 1970'.

    Author and year, because that is what a reader recognises a work by. The
    tag says the same thing and says it in fifty characters, which is unusable
    mid-sentence — it goes in the link this text is the label of, where an
    agent still finds it and a reader never has to.
    """
    authors = [name for name in record.get("authors") or [] if collapse_whitespace(name)]
    who = reference_store.surname(authors[0]) if authors else ""
    # 'Anon' and 'n.d.' rather than nothing at all, matching what base_tag puts
    # in a tag for the same gap. A citation with a blank where the author goes
    # reads as an error in the conversion.
    who = who or "Anon"
    if len(authors) > 1:
        who += " et al."
    return "%s, %s" % (who, record.get("year") or "n.d.")


def written_files(root: Path, slug: str) -> list[Path]:
    """The Markdown of the papers: what a citation can appear in.

    `references/` is skipped. Its pages are rendered from the store on every
    run, so rewriting them here would be undone immediately, and their links
    are not citations — they point back at the papers that cite them.
    """
    if slug:
        return sorted((root / slug).rglob("*.md"))
    return sorted(
        path for path in root.rglob("*/*.md") if path.parent.name != RECORDS_DIR
    )


def relink_citations(root: Path, slug: str, store: list[dict]) -> int:
    """Point every citation in the collection at its work's page.

    The conversion writes a `[cite: tag]` marker, because at that point the
    store has not been merged yet and the author and year a citation reads by
    come from the store — the version INSPIRE and Crossref confirmed, not the
    version the citing paper's bibliography happened to print. So this is where
    a citation becomes readable, on the run right after the paper is fetched.

    It runs over the whole collection on --render-only, which is what converts
    a collection built before citations were links, and one built while they
    still pointed into REFERENCES.md by anchor.
    """
    texts = {record["tag"]: citation_text(record) for record in store if record.get("tag")}
    directory = (root / RECORDS_DIR).resolve()
    touched = 0

    for path in written_files(root, slug):
        text = path.read_text(encoding="utf-8")
        # From a chapter this is `../../references`, from an INDEX.md
        # `../references`. Computed per file rather than assumed, so a citation
        # anywhere in the tree links to the right place.
        target = os.path.relpath(directory, path.resolve().parent)

        def replace(match: re.Match) -> str:
            tags = [collapse_whitespace(tag) for tag in match.group(1).split(",")]
            tags = [tag for tag in tags if tag]
            # A key the bibliography never defined survives the conversion as
            # itself. There is nothing to link it to, and half-linking the
            # marker would hide the one tag check_references.py must report.
            if not tags or any(tag not in texts for tag in tags):
                return match.group(0)
            return "(%s)" % "; ".join(
                "[%s](%s/%s.md)" % (texts[tag], target, tag) for tag in tags
            )

        replaced = reference_store.CITE_TAG.sub(replace, text)
        replaced = repoint_anchor_links(replaced, target)
        if replaced != text:
            path.write_text(replaced, encoding="utf-8")
            touched += 1
    return touched


# `([Lipari, 2002](../../REFERENCES.md#lipari_2002_...))`, as citations were
# written before each work had a page of its own.
ANCHOR_CITE_LINK = re.compile(
    r"\]\((?:[^)#]*/)?" + re.escape(reference_store.VIEW_NAME) + r"#([a-z0-9_]+)\)"
)


def repoint_anchor_links(text: str, target: str) -> str:
    """Move a citation that named a row of the table onto that work's page.

    The anchor form never worked in the VS Code preview: it resolves a
    cross-file fragment through the heading table of contents, so an anchor in
    a table cell is unreachable and the file merely opens at the top.
    """
    return ANCHOR_CITE_LINK.sub(
        lambda match: "](%s/%s.md)" % (target, match.group(1)), text
    )


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
    for path in written_files(root, slug):
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
    parser.add_argument(
        "--literature-root", type=Path, default=reference_store.default_root()
    )
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


def run(argv: list[str] | None = None) -> tuple[int, dict]:
    """Merge and render. Returns (exit status, the report `main` prints).

    `add_paper.py` calls this rather than the command line, so the counts come
    back as an object instead of as text it would have to parse off stdout.
    """
    args = build_parser().parse_args(argv)
    root = args.literature_root
    if not root.exists():
        return 1, {"error": "%s does not exist" % root}

    try:
        store = reference_store.load(root)
    except RuntimeError as error:
        return 1, {"error": str(error)}

    counts = {"added": 0, "updated": 0, "unchanged": 0}
    rewrites: dict[str, str] = {}
    slug = ""
    before = len(store)

    if args.manifest and not args.render_only:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        slug = manifest.get("slug", "")
        if not slug:
            return 1, {"error": "the manifest names no slug"}
        store, rewrites, counts = reference_store.merge(
            store, manifest.get("references") or [], slug
        )

    # literature/ is not in version control, so a store this run damaged cannot
    # be recovered from anywhere. Adding a paper only ever grows it.
    if len(store) < before and not args.force:
        return 1, {
            "error": "this would leave the store with %d records instead of %d; "
                     "pass --force if that is meant" % (len(store), before),
        }

    retagged = apply_rewrites(root, slug, rewrites)
    relinked = relink_citations(root, slug, store)
    reference_store.mark_held(store, root)
    if not args.render_only:
        reference_store.save(root, store)
    (root / reference_store.VIEW_NAME).write_text(render_table(store), encoding="utf-8")
    written, removed = write_records(root, store)

    return 0, {
        "slug": slug,
        "records": len(store),
        "unverified": sum(1 for record in store if not record.get("verified")),
        "held": sum(1 for record in store if record.get("held_as")),
        **counts,
        "retagged": retagged,
        "relinked": relinked,
        "pages_written": written,
        "pages_removed": removed,
        "store": str(reference_store.store_path(root)),
        "view": str(root / reference_store.VIEW_NAME),
        "pages": str(root / RECORDS_DIR),
    }


def main(argv: list[str] | None = None) -> int:
    status, report = run(argv)
    print(json.dumps(report, indent=2))
    return status


if __name__ == "__main__":
    sys.exit(main())
