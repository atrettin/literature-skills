#!/usr/bin/env python3
"""Ingest a paper from arXiv into the collection, and report what happened.

Every step of an ingest is already a script: the search, the conversion, the
reference merge, the citation check. This drives them in order, so that an agent
spends its context on the one thing no script can do — deciding which paper a
request means, and which work owns a name that two works want.

    add_paper.py --auto 2307.09241

**The exit code says who acts.**

    0   the collection holds the paper. No agent has to do anything.
    2   a structured exception that only judgement settles. The report carries
        an `exception` object with a code, and `add-paper/SKILL.md` has a
        section for each code.
    1   a usage error, or an argument this cannot work with.

**Two artefacts, and they are different sizes.** The full manifest goes to
`<paper_dir>/.ingest-manifest.json`: every reference of the paper, every label,
everything the conversion learned. The compact report goes to stdout: the
identity, the chapter table, the counts and the warnings, and no field that
grows with the size of a bibliography. An agent reads the report.
`update_references.py` reads the manifest.

Usage:
    add_paper.py --auto 2307.09241 1706.03621
    add_paper.py --auto --title "NuSTEC White Paper" --author "Alvarez-Ruso"
    add_paper.py --index-only jeong_2023_shallow_deep_inelastic
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

from lit import arxiv_fetch
from lit import check_references
from lit import collection_index
from lit import identity
from lit import rate_gate
from lit import reference_store
from lit import update_references
from lit import write_index
from lit.arxiv_search import collapse_whitespace

SCHEMA = "add-paper/report/1"

# How many papers run the fetch stage together. The gate still sends one request
# at a time, so this never raises the request rate: it fills the wait of one
# request with the work of another paper.
MAX_CONCURRENT_FETCHES = 2

# How many warnings the compact report prints. The full manifest holds them all.
REPORT_WARNINGS_SHOWN = 10

# How many authors the report names. `authors_total` gives the count of the rest.
AUTHORS_SHOWN = 3

MANIFEST_NAME = write_index.MANIFEST_NAME


# --------------------------------------------------------------------------
# warnings
# --------------------------------------------------------------------------

# A warning string from a called script, and the code it answers to. First match
# wins, so the more particular pattern comes first.
WARNING_CODES = (
    (re.compile(r"TexSoup could not parse", re.I), "PARSER_FALLBACK"),
    (re.compile(r"INSPIRE-HEP gave no record", re.I), "INSPIRE_NO_RECORD"),
    (re.compile(r"INSPIRE-HEP holds this paper", re.I), "INSPIRE_NO_JOURNAL"),
    (re.compile(r"INSPIRE-HEP lookup failed", re.I), "INSPIRE_LOOKUP_FAILED"),
    (re.compile(r"bibliography could not be resolved", re.I), "BIBLIOGRAPHY_FAILED"),
    (re.compile(r"cross-reference label", re.I), "UNRESOLVED_REFS"),
    (re.compile(r"figure source not found", re.I), "FIGURE_SOURCE_MISSING"),
    (re.compile(r"figure not converted", re.I), "FIGURE_CONVERTER_MISSING"),
    (re.compile(r"could not be confirmed against", re.I), "UNVERIFIED_REFERENCES"),
)

# The conversion reports placeholder residue as a warning of its own. The scoped
# citation check reports the same defect, and it names the files. Two scans are
# two definitions of residue and they drift apart, so this string is dropped
# here and `PLACEHOLDER_RESIDUE` is raised from the check alone.
RESIDUE_WARNING = re.compile(r"placeholder residue", re.I)


def classify(warnings: list[str], counts: dict) -> list[dict]:
    """Every warning string as `{code, detail, count}`.

    A string no pattern matches becomes `OTHER` rather than disappearing. An
    agent that meets a code it does not know must report it, and a warning that
    fell out of the report silently is one nobody ever meets.
    """
    entries = []
    for warning in warnings:
        if RESIDUE_WARNING.search(warning):
            continue
        code = "OTHER"
        for pattern, found in WARNING_CODES:
            if pattern.search(warning):
                code = found
                break
        entries.append({"code": code, "detail": collapse_whitespace(warning),
                        "count": counts.get(code, 1)})
    return entries


# --------------------------------------------------------------------------
# exceptions
# --------------------------------------------------------------------------


class Exception2(RuntimeError):
    """A structured exception: exit 2, and an agent decides what to do.

    Not a failure of the script. Each one names a question that has no
    mechanical answer, and carries the fields the answer needs.
    """

    def __init__(self, code: str, detail: str, **extra) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.extra = extra
        # The report as far as the run got. An exception raised after the paper
        # is on disk carries the chapters, the counts and the warnings with it,
        # so the agent handling the code sees what the run already did.
        self.report: dict | None = None

    def as_object(self) -> dict:
        return {"code": self.code, "detail": self.detail, **self.extra}


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------


def blank_report(arxiv_id: str = "") -> dict:
    """Every field of the schema, with the answer "nothing" in each.

    A reader never has to test whether a field is there. `null` and `[]` are
    answers, and a report that leaves a field out would make a missing value and
    an unknown value look the same.
    """
    return {
        "schema": SCHEMA,
        "status": "error",
        "arxiv_id": arxiv_id,
        "slug": "",
        "paper_dir": "",
        "index": "",
        "title": "",
        "authors": [],
        "authors_total": 0,
        "submitted_year": None,
        "publication": {"source": "none", "journal": "", "published_year": None,
                        "doi": "", "errata": [], "inspire_url": ""},
        "abs_url": "",
        "parser": "",
        "ingested": date.today().isoformat(),
        "chapters": [],
        "figures": 0,
        "figures_missing": 0,
        "references": {"cited": 0, "added": 0, "updated": 0, "unchanged": 0,
                       "retagged": 0, "relinked": 0, "unverified": 0, "held": 0},
        "checks": {"unresolved": [], "duplicates": [], "missing_pages": [],
                   "residue": [], "elsewhere": {}, "dangling_refs": 0,
                   "pre_existing": 0, "ok": True},
        "collection_row": "",
        "manifest": "",
        "warnings": [],
        "exception": None,
        "next_action": "none",
    }


def chapter_entries(manifest: dict, paper_dir: Path) -> list[dict]:
    """One entry per chapter file, with the counts `INDEX.md` shows."""
    return [
        {
            "file": row["file"],
            "number": row["number"],
            "title": row["title"],
            "words": row["words"],
            "named_anchors": row["named_anchors"],
            "bytes": row["bytes"],
            "subsections": row["subsections"],
        }
        for row in write_index.chapter_rows(manifest, paper_dir)
    ]


# --------------------------------------------------------------------------
# the stages of one ingest
# --------------------------------------------------------------------------


class Options:
    """What `arxiv_fetch.convert` reads off its parsed command line.

    The driver calls that function rather than the command line, so it hands it
    an object of the same shape instead of building an argument list and parsing
    it back.
    """

    def __init__(self, arxiv_id: str, slug: str, args) -> None:
        self.arxiv_id = arxiv_id
        self.slug = slug
        self.literature_root = args.literature_root
        self.max_chapter_bytes = arxiv_fetch.DEFAULT_MAX_CHAPTER_BYTES
        self.force = args.force
        self.no_inspire = args.no_inspire
        self.no_references = args.no_references
        self.dry_run = False
        self.keep_source = None


def resolve_identity(argument: str | None, args) -> str:
    try:
        return identity.resolve(argument, args.title, args.author, args.year)
    except identity.AmbiguousTitle as error:
        raise Exception2("AMBIGUOUS_TITLE", str(error), candidates=error.candidates)


def held_arxiv_id(root: Path, slug: str) -> str:
    for key, name in reference_store.held_index(root).items():
        if name == slug and key.startswith("arxiv:"):
            return key[len("arxiv:"):]
    return ""


def fetch(arxiv_id: str, args) -> tuple[dict, str]:
    """Stage A: download and convert. Returns (manifest, slug).

    This is the stage that waits on an API, and the only one the pipeline runs
    for more than one paper at a time. It writes the paper's own directory and
    nothing shared, so two of them never race.
    """
    root = args.literature_root
    options = Options(arxiv_id, args.slug or "", args)

    # The name is derived from the paper's own metadata, and the download is
    # what brings that. A dry conversion to learn the title first would cost a
    # second download of the same source, so the conversion writes into a
    # scratch directory and the paper moves to its name once the name is known.
    scratch = Path(tempfile.mkdtemp(prefix="add_paper_"))
    options.literature_root = scratch
    options.slug = "paper"
    options.force = True
    try:
        try:
            manifest = arxiv_fetch.convert(options)
        except arxiv_fetch.NoSource as error:
            raise Exception2("NO_ARXIV_SOURCE", str(error),
                             http_status=error.http_status, reason=error.reason)
        except arxiv_fetch.ParserFailure as error:
            raise Exception2("PARSER_FAILURE", str(error), main_tex=error.main_tex,
                             sections_found=error.sections_found)
        except arxiv_fetch.MetadataUnavailable as error:
            raise Exception2("NETWORK_UNAVAILABLE", str(error),
                             host="export.arxiv.org", reason=str(error))
        except rate_gate.GateTimeout as error:
            raise Exception2("NETWORK_UNAVAILABLE", str(error),
                             host="the request gate", reason=str(error))
        except RuntimeError as error:
            # What is left is an API that did not answer after its retries.
            # That is not a fault of the paper, so the code says to try later.
            raise Exception2("NETWORK_UNAVAILABLE", str(error),
                             host="arxiv.org", reason=str(error))

        manifest["arxiv_id"] = arxiv_id
        if args.slug:
            slug = args.slug
        else:
            try:
                slug = identity.derive_slug(manifest, root)
            except identity.TagCollision as error:
                raise Exception2("TAG_COLLISION", str(error), slug=error.slug,
                                 held_by=error.held_by,
                                 held_arxiv_id=error.held_arxiv_id,
                                 suggested_slug=error.suggested_slug)

        paper_dir = root / slug
        if paper_dir.exists() and not args.force:
            raise Exception2(
                "SLUG_EXISTS",
                "%s already holds a paper; pass --force to replace it" % paper_dir,
                slug=slug,
                existing_arxiv_id=held_arxiv_id(root, slug),
            )

        move_into_place(scratch / "paper", paper_dir)
        manifest["slug"] = slug
        manifest["paper_dir"] = str(paper_dir)
        return manifest, slug
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def move_into_place(source: Path, destination: Path) -> None:
    """Put the converted paper where the collection expects it."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def file_paper(manifest: dict, slug: str, args, report: dict) -> None:
    """Stage B: the index, the manifest, the store, the check, the row.

    Every step here writes something the whole collection shares, so the
    pipeline runs this for one paper at a time, in the order the caller named
    them.
    """
    root = args.literature_root
    paper_dir = Path(manifest["paper_dir"])

    index_path = write_index.write(paper_dir, manifest)
    report["index"] = str(index_path)

    manifest_path = paper_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    report["manifest"] = str(manifest_path)

    if not args.no_references:
        merge(manifest_path, root, report)

    failure = check(root, slug, report)

    description = collection_index.first_sentence(manifest.get("abstract") or "")
    try:
        report["collection_row"] = collection_index.add_row(root, report, description)
    except collection_index.CollectionIndexUnreadable as error:
        raise Exception2("COLLECTION_INDEX_UNREADABLE", str(error),
                         path=error.path, reason=error.reason)

    # Raised last, so that a paper whose citations do not resolve is still a
    # paper the collection lists. The next run then repairs the citations
    # rather than meeting a directory it has no row for.
    if failure is not None:
        raise failure


def merge(manifest_path: Path, root: Path, report: dict) -> None:
    status, counts = update_references.run(
        ["--manifest", str(manifest_path), "--literature-root", str(root)]
    )
    if status != 0:
        raise Exception2("REFERENCE_CHECK_FAILED",
                         counts.get("error", "the reference merge failed"),
                         unresolved=[], duplicates=[], missing_pages=[],
                         residue=[], elsewhere={})
    for name in ("added", "updated", "unchanged", "retagged", "relinked",
                 "unverified", "held"):
        report["references"][name] = counts.get(name, 0)


def check(root: Path, slug: str, report: dict) -> Exception2 | None:
    """The citation verdict for this paper, from one scoped call.

    `--paper` names the defects of this paper directly, so a second pass and a
    subtraction would buy nothing. A defect another paper carries stays in
    `elsewhere`, and it never fails this ingest.

    Returns the exception the caller must raise, or None. It is returned rather
    than raised so that the collection row is written first.
    """
    found = check_references.check(root, paper=slug)
    ok = not (found["unresolved"] or found["duplicates"] or found["missing_pages"]
              or found["stale"])
    report["checks"] = {
        "unresolved": [entry["tag"] for entry in found["unresolved"]],
        "duplicates": found["duplicates"],
        "missing_pages": found["missing_pages"],
        "residue": found["residue"],
        "elsewhere": found["elsewhere"],
        "dangling_refs": len(found["dangling_refs"]),
        # What the check reports for the rest of the collection: this run did
        # not create it, and this run does not fix it.
        "pre_existing": sum(
            value for value in found["elsewhere"].values() if isinstance(value, int)
        ),
        "ok": ok,
    }
    if found["residue"]:
        report["warnings"].append({
            "code": "PLACEHOLDER_RESIDUE",
            "detail": "%d file(s) of this paper hold a PH<number> marker or a "
                      "control character, where the text should hold what the "
                      "paper wrote: %s" % (
                          len(found["residue"]),
                          ", ".join(entry["in"] for entry in found["residue"][:5])),
            "count": len(found["residue"]),
        })
    if ok:
        return None
    return Exception2(
        "REFERENCE_CHECK_FAILED",
        "the citations of %s do not all resolve" % slug,
        unresolved=report["checks"]["unresolved"],
        duplicates=found["duplicates"],
        missing_pages=found["missing_pages"],
        residue=found["residue"],
        elsewhere=found["elsewhere"],
    )


def describe(manifest: dict, report: dict) -> None:
    """Copy the identity of the paper out of the manifest into the report."""
    authors = manifest.get("authors") or []
    paper_dir = Path(manifest.get("paper_dir") or "")
    report.update({
        "arxiv_id": manifest.get("arxiv_id", ""),
        "slug": manifest.get("slug", ""),
        "paper_dir": str(paper_dir),
        "title": manifest.get("title", ""),
        "authors": authors[:AUTHORS_SHOWN],
        "authors_total": len(authors),
        "submitted_year": manifest.get("submitted_year"),
        "publication": manifest.get("publication") or report["publication"],
        "abs_url": manifest.get("abs_url", ""),
        "parser": manifest.get("parser", ""),
        "ingested": manifest.get("ingested", report["ingested"]),
        "chapters": chapter_entries(manifest, paper_dir),
    })
    figures = manifest.get("figures") or []
    report["figures"] = len(figures)
    report["figures_missing"] = sum(1 for record in figures if not record.get("file"))
    report["references"]["cited"] = len(manifest.get("references") or [])


def ingest(arxiv_id: str, args, manifest: dict | None = None) -> dict:
    """One paper, end to end. Raises `Exception2`; never exits."""
    report = blank_report(arxiv_id)
    if manifest is None:
        manifest, slug = fetch(arxiv_id, args)
    else:
        slug = manifest["slug"]

    describe(manifest, report)
    warnings = list(manifest.get("warnings") or [])
    report["warnings"] = classify(
        warnings, {"UNRESOLVED_REFS": len(manifest.get("unresolved_refs") or [])}
    )
    if rate_gate.local_only():
        report["warnings"].append({
            "code": "RATE_GATE_LOCAL",
            "detail": "the request gate could not take a file lock under the "
                      "collection root, so it paced this process alone; another "
                      "process calling these APIs is not held back by it",
            "count": 1,
        })

    try:
        file_paper(manifest, slug, args, report)
    except Exception2 as error:
        # The paper is on disk by now. Everything the run learned travels with
        # the exception, so the agent that handles the code sees it.
        report["warnings"] = report["warnings"][:REPORT_WARNINGS_SHOWN]
        error.report = report
        raise

    report["status"] = "ingested"
    report["warnings"] = report["warnings"][:REPORT_WARNINGS_SHOWN]
    return report


# --------------------------------------------------------------------------
# the other two commands
# --------------------------------------------------------------------------


def rebuild_index(slug: str, args) -> dict:
    """Write `INDEX.md` again from the manifest and the files on disk."""
    paper_dir = args.literature_root / slug
    manifest = write_index.load_manifest(paper_dir)
    index_path = write_index.write(paper_dir, manifest)

    report = blank_report(manifest.get("arxiv_id", ""))
    describe(manifest, report)
    report["status"] = "ingested"
    report["index"] = str(index_path)
    report["manifest"] = str(paper_dir / MANIFEST_NAME)

    description = collection_index.first_sentence(manifest.get("abstract") or "")
    try:
        report["collection_row"] = collection_index.add_row(
            args.literature_root, report, description
        )
    except collection_index.CollectionIndexUnreadable as error:
        raise Exception2("COLLECTION_INDEX_UNREADABLE", str(error),
                         path=error.path, reason=error.reason)
    return report


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("arxiv_ids", nargs="*", help="one or more arXiv identifiers")
    parser.add_argument("--auto", action="store_true",
                        help="ingest the papers named, and report what happened")
    parser.add_argument("--index-only", metavar="SLUG",
                        help="write INDEX.md again from the manifest and the files")
    parser.add_argument("--title", help="search arXiv for this title instead")
    parser.add_argument("--author", help="one author name; the surname is what matters")
    parser.add_argument("--year", type=int, help="the year of the paper")
    parser.add_argument("--slug", help="the directory name to use, rather than a derived one")
    parser.add_argument("--force", action="store_true",
                        help="replace a paper directory that is already there")
    parser.add_argument("--literature-root", type=Path,
                        default=reference_store.default_root())
    parser.add_argument("--no-inspire", action="store_true",
                        help="skip the INSPIRE-HEP lookup")
    parser.add_argument("--no-references", action="store_true",
                        help="skip the bibliography and the reference merge")
    return parser


def emit(report: dict) -> None:
    """One report, as one JSON object on one line.

    One line per paper, so a caller ingesting several reads them apart without
    parsing a stream of indented objects.
    """
    print(json.dumps(report, ensure_ascii=False))


def failed(report: dict, error: Exception2) -> dict:
    report["status"] = "exception"
    report["exception"] = error.as_object()
    report["next_action"] = "handle_exception"
    return report


def run_auto(args) -> int:
    """Ingest every paper named, and return the exit status.

    Stage A waits on arXiv, and `MAX_CONCURRENT_FETCHES` papers run it together:
    the gate still sends one request at a time, so the pipeline fills the wait
    of one request with the conversion of another paper. Stage B writes the
    shared store, so it runs one paper at a time, in the order of the
    identifiers.
    """
    try:
        arxiv_ids = [resolve_identity(argument, args)
                     for argument in (args.arxiv_ids or [None])]
    except Exception2 as error:
        emit(failed(blank_report(), error))
        return 2

    if args.slug and len(arxiv_ids) > 1:
        print(json.dumps({"error": "--slug names one directory, so it takes one paper"}))
        return 1

    status = 0
    if len(arxiv_ids) == 1:
        for arxiv_id in arxiv_ids:
            status = max(status, one(arxiv_id, args, None))
        return status

    with concurrent.futures.ThreadPoolExecutor(MAX_CONCURRENT_FETCHES) as pool:
        fetched = [pool.submit(fetch, arxiv_id, args) for arxiv_id in arxiv_ids]
        for arxiv_id, future in zip(arxiv_ids, fetched):
            try:
                manifest, _ = future.result()
            except Exception2 as error:
                emit(failed(blank_report(arxiv_id), error))
                status = 2
                continue
            status = max(status, one(arxiv_id, args, manifest))
    return status


def one(arxiv_id: str, args, manifest: dict | None) -> int:
    try:
        emit(ingest(arxiv_id, args, manifest))
        return 0
    except Exception2 as error:
        report = error.report
        if report is None:
            report = blank_report(arxiv_id)
            if manifest is not None:
                describe(manifest, report)
        emit(failed(report, error))
        return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if bool(args.auto) == bool(args.index_only):
        print(json.dumps({"error": "give exactly one of --auto, --index-only"}))
        return 1

    # The collection this run writes is the collection whose gate it locks. The
    # directory comes first, because the gate locks a collection and never
    # creates one.
    args.literature_root.mkdir(parents=True, exist_ok=True)
    rate_gate.use_root(args.literature_root)

    if args.auto:
        if not args.arxiv_ids and not (args.title or args.author or args.year):
            print(json.dumps(
                {"error": "--auto needs an arXiv identifier, or --title, "
                          "--author or --year"}))
            return 1
        return run_auto(args)

    try:
        report = rebuild_index(args.index_only, args)
    except Exception2 as error:
        emit(failed(blank_report(), error))
        return 2
    except (RuntimeError, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        return 1

    emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
