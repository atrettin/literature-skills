#!/usr/bin/env python3
"""Which paper this is, and what the collection will call it.

Two questions stand between a request and a download, and both have an answer
that a script can reach:

  * **Which paper?** An arXiv identifier answers it directly. A title, an author
    and a year answer it only when the search comes back with one exact match
    and nothing else exact. Anything less is a judgement, and this module raises
    `AmbiguousTitle` with the candidates rather than guessing.
  * **What is it called here?** A work the collection already cites has a tag,
    and that tag is written into the chapters of every paper citing it. Reusing
    it as the directory name is what makes those citations resolve to the paper
    itself. Only a work nothing cites gets a fresh name.

Neither answer is printed for a reader. `add_paper.py` calls both.
"""

from __future__ import annotations

import re
from pathlib import Path

from lit import arxiv_search
from lit import reference_store
from lit import text

# How many title words a derived slug carries. A higher value separates two
# papers of one author in one year more often, and gives a longer directory
# name.
SLUG_TITLE_WORDS = 2

# How many candidates an `AmbiguousTitle` carries for the agent to choose from.
CANDIDATES_SHOWN = 5

# What an arXiv identifier looks like, in both styles arXiv has used:
# `2307.09241`, with an optional version, and `hep-ph/0207172`.
ARXIV_ID = re.compile(r"^(?:arxiv:)?(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?$",
                      re.IGNORECASE)


class AmbiguousTitle(RuntimeError):
    """The search found no single exact match. Only judgement settles it."""

    def __init__(self, message: str, candidates: list[dict], match: str = "none") -> None:
        super().__init__(message)
        self.candidates = candidates
        self.match = match


class TagCollision(RuntimeError):
    """The name this paper wants already belongs to another work.

    A tag, once assigned, is never reassigned: it sits in the chapter files of
    every paper that cites it. So the caller decides which work owns the name.
    """

    def __init__(self, message: str, slug: str, held_by: str, held_arxiv_id: str,
                 suggested_slug: str) -> None:
        super().__init__(message)
        self.slug = slug
        self.held_by = held_by
        self.held_arxiv_id = held_arxiv_id
        self.suggested_slug = suggested_slug


# --------------------------------------------------------------------------
# which paper
# --------------------------------------------------------------------------


def looks_like_arxiv_id(argument: str) -> bool:
    return bool(ARXIV_ID.match((argument or "").strip()))


def normalize(argument: str) -> str:
    """'arXiv:2307.09241v3' -> '2307.09241'. The version is not the paper."""
    return reference_store.normalize_arxiv(argument)


def candidate(entry: dict) -> dict:
    """One search hit, as much of it as a choice between papers needs."""
    return {
        "arxiv_id": entry.get("arxiv_id", ""),
        "title": entry.get("title", ""),
        "authors": entry.get("authors", [])[:3],
        "year": entry.get("year"),
        "doi": entry.get("doi", ""),
        "journal": entry.get("journal_ref", ""),
        "score": entry.get("score"),
        "match": entry.get("match", ""),
    }


def resolve(
    argument: str | None = None,
    title: str | None = None,
    author: str | None = None,
    year: int | None = None,
) -> str:
    """The arXiv identifier of the paper the caller means.

    An argument that looks like an identifier is taken as one, and no search
    runs: the caller already knows which paper it wants. Otherwise the query
    ladder of `arxiv_search` runs, and one result is accepted only when its
    `match` is `exact` and no second result is exact too. A second exact match
    means two papers agree with the query, which no rule here can choose
    between.
    """
    if argument:
        if not looks_like_arxiv_id(argument):
            raise AmbiguousTitle(
                "%r is not an arXiv identifier; give --title, --author and "
                "--year to search for it instead" % argument,
                candidates=[],
            )
        return normalize(argument)

    if not (title or author or year):
        raise ValueError("give an arXiv identifier, or --title, --author or --year")

    report = arxiv_search.run_search(title, author, year)
    results = report["results"]
    exact = [entry for entry in results if entry.get("match") == "exact"]

    if len(exact) == 1:
        return normalize(exact[0]["arxiv_id"])

    if len(exact) > 1:
        reason = "%d results match this query exactly" % len(exact)
    elif results:
        reason = "no result matches this query exactly; %d resemble it" % len(results)
    else:
        reason = "arXiv returned nothing for this query"

    raise AmbiguousTitle(
        reason,
        candidates=[candidate(entry) for entry in results[:CANDIDATES_SHOWN]],
        match=report["match"],
    )


# --------------------------------------------------------------------------
# what it is called here
# --------------------------------------------------------------------------


def base_slug(metadata: dict) -> str:
    """`<surname>_<year>_<keywords>`, the shape every name in the collection has.

    The year is the arXiv submission year. A journal carries a paper a year or
    more after the preprint, and the directory names and the order of the
    collection are built on the submission, so that they agree with each other.
    """
    authors = metadata.get("authors") or []
    who = text.slugify(
        reference_store.surname(authors[0]) if authors else "", limit=24, default="anon"
    )
    year = metadata.get("submitted_year") or metadata.get("year")
    when = str(year) if year else "nd"
    return "_".join(part for part in (who, when, title_words(metadata, SLUG_TITLE_WORDS)) if part)


def title_words(metadata: dict, count: int) -> str:
    """The first `count` title words that say which paper this is.

    `TAG_STOPWORDS` is what decides which words those are, so a slug derived
    here and a tag derived by `reference_store` drop the same words.
    """
    words = [
        word
        for word in text.slugify(
            metadata.get("title") or "", limit=200, default=""
        ).split("_")
        if word and word not in reference_store.TAG_STOPWORDS and not word.isdigit()
    ]
    return "_".join(words[:count])


def known_tag(root: Path, arxiv_id: str, doi: str) -> str:
    """The tag the store already answers for this work, or an empty string.

    Asked by identifier and then by DOI, never by title: a title match is what
    puts two different papers under one name.
    """
    try:
        store = reference_store.load(root)
    except RuntimeError:
        return ""

    wanted_arxiv = reference_store.normalize_arxiv(arxiv_id)
    wanted_doi = reference_store.normalize_doi(doi)
    for record in store:
        if wanted_arxiv and reference_store.normalize_arxiv(
            record.get("arxiv_id", "")
        ) == wanted_arxiv:
            return record.get("tag", "")
    for record in store:
        if wanted_doi and reference_store.normalize_doi(record.get("doi", "")) == wanted_doi:
            return record.get("tag", "")
    return ""


def slug_owner(root: Path, slug: str) -> tuple[str, str]:
    """What already answers to this name: (what holds it, its arXiv identifier).

    A directory of the collection holds it, or a record of the store carries it
    as a tag. Either way the caller learns which work it would be taking the
    name from. `("", "")` means the name is free.
    """
    held = {slug_name: arxiv_key[len("arxiv:"):]
            for arxiv_key, slug_name in reference_store.held_index(root).items()
            if arxiv_key.startswith("arxiv:")}
    if (root / slug).is_dir():
        return ("the paper directory", held.get(slug, ""))

    try:
        store = reference_store.load(root)
    except RuntimeError:
        return ("", "")
    for record in store:
        if record.get("tag") == slug:
            return ("a record of the reference store",
                    reference_store.normalize_arxiv(record.get("arxiv_id", "")))
    return ("", "")


def derive_slug(metadata: dict, root: Path) -> str:
    """The directory name this paper takes under the collection root.

    A work the collection already cites keeps the tag it is cited by. Every
    citation of it in the other chapters then resolves to the paper itself, and
    that is the whole reason to ask the store before deriving anything.

    Raises `TagCollision` when the name is taken by a different work. It does
    not raise when the name is taken by *this* work: a directory holding this
    same arXiv identifier is a re-ingest, which `--force` answers.
    """
    arxiv_id = reference_store.normalize_arxiv(metadata.get("arxiv_id", ""))
    doi = (metadata.get("publication") or {}).get("doi") or metadata.get("doi") or ""

    tag = known_tag(root, arxiv_id, doi)
    if tag:
        return tag

    slug = base_slug(metadata)
    holder, held_arxiv_id = slug_owner(root, slug)
    if holder and held_arxiv_id and held_arxiv_id != arxiv_id:
        raise TagCollision(
            "%s already answers to %r, and it is arXiv:%s rather than arXiv:%s"
            % (holder, slug, held_arxiv_id, arxiv_id),
            slug=slug,
            held_by=holder,
            held_arxiv_id=held_arxiv_id,
            suggested_slug=longer_slug(metadata),
        )
    return slug


def longer_slug(metadata: dict) -> str:
    """The same name with one more title word, for a caller settling a collision."""
    authors = metadata.get("authors") or []
    who = text.slugify(
        reference_store.surname(authors[0]) if authors else "", limit=24, default="anon"
    )
    year = metadata.get("submitted_year") or metadata.get("year")
    when = str(year) if year else "nd"
    return "_".join(
        part for part in (who, when, title_words(metadata, SLUG_TITLE_WORDS + 1)) if part
    )
