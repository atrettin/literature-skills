#!/usr/bin/env python3
"""Say how much of what a candidate paper cites the papers of your question know.

An agent that researches a task has a budget of ingests, and each ingest costs a
download, a conversion and minutes at the API rate limit. A title, a rank and 400
characters of an abstract do not say whether a candidate builds on the same works
as the papers already on disk. The reference store does say it: it holds every
work that every held paper cites, and it recognises one work by its DOI, its
arXiv identifier, its INSPIRE record number, or its journal, volume and page.

Two sets of **works** are compared, and never two sets of tags or two sets of
titles. `C` is the works the candidate cites. `S` is the union of the works that
the papers **in scope** cite. `reference_store.find_match` decides when two
records are the same work, so the store's rule of identity holds here too.

    containment = |C n S| / |C|            what share of the candidate's works
                                           the papers in scope know already
    overlap(p)  = |C n R_p| / min(|C|, |R_p|)
    overlap     = max over p of overlap(p)

`overlap` is the Szymkiewicz-Simpson coefficient. The `min` in the denominator
normalises for the length of a reference list: a review cites 500 works and a
letter cites 30, so their Jaccard index cannot pass 0.06 even when the letter
sits wholly inside the review. `jaccard` is reported for a reader who wants the
symmetric number, and nothing ever bands on it.

**The scope is the working set of the task, and not the whole collection.** A
collection is persistent and serves every task that came before yours. Measured
against all of it, a candidate that shares nothing with your question still reads
`high`, because some earlier task ingested a paper on its subject. `--scope` and
`--all-papers` are therefore a required pair with no default. A held paper
outside the scope is reported under `outside_scope`, with its coefficient and no
band: it is on disk already, so it is a thing to read before you spend an ingest,
and it is not evidence that your question is covered. A candidate the collection
holds is never compared with itself: `held_as` says the collection holds it, and
a row of coefficient 1.0 against itself would read as a second paper on the same
ground.

**The counts carry no weight.** A work that every paper in the field cites counts
the same as a work that one held paper cites. A rarity weight would need corpus
statistics that the store does not hold, and it would turn an auditable count
into a number that no reader can check by hand.

What a run costs:

    a candidate the collection holds   nothing. The store answers.
    any other candidate                two requests. One resolves the handle to
                                       an INSPIRE record, one reads its
                                       reference list.
    --resolve                          one further request per batch of
                                       unmatched references, up to RESOLVE_CAP.

**Run one lookup at a time.** INSPIRE limits its rate, every request here goes
through `inspire_lookup.fetch_record`, and that function paces them across
processes. Never start a sub-agent for each candidate, and never run two of these
checks together: a rate limit that you trip costs more time than the parallel
work saves.

Prints one JSON report on stdout. Writes nothing to disk.

The exit status is 0 for a report, 1 for a paper INSPIRE does not hold or a store
that does not parse, and 2 for a bad argument.

Usage:
    collection_overlap.py 1706.03621 --scope king_2025_right_handed_neutrinos
    collection_overlap.py --doi 10.1016/j.ppnp.2018.01.006 --scope <slug> --resolve
    collection_overlap.py --recid 1599542 --all-papers --max-papers 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inspire_citations  # noqa: E402
import inspire_lookup  # noqa: E402
import rate_gate  # noqa: E402
import reference_store  # noqa: E402
import references  # noqa: E402

# How many identified references a candidate needs before the report gives it a
# band. One reference moves the coefficient by 1/N, so a candidate with six of
# them swings by 0.17 for each one, and a band built on that says nothing. The
# counts stay true at every size, and they are reported whatever this value is.
MIN_COMPARABLE_REFS = 10

# At this coefficient and above, the reading says the candidate covers ground the
# papers of the question hold already.
HIGH_OVERLAP = 0.15

# Below this coefficient, the reading says the candidate brings new ground. New
# also means possibly off the subject, which is why that reading sends the agent
# back to the abstract rather than to an ingest.
LOW_OVERLAP = 0.05

# How many unmatched references `--resolve` looks up. This is three batches of
# `references.BATCH_SIZE`, and thus three further requests.
RESOLVE_CAP = 120

# How many held papers the `closest` and `outside_scope` lists report. The
# `overlap` comes from the first row of `closest`; the rows under it show whether
# one held paper is close or many are.
MAX_PAPERS = 10

# The fixed words for each band. An agent gives the sentence to the user as it
# stands, so that one reader reads the same words for the same evidence every
# time.
READINGS = {
    "high": (
        "This paper draws on the works you read for this question already. It "
        "probably covers ground you hold now. Spend an ingest on it only when "
        "the question needs this paper's own words."
    ),
    "partial": (
        "This paper shares part of its ground with the papers of this question. "
        "The number decides nothing on its own. Read the abstract again."
    ),
    "low": (
        "This paper draws on works the papers of this question do not cite. It "
        "brings new ground, and it may also be off the subject. Read the "
        "abstract again before you spend an ingest."
    ),
}

# Too few references carry an identifier for a ratio to mean anything.
THIN_READING = (
    "Too few references carry an identifier. The counts hold. The ratio does not."
)

# No paper is in scope. A task holds an empty working set at iteration 1, and
# that is an answer rather than an error: nothing here can band the candidate,
# and `outside_scope` is where the run still helps.
EMPTY_SCOPE_READING = (
    "No paper of this question is in scope yet. The counts hold, and nothing "
    "here bands the candidate. Read `outside_scope`: it names the held papers "
    "that share references with this one."
)

# The words that go with `outside_scope`, whatever that list holds. These papers
# never lift or lower the band, because an earlier task chose them for a subject
# of its own.
OUTSIDE_SCOPE_READING = (
    "The collection holds these papers from other work. They share references "
    "with this candidate. Read them before you spend an ingest, and add one to "
    "your working set when its text bears on a sub-question."
)


# --------------------------------------------------------------------------
# what a reference is, and which work it names
# --------------------------------------------------------------------------


def probe_of(entry: dict) -> dict:
    """One INSPIRE reference entry as a record that `find_match` can compare.

    An entry that INSPIRE resolved points at a record number, and it frequently
    prints a DOI or an arXiv identifier of its own. Each of those three names the
    work on its own, so all three go into the probe and `identity_keys` orders
    them strongest first.
    """
    reference = entry.get("reference") or {}
    dois = [str(doi) for doi in reference.get("dois") or [] if doi]
    eprint = reference.get("arxiv_eprint")
    eprints = [
        str(value)
        for value in (eprint if isinstance(eprint, list) else [eprint])
        if value
    ]
    return {
        "doi": reference_store.normalize_doi(dois[0]) if dois else "",
        "arxiv_id": reference_store.normalize_arxiv(eprints[0]) if eprints else "",
        "inspire_id": references.recid_of(entry),
    }


def candidate_from_store(slug: str, store: list[dict]) -> tuple[set[str], int, int]:
    """The works a held paper cites, out of the store. No request at all.

    The ingest resolved this paper's whole bibliography and wrote it here, so
    every work carries a tag and none of them is unidentified.
    """
    tags = {
        str(record["tag"])
        for record in store
        if record.get("tag")
        and any(entry.get("slug") == slug for entry in record.get("cited_by") or [])
    }
    return tags, len(tags), 0


def candidate_from_inspire(
    recid: str, store: list[dict], resolve: bool = False
) -> tuple[set[str], int, int]:
    """The works a candidate cites, matched against the store, from INSPIRE.

    Returns the tags that matched, how many references INSPIRE listed, and how
    many of those carry no handle at all. A reference with no handle matches
    nothing and can never be recognised, so it leaves every set and every ratio,
    and the count of them is reported instead: a ratio over an unknown base tells
    the agent nothing.

    `resolve` runs the second pass. A store record carries an `inspire_id` only
    when INSPIRE resolved that record, so a reference that matches nothing by its
    record number can still be the same work under a DOI. The pass asks INSPIRE
    for those record numbers and matches again on what comes back.
    """
    hits = references.inspire_search("recid %s" % recid, ("references",), size=1)
    entries = (hits[0].get("references") or []) if hits else []

    index = reference_store.build_index(store)
    tags: set[str] = set()
    unidentified = 0
    unmatched: list[str] = []

    for entry in entries:
        probe = probe_of(entry)
        if not reference_store.identity_keys(probe):
            unidentified += 1
            continue
        found = reference_store.find_match(index, probe)
        if found is not None:
            if found.get("tag"):
                tags.add(str(found["tag"]))
        elif probe["inspire_id"] and probe["inspire_id"] not in unmatched:
            unmatched.append(probe["inspire_id"])

    if resolve and unmatched:
        for record in references.fetch_by_recid(unmatched[:RESOLVE_CAP]).values():
            found = reference_store.find_match(index, record)
            if found is not None and found.get("tag"):
                tags.add(str(found["tag"]))

    return tags, len(entries), unidentified


# --------------------------------------------------------------------------
# the papers, and which of them the question is about
# --------------------------------------------------------------------------


def paper_sets(store: list[dict]) -> dict[str, set[str]]:
    """For each paper the collection knows, the tags of the works it cites."""
    sets: dict[str, set[str]] = {}
    for record in store:
        tag = record.get("tag")
        if not tag:
            continue
        for entry in record.get("cited_by") or []:
            slug = str(entry.get("slug") or "")
            if slug:
                sets.setdefault(slug, set()).add(str(tag))
    return sets


def split_scope(
    sets: dict[str, set[str]], scope_slugs: list[str] | None
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Divide the papers into the ones in scope and the ones outside it.

    `scope_slugs` of `None` is `--all-papers`: every paper is in scope, and
    nothing is outside it.
    """
    if scope_slugs is None:
        return dict(sets), {}
    wanted = set(scope_slugs)
    in_scope = {slug: works for slug, works in sets.items() if slug in wanted}
    outside = {slug: works for slug, works in sets.items() if slug not in wanted}
    return in_scope, outside


# --------------------------------------------------------------------------
# the measure
# --------------------------------------------------------------------------


def ratio(numerator: int, denominator: int) -> float:
    """A share, to two places. A base of nothing gives 0.0, and not an error."""
    return round(numerator / denominator, 2) if denominator else 0.0


def band_of(coefficient: float) -> str:
    if coefficient >= HIGH_OVERLAP:
        return "high"
    if coefficient < LOW_OVERLAP:
        return "low"
    return "partial"


def score(
    candidate: dict, sets: dict[str, set[str]], max_papers: int = MAX_PAPERS
) -> dict:
    """The ratios, the counts, the band and the per-paper list, over `sets`.

    Give it the papers in scope. The papers outside the scope go through the same
    function, and the caller drops the band and the reading from that result, so
    that the two lists carry comparable numbers and neither one decides the
    other.
    """
    tags: set[str] = candidate["tags"]
    size: int = candidate["identified"]

    union: set[str] = set()
    for works in sets.values():
        union |= works
    shared = tags & union

    closest = []
    for slug, works in sets.items():
        common = tags & works
        closest.append({
            "slug": slug,
            "references": len(works),
            "shared": len(common),
            "overlap": ratio(len(common), min(size, len(works))),
        })
    closest.sort(key=lambda item: (-item["overlap"], item["slug"]))

    overlap = closest[0]["overlap"] if closest else 0.0
    comparable = bool(sets) and size >= MIN_COMPARABLE_REFS
    if comparable:
        band = band_of(overlap)
        reading = READINGS[band]
    else:
        band = None
        reading = THIN_READING if sets else EMPTY_SCOPE_READING

    return {
        "papers": len(sets),
        "works": len(union),
        "shared": len(shared),
        "containment": ratio(len(shared), size),
        "overlap": overlap,
        "jaccard": ratio(len(shared), size + len(union) - len(shared)),
        "closest": closest[:max_papers],
        "comparable": comparable,
        "band": band,
        "reading": reading,
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("arxiv_id", nargs="?", help="the candidate, by its arXiv identifier")
    parser.add_argument("--doi", help="name the candidate by DOI instead")
    parser.add_argument("--recid", help="name the candidate by INSPIRE record number instead")
    # The scope, and no default. A band measured over a persistent collection
    # answers for every task that collection ever served, and not for this one.
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--scope",
        action="append",
        default=[],
        metavar="SLUG",
        help="a paper of the working set of this question; repeat it for each one",
    )
    scope.add_argument(
        "--all-papers",
        action="store_true",
        help="put every held paper in scope; for a question about the collection "
        "itself. The research loop never uses it",
    )
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="run the second matching pass; it costs one request for each %d "
        "unmatched references" % references.BATCH_SIZE,
    )
    parser.add_argument(
        "--max-papers", type=int, default=MAX_PAPERS, metavar="N",
        help="how many held papers each list reports (default %d)" % MAX_PAPERS,
    )
    parser.add_argument(
        "--literature-root", type=Path, default=reference_store.default_root()
    )
    return parser


def fail(message: str, code: int, **fields: object) -> int:
    print(json.dumps({"error": message, "band": None, **fields}, indent=2))
    return code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.literature_root

    if not (args.arxiv_id or args.doi or args.recid):
        return fail("give an arXiv identifier, --doi or --recid", 2)
    if args.max_papers < 1:
        return fail("--max-papers must be at least 1", 2)

    try:
        store = reference_store.load(root)
    except RuntimeError as error:
        return fail(str(error), 1)

    sets = paper_sets(store)
    scope_slugs = None if args.all_papers else sorted(set(args.scope))
    if scope_slugs is not None:
        # A slug with a typo would empty the scope silently. Every candidate
        # would then read `low`, and the agent would spend ingests on papers the
        # collection holds already.
        unknown = [slug for slug in scope_slugs if slug not in sets]
        if unknown:
            return fail(
                "no such paper in the collection", 2,
                unknown_papers=unknown, papers=sorted(sets),
            )

    # Whether the collection holds the candidate is read from the handle the
    # caller gave, before anything is sent. A held candidate is then answered
    # wholly from disk, and the run costs no request at all.
    held = reference_store.held_index(root)
    probe = {
        "arxiv_id": args.arxiv_id or "",
        "doi": args.doi or "",
        "inspire_id": args.recid or "",
    }
    held_as = next(
        (held[key] for key in reference_store.identity_keys(probe) if key in held), None
    )

    if held_as:
        known = reference_store.find_match(reference_store.build_index(store), probe) or {}
        recid = str(known.get("inspire_id") or "")
        paper = {
            "inspire_id": int(recid) if recid.isdigit() else None,
            "title": known.get("title") or "",
            "arxiv_id": known.get("arxiv_id") or probe["arxiv_id"],
            "doi": known.get("doi") or probe["doi"],
            "inspire_url": inspire_lookup.RECORD_URL % recid if recid else "",
        }
        tags, listed, unidentified = candidate_from_store(held_as, store)
        source = "store"
    else:
        # The scope is checked above, so a slug with a typo costs no request.
        rate_gate.use_root(root)
        paper = inspire_citations.resolve_paper(
            args.arxiv_id or "", args.doi or "", args.recid or ""
        )
        if not paper["found"]:
            return fail(paper["reason"], 1)
        tags, listed, unidentified = candidate_from_inspire(
            str(paper.get("inspire_id") or ""), store, args.resolve
        )
        source = "inspire"

    # A paper is never compared with itself. The collection holding the
    # candidate is what `held_as` says; a row of coefficient 1.0 against itself
    # would sit in `closest` or in `outside_scope` and read as a second paper on
    # the same ground.
    others = {slug: works for slug, works in sets.items() if slug != held_as}
    candidate = {"tags": tags, "identified": listed - unidentified}
    in_scope, outside = split_scope(others, scope_slugs)
    scored = score(candidate, in_scope, args.max_papers)
    beyond = score(candidate, outside, args.max_papers)

    report = {
        "paper": {
            "recid": paper.get("inspire_id"),
            "title": paper.get("title", ""),
            "arxiv_id": paper.get("arxiv_id", ""),
            "doi": paper.get("doi", ""),
            "held_as": held_as,
            "inspire_url": paper.get("inspire_url", ""),
        },
        "source": source,
        "literature_root": str(root),
        "candidate_references": {
            "listed": listed,
            "identified": candidate["identified"],
            "unidentified": unidentified,
        },
        "scope": {
            "mode": "all_papers" if args.all_papers else "working_set",
            "papers": sorted(others) if scope_slugs is None else scope_slugs,
            "papers_in_collection": len(sets),
            "outside_scope_papers": len(outside),
        },
        "in_scope": {"papers": scored["papers"], "works": scored["works"]},
        "shared_with_scope": scored["shared"],
        "containment": scored["containment"],
        "overlap": scored["overlap"],
        "jaccard": scored["jaccard"],
        "closest": scored["closest"],
        "outside_scope": beyond["closest"],
        "outside_scope_reading": OUTSIDE_SCOPE_READING,
        "comparable": scored["comparable"],
        "band": scored["band"],
        "reading": scored["reading"],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
