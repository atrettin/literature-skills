#!/usr/bin/env python3
"""The reference store: what a cited work is, what it is called, where it lives.

`literature/.references.jsonl` holds one JSON object per line, one per cited
work. It is the *store*, not the view — REFERENCES.md is rendered from it by
update_references.py, and nothing in this module formats anything for a reader.
Keeping the two apart means the store can be chosen for integrity and cheap
schema change while the table is chosen for reading.

A record looks like this, and every field but `tag` may be absent:

    {"tag": "lipari_2002_neutrino_oscillation_studies",
     "title": "...", "authors": ["Lipari, Paolo"], "year": 2002,
     "journal": "Nucl.Phys.B Proc.Suppl. 112 (2002) 274",
     "doi": "10.1016/...", "arxiv_id": "hep-ph/0207172",
     "inspire_id": "590543", "citation_count": 53,
     "source": "inspire", "match": "arxiv", "verified": true,
     "cited_by": [{"slug": "jeong_2023_...", "key": "Lipari:2002at"}],
     "held_as": null, "first_seen": "2026-08-07"}

Two rules hold the whole design together:

  * **Identity is not the tag.** Two records are the same work when they share
    a DOI, an arXiv identifier or an INSPIRE record number — never because
    their tags happen to agree.
  * **A tag, once assigned, is never reassigned.** Tags are written into the
    chapter files of papers already on disk. Changing one silently breaks every
    citation that used it, and nothing but check_references.py would notice.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from lit.arxiv_search import collapse_whitespace, normalize_title, slugify

STORE_NAME = ".references.jsonl"
VIEW_NAME = "REFERENCES.md"
# One page per cited work, for a reader following a citation. The tag names the
# file, so a citation carries its tag in plain sight either way.
RECORDS_DIR = "references"

# How a citation is written, in the two forms it passes through. The
# conversion leaves the marker; update_references.py turns it into the link a
# reader follows. Both shapes are matched in three scripts, so they live here
# rather than in whichever one needed them first.
#
#   [cite: lipari_2002_neutrino_oscillation_neutrino_cross]
#   ([Lipari, 2002](../../references/lipari_2002_neutrino_oscillation_neutrino_cross.md))
CITE_TAG = re.compile(r"\[cite:\s*([^\]]*)\]")
CITE_LINK = re.compile(r"\]\((?:[^)]*/)?" + re.escape(RECORDS_DIR) + r"/([^/)\s]+)\.md\)")

# Title words that say nothing about which paper this is. Dropping them keeps
# a tag short enough to read inside a sentence.
TAG_STOPWORDS = frozenset(
    """a an and are as at by for from in into is its of on or the to with within
    new study studies measurement measurements observation analysis using via
    towards toward its their this that these those effects effect""".split()
)
TAG_TITLE_WORDS = 4


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------


def normalize_doi(doi: str) -> str:
    """Case-fold a DOI and drop the resolver prefix authors often paste in."""
    doi = collapse_whitespace(str(doi or "")).lower()
    doi = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi.rstrip(".,;)")


def normalize_arxiv(arxiv_id: str) -> str:
    """'arXiv:2307.09241v3' -> '2307.09241'; old-style ids keep their prefix."""
    identifier = collapse_whitespace(str(arxiv_id or ""))
    identifier = re.sub(r"^(?:arxiv:)\s*", "", identifier, flags=re.IGNORECASE)
    identifier = re.sub(r"v\d+$", "", identifier)
    return identifier.lower()


def identity_keys(record: dict) -> list[str]:
    """Every handle by which this record can be recognised as the same work.

    Ordered strongest first. The title fallback carries the year with it: two
    different papers share a title far more often than they share a title *and*
    a year, and a bare title match across decades is nearly always wrong.
    """
    keys = []
    doi = normalize_doi(record.get("doi", ""))
    if doi:
        keys.append("doi:" + doi)
    arxiv_id = normalize_arxiv(record.get("arxiv_id", ""))
    if arxiv_id:
        keys.append("arxiv:" + arxiv_id)
    inspire_id = collapse_whitespace(str(record.get("inspire_id") or ""))
    if inspire_id:
        keys.append("inspire:" + inspire_id)
    # Journal, volume and page name an article exactly, and for anything
    # published before DOIs they are the only handle two papers will agree on.
    journal = collapse_whitespace(str(record.get("journal_key") or ""))
    if journal:
        keys.append("journal:" + journal)
    title = normalize_title(record.get("title") or "")
    if title:
        keys.append("title:%s|%s" % (title, record.get("year") or ""))
    # A work no lookup recognised, with no title of its own — a personal
    # communication, a talk. Its own bibliography line is all it has, and
    # without this it would match nothing, not even itself, so every merge
    # would store it again under a new tag.
    if not keys:
        raw = normalize_title(record.get("raw") or "")
        if raw:
            keys.append("raw:" + raw)
    return keys


def build_index(records: list[dict]) -> dict[str, dict]:
    index = {}
    for record in records:
        for key in identity_keys(record):
            index.setdefault(key, record)
    return index


def find_match(index: dict[str, dict], record: dict) -> dict | None:
    for key in identity_keys(record):
        found = index.get(key)
        if found is not None:
            return found
    return None


def add_to_index(index: dict[str, dict], record: dict) -> None:
    for key in identity_keys(record):
        index.setdefault(key, record)


# --------------------------------------------------------------------------
# tags
# --------------------------------------------------------------------------


def surname(author: str) -> str:
    """The family name out of 'Lipari, Paolo' or 'P. Lipari' or 'Lipari'."""
    author = collapse_whitespace(re.sub(r"\\[a-zA-Z]+", " ", str(author or "")))
    if "," in author:
        return author.split(",", 1)[0].strip()
    parts = [part for part in author.split() if part]
    # Trailing initials happen ("Brieva F.A."); the name is what is left.
    while len(parts) > 1 and re.fullmatch(r"(?:[A-Z]\.?){1,3}", parts[-1]):
        parts.pop()
    return parts[-1] if parts else ""


def base_tag(record: dict) -> str:
    """The tag a record wants, before collisions are settled.

    `<surname>_<year>_<title words>`, the same shape as a paper's directory
    name, so a cited work that is later ingested in full keeps one identifier.
    """
    authors = record.get("authors") or []
    who = slugify(surname(authors[0]) if authors else "", limit=24, default="anon")
    year = record.get("year")
    when = str(year) if year else "nd"
    # A terse bibliography entry often carries no title at all. What its own
    # line said about the work, or failing that where it appeared, still names
    # it well enough to recognise in a sentence.
    subject = record.get("title") or record.get("about") or record.get("journal") or ""
    words = [
        word
        for word in slugify(subject, limit=200, default="").split("_")
        if word and word not in TAG_STOPWORDS and not word.isdigit()
    ]
    what = "_".join(words[:TAG_TITLE_WORDS])
    return "_".join(part for part in (who, when, what) if part)


def suffixed(tag: str, position: int) -> str:
    """The first collision keeps the plain tag; the next ones get _b, _c, …"""
    if position <= 0:
        return tag
    return "%s_%s" % (tag, chr(ord("a") + position))


def assign_tags(records: list[dict], store: list[dict]) -> None:
    """Give every record a tag, in place, reusing the store's where it can.

    A work already in the store keeps the tag it already has — that tag is
    written into chapter files elsewhere in the collection. Within one batch,
    records that collide on a base tag are ordered by identity rather than by
    the order the bibliography happened to list them, so re-ingesting a paper
    produces the same tags it produced last time.
    """
    index = build_index(store)
    taken = {record["tag"] for record in store if record.get("tag")}

    fresh = []
    for record in records:
        known = find_match(index, record)
        if known is not None and known.get("tag"):
            record["tag"] = known["tag"]
        else:
            fresh.append(record)

    by_base: dict[str, list[dict]] = {}
    for record in fresh:
        by_base.setdefault(base_tag(record), []).append(record)

    for base, group in sorted(by_base.items()):
        group.sort(key=lambda item: (identity_keys(item) or [""])[0])
        position = 0
        for record in group:
            while suffixed(base, position) in taken:
                position += 1
            record["tag"] = suffixed(base, position)
            taken.add(record["tag"])
            add_to_index(index, record)
            position += 1


# --------------------------------------------------------------------------
# merging
# --------------------------------------------------------------------------


# Fields a later, better-resolved sighting of a work may fill in. The tag is
# not among them, and neither is cited_by.
MERGEABLE = (
    "title", "authors", "year", "journal", "journal_key", "doi", "arxiv_id",
    "inspire_id", "citation_count",
)


def better(candidate: dict, current: dict) -> bool:
    """Does the candidate deserve to overwrite what is already stored?"""
    if candidate.get("verified") and not current.get("verified"):
        return True
    if current.get("verified") and not candidate.get("verified"):
        return False
    filled = lambda record: sum(1 for name in MERGEABLE if record.get(name))  # noqa: E731
    return filled(candidate) > filled(current)


def merge(store: list[dict], incoming: list[dict], slug: str) -> tuple[list[dict], dict[str, str], dict]:
    """Fold one paper's references into the store.

    Returns (records, tag rewrites, counts). A rewrite maps a tag the incoming
    records were given to the tag the store already uses for that work — the
    caller must apply it to the citing paper's chapters, or those citations
    point at a tag no record answers to.
    """
    records = [dict(record) for record in store]
    index = build_index(records)
    rewrites: dict[str, str] = {}
    counts = {"added": 0, "updated": 0, "unchanged": 0}

    for record in incoming:
        key = collapse_whitespace(str(record.get("key") or ""))
        known = find_match(index, record)
        if known is None:
            fresh = {name: value for name, value in record.items() if name != "key"}
            fresh["cited_by"] = [{"slug": slug, "key": key}]
            fresh.setdefault("held_as", None)
            records.append(fresh)
            add_to_index(index, fresh)
            counts["added"] += 1
            continue

        if record.get("tag") and record["tag"] != known.get("tag"):
            rewrites[record["tag"]] = known["tag"]

        changed = False
        if better(record, known):
            for name in MERGEABLE:
                value = record.get(name)
                if value and value != known.get(name):
                    known[name] = value
                    changed = True
            for name in ("source", "match", "verified"):
                if record.get(name) != known.get(name):
                    known[name] = record.get(name)
                    changed = True

        citations = known.setdefault("cited_by", [])
        if not any(entry.get("slug") == slug and entry.get("key") == key for entry in citations):
            citations.append({"slug": slug, "key": key})
            citations.sort(key=lambda entry: (entry.get("slug") or "", entry.get("key") or ""))
            changed = True

        counts["updated" if changed else "unchanged"] += 1

    return records, rewrites, counts


def held_index(root: Path) -> dict[str, str]:
    """Map each identifier of a paper held in full to the directory holding it.

    Keys are the `arxiv:` and `doi:` forms of `identity_keys`, read from the
    INDEX.md of every paper, so a caller with a DOI or an arXiv identifier in
    hand can ask whether the collection already holds that work. A root that
    does not exist holds nothing, which is an answer rather than an error: a
    project may have no collection yet.
    """
    held: dict[str, str] = {}
    for index_file in sorted(root.glob("*/INDEX.md")):
        text = index_file.read_text(encoding="utf-8", errors="replace")
        slug = index_file.parent.name
        for match in re.finditer(r"^\|\s*arXiv\s*\|\s*\[([^\]]+)\]", text, flags=re.MULTILINE):
            held["arxiv:" + normalize_arxiv(match.group(1))] = slug
        for match in re.finditer(r"^\|\s*DOI\s*\|\s*\[([^\]]+)\]", text, flags=re.MULTILINE):
            held["doi:" + normalize_doi(match.group(1))] = slug
    return held


def mark_held(records: list[dict], root: Path) -> int:
    """Point every record at the paper directory holding that work in full.

    Matched on the arXiv identifier and DOI written in each INDEX.md, not on
    the tag, so a paper whose directory name differs from its reference tag is
    still recognised.
    """
    held = held_index(root)

    changed = 0
    for record in records:
        found = None
        for key in identity_keys(record):
            if key in held:
                found = held[key]
                break
        if record.get("held_as") != found:
            record["held_as"] = found
            changed += 1
    return changed


# --------------------------------------------------------------------------
# the file
# --------------------------------------------------------------------------


def default_root() -> Path:
    """Where the collection is: `$LITERATURE_ROOT`, or `literature` beside you.

    One collection can serve many projects. A paper costs a download, a
    conversion and a place in the reference store, and paying that again in
    the next project buys nothing. The variable names a directory that outlives
    any one project; without it the collection belongs to the project, as the
    path in every skill says.

    Every script reads this as the default of `--literature-root`, so the flag
    still wins where a caller names a root of its own.
    """
    return Path(os.environ.get("LITERATURE_ROOT") or "literature")


def store_path(root: Path) -> Path:
    return root / STORE_NAME


def load(root: Path) -> list[dict]:
    """Read the store. A missing store is an empty one; a broken line is not.

    A malformed line is reported with its number rather than skipped: skipping
    would drop references silently, which is the failure this whole feature
    exists to remove.
    """
    path = store_path(root)
    if not path.exists():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise RuntimeError("%s line %d is not valid JSON: %s" % (path, number, error))
    return records


def save(root: Path, records: list[dict]) -> None:
    """Write the store atomically, so an interrupted run cannot truncate it."""
    path = store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda record: record.get("tag") or "")
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=".references-", suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            for record in ordered:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
