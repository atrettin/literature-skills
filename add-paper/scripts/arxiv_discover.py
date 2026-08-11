#!/usr/bin/env python3
"""Search arXiv for papers about a subject, by what their abstracts say.

Prints a JSON report on stdout. No side effects; nothing is downloaded.

Each result says whether the local collection already holds the paper, so the
report separates what is new from what is on disk:

    held_as     the directory holding this paper in full
    known_as    the tag of a work a paper here cites, but does not hold
    both null   a paper the collection does not know

Every result also carries the facts that say what kind of answer it is: its
length, its citation count and whether a review venue published it. One INSPIRE
request describes the shortlist, after the arXiv requests. None of those facts
enters the score. `--kind` and `--sort` let the caller act on them.

Usage:
    arxiv_discover.py --topic "how meson exchange currents change the cross section"
    arxiv_discover.py --topic "neutrino oscillation" --category hep-ph --since 2020
    arxiv_discover.py --topic "we review the status of sterile neutrinos" --kind review
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_facts  # noqa: E402
import reference_store  # noqa: E402
import rerank  # noqa: E402
from arxiv_search import (  # noqa: E402
    COURTESY_DELAY_S,
    SUMMARY_CHARS,
    fetch_feed,
    parse_entries,
    query_words,
    truncate,
)

# arXiv orders by relevance across the whole corpus, which is a coarser judgement
# than the one this script makes. Ask for far more than the caller wants and let
# the ranking choose: the scoring is local and cheap, the request is neither.
CANDIDATES = 100

# Below this, the strict query has told us little, and the broad rung is worth
# its three-second wait.
MIN_RESULTS = 5

AUTHORS_SHOWN = 3
MAX_TERMS = 12
MIN_TERM_CHARS = 3

# How many of the ranked candidates one INSPIRE request describes. `--kind` and
# `--sort` work over this shortlist. `references.BATCH_SIZE` is 40, so this
# value costs one request.
ENRICH_CANDIDATES = 40

# The order of the shortlist when the caller asks for none.
DEFAULT_SORT = "relevance"
SORTS = ("relevance", "recent", "cited")
KINDS = ("any", "review")

# A category is `hep-ph`, or `astro-ph.HE` with a subcategory. arXiv answers an
# unknown field or a malformed category with zero results and no error, so a
# typo here would read as "no such paper exists". Check it before asking.
CATEGORY = re.compile(r"^[a-z-]+(?:\.[A-Za-z-]+)?$")

# Words that say nothing about which papers to find. This is deliberately not
# `reference_store.TAG_STOPWORDS`: that set drops `measurement`, `analysis`,
# `effect` and `study` to keep a tag short, and those are exactly the words that
# tell arXiv what kind of paper a question wants.
TOPIC_STOPWORDS = frozenset(
    """a about also an and any are as at be been between both but by can could do
    does each for from had has have how if in into is it its many more most much
    no not of on or our over own same so some such than that the their them then
    there these they this those to under upon us use used using very was we were
    what when where which while who why will with within would""".split()
)

# Words that say which *kind* of paper the caller wants, and nothing about its
# subject. No abstract carries them, so the strict rung fails on every one of
# them and `missing_terms` then names the wrong thing. The arXiv query drops
# them. The cross-encoder keeps them: it compares the whole topic against an
# abstract, and a topic that reads like a review abstract ranks a review first.
META_TERMS = frozenset(
    "review status present summarising theoretically motivated".split()
)


@dataclass
class Options:
    """What the search was asked for. `main` fills this from the command line."""

    topic: str
    categories: list[str] = field(default_factory=list)
    since: int | None = None
    max_results: int = 15
    kind: str = "any"
    sort: str = DEFAULT_SORT
    literature_root: Path = field(default_factory=reference_store.default_root)


# --------------------------------------------------------------------------
# the question, as terms
# --------------------------------------------------------------------------


def topic_terms(text: str) -> list[str]:
    """Reduce a research question to the words worth searching an abstract for.

    Order is kept and duplicates are dropped, so the query reads like the
    question and no word is asked for twice. A word of `META_TERMS` describes
    the wanted paper rather than its subject, and leaves here.
    """
    terms = []
    for word in query_words(text).lower().split():
        if len(word) < MIN_TERM_CHARS or word in TOPIC_STOPWORDS or word in META_TERMS:
            continue
        if word not in terms:
            terms.append(word)
    return terms[:MAX_TERMS]


def meta_terms_of(text: str) -> list[str]:
    """The words `topic_terms` dropped as meta-vocabulary, in the order given.

    The report names them, so a reader sees why `review` is absent from
    `query.terms` and does not read that absence as a fault.
    """
    dropped = []
    for word in query_words(text).lower().split():
        if word in META_TERMS and word not in dropped:
            dropped.append(word)
    return dropped


# --------------------------------------------------------------------------
# query construction
# --------------------------------------------------------------------------


def build_filters(options: Options) -> list[str]:
    clauses = []
    if options.categories:
        # `cat:astro-ph` does not include `cat:astro-ph.HE`; arXiv treats a
        # subcategory as a separate category, not as a member of its parent.
        # Several categories are therefore an OR of exact names.
        joined = " OR ".join("cat:%s" % name for name in options.categories)
        clauses.append("(%s)" % joined if len(options.categories) > 1 else joined)
    if options.since:
        # The window the caller asked for, not one widened by a year.
        # `arxiv_search` widens because a user quotes the year of a journal
        # against the date of a preprint; here the caller chose the window.
        clauses.append(
            "submittedDate:[%d01010000 TO %s]" % (options.since, time.strftime("%Y%m%d%H%M"))
        )
    return clauses


def build_strict_query(terms: list[str], options: Options) -> str:
    """Every term, each scoped to the abstract on its own.

    The scope covers one word. `abs:quasielastic neutrino` scopes only the
    first, and searches the whole record for the rest — 41 649 papers where the
    scoped form finds a few thousand. A quoted phrase goes the other way and is
    far too strict: `abs:"quasielastic neutrino scattering"` finds six papers,
    while the same three words joined with AND find 135. One clause per term is
    the form that answers a question.
    """
    return " AND ".join(["abs:%s" % term for term in terms] + build_filters(options))


def build_broad_query(terms: list[str], options: Options) -> str:
    """Any term, anywhere in the record.

    For a question narrow enough that no single paper carries all of its words.
    The ranking sorts out what this drags in, so a wide net costs little.
    Parentheses go in as characters: urlencode escapes them on the way out, and
    the `%28` of the API manual would arrive double-escaped and match almost
    nothing.
    """
    group = "(%s)" % " OR ".join("all:%s" % term for term in terms)
    return " AND ".join([group] + build_filters(options))


# --------------------------------------------------------------------------
# the search
# --------------------------------------------------------------------------


Fetch = Callable[[str, int], str]


def gather(terms: list[str], options: Options, fetch: Fetch) -> tuple[list[dict], list[dict]]:
    """Run the ladder. Returns (entries, the queries that ran).

    The broad rung adds to the strict rung's hits rather than replacing them: a
    paper that carried every term is a better answer than one that carried any,
    and the merge keeps that order for the ranking to start from. Both queries
    are reported, because both shaped the result and each result says which of
    them found it.
    """
    strict = build_strict_query(terms, options)
    entries = parse_entries(fetch(strict, CANDIDATES))
    for entry in entries:
        entry["found_by"] = "strict"
    queries = [{"rung": "strict", "search_query": strict}]
    if len(entries) >= MIN_RESULTS:
        return entries, queries

    broad = build_broad_query(terms, options)
    if broad == strict:
        return entries, queries

    time.sleep(COURTESY_DELAY_S)
    try:
        found = parse_entries(fetch(broad, CANDIDATES))
    except (RuntimeError, ET.ParseError, urllib.error.URLError):
        # The strict rung already answered something. Losing the widening is
        # worth less than losing that.
        return entries, queries

    seen = {entry["arxiv_id"] for entry in entries}
    for entry in found:
        if entry["arxiv_id"] not in seen:
            entry["found_by"] = "broad"
            entries.append(entry)
            seen.add(entry["arxiv_id"])
    queries.append({"rung": "broad", "search_query": broad})
    return entries, queries


def annotate_local(entries: list[dict], root: Path) -> dict[str, int]:
    """Say of each paper whether the collection holds it, or merely cites it.

    A collection that does not exist yet is not an error: every paper is then
    new, which is the true answer for a project starting out.
    """
    held = reference_store.held_index(root)
    try:
        records = reference_store.load(root)
    except RuntimeError:
        # A damaged store must not cost the caller the search it asked for.
        records = []
    index = reference_store.build_index(records)

    counts = {"held": 0, "cited": 0, "new": 0}
    for entry in entries:
        probe = {"arxiv_id": entry["arxiv_id"], "doi": entry.get("doi", "")}
        keys = reference_store.identity_keys(probe)
        entry["held_as"] = next((held[key] for key in keys if key in held), None)

        known = reference_store.find_match(index, probe)
        entry["known_as"] = known.get("tag") if known else None
        entry["cited_by"] = (
            sorted({item.get("slug", "") for item in known.get("cited_by") or []})
            if known
            else []
        )

        if entry["held_as"]:
            counts["held"] += 1
        elif entry["known_as"]:
            counts["cited"] += 1
        else:
            counts["new"] += 1
    return counts


def present(entry: dict) -> dict:
    """One result, as the report gives it.

    The abstract is cut here and not before: the cross-encoder ranks on the
    whole of it, and only the reader gets the short form.
    """
    authors = entry.get("authors") or []
    return {
        "arxiv_id": entry["arxiv_id"],
        "title": entry["title"],
        "authors": authors[:AUTHORS_SHOWN],
        "authors_total": len(authors),
        "year": entry["year"],
        "summary": truncate(entry["summary"], SUMMARY_CHARS),
        "doi": entry.get("doi", ""),
        "journal_ref": entry.get("journal_ref", ""),
        "journal": entry.get("journal"),
        "abs_url": entry["abs_url"],
        "pdf_url": entry.get("pdf_url", ""),
        "citation_count": entry.get("citation_count"),
        "pages": entry.get("pages"),
        "pages_source": entry.get("pages_source"),
        "kind": entry.get("kind", "unknown"),
        "document_type": entry.get("document_type"),
        "inspire_id": entry.get("inspire_id"),
        "relevance_rank": entry.get("relevance_rank"),
        "score": entry["score"],
        "coverage": entry["coverage"],
        "missing_terms": entry["missing_terms"],
        "found_by": entry["found_by"],
        "held_as": entry["held_as"],
        "known_as": entry["known_as"],
        "cited_by": entry["cited_by"],
    }


def filter_by_kind(entries: list[dict], kind: str) -> tuple[list[dict], dict | None]:
    """Keep the papers of the kind the caller asked for, and count the rest.

    `any` keeps everything and reports no filter. The counts separate a paper
    of another kind from a paper nobody described: `dropped_unknown` is how many
    candidates INSPIRE and arXiv both left without a venue, and a review that is
    still a preprint is among them.
    """
    if kind == "any":
        return entries, None

    kept = [entry for entry in entries if entry.get("kind") == kind]
    return kept, {
        "requested": kind,
        "kept": len(kept),
        "dropped_not_review": sum(
            1 for entry in entries if entry.get("kind") not in (kind, "unknown")
        ),
        "dropped_unknown": sum(1 for entry in entries if entry.get("kind") == "unknown"),
    }


def resort(entries: list[dict], sort: str) -> list[dict]:
    """Re-order the shortlist. It never changes which papers are on it.

    The cross-encoder chose the shortlist, and every entry keeps its
    `relevance_rank`, so a re-sorted list still shows how the model ranked each
    paper. A missing date or a missing citation count sorts last: a fact nobody
    gave must not read as a small number.
    """
    if sort not in ("recent", "cited"):
        return entries

    field = "published" if sort == "recent" else "citation_count"
    # The relevance order first, so that a tie between two dates or two counts
    # falls back to it. Both sorts below are stable and keep it.
    by_rank = sorted(entries, key=lambda entry: entry.get("relevance_rank") or 0)
    answered = [entry for entry in by_rank if entry.get(field) is not None]
    silent = [entry for entry in by_rank if entry.get(field) is None]
    return sorted(answered, key=lambda entry: entry[field], reverse=True) + silent


def search(options: Options, fetch: Fetch = fetch_feed) -> dict:
    """Find papers about a subject and say which of them the collection holds."""
    terms = topic_terms(options.topic)
    if not terms:
        raise ValueError("--topic holds no word to search for; write the subject in full")

    entries, queries = gather(terms, options, fetch)
    ranked, backend, note = rerank.rank(options.topic, terms, entries)
    for position, entry in enumerate(ranked, start=1):
        entry["relevance_rank"] = position

    # One INSPIRE request, after every arXiv request, over the head of the
    # ranked list. `--kind` and `--sort` work over that shortlist.
    shortlist = ranked[: max(ENRICH_CANDIDATES, options.max_results)]
    enrichment = paper_facts.enrich(shortlist[:ENRICH_CANDIDATES])
    for entry in shortlist:
        paper_facts.describe(entry)

    shortlist, kind_filter = filter_by_kind(shortlist, options.kind)

    sort = options.sort
    if sort == "cited" and not enrichment["matched"]:
        sort = "relevance"
        note = join_notes(
            note, "no candidate carries a citation count; kept the relevance order"
        )
    shortlist = resort(shortlist, sort)

    kept = shortlist[: options.max_results]
    counts = annotate_local(kept, options.literature_root)

    return {
        "query": {
            "topic": options.topic,
            "terms": terms,
            "meta_terms_dropped": meta_terms_of(options.topic),
            "categories": options.categories,
            "since": options.since,
            "queries": queries,
        },
        "ranking": {
            "backend": backend,
            "sort": sort,
            "note": note,
            "candidates": len(entries),
        },
        "enrichment": enrichment,
        "kind_filter": kind_filter,
        "counts": dict(counts, total=len(kept)),
        "results": [present(entry) for entry in kept],
    }


def join_notes(*notes: str | None) -> str | None:
    """One note out of several, so no reason is lost to another."""
    said = [note for note in notes if note]
    return "; ".join(said) if said else None


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--topic",
        help="the subject to search for, written as a full phrase; the search "
        "reads its words and the ranking reads the whole of it",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        dest="categories",
        metavar="NAME",
        help="an arXiv category such as hep-ph or astro-ph.HE; repeatable, and "
        "exact, since a category does not include its subcategories",
    )
    parser.add_argument("--since", type=int, help="earliest year of submission")
    parser.add_argument("--max-results", type=int, default=15)
    parser.add_argument(
        "--kind",
        choices=KINDS,
        default="any",
        help="which kinds of paper to report; review keeps the papers a review "
        "venue or an INSPIRE document type names as a review, and thus drops a "
        "review that is still a preprint",
    )
    parser.add_argument(
        "--sort",
        choices=SORTS,
        default=DEFAULT_SORT,
        help="the order of the shortlist; it re-orders the papers the ranking "
        "chose, and never changes which papers those are",
    )
    parser.add_argument(
        "--literature-root", type=Path, default=reference_store.default_root()
    )
    return parser


def fail(message: str, code: int) -> int:
    print(json.dumps({"error": message, "results": []}, indent=2))
    return code


def main() -> int:
    args = build_parser().parse_args()
    if not args.topic:
        return fail("give --topic", 2)
    for name in args.categories:
        if not CATEGORY.match(name):
            return fail("'%s' is not an arXiv category, such as hep-ph" % name, 2)

    options = Options(
        topic=args.topic,
        categories=args.categories,
        since=args.since,
        max_results=args.max_results,
        kind=args.kind,
        sort=args.sort,
        literature_root=args.literature_root,
    )
    try:
        report = search(options)
    except ValueError as error:
        return fail(str(error), 2)
    except (RuntimeError, ET.ParseError, urllib.error.URLError) as error:
        return fail(str(error), 1)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
