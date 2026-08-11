#!/usr/bin/env python3
"""Turn a paper's bibliography into records that a citation can point at.

A citation in a converted chapter reads `[cite: Lipari:2002at]`, and the key on
its own is the citing author's private label that nothing in the collection can
interpret. This module reads the bibliography that arXiv ships alongside the
TeX, works out which publication each key names, and asks INSPIRE-HEP and
Crossref for the exact title, authors, year, journal and DOI.

The LaTeX key is the only thing that maps a `\\cite` to a publication — INSPIRE
cannot do it, because its own reference labels are bibliography *numbers*, not
keys. So the local `.bbl` or `.bib` always comes first, and the online lookups
only make its entries exact.

What comes back is a list of records shaped for reference_store.py, each also
carrying the `key` it was cited by. Nothing is invented: a work no lookup
recognises keeps whatever its own bibliography said and is marked unverified,
because a citation pointing at the wrong paper is worse than one pointing at a
thin description of the right one.

Usage:
    references.py --source-dir ./src --arxiv-id 2307.09241
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inspire_lookup  # noqa: E402
import rate_gate  # noqa: E402
import reference_store  # noqa: E402
from arxiv_search import (  # noqa: E402
    EXACT_TITLE_RATIO,
    USER_AGENT,
    collapse_whitespace,
    fetch_by_ids,
    normalize_title,
)

CROSSREF_URL = "https://api.crossref.org/works/%s"
CROSSREF_HOST = "api.crossref.org"
CROSSREF_TIMEOUT_S = 20.0

# The pace Crossref asks of a client with no polite-pool token.
CROSSREF_PACE_S = 0.5
rate_gate.set_interval(CROSSREF_HOST, CROSSREF_PACE_S)

# INSPIRE allows 15 requests per IP in any 5-second window. Every lookup here
# is batched, so a 74-reference paper costs a handful of requests; this keeps
# even a pathological one under the limit. The pace itself lives in
# `inspire_lookup`, beside the one function that sends every INSPIRE request.
INSPIRE_PACE_S = inspire_lookup.INSPIRE_PACE_S
BATCH_SIZE = 40

INSPIRE_FIELDS = (
    "control_number", "titles", "authors", "publication_info", "dois",
    "arxiv_eprints", "citation_count", "texkeys",
)

# INSPIRE's own key style: Surname:YYYYabc. A paper whose keys look like this
# took them from INSPIRE, and INSPIRE can hand them straight back.
TEXKEY = re.compile(r"^[A-Za-z][\w'-]*:\d{4}[a-z]{2,3}$")

CITE_COMMAND = re.compile(
    r"\\(?:cite|citep|citet|citealp|citealt|citeauthor|citeyear|onlinecite)"
    r"\s*(?:\[[^\]]*\])*\s*\{([^}]*)\}"
)

# LaTeX accents, as the combining character that follows the letter they sit on.
ACCENTS = {
    '"': "̈", "'": "́", "`": "̀", "^": "̂",
    "~": "̃", "=": "̄", ".": "̇",
}
# Commands that stand for a letter or a mark of their own. Without these,
# \textendash{} vanishes and glues "Neutrino-nucleus" into "Neutrinonucleus".
LETTERS = {
    "textendash": "–", "textemdash": "—", "textquotesingle": "'",
    "ss": "ß", "aa": "å", "AA": "Å", "ae": "æ",
    "AE": "Æ", "oe": "œ", "OE": "Œ", "o": "ø",
    "O": "Ø", "l": "ł", "L": "Ł", "i": "i", "j": "j",
}

# In a .bbl these carry the meaning in their *second* argument:
# \bibinfo {author} {P.~Lipari}, \href {https://doi.org/...} {Nucl. Phys. B}.
SECOND_ARGUMENT = ("bibinfo", "bibfield", "href", "Eprint", "@href", "translation")

# revtex's own bookkeeping. Their arguments are markers, not words: unwrapped
# like anything else they leave "NoStop" sitting at the end of a reference.
BOOKKEEPING = re.compile(
    r"\\(?:BibitemOpen|BibitemShut|bibitem(?:No)?Stop|EOS|natexlab|noopsort)"
    r"\s*(?:\{[^{}]*\})?"
)

# Every other command: keep what it wraps, drop the name. It must leave the
# commands above alone until their second argument is free of braces — hence
# the lookahead, which still lets through look-alikes such as \href@noop.
GENERIC_COMMAND = re.compile(
    r"\\(?!(?:%s)[^a-zA-Z@])[a-zA-Z@]+\*?\s*\{([^{}]*)\}"
    % "|".join(re.escape(name) for name in SECOND_ARGUMENT)
)

DOI_PATTERNS = (
    re.compile(r"(?:https?://)?(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s{}\"'<>]+)", re.IGNORECASE),
    re.compile(r"\bdoi\s*[:=]\s*\{?(10\.\d{4,9}/[^\s{},\"'<>]+)", re.IGNORECASE),
    re.compile(r"\b(10\.\d{4,9}/[^\s{},;\"'<>]+)"),
)
ARXIV_PATTERNS = (
    re.compile(r"(?:https?://)?arxiv\.org/(?:abs|pdf)/([\w.\-]+/\d{7}|\d{4}\.\d{4,5})", re.IGNORECASE),
    re.compile(r"\barxiv\s*[:=]\s*\{?([\w.\-]+/\d{7}|\d{4}\.\d{4,5})", re.IGNORECASE),
    re.compile(r"\beprint\s*[:=]\s*\{?\"?([\w.\-]+/\d{7}|\d{4}\.\d{4,5})", re.IGNORECASE),
    re.compile(r"\b((?:hep-(?:ph|ex|th|lat)|nucl-(?:th|ex)|astro-ph|gr-qc|math-ph|quant-ph)/\d{7})"),
)

# An identifier carries four digits that read as a year and are not one. The
# arXiv number 2004.06601 belongs to April 2020, and hep-ph/0207172 to July
# 2002. A DOI suffix and a URL hold digits of their own. Take all of them out
# of the text before anything looks in it for a year.
IDENTIFIER_PATTERNS = (
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b"),
    re.compile(r"\b[\w.\-]+/\d{7}(?:v\d+)?\b"),
    re.compile(r"\b10\.\d{4,9}/\S+"),
)


# --------------------------------------------------------------------------
# reading the citing paper
# --------------------------------------------------------------------------


def collect_cite_keys(body: str) -> list[str]:
    """Every key the body cites, in the order it first cites them."""
    keys: list[str] = []
    seen = set()
    for match in CITE_COMMAND.finditer(body):
        for key in match.group(1).split(","):
            key = collapse_whitespace(key)
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


# --------------------------------------------------------------------------
# LaTeX scanning
# --------------------------------------------------------------------------


def skip_group(text: str, index: int, opener: str, closer: str) -> int:
    """Index just past a balanced group, counting braces inside brackets too."""
    depth = 0
    while index < len(text):
        character = text[index]
        if character == "\\":
            index += 2
            continue
        if character == opener:
            depth += 1
        elif character == closer:
            depth -= 1
            if depth == 0:
                return index + 1
        elif opener == "[" and character == "{":
            index = skip_group(text, index, "{", "}") - 1
        index += 1
    return index


def read_braced(text: str, index: int) -> tuple[str, int]:
    """The contents of the group starting at `index`, and the index past it."""
    end = skip_group(text, index, "{", "}")
    return text[index + 1 : max(end - 1, index + 1)], end


def restore_accents(text: str) -> str:
    """'Arg\\"uelles' -> 'Argüelles', 'Sobczy\\'nski' -> 'Sobczyński'.

    Author surnames are what tags are built from, so an accent dropped here
    turns into a different tag than the same name spelled plainly elsewhere.
    """
    def combine(match: re.Match) -> str:
        letter = match.group(2) or match.group(3) or ""
        return unicodedata.normalize("NFC", letter + ACCENTS[match.group(1)])

    text = re.sub(
        r"\\([\"'`^~=.])\s*(?:\{(\w)\}|(\w))",
        combine,
        text,
    )
    for command, replacement in LETTERS.items():
        text = re.sub(r"\\%s(?![a-zA-Z])\s*(?:\{\})?" % re.escape(command), replacement, text)
    return text


def flatten(text: str) -> str:
    """Reduce a LaTeX bibliography entry to the words a reader would see.

    The two rules have to alternate, innermost first. `\\bibinfo {author}
    {\\bibnamefont {Kling}}` only becomes "Kling" once the inner command is
    gone; unwrap it in the wrong order and `\\bibinfo {author}` reads as a
    one-argument command whose text is the field name, leaving "author" in the
    middle of the reference.
    """
    text = restore_accents(text)
    text = BOOKKEEPING.sub(" ", text)
    for _ in range(6):
        before = text
        while True:
            unwrapped = GENERIC_COMMAND.sub(r"\1", text)
            if unwrapped == text:
                break
            text = unwrapped
        for name in SECOND_ARGUMENT:
            text = re.sub(
                r"\\%s\s*\{[^{}]*\}\s*\{([^{}]*)\}" % re.escape(name), r"\1", text
            )
        if text == before:
            break
    text = re.sub(r"\\[a-zA-Z@]+\*?\s*", " ", text)
    text = text.replace("~", " ").replace("\\&", "&")
    text = re.sub(r"[{}]", "", text)
    text = text.replace("``", '"').replace("''", '"')
    # A trailing full stop is left alone: it ends a reference line naturally,
    # and stripping it turns the author "Farzan, Y." into "Farzan, Y".
    return collapse_whitespace(text).strip(" ,;")


# --------------------------------------------------------------------------
# identifiers hiding in the entry text
# --------------------------------------------------------------------------


# A journal, a volume and a page name an article exactly, and a bibliography
# that predates DOIs gives nothing else. Two orderings are in circulation:
# "Phys. Rev. C 48 (1993) 1246" and "Phys. Lett. B429, 263 (1998)".
JOURNAL_REFS = (
    re.compile(
        r"([A-Z][A-Za-z.\s]{2,40}?)\s*([A-Z]?)\s*(\d+)\s*"
        r"(?:,\s*(?:nos?\.?\s*\d+\s*)?)?,?\s*\((\d{4})\)\s*,?\s*(\d+)"
    ),
    re.compile(
        r"([A-Z][A-Za-z.\s]{2,40}?)\s*([A-Z]?)\s*(\d+)\s*,\s*(\d+)\s*\((\d{4})\)"
    ),
)


def parse_journal_ref(text: str) -> tuple[str, str, str] | None:
    """('Phys.Rev.C', '48', '1246') out of 'Phys. Rev. C 48 (1993) 1246'."""
    for position, pattern in enumerate(JOURNAL_REFS):
        match = pattern.search(text)
        if not match:
            continue
        name, series, volume = match.group(1), match.group(2), match.group(3)
        page = match.group(5) if position == 0 else match.group(4)
        journal = collapse_whitespace(name).replace(" ", "") + series
        if len(journal) < 4:
            continue
        return journal, volume, page
    return None


def journal_key(journal: str, volume: str, page: str) -> str:
    """The comparable form of a journal reference, free of house style.

    'Phys. Rev. C' and 'Phys.Rev.C' name one journal; only the letters decide.
    """
    return "%s,%s,%s" % (re.sub(r"[^0-9a-z]+", "", journal.lower()), volume, page)


def volume_page(key: str) -> str:
    """The journal key with the journal dropped: '48,1246'.

    Bibliographies spell journals out ('Nuclear Physics A291') where INSPIRE
    abbreviates ('Nucl.Phys.A'), and no table of abbreviations ever covers
    every house style. Within one paper's reference list the volume and page
    alone still single a work out, so they serve as the looser join.
    """
    return key.split(",", 1)[1] if "," in key else ""


def key_from_publication(entries: list[dict] | None) -> list[str]:
    """Journal keys for every way an INSPIRE record states where it appeared."""
    keys = []
    for entry in entries or []:
        title = str(entry.get("journal_title") or "")
        volume = str(entry.get("journal_volume") or "")
        page = str(entry.get("page_start") or entry.get("artid") or "")
        if title and volume and page:
            keys.append(journal_key(title, volume, page))
    return keys


def find_doi(text: str) -> str:
    for pattern in DOI_PATTERNS:
        match = pattern.search(text)
        if match:
            return reference_store.normalize_doi(match.group(1))
    return ""


def find_arxiv(text: str) -> str:
    for pattern in ARXIV_PATTERNS:
        match = pattern.search(text)
        if match:
            return reference_store.normalize_arxiv(match.group(1))
    return ""


# --------------------------------------------------------------------------
# .bib files
# --------------------------------------------------------------------------


BIB_FIELDS = {
    "title": "title",
    "author": "author",
    "year": "year",
    "journal": "journal",
    "volume": "volume",
    "pages": "pages",
    "number": "number",
    "doi": "doi",
    "eprint": "eprint",
    "archiveprefix": "archiveprefix",
}


def parse_bib_text(text: str) -> dict[str, dict]:
    """key -> fields, for every @entry in a .bib file.

    Written by hand rather than with a BibTeX library: the files that reach
    here are whatever the authors happened to submit, and a parser that gives
    up on one malformed entry would cost the whole bibliography.
    """
    entries: dict[str, dict] = {}
    for match in re.finditer(r"@(\w+)\s*\{", text):
        if match.group(1).lower() in ("comment", "preamble", "string", "control"):
            continue
        end = skip_group(text, match.end() - 1, "{", "}")
        body = text[match.end() : max(end - 1, match.end())]
        key, _, rest = body.partition(",")
        key = collapse_whitespace(key)
        if not key:
            continue
        entries[key] = parse_bib_fields(rest)
    return entries


def parse_bib_fields(body: str) -> dict:
    fields: dict[str, str] = {}
    index = 0
    while index < len(body):
        match = re.compile(r"(\w+)\s*=\s*").search(body, index)
        if not match:
            break
        name = match.group(1).lower()
        index = match.end()
        if index >= len(body):
            break
        if body[index] == "{":
            value, index = read_braced(body, index)
        elif body[index] == '"':
            end = body.find('"', index + 1)
            while end > 0 and body[end - 1] == "\\":
                end = body.find('"', end + 1)
            value = body[index + 1 : end if end > 0 else len(body)]
            index = (end + 1) if end > 0 else len(body)
        else:
            end = body.find(",", index)
            value = body[index : end if end > 0 else len(body)]
            index = (end + 1) if end > 0 else len(body)
        if name in BIB_FIELDS:
            fields[name] = collapse_whitespace(value)
    return fields


def from_bib_entry(fields: dict) -> dict:
    """A .bib entry as a reference record."""
    authors = [
        collapse_whitespace(name)
        for name in re.split(r"\s+and\s+", fields.get("author", ""))
        if collapse_whitespace(name)
    ]
    year = fields.get("year", "")
    journal = " ".join(
        part
        for part in (
            collapse_whitespace(fields.get("journal", "")),
            collapse_whitespace(fields.get("volume", "")),
            "(%s)" % year if year else "",
            collapse_whitespace(fields.get("pages", "")).split("--")[0],
        )
        if part
    )
    eprint = fields.get("eprint", "")
    prefix = fields.get("archiveprefix", "arXiv").lower()
    record = {
        "title": flatten(fields.get("title", "")),
        "authors": [flatten(name) for name in authors],
        "year": int(year) if year.isdigit() else None,
        "journal": collapse_whitespace(journal) if fields.get("journal") else "",
        "doi": reference_store.normalize_doi(fields.get("doi", "")),
        "arxiv_id": reference_store.normalize_arxiv(eprint) if prefix == "arxiv" else "",
    }
    # The .bib states the parts outright, so they need no pattern to be found.
    page = collapse_whitespace(fields.get("pages", "")).split("--")[0].split("-")[0]
    if fields.get("journal") and fields.get("volume") and page:
        compact = collapse_whitespace(fields["journal"]).replace(" ", "")
        record["journal_key"] = journal_key(compact, fields["volume"], page)
        record["journal_query"] = "%s,%s,%s" % (compact, fields["volume"], page)
    return record


# --------------------------------------------------------------------------
# .bbl files and inline bibliographies
# --------------------------------------------------------------------------


def split_bibitems(text: str) -> list[tuple[str, str]]:
    """[(key, raw entry text)] in bibliography order."""
    items = []
    for match in re.finditer(r"\\bibitem\s*(?=[\[{])", text):
        index = match.end()
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == "[":
            index = skip_group(text, index, "[", "]")
            while index < len(text) and text[index].isspace():
                index += 1
        if index >= len(text) or text[index] != "{":
            continue
        key, index = read_braced(text, index)
        key = collapse_whitespace(key)
        following = re.search(r"\\bibitem\s*[\[{]|\\end\s*\{thebibliography\}", text[index:])
        body = text[index : index + following.start()] if following else text[index:]
        if key:
            items.append((key, body))
    return items


def parse_bibinfo(raw: str) -> dict:
    """The fields a revtex .bbl states outright, as \\bibinfo {name} {value}."""
    fields: dict[str, list[str]] = {}
    for match in re.finditer(r"\\bibinfo\s*\{", raw):
        name, index = read_braced(raw, match.end() - 1)
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw) or raw[index] != "{":
            continue
        value, _ = read_braced(raw, index)
        fields.setdefault(collapse_whitespace(name).lower(), []).append(flatten(value))
    return fields


NAME_LIKE = re.compile(
    r"^(?:[A-Z]\.\s*)*[A-Z][\w'\u2019-]+(?:\s+(?:[A-Z]\.\s*)*[A-Z][\w'\u2019-]+)?"
    r"(?:,?\s*(?:[A-Z]\.\s*)+)?$"
)


def guess_authors(text: str) -> tuple[list[str], str]:
    """Split 'F.A. Brieva and J.R. Rook, Nucl. Phys. A291 (1977) 299.'

    Terse bibliography styles give no field markers at all, so the split runs on
    what a name looks like — initials, or two capitalised words — and stops at
    the first chunk that is not one. Returns (authors, whatever followed).
    """
    chunks: list[tuple[str, int]] = []
    index = 0
    for separator in re.finditer(r",|\s+and\s+", text):
        chunks.append((text[index : separator.start()], index))
        index = separator.end()
    chunks.append((text[index:], index))

    authors: list[str] = []
    for chunk, start in chunks:
        candidate = collapse_whitespace(chunk)
        if candidate and len(candidate.split()) <= 4 and NAME_LIKE.match(candidate):
            authors.append(candidate)
            continue
        return authors, collapse_whitespace(text[start:]).strip(" ,;")
    return authors, ""


def mask_identifiers(text: str) -> str:
    """The text with each identifier replaced by as many spaces.

    Spaces rather than nothing: the words on either side of an identifier must
    stay two words.
    """
    for pattern in IDENTIFIER_PATTERNS:
        text = pattern.sub(lambda match: " " * len(match.group(0)), text)
    return text


def find_year(text: str) -> int | None:
    """The year that a bibliography entry states, and None where it states none.

    A year in parentheses is the year of the work. Where the entry gives none,
    the last four digits that can be a year are the best that the line offers.
    A year later than next year is neither: a page range or a report number
    reached the pattern.
    """
    plain = mask_identifiers(text)
    limit = datetime.date.today().year + 1
    years = re.findall(r"\((\d{4})\)", plain) or re.findall(r"\b(1[89]\d\d|20\d\d)\b", plain)
    for year in reversed(years):
        if int(year) <= limit:
            return int(year)
    return None


def from_bbl_entry(raw: str) -> dict:
    """A .bbl entry as a reference record, as far as its style permits."""
    stated = parse_bibinfo(raw)
    plain = flatten(raw)
    record = {
        "title": (stated.get("title") or [""])[0],
        "authors": [name for name in stated.get("author", []) if name],
        "year": None,
        "journal": "",
        "doi": find_doi(raw),
        "arxiv_id": find_arxiv(raw),
        "raw": plain,
    }
    years = stated.get("year") or []
    if years and years[0].isdigit():
        record["year"] = int(years[0])

    journal = (stated.get("journal") or [""])[0]
    if journal:
        record["journal"] = collapse_whitespace(
            " ".join(
                part
                for part in (
                    journal,
                    (stated.get("volume") or [""])[0],
                    "(%s)" % record["year"] if record["year"] else "",
                    (stated.get("pages") or [""])[0],
                )
                if part
            )
        )

    if not record["authors"]:
        # What follows the authors is the work itself: its title, where it
        # appeared, or both, depending on the style. It is not a journal
        # reference, and storing it as one puts a whole sentence in that
        # column — beside the same sentence already shown as the title. Keep it
        # for the tag, which needs words about the work, and nothing else.
        record["authors"], record["about"] = guess_authors(plain)
    if record["year"] is None:
        record["year"] = find_year(plain)

    found = parse_journal_ref(record["journal"] or plain)
    if found:
        record["journal_key"] = journal_key(*found)
        record["journal_query"] = ",".join(found)
        if not record["journal"]:
            name, volume, page = found
            year = record["year"]
            record["journal"] = collapse_whitespace(
                "%s %s %s %s" % (name, volume, "(%s)" % year if year else "", page)
            )
    return record


WORK_SEPARATOR = re.compile(r";(?![^{]*\})|\\\\")


def split_multiple_works(raw: str) -> list[str]:
    """One \\bibitem often holds several papers. Split it into one each.

    A bibliography that predates DOIs routinely packs a whole line of related
    work behind a single key, separated by a semicolon or a line break. Left
    whole, those become one record whose journal field is two journals.

    Splitting is refused unless the pieces really are separate references —
    each carrying an identifier, or each carrying a year of its own. Otherwise
    an entry ending '; see also the erratum' would fragment into a reference to
    nothing.
    """
    pieces = [piece for piece in WORK_SEPARATOR.split(raw) if collapse_whitespace(piece)]
    if len(pieces) < 2:
        return [raw]
    identified = [piece for piece in pieces if find_doi(piece) or find_arxiv(piece)]
    if len(identified) > 1:
        return pieces
    dated = [
        piece
        for piece in pieces
        if find_year(flatten(piece)) and len(flatten(piece).split()) >= 4
    ]
    return pieces if len(dated) > 1 else [raw]


# --------------------------------------------------------------------------
# putting the bibliography together
# --------------------------------------------------------------------------


def strip_comments(text: str) -> str:
    """Drop TeX comments. A .bbl is full of them, and they are not references.

    BibTeX styles write their own bookkeeping into the .bbl behind `%`. Left in,
    it flattens into the entry text and ends up in a title or a tag.
    """
    return "\n".join(
        re.sub(r"(?<!\\)((?:\\\\)*)%.*$", r"\1", line) for line in text.split("\n")
    )


def read_bibliography(source_dir: Path, body: str) -> tuple[dict[str, dict], list[tuple[str, str]]]:
    """(.bib entries by key, ordered .bbl items) from a paper's source."""
    bib: dict[str, dict] = {}
    for path in sorted(source_dir.rglob("*.bib")):
        try:
            bib.update(parse_bib_text(strip_comments(path.read_text(encoding="utf-8", errors="replace"))))
        except OSError:
            continue

    items: list[tuple[str, str]] = []
    for path in sorted(source_dir.rglob("*.bbl")):
        try:
            items.extend(
                split_bibitems(strip_comments(path.read_text(encoding="utf-8", errors="replace")))
            )
        except OSError:
            continue
    if not items:
        items = split_bibitems(strip_comments(body))
    return bib, items


def build_entries(source_dir: Path, body: str, keys: list[str]) -> list[dict]:
    """One record per cited work, from the paper's own bibliography alone.

    A key cited but never defined is dropped: there is nothing to say about it,
    and the citation keeps its original text so the omission stays visible.
    """
    bib, items = read_bibliography(source_dir, body)
    ordinals = {key: number for number, (key, _) in enumerate(items, start=1)}
    raws = dict(items)
    wanted = keys or list(raws) or list(bib)

    entries: list[dict] = []
    for key in wanted:
        raw = raws.get(key)
        pieces = split_multiple_works(raw) if raw else []
        for part, piece in enumerate(pieces or [None]):
            record: dict = {
                "key": key,
                "part": part,
                "ordinal": ordinals.get(key) if part == 0 else None,
                "title": "", "authors": [], "year": None, "journal": "",
                "doi": "", "arxiv_id": "", "journal_key": "", "raw": "", "about": "",
                "source": "bibliography", "match": "none", "verified": False,
            }
            if piece is not None:
                record.update(from_bbl_entry(piece))
            if part == 0 and key in bib:
                # The .bib is the authors' own structured data; the .bbl is what
                # BibTeX made of it. Prefer the former, field by field.
                for name, value in from_bib_entry(bib[key]).items():
                    if value:
                        record[name] = value
            if record["title"] or record["authors"] or record["doi"] or record["arxiv_id"] or record["raw"]:
                entries.append(record)
    return entries


# --------------------------------------------------------------------------
# INSPIRE
# --------------------------------------------------------------------------


def inspire_search(
    query: str, fields: tuple[str, ...], size: int = BATCH_SIZE, sort: str | None = None
) -> list[dict]:
    """Run one INSPIRE search and return the hits' metadata. Never raises."""
    return search_payload(query, fields, size, sort)[0]


def search_payload(
    query: str, fields: tuple[str, ...], size: int = BATCH_SIZE, sort: str | None = None
) -> tuple[list[dict], int]:
    """The hits' metadata and how many hits there are in all.

    A search that asks for twenty of three thousand answers with twenty. The
    total says which of those two numbers the caller is holding.
    """
    query_parts = {"q": query, "fields": ",".join(fields), "size": size}
    if sort:
        query_parts["sort"] = sort
    params = urllib.parse.urlencode(query_parts)
    try:
        # `fetch_record` holds the gate for the request, which is where the
        # pace between two INSPIRE calls is kept.
        payload = inspire_lookup.fetch_record("literature?" + params)
    except RuntimeError:
        return [], 0
    if not payload:
        return [], 0
    hits = (payload.get("hits") or {}).get("hits") or []
    total = (payload.get("hits") or {}).get("total")
    return (
        [hit.get("metadata") or {} for hit in hits],
        total if isinstance(total, int) else len(hits),
    )


def in_batches(items: list, size: int = BATCH_SIZE):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def from_inspire_record(metadata: dict) -> dict:
    """An INSPIRE record as a reference record."""
    publication, _ = inspire_lookup.format_publication(metadata.get("publication_info"))
    titles = metadata.get("titles") or []
    dois = [
        reference_store.normalize_doi(str(doi.get("value") or ""))
        for doi in metadata.get("dois") or []
        if str(doi.get("material") or "").lower() not in inspire_lookup.CORRECTION_MATERIALS
    ]
    eprints = [
        reference_store.normalize_arxiv(str(eprint.get("value") or ""))
        for eprint in metadata.get("arxiv_eprints") or []
    ]
    authors = [
        collapse_whitespace(str(author.get("full_name") or ""))
        for author in metadata.get("authors") or []
    ]
    keys = key_from_publication(metadata.get("publication_info"))
    return {
        "title": collapse_whitespace(str(titles[0].get("title") or "")) if titles else "",
        "authors": [name for name in authors if name],
        "year": publication["year"],
        "journal": publication["journal"],
        "journal_key": keys[0] if keys else "",
        "doi": dois[0] if dois else "",
        "arxiv_id": eprints[0] if eprints else "",
        "inspire_id": str(metadata.get("control_number") or ""),
        "citation_count": metadata.get("citation_count"),
        "source": "inspire",
    }


def recid_of(entry: dict) -> str:
    """The record number an INSPIRE reference points at, if it points anywhere."""
    reference = (entry.get("record") or {}).get("$ref") or ""
    return reference.rstrip("/").rsplit("/", 1)[-1] if reference else ""


def index_reference_list(entries: list[dict]) -> dict[str, dict]:
    """INSPIRE's reference list, keyed every way an entry can be matched.

    An older paper's reference list carries no titles and no DOIs at all —
    only where each work appeared. The journal key is what resolves those.
    """
    indexes: dict[str, dict] = {
        "doi": {}, "arxiv": {}, "journal": {}, "volume_page": {}, "title": {}, "ordinal": {},
    }
    clashing = set()
    for entry in entries:
        reference = entry.get("reference") or {}
        recid = recid_of(entry)
        if not recid:
            continue
        for doi in reference.get("dois") or []:
            indexes["doi"].setdefault(reference_store.normalize_doi(str(doi)), recid)
        eprint = reference.get("arxiv_eprint")
        for value in eprint if isinstance(eprint, list) else [eprint]:
            if value:
                indexes["arxiv"].setdefault(reference_store.normalize_arxiv(str(value)), recid)
        publication = reference.get("publication_info")
        for key in key_from_publication(
            publication if isinstance(publication, list) else [publication or {}]
        ):
            indexes["journal"].setdefault(key, recid)
            loose = volume_page(key)
            if indexes["volume_page"].setdefault(loose, recid) != recid:
                clashing.add(loose)
        title = ((reference.get("title") or {}).get("title")) or ""
        if title:
            indexes["title"].setdefault(normalize_title(str(title)), recid)
        label = collapse_whitespace(str(reference.get("label") or ""))
        if label.isdigit():
            indexes["ordinal"].setdefault(int(label), recid)

    # Two works in one bibliography sharing a volume and a page number is rare,
    # but where it happens the looser join cannot tell them apart, so it drops
    # both rather than pick one.
    for key in clashing:
        indexes["volume_page"].pop(key, None)
    return indexes


def match_reference_list(entries: list[dict], indexes: dict[str, dict]) -> None:
    """Attach an INSPIRE record number to each entry, in place.

    The ordinal join comes last and never counts as verified. A bibliography's
    order and INSPIRE's labels agree only while both lists hold the same works,
    and they stop agreeing at the first multi-work `\\bibitem` or the first
    reference INSPIRE could not resolve. Past that point the join is off by one
    and would hang a real, wrong publication on a real claim.
    """
    for entry in entries:
        wanted = {
            "doi": entry["doi"],
            "arxiv": entry["arxiv_id"],
            "journal": entry.get("journal_key", ""),
            "volume_page": volume_page(entry.get("journal_key", "")),
            "title": normalize_title(entry["title"]) if entry["title"] else "",
            "ordinal": entry["ordinal"],
        }
        for kind in ("doi", "arxiv", "journal", "volume_page", "title", "ordinal"):
            value = wanted[kind]
            recid = indexes[kind].get(value) if value else ""
            if recid:
                entry["inspire_id"] = recid
                entry["match"] = kind
                break


def lookup_unmatched(entries: list[dict]) -> None:
    """Find record numbers for the entries the reference list did not cover."""
    for field, prefix, kind in (("arxiv_id", "arxiv", "arxiv"), ("doi", "doi", "doi")):
        pending = [entry for entry in entries if not entry.get("inspire_id") and entry[field]]
        values = sorted({entry[field] for entry in pending})
        found: dict[str, str] = {}
        for batch in in_batches(values):
            query = " or ".join('%s:"%s"' % (prefix, value) for value in batch)
            for metadata in inspire_search(query, INSPIRE_FIELDS, size=len(batch)):
                record = from_inspire_record(metadata)
                if record[field]:
                    found[record[field]] = record["inspire_id"]
        for entry in pending:
            if entry[field] in found:
                entry["inspire_id"] = found[entry[field]]
                entry["match"] = kind

    lookup_by_journal(entries)

    pending = [
        entry
        for entry in entries
        if not entry.get("inspire_id") and TEXKEY.match(entry["key"]) and entry["part"] == 0
    ]
    keys = sorted({entry["key"] for entry in pending})
    found = {}
    for batch in in_batches(keys):
        query = " or ".join('texkeys:"%s"' % key for key in batch)
        for metadata in inspire_search(query, INSPIRE_FIELDS + ("texkeys",), size=len(batch)):
            for texkey in metadata.get("texkeys") or []:
                found[collapse_whitespace(str(texkey))] = str(metadata.get("control_number") or "")
    for entry in pending:
        if found.get(entry["key"]):
            entry["inspire_id"] = found[entry["key"]]
            entry["match"] = "texkey"


def lookup_by_journal(entries: list[dict]) -> None:
    """Find the works a pre-DOI bibliography names only by where they appeared.

    A journal, a volume and a page identify an article exactly, so this is a
    lookup and not a guess — but the parse that produced them is a guess, and a
    misread volume could land on a real, wrong article. The record only counts
    when its own author list contains the surname the bibliography gave.
    """
    pending = [
        entry
        for entry in entries
        if not entry.get("inspire_id") and entry.get("journal_key")
    ]
    if not pending:
        return

    # INSPIRE's journal search wants the name as journals write it —
    # "Adv.Nucl.Phys.,16,1", not the letters-only form used for comparison.
    queries = sorted({entry["journal_query"] for entry in pending if entry.get("journal_query")})
    found: dict[str, dict] = {}
    for batch in in_batches(queries):
        query = " or ".join("j %s" % item for item in batch)
        for metadata in inspire_search(query, INSPIRE_FIELDS, size=len(batch)):
            record = from_inspire_record(metadata)
            for key in key_from_publication(metadata.get("publication_info")):
                found.setdefault(key, record)

    for entry in pending:
        record = found.get(entry["journal_key"])
        if record:
            entry["inspire_id"] = record["inspire_id"]
            entry["match"] = "journal"


def fetch_by_recid(recids: list[str]) -> dict[str, dict]:
    """The authoritative record behind every number, with its citation count."""
    records: dict[str, dict] = {}
    for batch in in_batches(sorted(set(recids))):
        query = " or ".join("recid %s" % recid for recid in batch if recid.isdigit())
        if not query:
            continue
        for metadata in inspire_search(query, INSPIRE_FIELDS, size=len(batch)):
            number = str(metadata.get("control_number") or "")
            if number:
                records[number] = from_inspire_record(metadata)
    return records


# --------------------------------------------------------------------------
# Crossref, for everything outside high-energy physics
# --------------------------------------------------------------------------


def fetch_crossref(doi: str) -> dict | None:
    """Resolve a DOI that INSPIRE does not hold. Never raises."""
    url = CROSSREF_URL % urllib.parse.quote(doi, safe="/")
    query = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with rate_gate.request(CROSSREF_HOST):
            with urllib.request.urlopen(query, timeout=CROSSREF_TIMEOUT_S) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError,
            rate_gate.GateTimeout):
        return None
    work = payload.get("message") or {}
    if not work:
        return None

    titles = work.get("title") or []
    authors = []
    for author in work.get("author") or []:
        family = collapse_whitespace(str(author.get("family") or ""))
        given = collapse_whitespace(str(author.get("given") or ""))
        if family:
            authors.append("%s, %s" % (family, given) if given else family)
    dates = (work.get("issued") or {}).get("date-parts") or [[]]
    year = dates[0][0] if dates and dates[0] else None
    journal = " ".join(
        part
        for part in (
            collapse_whitespace((work.get("container-title") or [""])[0]),
            collapse_whitespace(str(work.get("volume") or "")),
            "(%s)" % year if year else "",
            collapse_whitespace(str(work.get("page") or "")).split("-")[0],
        )
        if part
    )
    return {
        "title": collapse_whitespace(str(titles[0])) if titles else "",
        "authors": authors,
        "year": year if isinstance(year, int) else None,
        "journal": collapse_whitespace(journal),
        "doi": reference_store.normalize_doi(str(work.get("DOI") or doi)),
        "source": "crossref",
    }


# --------------------------------------------------------------------------
# arXiv, for the works that only arXiv holds
# --------------------------------------------------------------------------


def fill_from_arxiv(entries: list[dict]) -> None:
    """Ask arXiv about the entries that neither INSPIRE nor Crossref answered.

    A comment, a note, a preprint that no journal published: INSPIRE holds many
    of them and not all, and Crossref holds only what carries a DOI. The
    bibliography prints an arXiv number for such a work, and arXiv answers that
    number with the title, the authors and the date it received the paper.

    That date gives the year. The digits of the number do not: 2004.06601 is
    from April 2020.

    Fills an empty field and keeps a full one, because the bibliography states
    the work as its own authors read it.
    """
    wanted: dict[str, list[dict]] = {}
    for entry in entries:
        arxiv_id = reference_store.normalize_arxiv(entry.get("arxiv_id") or "")
        if arxiv_id and not entry.get("inspire_id") and entry["source"] != "crossref":
            wanted.setdefault(arxiv_id, []).append(entry)
    if not wanted:
        return

    for record in fetch_by_ids(sorted(wanted)):
        for entry in wanted[record["arxiv_id"]]:
            for name in ("title", "authors", "year"):
                if not entry.get(name) and record.get(name):
                    entry[name] = record[name]
            if not entry.get("doi") and record.get("doi"):
                entry["doi"] = reference_store.normalize_doi(record["doi"])
            # arXiv answered the number that the bibliography itself printed,
            # which is the strongest match there is.
            entry["source"] = "arxiv"
            entry["match"] = "arxiv"


# --------------------------------------------------------------------------
# INSPIRE by title, the last resort
# --------------------------------------------------------------------------


def lookup_by_title(entries: list[dict]) -> None:
    """Match on the title alone, and say plainly that that is what happened.

    Accepted only above the same ratio arxiv_search.py calls an exact title
    match, and still left unverified: titles repeat across proceedings, theses
    and their journal versions.
    """
    for entry in entries:
        if entry.get("inspire_id") or not entry["title"]:
            continue
        wanted = normalize_title(entry["title"])
        for metadata in inspire_search('t "%s"' % entry["title"], INSPIRE_FIELDS, size=3):
            record = from_inspire_record(metadata)
            ratio = difflib.SequenceMatcher(None, wanted, normalize_title(record["title"])).ratio()
            if ratio >= EXACT_TITLE_RATIO:
                entry["inspire_id"] = record["inspire_id"]
                entry["match"] = "title"
                break


# --------------------------------------------------------------------------
# the whole job
# --------------------------------------------------------------------------


# A match is verified when the thing matched on identifies the work on its own.
# A journal, a volume and a page do, and so do the two looser joins built on
# them once the authors have been checked. "title" and "ordinal" never do — see
# match_reference_list and lookup_by_title.
VERIFIED_MATCHES = ("doi", "arxiv", "texkey", "journal", "volume_page")

# Matches reached by working out which publication is meant, rather than by
# reading an identifier off the page. Each is thrown away unless the record it
# landed on carries the author the bibliography named.
CHECKED_MATCHES = ("journal", "volume_page", "ordinal")


def authors_agree(entry: dict, record: dict) -> bool:
    """Does the found record carry the surname the bibliography gave?

    An entry that names no author at all cannot disagree, so it passes: the
    match still rests on a journal, a volume and a page.
    """
    if not entry.get("authors"):
        return True
    wanted = reference_store.surname(entry["authors"][0]).lower()
    if not wanted:
        return True
    surnames = [reference_store.surname(name).lower() for name in record.get("authors") or []]
    return any(wanted in name or name in wanted for name in surnames if name)


def resolve(entries: list[dict], arxiv_id: str, warnings: list[str]) -> list[dict]:
    """Fill the entries in from INSPIRE and Crossref. Modifies them in place."""
    if not entries:
        return entries

    reference_list = []
    if arxiv_id:
        hits = inspire_search("arxiv:%s" % arxiv_id, ("references",), size=1)
        reference_list = (hits[0].get("references") or []) if hits else []
    if reference_list:
        match_reference_list(entries, index_reference_list(reference_list))
    else:
        warnings.append(
            "INSPIRE holds no reference list for this paper; every reference had "
            "to be looked up on its own"
        )

    lookup_unmatched(entries)
    lookup_by_title(entries)

    canonical = fetch_by_recid([entry["inspire_id"] for entry in entries if entry.get("inspire_id")])
    for entry in entries:
        record = canonical.get(entry.get("inspire_id", ""))
        if not record:
            continue
        if entry["match"] in CHECKED_MATCHES and not authors_agree(entry, record):
            entry["inspire_id"] = ""
            entry["match"] = "none"
            continue
        # INSPIRE's reference list often states less about a work than the
        # bibliography did. Where the record it led to carries the identifier
        # the bibliography also gave, the two confirm each other, and a match
        # made on a title alone is really a match on that identifier.
        for kind, field in (("doi", "doi"), ("arxiv", "arxiv_id")):
            if entry[field] and entry[field] == record.get(field):
                entry["match"] = kind
        for name, value in record.items():
            if value not in (None, "", []):
                entry[name] = value

    for entry in entries:
        if entry.get("inspire_id") or not entry["doi"]:
            continue
        record = fetch_crossref(entry["doi"])
        if record:
            for name, value in record.items():
                if value not in (None, "", []):
                    entry[name] = value
            entry["match"] = "doi"

    fill_from_arxiv(entries)

    for entry in entries:
        entry["verified"] = entry["match"] in VERIFIED_MATCHES
        if entry["source"] == "bibliography":
            entry["match"] = "none"

    unverified = sum(1 for entry in entries if not entry["verified"])
    if unverified:
        warnings.append(
            "%d of %d references could not be confirmed against INSPIRE or Crossref; "
            "their rows are marked in REFERENCES.md" % (unverified, len(entries))
        )
    return entries


def tidy(entry: dict) -> dict:
    """Drop the working fields, and the empty ones the store need not carry.

    `raw` is kept only where it is the best description there is: an entry that
    resolved to a title has no use for the bibliography line it came from.
    """
    working = ("ordinal", "part", "journal_query", "about")
    record = {
        name: value
        for name, value in entry.items()
        if name not in working and value not in ("", [])
    }
    if record.get("title"):
        record.pop("raw", None)
    return record


def collect(
    source_dir: Path, body: str, arxiv_id: str, literature_root: Path, warnings: list[str]
) -> tuple[list[dict], dict[str, list[str]]]:
    """Every work this paper cites, tagged, plus the key -> tags map.

    The tags come from the store, so a work another paper already cites keeps
    the tag that paper's chapters already name.
    """
    entries = build_entries(source_dir, body, collect_cite_keys(body))
    resolve(entries, arxiv_id, warnings)

    try:
        store = reference_store.load(literature_root)
    except RuntimeError as error:
        warnings.append("the reference store could not be read (%s); tags may collide" % error)
        store = []
    reference_store.assign_tags(entries, store)

    key_tags: dict[str, list[str]] = {}
    for entry in sorted(entries, key=lambda item: item["part"]):
        key_tags.setdefault(entry["key"], []).append(entry["tag"])
    return [tidy(entry) for entry in entries], key_tags


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--source-dir", type=Path, required=True, help="extracted TeX source")
    parser.add_argument("--arxiv-id", default="", help="the citing paper, for INSPIRE's reference list")
    parser.add_argument(
        "--literature-root", type=Path, default=reference_store.default_root()
    )
    parser.add_argument("--no-lookup", action="store_true", help="read the bibliography, look nothing up")
    args = parser.parse_args()

    body = ""
    for path in sorted(args.source_dir.rglob("*.tex")):
        body += path.read_text(encoding="utf-8", errors="replace") + "\n"

    warnings: list[str] = []
    if args.no_lookup:
        entries = build_entries(args.source_dir, body, collect_cite_keys(body))
        reference_store.assign_tags(entries, [])
        references, key_tags = [tidy(entry) for entry in entries], {}
    else:
        references, key_tags = collect(
            args.source_dir, body, args.arxiv_id, args.literature_root, warnings
        )

    print(json.dumps(
        {"references": references, "key_tags": key_tags, "warnings": warnings}, indent=2
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
