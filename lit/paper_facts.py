"""The facts that describe a candidate paper: its length, its kind, its citations.

A search reports which papers answer a question. These fields say what each
answer is: a 63-page report in `Phys.Rept.`, or a 4-page contribution to a
workshop. An agent reads them and chooses what to read first.

None of them enters the score. Citation count and author count both point the
wrong way for a research question: a recent paper that settles a point carries
few citations, and a large collaboration carries many authors and says nothing
about the kind of the paper. So these travel beside the score as fields, and the
caller decides.

A fact that no source gives is `None`. It is never `0`, and never a guess.
"""

from __future__ import annotations

import re

from lit import references
from lit.text import collapse_whitespace

# The first "<number> page" or "<number> pages" of an arXiv comment. The comment
# is free text, so this reads a length where the authors wrote one and nothing
# where they wrote something else.
PAGE_IN_COMMENT = re.compile(r"(\d+)\s*pages?\b", re.IGNORECASE)

# A number above this is not a length. A comment carries volume numbers, years
# and conference dates, and any of them can stand next to the word "pages".
PAGE_COUNT_MAX = 1000

# The journals whose name says that a paper is a review. A journal name is
# evidence about the kind of a paper. An author count is not, and a citation
# count is not. Comparison goes through `normalise_venue`, so the spelling of
# the spaces and the full stops here does not matter.
REVIEW_VENUES = (
    "Phys.Rept.",
    "Rev.Mod.Phys.",
    "Prog.Part.Nucl.Phys.",
    "Ann.Rev.Nucl.Part.Sci.",
    "Ann.Rev.Astron.Astrophys.",
    "Living Rev.Rel.",
)

# The INSPIRE document types that name a review. INSPIRE gives a document type
# for some records only.
REVIEW_DOCUMENT_TYPES = frozenset({"review"})

# What one INSPIRE search asks for. `references.BATCH_SIZE` is 40, so a
# shortlist of this length costs exactly one request.
INSPIRE_FIELDS = (
    "arxiv_eprints",
    "citation_count",
    "document_type",
    "publication_info",
    "number_of_pages",
    "control_number",
)


# --------------------------------------------------------------------------
# length
# --------------------------------------------------------------------------


def page_count(comment: str, inspire_pages: object = None) -> tuple[int | None, str | None]:
    """The length of a paper, and which source gave it.

    The arXiv comment comes first, because arXiv answers for every preprint and
    INSPIRE holds no record for many of them. Returns (None, None) when neither
    source gives a number that can be a length.
    """
    match = PAGE_IN_COMMENT.search(comment or "")
    if match:
        pages = int(match.group(1))
        if 1 <= pages <= PAGE_COUNT_MAX:
            return pages, "arxiv_comment"

    if isinstance(inspire_pages, (int, str)):
        text = str(inspire_pages).strip()
        if text.isdigit() and 1 <= int(text) <= PAGE_COUNT_MAX:
            return int(text), "inspire"

    return None, None


# --------------------------------------------------------------------------
# kind
# --------------------------------------------------------------------------


def normalise_venue(text: str) -> str:
    """Lower case, without spaces and without full stops.

    `Phys. Rept.` and `Phys.Rept.` then compare as one string, which is what
    lets an arXiv `journal_ref` and an INSPIRE `publication_info` be read
    against the same list of names.
    """
    return collapse_whitespace(text or "").lower().replace(" ", "").replace(".", "")


def classify_kind(journal: str, document_types: list[str] | None = None) -> str:
    """What kind of paper this is: `review`, `article` or `unknown`.

    It reads the journal name and the INSPIRE document types, and nothing else.
    It reads no author count and no citation count: a paper with 136 authors and
    645 citations is not thereby a review, and treating either number as
    evidence would rank a large collaboration's measurement as a survey.

    A preprint has no venue and no document type. Its kind is `unknown`, which
    says that nobody answered — not that the paper is not a review.
    """
    types = [collapse_whitespace(str(item)).lower() for item in document_types or []]
    if any(item in REVIEW_DOCUMENT_TYPES for item in types):
        return "review"

    venue = normalise_venue(journal)
    if venue and any(venue.startswith(normalise_venue(name)) for name in REVIEW_VENUES):
        return "review"

    if venue or types:
        return "article"
    return "unknown"


def describe(entry: dict) -> None:
    """Write `pages`, `pages_source` and `kind` onto one candidate.

    Pure, and safe to run on a candidate INSPIRE never described: it then reads
    the arXiv comment and the arXiv `journal_ref` alone.
    """
    pages, source = page_count(entry.get("comment", ""), entry.get("inspire_pages"))
    entry["pages"] = pages
    entry["pages_source"] = source
    entry["kind"] = classify_kind(
        entry.get("journal") or entry.get("journal_ref", ""),
        entry.get("document_type"),
    )


# --------------------------------------------------------------------------
# INSPIRE
# --------------------------------------------------------------------------


def enrich(entries: list[dict]) -> dict:
    """Describe these candidates from INSPIRE, in one request.

    Writes `citation_count`, `document_type`, `inspire_id`, `journal` and
    `inspire_pages` onto every entry INSPIRE holds. An entry INSPIRE does not
    hold keeps `None` in each of them, because a silent source is not a count of
    zero.

    Returns {"requested", "matched", "note"} for the report. It never raises:
    `references.inspire_search` answers a failed request with an empty list.
    """
    for entry in entries:
        for field in ("citation_count", "document_type", "inspire_id", "journal"):
            entry.setdefault(field, None)
        entry.setdefault("inspire_pages", None)

    identifiers = [entry["arxiv_id"] for entry in entries if entry.get("arxiv_id")]
    if not identifiers:
        return {"requested": 0, "matched": 0, "note": "no candidate carries an arXiv identifier"}

    query = " or ".join('arxiv:"%s"' % identifier for identifier in identifiers)
    records = references.inspire_search(query, INSPIRE_FIELDS, size=len(identifiers))

    by_identifier: dict[str, dict] = {}
    for metadata in records:
        for eprint in metadata.get("arxiv_eprints") or []:
            value = collapse_whitespace(str(eprint.get("value") or ""))
            if value:
                by_identifier.setdefault(value, metadata)

    matched = 0
    for entry in entries:
        metadata = by_identifier.get(entry.get("arxiv_id", ""))
        if not metadata:
            continue
        matched += 1
        publication, _ = references.inspire_lookup.format_publication(
            metadata.get("publication_info")
        )
        count = metadata.get("citation_count")
        entry["citation_count"] = count if isinstance(count, int) else None
        entry["document_type"] = [
            collapse_whitespace(str(item)) for item in metadata.get("document_type") or []
        ]
        entry["inspire_id"] = (
            str(metadata.get("control_number")) if metadata.get("control_number") else None
        )
        entry["journal"] = publication["journal"] or None
        entry["inspire_pages"] = metadata.get("number_of_pages")

    note = None
    if not records:
        note = "INSPIRE answered nothing; citation counts and document types are null"
    return {"requested": len(entries), "matched": matched, "note": note}
