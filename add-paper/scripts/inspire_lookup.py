#!/usr/bin/env python3
"""Ask INSPIRE-HEP where an arXiv paper was published.

arXiv knows the preprint. Its `journal_ref` field is filled in by the authors
and is empty for most records, so it does not say where the paper ended up.
INSPIRE-HEP keys its own records on the arXiv identifier and does say.

Prints a JSON report on stdout. No side effects; nothing is downloaded.

The report's "found" field says whether INSPIRE holds the paper at all. A
paper that INSPIRE holds but that has not been published yet comes back with
"found": true and an empty "journal" — that is a preprint, not a miss.

INSPIRE allows 15 requests per IP in any 5-second window. One paper costs one
request, so a single run never comes near that; a run that is rate-limited
anyway waits out the whole window before it tries again.

Usage:
    inspire_lookup.py 2307.09241
    inspire_lookup.py --doi 10.1016/j.ppnp.2018.01.006
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rate_gate  # noqa: E402
from arxiv_search import USER_AGENT, collapse_whitespace  # noqa: E402

API_ROOT = "https://inspirehep.net/api"
API_HOST = "inspirehep.net"
RECORD_URL = "https://inspirehep.net/literature/%s"

REQUEST_TIMEOUT_S = 30.0
MAX_RETRIES = 3
RETRY_DELAY_S = 3.0

# INSPIRE allows 15 requests per IP in any 5-second window and answers the
# rest with HTTP 429. A blocked request still counts against the quota, so
# retrying before the window has passed only spends the next slot on another
# 429. Wait out the whole window.
RATE_LIMIT_WINDOW_S = 5.0
MAX_RETRY_DELAY_S = 60.0

# The pace between two INSPIRE requests. Every request to INSPIRE in these
# scripts passes through `fetch_record` below, whether it reads one record or
# runs a search, so the pace belongs beside that function. `references.py` reads
# the name from here.
INSPIRE_PACE_S = 0.5
rate_gate.set_interval(API_HOST, INSPIRE_PACE_S)

# An erratum is published separately from the paper it corrects. It belongs in
# its own row of INDEX.md, never in the Journal field.
CORRECTION_MATERIALS = ("erratum", "addendum", "corrigendum")


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------


def format_pages(entry: dict) -> str:
    """'113010' from an article id, or '1-68' from a page range."""
    artid = collapse_whitespace(str(entry.get("artid") or ""))
    if artid:
        return artid
    start = collapse_whitespace(str(entry.get("page_start") or ""))
    end = collapse_whitespace(str(entry.get("page_end") or ""))
    if start and end:
        return "%s-%s" % (start, end)
    return start


def format_entry(entry: dict) -> str:
    """'Phys.Rev.D 108 (2023) 113010', with each missing part left out."""
    parts = [collapse_whitespace(str(entry.get("journal_title") or ""))]
    volume = collapse_whitespace(str(entry.get("journal_volume") or ""))
    if volume:
        parts.append(volume)
    year = entry.get("year")
    if year:
        parts.append("(%s)" % year)
    pages = format_pages(entry)
    if pages:
        parts.append(pages)
    return " ".join(part for part in parts if part)


def format_publication(publication_info: list[dict] | None) -> tuple[dict, list[str]]:
    """Split INSPIRE's publication_info into the publication and its errata.

    Returns ({journal, year}, [formatted erratum, ...]). The journal is empty
    when no entry names a journal — a record that carries only a conference
    number, or none at all.
    """
    publication = {"journal": "", "year": None}
    errata = []
    for entry in publication_info or []:
        if not entry.get("journal_title"):
            continue
        material = str(entry.get("material") or "").lower()
        if material in CORRECTION_MATERIALS:
            errata.append(format_entry(entry))
        elif not publication["journal"]:
            publication = {"journal": format_entry(entry), "year": entry.get("year")}
    return publication, errata


# --------------------------------------------------------------------------
# the API
# --------------------------------------------------------------------------


def strip_version(arxiv_id: str) -> str:
    """'2307.09241v3' -> '2307.09241'."""
    return re.sub(r"v\d+$", "", collapse_whitespace(arxiv_id))


def fetch_record(path: str) -> dict | None:
    """GET one INSPIRE record. None means INSPIRE does not hold it (404)."""
    url = "%s/%s" % (API_ROOT, path)
    query = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error = None
    for attempt in range(MAX_RETRIES):
        delay = RETRY_DELAY_S
        try:
            # The gate paces this against every other INSPIRE request, here and
            # in any other process reading the same collection.
            with rate_gate.request(API_HOST):
                with urllib.request.urlopen(query, timeout=REQUEST_TIMEOUT_S) as response:
                    return json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 429:
                # Never less than the rate-limit window, and longer when
                # INSPIRE says so itself.
                retry_after = error.headers.get("Retry-After") if error.headers else None
                delay = RATE_LIMIT_WINDOW_S
                if retry_after and str(retry_after).strip().isdigit():
                    delay = max(delay, float(str(retry_after).strip()))
                delay = min(delay, MAX_RETRY_DELAY_S)
                last_error = error
            elif 500 <= error.code < 600:
                last_error = error
            else:
                raise RuntimeError("INSPIRE answered HTTP %d" % error.code) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
        if attempt < MAX_RETRIES - 1:
            time.sleep(delay)
    raise RuntimeError("INSPIRE did not answer: %s" % last_error)


def build_report(record: dict) -> dict:
    metadata = record.get("metadata") or {}
    publication, errata = format_publication(metadata.get("publication_info"))
    dois = [
        collapse_whitespace(str(doi.get("value") or ""))
        for doi in metadata.get("dois") or []
        if str(doi.get("material") or "").lower() not in CORRECTION_MATERIALS
    ]
    inspire_id = metadata.get("control_number")
    titles = metadata.get("titles") or []
    eprints = [
        collapse_whitespace(str(eprint.get("value") or ""))
        for eprint in metadata.get("arxiv_eprints") or []
    ]
    return {
        "found": True,
        # Empty for a paper that was never posted to arXiv — a thesis, or an
        # older conference proceeding.
        "arxiv_id": eprints[0] if eprints else "",
        "journal": publication["journal"],
        "published_year": publication["year"],
        "doi": dois[0] if dois else "",
        "errata": errata,
        "title": collapse_whitespace(str(titles[0].get("title") or "")) if titles else "",
        "document_type": metadata.get("document_type") or [],
        "preprint_date": metadata.get("preprint_date") or "",
        "inspire_id": inspire_id,
        "inspire_url": RECORD_URL % inspire_id if inspire_id else "",
    }


def missing(reason: str) -> dict:
    return {
        "found": False,
        "reason": reason,
        "journal": "",
        "published_year": None,
        "doi": "",
        "errata": [],
    }


def lookup_by_arxiv(arxiv_id: str) -> dict:
    """Look a paper up by its arXiv identifier. Never raises."""
    identifier = strip_version(arxiv_id)
    if not identifier:
        return missing("no arXiv identifier given")
    try:
        record = fetch_record("arxiv/%s" % urllib.parse.quote(identifier, safe="/."))
    except RuntimeError as error:
        return missing(str(error))
    if record is None:
        return missing("INSPIRE holds no record for arXiv:%s" % identifier)
    return build_report(record)


def lookup_by_doi(doi: str) -> dict:
    """Look a paper up by its DOI. Never raises."""
    identifier = collapse_whitespace(doi)
    if not identifier:
        return missing("no DOI given")
    try:
        record = fetch_record("doi/%s" % urllib.parse.quote(identifier, safe="/."))
    except RuntimeError as error:
        return missing(str(error))
    if record is None:
        return missing("INSPIRE holds no record for doi:%s" % identifier)
    return build_report(record)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("arxiv_id", nargs="?", help="arXiv identifier, for example 2307.09241")
    parser.add_argument("--doi", help="look the paper up by DOI instead")
    args = parser.parse_args()

    if not args.arxiv_id and not args.doi:
        parser.error("give an arXiv identifier or --doi")

    report = lookup_by_arxiv(args.arxiv_id) if args.arxiv_id else missing("no arXiv identifier")
    if not report["found"] and args.doi:
        report = lookup_by_doi(args.doi)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
