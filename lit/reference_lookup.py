#!/usr/bin/env python3
"""Say what a citation points at, given its tag.

A chapter cites `[cite: singh_1993_inclusive_quasielastic_neutrino_reactions]`.
This turns that tag into the publication it names — title, authors, year,
journal, DOI, arXiv identifier — read straight out of the reference store.

Use this rather than reading REFERENCES.md. That file is a view meant for a
person browsing; it holds one row for every work every paper here cites, and it
grows without limit. This reads the store, answers in JSON, and costs one row.

Author lists are collapsed by default. A high-energy physics paper can carry
three thousand authors, and a citation almost never turns on the four hundredth
of them; `authors_total` says how many there were, and --all-authors gets them.

Prints JSON on stdout. Reads only; nothing is written or downloaded.

Usage:
    reference_lookup.py lipari_2002_neutrino_oscillation_neutrino_cross
    reference_lookup.py --search "quasielastic neutrino"
    reference_lookup.py --arxiv 1611.07770 --all-authors
    reference_lookup.py --cited-by juszczak_2003_recoil_nucleon_spectrum
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lit import reference_store
from lit.arxiv_search import collapse_whitespace

DEFAULT_AUTHORS = 3

# Kept out of the answer: bookkeeping that says nothing about the publication.
INTERNAL = ("journal_key", "raw", "about", "first_seen")


def collapse_authors(authors: list[str], limit: int | None) -> list[str]:
    if limit is None or len(authors) <= limit:
        return authors
    return authors[:limit] + ["et al. (%d more)" % (len(authors) - limit)]


def present(record: dict, limit: int | None) -> dict:
    """One record as an answer: everything about the work, nothing about the file."""
    authors = [name for name in record.get("authors") or [] if collapse_whitespace(name)]
    doi = reference_store.normalize_doi(record.get("doi", ""))
    arxiv_id = reference_store.normalize_arxiv(record.get("arxiv_id", ""))

    answer = {name: value for name, value in record.items() if name not in INTERNAL}
    answer["authors"] = collapse_authors(authors, limit)
    answer["authors_total"] = len(authors)
    answer["cited_by"] = sorted(
        {entry.get("slug", "") for entry in record.get("cited_by") or [] if entry.get("slug")}
    )
    if doi:
        answer["doi_url"] = "https://doi.org/%s" % doi
    if arxiv_id:
        answer["arxiv_url"] = "https://arxiv.org/abs/%s" % arxiv_id
    # A work no lookup could confirm has no title of its own. Its bibliography
    # line is then the only description there is, so it answers as the title.
    if not answer.get("title") and record.get("raw"):
        answer["title"] = record["raw"]
        answer["title_source"] = "the citing paper's bibliography, unconfirmed"
    return answer


def haystack(record: dict) -> str:
    parts = [
        record.get("tag", ""), record.get("title", ""), record.get("journal", ""),
        record.get("doi", ""), record.get("arxiv_id", ""), record.get("raw", ""),
        str(record.get("year") or ""),
    ]
    parts.extend(record.get("authors") or [])
    return " ".join(parts).lower()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("tags", nargs="*", help="one or more reference tags")
    parser.add_argument("--search", help="substring of a title, author, journal or identifier")
    parser.add_argument("--doi", help="look a work up by DOI")
    parser.add_argument("--arxiv", help="look a work up by arXiv identifier")
    parser.add_argument(
        "--cited-by", metavar="SLUG", help="every work this paper of the collection cites"
    )
    parser.add_argument(
        "--authors",
        type=int,
        default=DEFAULT_AUTHORS,
        metavar="N",
        help="show at most N authors of each work (default %d)" % DEFAULT_AUTHORS,
    )
    parser.add_argument("--all-authors", action="store_true", help="show every author")
    parser.add_argument(
        "--literature-root", type=Path, default=reference_store.default_root()
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not (args.tags or args.search or args.doi or args.arxiv or args.cited_by):
        build_parser().error("give a tag, --search, --doi, --arxiv or --cited-by")

    try:
        store = reference_store.load(args.literature_root)
    except RuntimeError as error:
        print(json.dumps({"error": str(error)}, indent=2))
        return 1

    limit = None if args.all_authors else max(args.authors, 1)
    by_tag = {record.get("tag", ""): record for record in store}

    found: list[dict] = []
    missing: list[str] = []
    seen: set[str] = set()

    def take(record: dict) -> None:
        tag = record.get("tag", "")
        if tag not in seen:
            seen.add(tag)
            found.append(record)

    for tag in args.tags:
        tag = collapse_whitespace(tag).strip(",")
        record = by_tag.get(tag)
        if record is None:
            missing.append(tag)
        else:
            take(record)

    if args.doi:
        wanted = reference_store.normalize_doi(args.doi)
        matched = [r for r in store if reference_store.normalize_doi(r.get("doi", "")) == wanted]
        for record in matched:
            take(record)
        if not matched:
            missing.append("doi:" + wanted)

    if args.arxiv:
        wanted = reference_store.normalize_arxiv(args.arxiv)
        matched = [
            r for r in store if reference_store.normalize_arxiv(r.get("arxiv_id", "")) == wanted
        ]
        for record in matched:
            take(record)
        if not matched:
            missing.append("arxiv:" + wanted)

    if args.cited_by:
        for record in store:
            if any(
                entry.get("slug") == args.cited_by for entry in record.get("cited_by") or []
            ):
                take(record)

    if args.search:
        needle = collapse_whitespace(args.search).lower()
        for record in store:
            if needle in haystack(record):
                take(record)

    def most_cited_first(record: dict) -> tuple[int, str]:
        # A record with no count sorts after every record that has one, however
        # small: an unknown count is not a count of zero.
        count = record.get("citation_count")
        return (-count if isinstance(count, int) else 1, record.get("tag") or "")

    found.sort(key=most_cited_first)

    print(json.dumps({
        "found": len(found),
        "missing": missing,
        "references": [present(record, limit) for record in found],
    }, indent=2, ensure_ascii=False))
    # A tag that answers to nothing is the failure this tooling exists to catch.
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
