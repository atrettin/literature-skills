#!/usr/bin/env python3
"""Report the multiword terms of the literature that a topic phrase does not hold.

A subject can have a second name that shares no word with the first. "Sterile
neutrino" and "heavy neutral lepton" name closely related objects, and the two
phrases have no word in common. A query that holds one name never finds the
papers that use the other name.

The titles in the reference store are the field's own words for the subject.
This counts the 2-word and 3-word terms of those titles, drops each term the
topic already holds, and reports the frequent rest. A term carries the number of
titles that use it and a few of those titles, thus a reader sees the evidence.

The scope is required. A collection serves many tasks, and it keeps the papers
of each. A scan of the whole store therefore reports the vocabulary of somebody
else's subject as another name for yours. `--cited-by` names the papers of one
task. `--all-papers` is the explicit opt-out, for a question about the
collection itself. There is no default.

Prints one JSON report on stdout. It reads the store on disk, and calls no API.

The exit status is 0 whenever the scan ran, 1 when the store does not parse, and
2 when the scope is absent or names a paper the collection does not know. An
empty `terms` list is an answer, and not a failure.

Usage:
    terminology_scan.py --topic "the seesaw mechanism" --cited-by king_2025_seesaw
    terminology_scan.py --topic "neutrino cross sections" --all-papers
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arxiv_discover  # noqa: E402
import reference_store  # noqa: E402
from arxiv_search import normalize_title  # noqa: E402

# `term_matches` decides when a word of a title is a word the topic already
# holds. It compares two words by prefix, at `rerank.MIN_PREFIX`, thus
# `neutrinos` answers `neutrino`. That constant needs no row of its own in
# TUNING.md: the row for `rerank.MIN_PREFIX` covers it, and the rule here is the
# rule the arXiv search uses.
from rerank import term_matches  # noqa: E402

# The lengths of a term. A single word is what the topic's own term list already
# holds, and one word is too ambiguous to name a subject. A phrase of four words
# is a title, and its count falls under any useful threshold.
NGRAM_SIZES = (2, 3)

# How many titles must hold a term before the report keeps it. Under this value,
# a phrase that names nothing reaches the report beside a name that the field
# uses.
MIN_TITLES = 4

# How many terms the report holds. Each term costs the reader a judgement.
MAX_TERMS = 20

# How many titles a term names as evidence. A reader reads these to see what a
# term is about, before it asks an agent about that term.
EXAMPLES_PER_TERM = 3

# A shorter term goes when a longer term that holds it reaches this share of its
# count. "Neutral lepton" adds nothing beside "heavy neutral lepton" when both
# count 11 titles. The longer term is the name.
SUBSUME_RATIO = 0.8

# How much a word shared with the topic lifts the score of a term. A shared word
# is evidence that the two names point at one area.
SHARED_WORD_BONUS = 1.0

# Words that describe a kind of paper, and not a subject. A term never begins or
# ends with one, thus "search for heavy" stays out and "heavy neutral lepton"
# comes through. A word of this list inside a term stays.
TITLE_FURNITURE = frozenset(
    """search searches measurement measurements observation observations
    constraint constraints limit limits evidence study studies review overview
    status implications prospects test tests analysis new first precise improved
    report results""".split()
)

# The name of a LaTeX command in a title. It goes before the title is divided,
# thus `\emph{sterile neutrinos}` gives no term that begins with `emph`.
LATEX_COMMAND = re.compile(r"\\[a-zA-Z]+")

# A hyphen between two alphanumerics belongs to the word. It becomes a space,
# thus "right-handed neutrinos" gives the term "right handed neutrino". Every
# other mark divides the title: without that rule, "Neutrino cross sections:
# interface of shallow inelastic scattering" gives the term "sections
# interface", which no author wrote.
IN_WORD_HYPHEN = re.compile(r"(?<=[0-9A-Za-z])[-‐‑](?=[0-9A-Za-z])")
SEPARATOR = re.compile(r"[^0-9A-Za-z ]+")


# --------------------------------------------------------------------------
# a title, as terms
# --------------------------------------------------------------------------


def segments(title: str) -> list[list[str]]:
    """The words of a title, divided at each mark of punctuation.

    An n-gram comes from one segment, thus a term never crosses a colon, a
    comma, a dash or a bracket.
    """
    text = IN_WORD_HYPHEN.sub(" ", LATEX_COMMAND.sub(" ", title))
    divided = []
    for piece in SEPARATOR.split(text):
        words = normalize_title(piece).split()
        if words:
            divided.append(words)
    return divided


def is_a_term(words: list[str]) -> bool:
    """Can this n-gram name a subject?

    "Of the sterile" and "neutrino in" are not names, and "search for heavy"
    describes a kind of paper. A function word inside a term stays: "decay of
    the pion" has "decay" and "pion" as its ends.
    """
    for end in (words[0], words[-1]):
        if end in arxiv_discover.TOPIC_STOPWORDS or end in TITLE_FURNITURE:
            return False
    return not any(word.isdigit() for word in words)


def terms_of(title: str, sizes: tuple[int, ...] = NGRAM_SIZES) -> set[str]:
    """The distinct terms of one title.

    A set, thus a title that repeats a phrase gives one vote for it. The count
    of a term is then the number of works that use the term.
    """
    found = set()
    for words in segments(title):
        for size in sizes:
            for start in range(len(words) - size + 1):
                gram = words[start:start + size]
                if is_a_term(gram):
                    found.add(" ".join(gram))
    return found


# --------------------------------------------------------------------------
# counting, over the records in scope
# --------------------------------------------------------------------------


def count_titles(
    records: list[dict],
) -> tuple[dict[str, int], dict[str, list[dict]], dict]:
    """Count each term by the titles that hold it, and keep a few of those titles.

    A record with no title is counted, and then skipped. `raw` is never read: an
    unresolved bibliography line carries authors, a journal and a page range,
    and those words are not terms.
    """
    counts: dict[str, int] = {}
    examples: dict[str, list[dict]] = {}
    scanned = {"records": len(records), "titles": 0, "without_title": 0}

    for record in records:
        title = str(record.get("title") or "").strip()
        if not title:
            scanned["without_title"] += 1
            continue
        scanned["titles"] += 1
        for term in sorted(terms_of(title)):
            counts[term] = counts.get(term, 0) + 1
            seen = examples.setdefault(term, [])
            if len(seen) < EXAMPLES_PER_TERM:
                seen.append({"tag": record.get("tag") or "", "title": title})

    return counts, examples, scanned


# --------------------------------------------------------------------------
# what the topic does not hold
# --------------------------------------------------------------------------


def shared_and_new(term: str, topic_terms: list[str]) -> tuple[list[str], list[str]]:
    """The words of a term that the topic carries, and the words it does not."""
    topic = set(topic_terms)
    shared = [word for word in term.split() if term_matches(word, topic)]
    new = [word for word in term.split() if not term_matches(word, topic)]
    return shared, new


def holds_inside(shorter: str, longer: str) -> bool:
    """Do the words of the shorter term stand together inside the longer one?"""
    short_words = shorter.split()
    long_words = longer.split()
    span = len(short_words)
    return any(
        long_words[start:start + span] == short_words
        for start in range(len(long_words) - span + 1)
    )


def subsumed(counts: dict[str, int], kept: list[str]) -> set[str]:
    """The shorter terms that a longer kept term makes redundant.

    "Neutral lepton" goes when "heavy neutral lepton" reaches `SUBSUME_RATIO` of
    its count. A shorter term far more frequent than every longer term that
    holds it stays: it then names something of its own.
    """
    gone = set()
    for shorter in kept:
        for longer in kept:
            if len(longer.split()) <= len(shorter.split()):
                continue
            if not holds_inside(shorter, longer):
                continue
            if counts[shorter] * SUBSUME_RATIO <= counts[longer]:
                gone.add(shorter)
                break
    return gone


# --------------------------------------------------------------------------
# the scope
# --------------------------------------------------------------------------


def papers_of(root: Path, records: list[dict]) -> list[str]:
    """Every paper slug that the collection knows.

    A directory with an `INDEX.md` is a paper held in full. A slug in the
    `cited_by` of a record names the same kind of paper, from the side of the
    works that it cites. The scan reads both, thus a slug is recognised whether
    or not the caller's root holds the paper directories.
    """
    slugs = {path.parent.name for path in root.glob("*/INDEX.md")}
    for record in records:
        for entry in record.get("cited_by") or []:
            slug = str(entry.get("slug") or "")
            if slug:
                slugs.add(slug)
    return sorted(slugs)


def cited_by(records: list[dict], slugs: list[str]) -> list[dict]:
    """The records that one of these papers cites."""
    wanted = set(slugs)
    return [
        record
        for record in records
        if any(entry.get("slug") in wanted for entry in record.get("cited_by") or [])
    ]


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------


def scan(
    root: Path,
    topic: str,
    records: list[dict],
    papers: list[str],
    scope_papers: list[str],
    mode: str,
    min_titles: int = MIN_TITLES,
    max_terms: int = MAX_TERMS,
) -> dict:
    """The whole answer, for one topic over the records in scope."""
    terms = arxiv_discover.topic_terms(topic)
    counts, examples, scanned = count_titles(records)

    frequent = [term for term, count in counts.items() if count >= min_titles]
    # A term whose every word the topic carries is a term the query searched for
    # already. The report says what the query does not hold.
    described = {term: shared_and_new(term, terms) for term in frequent}
    kept = sorted(term for term in frequent if described[term][1])
    gone = subsumed(counts, kept)
    kept = [term for term in kept if term not in gone]

    reported = []
    for term in kept:
        shared, new = described[term]
        share = len(shared) / len(term.split())
        reported.append({
            "term": term,
            "titles": counts[term],
            "shared_words": shared,
            "new_words": new,
            "score": round(counts[term] * (1 + SHARED_WORD_BONUS * share), 4),
            "examples": examples[term],
        })
    reported.sort(key=lambda item: (-item["score"], -item["titles"], item["term"]))

    return {
        "topic": topic,
        "literature_root": str(root),
        "scope": {
            "mode": mode,
            "papers": scope_papers,
            "titles_read": scanned["titles"],
            "papers_in_collection": len(papers),
        },
        "scanned": scanned,
        "topic_terms": terms,
        "settings": {
            "ngram_sizes": list(NGRAM_SIZES),
            "min_titles": min_titles,
            "max_terms": max_terms,
        },
        "terms": reported[:max_terms],
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--topic",
        required=True,
        help="the subject, written as a full phrase; the scan drops each term "
        "that this phrase holds already",
    )
    # The scope, and no default. A scan of the whole store answers a question
    # about the collection, and one collection serves more than one task.
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--cited-by",
        action="append",
        default=[],
        metavar="SLUG",
        dest="cited_by",
        help="read the titles of the works that this paper cites; repeat it for "
        "each paper of the working set",
    )
    scope.add_argument(
        "--all-papers",
        action="store_true",
        help="read the titles of the whole store; for a question about the "
        "collection itself",
    )
    parser.add_argument(
        "--min-count", type=int, default=MIN_TITLES, metavar="N",
        help="how many titles must hold a term (default %d)" % MIN_TITLES,
    )
    parser.add_argument(
        "--max-terms", type=int, default=MAX_TERMS, metavar="N",
        help="how many terms the report holds (default %d)" % MAX_TERMS,
    )
    parser.add_argument(
        "--literature-root", type=Path, default=reference_store.default_root()
    )
    return parser


def fail(message: str, code: int, **fields: object) -> int:
    print(json.dumps({"error": message, "terms": [], **fields}, indent=2))
    return code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.literature_root

    if not arxiv_discover.topic_terms(args.topic):
        return fail("--topic holds no word to compare against; write it in full", 2)

    try:
        records = reference_store.load(root)
    except RuntimeError as error:
        return fail(str(error), 1)

    papers = papers_of(root, records)
    if args.all_papers:
        mode, scope_papers, in_scope = "all_papers", papers, records
    else:
        unknown = sorted(slug for slug in args.cited_by if slug not in papers)
        if unknown:
            # Never an empty term list. A slug with a typo would narrow the scan
            # to nothing, and an empty report reads as "the field has no other
            # names for this subject".
            return fail(
                "no such paper in the collection", 2,
                unknown_papers=unknown, papers=papers,
            )
        mode = "cited_by"
        scope_papers = sorted(set(args.cited_by))
        in_scope = cited_by(records, scope_papers)

    report = scan(
        root, args.topic, in_scope, papers, scope_papers, mode,
        min_titles=max(args.min_count, 1),
        max_terms=max(args.max_terms, 1),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
