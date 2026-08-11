#!/usr/bin/env python3
"""Follow the citations of a paper, forwards and backwards.

A search of abstracts finds papers that describe themselves in the words of the
question. The literature also holds papers that answer the question but say it
differently, and the citation graph reaches those: a paper cites the work it
builds on, and the papers that cite it are its corrections, its applications and
the state of the art after it.

Two directions, and they cost different things:

    citing   the papers that cite this one, from INSPIRE-HEP. One search.
    cited    the works this one draws on. A paper the collection holds in full
             answers out of the reference store for nothing; any other paper
             costs its reference list and one batch of lookups.

Each result says whether the local collection already holds the paper, in the
same three forms `arxiv_discover.py` uses: `held_as` is the directory holding it
in full, `known_as` is the tag of a work the collection cites but does not hold,
and both empty is a paper the collection does not know.

A `citation_count` measures attention, not correctness. A wrong paper that
started an argument is cited more than a right one that ended it.

Prints a JSON report on stdout. Reads only; nothing is downloaded into the
collection.

INSPIRE allows 15 requests per IP in any 5-second window. One run of this costs
two requests, or three with a reference list to fetch, and every request goes
through the same waiting that `inspire_lookup.py` uses.

Usage:
    inspire_citations.py 1706.03621
    inspire_citations.py 1706.03621 --direction citing --sort mostrecent
    inspire_citations.py --doi 10.1016/j.ppnp.2018.01.006 --direction cited
    inspire_citations.py --recid 1599542 --direction both --max-results 30
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arxiv_discover  # noqa: E402
import inspire_lookup  # noqa: E402
import rate_gate  # noqa: E402
import reference_store  # noqa: E402
import references  # noqa: E402
from arxiv_search import SUMMARY_CHARS, collapse_whitespace, truncate  # noqa: E402

AUTHORS_SHOWN = 3

# How many citing papers to bring back. A well-cited review has thousands, and
# nobody triages thousands; the ranking that matters is INSPIRE's sort, and it
# puts what the caller asked for first.
MAX_RESULTS = 20

# How many of a paper's own references to look up. A review cites five hundred
# works, one batch resolves forty, and a caller who needs the five hundred and
# first is really asking a different question.
CITED_FETCH_CAP = 40

# What "the papers that cite this" should mean by default. Most cited first
# answers "what did the field build on this", which is the question that sends
# a reader to the citation graph in the first place; most recent answers "what
# came after it", which is the second question and is one flag away.
DEFAULT_SORT = "mostcited"
SORTS = ("mostcited", "mostrecent")


# --------------------------------------------------------------------------
# the paper the question is about
# --------------------------------------------------------------------------


def resolve_paper(arxiv_id: str, doi: str, recid: str) -> dict:
    """Find the paper on INSPIRE by whichever handle the caller had."""
    if recid:
        path = "literature/%s" % urllib.parse.quote(recid, safe="")
        label = "recid %s" % recid
    elif arxiv_id:
        identifier = inspire_lookup.strip_version(arxiv_id)
        path = "arxiv/%s" % urllib.parse.quote(identifier, safe="/.")
        label = "arXiv:%s" % identifier
    else:
        path = "doi/%s" % urllib.parse.quote(collapse_whitespace(doi), safe="/.")
        label = "doi:%s" % collapse_whitespace(doi)

    try:
        record = inspire_lookup.fetch_record(path)
    except RuntimeError as error:
        return inspire_lookup.missing(str(error))
    if record is None:
        return inspire_lookup.missing("INSPIRE holds no record for %s" % label)

    report = inspire_lookup.build_report(record)
    metadata = record.get("metadata") or {}
    report["citation_count"] = metadata.get("citation_count")
    return report


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------


def abstract_of(metadata: dict) -> str:
    """The paper's abstract, cut to the length that triage needs.

    Enough to decide whether the paper is worth fetching, and never enough to
    cite: a claim belongs to the full text, which this script does not read.
    """
    for entry in metadata.get("abstracts") or []:
        value = collapse_whitespace(str(entry.get("value") or ""))
        if value:
            return truncate(value, SUMMARY_CHARS)
    return ""


def present(record: dict) -> dict:
    """One paper, as the report gives it."""
    authors = [name for name in record.get("authors") or [] if name]
    return {
        "title": record.get("title", ""),
        "authors": authors[:AUTHORS_SHOWN],
        "authors_total": len(authors),
        "year": record.get("year"),
        "journal": record.get("journal", ""),
        "doi": record.get("doi", ""),
        "arxiv_id": record.get("arxiv_id", ""),
        "inspire_id": record.get("inspire_id", ""),
        "citation_count": record.get("citation_count"),
        "summary": record.get("summary", ""),
        "verified": record.get("verified", True),
        "held_as": record.get("held_as"),
        "known_as": record.get("known_as"),
        "cited_by": record.get("cited_by") or [],
    }


def section(entries: list[dict], root: Path, source: str, total: int) -> dict:
    """A list of papers with what the collection knows about each."""
    counts = arxiv_discover.annotate_local(entries, root)
    return {
        "source": source,
        "total": total,
        "returned": len(entries),
        "counts": counts,
        "results": [present(entry) for entry in entries],
    }


# --------------------------------------------------------------------------
# the two directions
# --------------------------------------------------------------------------


def citing(recid: str, sort: str, max_results: int, root: Path) -> dict:
    """The papers that cite this one, most cited or most recent first."""
    fields = references.INSPIRE_FIELDS + ("abstracts",)
    metadata, total = references.search_payload(
        "refersto recid %s" % recid, fields, size=max_results, sort=sort
    )
    entries = []
    for item in metadata:
        entry = references.from_inspire_record(item)
        entry["summary"] = abstract_of(item)
        entries.append(entry)
    return section(entries, root, "inspire", total)


def cited_from_store(slug: str, root: Path, max_results: int) -> dict:
    """What a held paper cites, out of the reference store. No request at all.

    Ingesting a paper resolves its whole bibliography and writes it to the
    store. Asking INSPIRE the same question again would be slower and would
    answer with less: the store holds the tag each work is cited by here.
    """
    try:
        store = reference_store.load(root)
    except RuntimeError:
        return {"source": "store", "total": 0, "returned": 0,
                "counts": {"held": 0, "cited": 0, "new": 0}, "results": [], "error": "store unreadable"}

    found = [
        record
        for record in store
        if any(entry.get("slug") == slug for entry in record.get("cited_by") or [])
    ]

    def most_cited_first(record: dict) -> tuple[int, str]:
        count = record.get("citation_count")
        return (-count if isinstance(count, int) else 1, record.get("tag") or "")

    found.sort(key=most_cited_first)
    kept = found[:max_results]
    for record in kept:
        # The store answers `known_as` itself, and it answers for works no
        # identifier reaches — a talk, a private communication — which a lookup
        # by DOI or arXiv identifier would drop.
        record["known_as"] = record.get("tag")
        record["cited_by"] = sorted(
            {entry.get("slug", "") for entry in record.get("cited_by") or [] if entry.get("slug")}
        )
    counts = {"held": 0, "cited": 0, "new": 0}
    for record in kept:
        counts["held" if record.get("held_as") else "cited"] += 1
    return {
        "source": "store",
        "total": len(found),
        "returned": len(kept),
        "counts": counts,
        "results": [present(record) for record in kept],
    }


def cited_from_inspire(recid: str, root: Path, max_results: int) -> dict:
    """What a paper the collection does not hold draws on, from INSPIRE."""
    hits = references.inspire_search("recid %s" % recid, ("references",), size=1)
    entries = (hits[0].get("references") or []) if hits else []
    recids = [number for number in (references.recid_of(entry) for entry in entries) if number]

    fetched = references.fetch_by_recid(recids[:CITED_FETCH_CAP])
    # INSPIRE lists a paper's references in the order the paper printed them,
    # and that order says nothing about which one matters. Most cited first
    # puts the works the field leans on at the top.
    ordered = sorted(
        fetched.values(),
        key=lambda record: (
            -record["citation_count"] if isinstance(record.get("citation_count"), int) else 1,
            record.get("title") or "",
        ),
    )
    return section(ordered[:max_results], root, "inspire", len(entries))


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("arxiv_id", nargs="?", help="arXiv identifier, for example 1706.03621")
    parser.add_argument("--doi", help="name the paper by DOI instead")
    parser.add_argument("--recid", help="name the paper by INSPIRE record number instead")
    parser.add_argument(
        "--direction",
        choices=("citing", "cited", "both"),
        default="citing",
        help="citing: the papers that cite this one. cited: the works it draws "
        "on. both: each of them (default: citing)",
    )
    parser.add_argument(
        "--sort",
        choices=SORTS,
        default=DEFAULT_SORT,
        help="order of the citing papers (default: %s)" % DEFAULT_SORT,
    )
    parser.add_argument("--max-results", type=int, default=MAX_RESULTS)
    parser.add_argument(
        "--literature-root", type=Path, default=reference_store.default_root()
    )
    return parser


def fail(message: str, code: int) -> int:
    print(json.dumps({"found": False, "reason": message}, indent=2))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (args.arxiv_id or args.doi or args.recid):
        return fail("give an arXiv identifier, --doi or --recid", 2)
    if args.max_results < 1:
        return fail("--max-results must be at least 1", 2)
    rate_gate.use_root(args.literature_root)

    paper = resolve_paper(args.arxiv_id or "", args.doi or "", args.recid or "")
    if not paper["found"]:
        return fail(paper["reason"], 1)

    root = args.literature_root
    held = reference_store.held_index(root)
    probe = {"arxiv_id": paper.get("arxiv_id", ""), "doi": paper.get("doi", "")}
    held_as = next(
        (held[key] for key in reference_store.identity_keys(probe) if key in held), None
    )

    report = {
        "paper": {
            "recid": paper.get("inspire_id"),
            "title": paper.get("title", ""),
            "arxiv_id": paper.get("arxiv_id", ""),
            "doi": paper.get("doi", ""),
            "journal": paper.get("journal", ""),
            "citation_count": paper.get("citation_count"),
            "inspire_url": paper.get("inspire_url", ""),
            "held_as": held_as,
        },
        "query": {
            "direction": args.direction,
            "sort": args.sort,
            "max_results": args.max_results,
        },
    }

    recid = str(paper.get("inspire_id") or "")
    if args.direction in ("citing", "both"):
        report["citing"] = citing(recid, args.sort, args.max_results, root)
    if args.direction in ("cited", "both"):
        report["cited"] = (
            cited_from_store(held_as, root, args.max_results)
            if held_as
            else cited_from_inspire(recid, root, args.max_results)
        )

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
