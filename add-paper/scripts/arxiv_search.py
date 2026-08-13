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

import difflib
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rate_gate  # noqa: E402

API_URL = "http://export.arxiv.org/api/query"
API_HOST = "export.arxiv.org"
USER_AGENT = "neutrino-factory-literature/0.1 (local research tooling)"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"

# arXiv asks for no more than one request every three seconds. `rate_gate` keeps
# that pace for every script that calls arXiv, in this process and in any other.
COURTESY_DELAY_S = 3.0
rate_gate.set_interval(API_HOST, COURTESY_DELAY_S)
rate_gate.set_interval("arxiv.org", COURTESY_DELAY_S)

REQUEST_TIMEOUT_S = 30.0
MAX_RETRIES = 3

# How many identifiers one id_list request carries. The arXiv API accepts up to
# 2000, and a bibliography holds far fewer references than that, so this value
# only decides whether a very long one costs one request or two.
ID_BATCH = 100

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


# The length under which a name keeps a cut word rather than lose more of the
# title. A name that says too little is worse than a name ending in half a word.
SLUG_MIN_CHARS = 24


def slugify(
    text: str, limit: int = 48, default: str = "section", whole_words: bool = False
) -> str:
    """Reduce text to the lower-case underscore form used for names on disk.

    Directory names, chapter file names and reference tags all pass through
    here, so a work held in full and the same work cited by another paper end
    up under one identifier. Callers naming something other than a section
    should say so: `default` is what comes back when nothing survives.

    `whole_words` cuts back to the last `_` when the cut at `limit` falls
    inside a word. It is off by default, and only a chapter file name asks for
    it: a reference tag sits inside the chapters of every paper citing the
    work, so a tag that moves breaks citations across the whole collection.
    """
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    # Fold accents onto their base letter first. Stripping them as punctuation
    # instead turns Glück into gl_ck and Argüelles into arg_elles, which read
    # as damage rather than as names.
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    cut = text[:limit]
    if whole_words and len(text) > limit and text[limit] != "_":
        # The cut fell inside a word. The last `_` is where that word began.
        shorter = cut.rsplit("_", 1)[0] if "_" in cut else cut
        if len(shorter) >= SLUG_MIN_CHARS:
            cut = shorter
    return cut.rstrip("_") or default


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


def read_feed(params: dict) -> str:
    url = "%s?%s" % (API_URL, urllib.parse.urlencode(params))
    query = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for _ in range(MAX_RETRIES):
        try:
            # The gate holds the three seconds arXiv asks for, so a retry waits
            # exactly as long as a first attempt does.
            with rate_gate.request(API_HOST):
                with urllib.request.urlopen(query, timeout=REQUEST_TIMEOUT_S) as response:
                    return response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as error:  # noqa: PERF203
            last_error = error
    raise RuntimeError("arXiv API request failed: %s" % last_error)


def fetch_feed(search_query: str, max_results: int) -> str:
    return read_feed(
        {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )


def fetch_by_ids(arxiv_ids: list[str]) -> list[dict]:
    """The record of each identifier given, as far as arXiv knows it.

    arXiv answers an identifier it does not know with an error entry, which
    carries no identifier of its own and thus drops out here. The caller gets
    fewer records than it asked for, and never a wrong one.
    """
    entries = []
    for start in range(0, len(arxiv_ids), ID_BATCH):
        batch = arxiv_ids[start : start + ID_BATCH]
        feed = read_feed({"id_list": ",".join(batch), "start": 0, "max_results": len(batch)})
        entries.extend(entry for entry in parse_entries(feed) if entry["arxiv_id"] in batch)
    return entries


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
                # Free text the authors write. Most records give a page count
                # in it, which is the only length arXiv publishes at all.
                "comment": collapse_whitespace(entry.findtext(ARXIV_NS + "comment") or ""),
                "pdf_url": pdf_url,
                "abs_url": "https://arxiv.org/abs/%s" % arxiv_id,
            }
        )
    return entries


def split_id(raw_id: str) -> tuple[str, str]:
    """'http://arxiv.org/abs/1706.03621v3' -> ('1706.03621', 'v3').

    An old-style identifier names its archive, and the archive is part of it:
    '.../abs/hep-ph/0207172v1' -> ('hep-ph/0207172', 'v1').
    """
    tail = raw_id.split("/abs/", 1)[-1] if "/abs/" in raw_id else raw_id.rsplit("/", 1)[-1]
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


def run_search(
    title: str | None, author: str | None, year: int | None, max_results: int = 10
) -> dict:
    """The query ladder, scored: what `main` prints and what `identity` reads.

    Three rungs, each looser than the one before, and the first that answers
    wins. Raises `RuntimeError` when arXiv answers none of them.
    """
    query = build_search_query(title, author, year)
    entries = parse_entries(fetch_feed(query, max_results))

    used_query = query
    for build in (build_fallback_query, build_loose_query):
        if entries:
            break
        looser = build(title, author)
        if not looser or looser == used_query:
            continue
        try:
            entries = parse_entries(fetch_feed(looser, max_results))
            used_query = looser
        except (RuntimeError, ET.ParseError):
            entries = []

    results = []
    for entry in entries:
        score, match, agreement = score_entry(entry, title, author, year)
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

    return {
        "query": {
            "title": title,
            "author": author,
            "year": year,
            "search_query": used_query,
        },
        "match": overall,
        "results": results,
    }
