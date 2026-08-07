#!/usr/bin/env python3
"""Search arXiv for a paper by title, author and/or year.

Prints a JSON report on stdout. No side effects; nothing is downloaded.

The report's top-level "match" field drives the caller's branch:

    exact        one result agrees with every field that was supplied
    approximate  results resemble the query but nothing agrees closely enough
    none         nothing resembles the query

Usage:
    arxiv_search.py --title "NuSTEC White Paper" --year 2018
    arxiv_search.py --author "Pandey" --title "neutrino-nucleus scattering"
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API_URL = "http://export.arxiv.org/api/query"
USER_AGENT = "neutrino-factory-literature/0.1 (local research tooling)"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"

# arXiv asks for no more than one request every three seconds.
COURTESY_DELAY_S = 3.0
REQUEST_TIMEOUT_S = 30.0
MAX_RETRIES = 3

EXACT_TITLE_RATIO = 0.95
APPROX_TITLE_RATIO = 0.60
SUMMARY_CHARS = 400


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------


def normalize_title(text: str) -> str:
    """Case-fold, drop LaTeX markup and punctuation, collapse whitespace."""
    # Drop the command names of LaTeX markup ("$C_5^A$", "\emph{...}"). The
    # punctuation rule below would otherwise leave "emph" in the title and
    # push a true match under EXACT_TITLE_RATIO.
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text.lower())
    return " ".join(text.split())


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def query_words(text: str) -> str:
    """Reduce a title to the bare words that arXiv's phrase search accepts."""
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text)
    return " ".join(text.split())


def last_name(author: str) -> str:
    """Return the surname of a 'First M. Last' or 'Last, First' string."""
    author = collapse_whitespace(author)
    if "," in author:
        return normalize_title(author.split(",", 1)[0])
    parts = author.split()
    return normalize_title(parts[-1]) if parts else ""


# --------------------------------------------------------------------------
# query construction
# --------------------------------------------------------------------------


def build_search_query(title: str | None, author: str | None, year: int | None) -> str:
    clauses = []
    if title:
        # Punctuation inside the quoted phrase makes arXiv return nothing at
        # all: ti:"C(5)_A axial form factor" finds no entry, while the same
        # phrase reduced to words finds the paper. Search on the words.
        clauses.append('ti:"%s"' % query_words(title))
    if author:
        clauses.append('au:"%s"' % collapse_whitespace(author))
    if year:
        # submittedDate is the date of the *preprint*. Users quote the year of
        # the journal, which is often one later — a proceedings volume dated
        # 2005 routinely holds a preprint submitted in 2004. Search both years,
        # or the true paper never enters the result set at all.
        clauses.append(
            "submittedDate:[%d01010000 TO %d12312359]" % (year - 1, year)
        )
    if not clauses:
        raise ValueError("at least one of --title, --author, --year is required")
    return " AND ".join(clauses)


def build_fallback_query(title: str | None, author: str | None) -> str | None:
    """A looser query, used when the field-scoped phrase returns nothing.

    Words joined with AND, not a quoted phrase. A phrase fails outright when the
    real title spells a symbol differently from the query ("$C_5^A$" against
    "C(5)_A"), even though every remaining word of the title agrees. Single
    letters and digits are dropped for the same reason: they are exactly the
    part of a title that notation changes.
    """
    clauses = []
    if title:
        words = [word for word in query_words(title).split() if len(word) > 2]
        clauses.extend("ti:%s" % word for word in words[:12])
    if author:
        clauses.append('au:"%s"' % query_words(author))
    if not clauses:
        return None
    return " AND ".join(clauses)


def build_loose_query(title: str | None, author: str | None) -> str | None:
    """Last resort: the author anchors the search, the title words only rank it.

    An AND of title words still fails when the journal title carries a word the
    preprint never had — "medium-mass nuclei" against "medium nuclei". Requiring
    the author and merely OR-ing the words survives that. Scoring throws away
    the extra papers this pulls in, so a wide net costs nothing here.
    """
    if not author:
        return None
    clauses = ['au:"%s"' % query_words(author)]
    words = [word for word in query_words(title or "").split() if len(word) > 3]
    if words:
        clauses.append("(%s)" % " OR ".join("ti:%s" % word for word in words[:12]))
    return " AND ".join(clauses)


def fetch_feed(search_query: str, max_results: int) -> str:
    params = urllib.parse.urlencode(
        {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    url = "%s?%s" % (API_URL, params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        if attempt:
            time.sleep(COURTESY_DELAY_S)
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as error:  # noqa: PERF203
            last_error = error
    raise RuntimeError("arXiv API request failed: %s" % last_error)


# --------------------------------------------------------------------------
# response parsing
# --------------------------------------------------------------------------


def parse_entries(feed_xml: str) -> list[dict]:
    root = ET.fromstring(feed_xml)
    entries = []
    for entry in root.findall(ATOM + "entry"):
        raw_id = (entry.findtext(ATOM + "id") or "").strip()
        arxiv_id, version = split_id(raw_id)
        if not arxiv_id:
            continue
        published = (entry.findtext(ATOM + "published") or "").strip()
        authors = [
            collapse_whitespace(name.text or "")
            for name in entry.findall(ATOM + "author/" + ATOM + "name")
        ]
        pdf_url = ""
        for link in entry.findall(ATOM + "link"):
            if link.get("title") == "pdf":
                pdf_url = link.get("href") or ""
        entries.append(
            {
                "arxiv_id": arxiv_id,
                "version": version,
                "title": collapse_whitespace(entry.findtext(ATOM + "title") or ""),
                "authors": authors,
                "year": int(published[:4]) if published[:4].isdigit() else None,
                "published": published,
                "summary": collapse_whitespace(entry.findtext(ATOM + "summary") or ""),
                "doi": (entry.findtext(ARXIV_NS + "doi") or "").strip(),
                "journal_ref": (entry.findtext(ARXIV_NS + "journal_ref") or "").strip(),
                "pdf_url": pdf_url,
                "abs_url": "https://arxiv.org/abs/%s" % arxiv_id,
            }
        )
    return entries


def split_id(raw_id: str) -> tuple[str, str]:
    """'http://arxiv.org/abs/1706.03621v3' -> ('1706.03621', 'v3')."""
    tail = raw_id.rsplit("/", 1)[-1]
    match = re.match(r"^(.*?)(v\d+)?$", tail)
    if not match:
        return tail, ""
    return match.group(1), match.group(2) or ""


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------


def score_entry(
    entry: dict, title: str | None, author: str | None, year: int | None
) -> tuple[float, str, dict]:
    """Return (score, match_class, per-field agreement)."""
    agreement = {}

    if title:
        wanted_title = normalize_title(title)
        found_title = normalize_title(entry["title"])
        ratio = difflib.SequenceMatcher(None, wanted_title, found_title).ratio()
        agreement["title"] = ratio >= EXACT_TITLE_RATIO
        # A short partial title ("neutrino nucleus") scores low against a long
        # real one. Fall back to how many of its words the real title contains,
        # so partial titles still reach the approximate band.
        wanted_words = wanted_title.split()
        if wanted_words:
            found_words = set(found_title.split())
            containment = sum(1 for word in wanted_words if word in found_words)
            ratio = max(ratio, containment / len(wanted_words))
    else:
        ratio = 0.0

    if author:
        wanted = last_name(author)
        agreement["author"] = any(
            wanted and wanted in last_name(name) for name in entry["authors"]
        )

    if year:
        # A preprint submitted the year before its journal year still agrees.
        agreement["year"] = entry["year"] in (year - 1, year)

    # Score: the title ratio when a title was given, otherwise the share of
    # the other supplied fields that agree.
    if title:
        score = ratio
        bonus = 0.0
        for key in ("author", "year"):
            if key in agreement and agreement[key]:
                bonus += 0.02
        score = min(1.0, score + bonus)
    else:
        checks = [value for value in agreement.values()]
        score = (sum(1 for value in checks if value) / len(checks)) if checks else 0.0

    if agreement and all(agreement.values()) and (not title or agreement["title"]):
        match = "exact"
    elif (title and ratio >= APPROX_TITLE_RATIO) or (not title and score > 0.0):
        match = "approximate"
    else:
        match = "none"

    return score, match, agreement


def truncate(text: str, limit: int = SUMMARY_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--title", help="paper title, exact or partial")
    parser.add_argument("--author", help="one author name; the surname is what matters")
    parser.add_argument(
        "--year",
        type=int,
        help="year of the paper; the preprint year or the journal year, "
        "since the search covers this year and the one before it",
    )
    parser.add_argument("--max-results", type=int, default=10)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not (args.title or args.author or args.year):
        print(
            json.dumps(
                {
                    "match": "none",
                    "error": "give at least one of --title, --author, --year",
                    "results": [],
                },
                indent=2,
            )
        )
        return 2

    query = build_search_query(args.title, args.author, args.year)
    try:
        entries = parse_entries(fetch_feed(query, args.max_results))
    except (RuntimeError, ET.ParseError) as error:
        print(json.dumps({"match": "none", "error": str(error), "results": []}, indent=2))
        return 1

    used_query = query
    for build in (build_fallback_query, build_loose_query):
        if entries:
            break
        looser = build(args.title, args.author)
        if not looser or looser == used_query:
            continue
        time.sleep(COURTESY_DELAY_S)
        try:
            entries = parse_entries(fetch_feed(looser, args.max_results))
            used_query = looser
        except (RuntimeError, ET.ParseError):
            entries = []

    results = []
    for entry in entries:
        score, match, agreement = score_entry(entry, args.title, args.author, args.year)
        if match == "none":
            continue
        entry = dict(entry)
        entry["summary"] = truncate(entry["summary"])
        entry["score"] = round(score, 4)
        entry["match"] = match
        entry["agreement"] = agreement
        results.append(entry)

    results.sort(key=lambda item: item["score"], reverse=True)

    if results and results[0]["match"] == "exact":
        overall = "exact"
        # An exact match is only unambiguous when no other hit is also exact.
        if sum(1 for item in results if item["match"] == "exact") > 1:
            overall = "approximate"
    elif results:
        overall = "approximate"
    else:
        overall = "none"

    print(
        json.dumps(
            {
                "query": {
                    "title": args.title,
                    "author": args.author,
                    "year": args.year,
                    "search_query": used_query,
                },
                "match": overall,
                "results": results,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
