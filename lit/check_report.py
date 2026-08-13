#!/usr/bin/env python3
"""Check that every citation in a report still points at something.

A report answers a question in its own words and attributes each claim to the
place in the literature the claim came from. The attribution is a link, and a
link is easy to write and easy to get wrong: the chapter is renamed, the anchor
never existed, the work is cited in the text and missing from the references.
A reader finds out by clicking. This finds out first.

This reads every link the way a reader reads it: relative to the report. A
link that does not open there is broken, wherever else the file sits. The
collection root gives the diagnosis and not the verdict. A root that holds the
file the link names tells the reader to repair the path in the report. A root
that holds nothing for the link tells the reader to get the paper.

What it reports:

    broken link     a link whose file is not there, whose file the collection
                    holds at another place, or whose anchor is not in it
    unknown tag     a link to a reference page no record in the store answers
    cite marker     a `[cite: tag]` marker copied out of a chapter, unresolved
    bibliography    cited_but_not_listed: a work the text cites and the
                    references omit; listed_but_not_cited: a work the
                    references list and the text cites nowhere
    unflagged       a work the collection could not confirm, cited without the
                    ⚠ that says so
    absent work     a work the report cites and the collection does not hold
    no citations    a report that attributes nothing to anything

Exit status is 1 when any of those was found. An absent work is the one
exception. The report names such a work and a reader can go and get it, thus
the list of them describes the collection and not the report.

A missing research log is reported and does not fail: the log is the record of
how the report was reached, and a report written another way is still auditable.

Usage:
    check_report.py reports/axial-mass.md
    check_report.py reports/axial-mass.md --literature-root ~/literature
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

from lit import cli, paths, reference_store
from lit.text import collapse_whitespace
from lit.check_references import ANCHOR

# `[Katori 2018](../literature/katori_2018/chapters/03_model.md#sec-form-factors)`.
# The target stops at the first space, so a link carrying a title —
# `(path "Title")` — keeps only its path.
LINK = re.compile(r"\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)")

# Where the references of the report begin. The last one wins: a body section
# may well discuss the word.
BIBLIOGRAPHY = re.compile(r"^#{1,6}\s+References\s*$", re.IGNORECASE | re.MULTILINE)

# What marks a work the collection could not confirm, wherever it is written.
UNVERIFIED_MARK = "⚠"

MARKDOWN_SUFFIXES = (".md", ".markdown")

# The shape of the collection, as a link writes it. A paper directory holds an
# INDEX.md, its chapters in one directory and its figures in another. The pages
# of the reference store sit together under one more directory. These names let
# a link that reaches no file still say which work it cites.
PAPER_SUBDIRS = ("chapters", "figures", "figures_raw")
PAPER_INDEX = "INDEX.md"

# How much of a link must name a place in the collection before the collection
# is searched for it. Two parts is a directory and a name, which the layout
# above always gives. One part is a bare file name, and a report that links
# `../README.md` means the README of its own project.
COLLECTION_TAIL_PARTS = 2


# --------------------------------------------------------------------------
# links
# --------------------------------------------------------------------------


def heading_anchors(text: str) -> set[str]:
    """The anchors a renderer makes out of the headings themselves.

    A converted chapter carries `<a id="sec-pcac"></a>` of its own, and those
    are the anchors a citation should use. A file the conversion never touched
    — an INDEX.md, a report — has only its headings, and a link to one of those
    resolves in every Markdown renderer, so it resolves here too.
    """
    found = set()
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.*?)\s*$", line)
        if not match:
            continue
        slug = re.sub(r"[^\w\- ]", "", match.group(1).lower()).strip()
        found.add(re.sub(r"\s+", "-", slug))
    return found


def anchors_of(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return set(ANCHOR.findall(text)) | heading_anchors(text)


def local_links(text: str, report: Path) -> list[dict]:
    """Every link in the report that names a file, with where it lands.

    A link to someone else's site is not this script's business: nothing here
    can say whether it resolves, and guessing would be worse than silence.
    """
    found = []
    for raw in LINK.findall(text):
        target = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
        if re.match(r"^(?:https?|mailto|ftp):", target, flags=re.IGNORECASE):
            continue
        if target.startswith("#"):
            path_part, anchor = "", target[1:]
        else:
            path_part, _, anchor = target.partition("#")
        if not path_part and not anchor:
            continue
        base = report if not path_part else (report.parent / path_part)
        found.append(
            {"link": target, "path": base, "anchor": anchor, "target": path_part}
        )
    return found


def check_links(links: list[dict], root: Path) -> list[dict]:
    """Every link that leads nowhere, and why.

    Each link starts at the report, because that is where a reader starts. A
    link that opens nothing from there is broken. What the collection holds
    names the repair:

    - the root holds the file. The report was written for a collection at
      another place, and the path in the report is what to repair.
    - the root holds nothing for the link. This collection does not hold the
      work, and the paper is what to get.
    """
    broken = []
    anchors: dict[Path, set[str]] = {}
    for link in links:
        path = link["path"]
        if not path.is_file():
            broken.append(elsewhere(link, root))
            continue
        if not link["anchor"] or path.suffix.lower() not in MARKDOWN_SUFFIXES:
            # A fragment on anything but Markdown is the renderer's business,
            # not this script's: a line number in a source file resolves in an
            # editor and there is no anchor here to look for.
            continue
        resolved = path.resolve()
        if resolved not in anchors:
            anchors[resolved] = anchors_of(path)
        if link["anchor"] not in anchors[resolved]:
            broken.append({"link": link["link"], "why": "no such anchor"})
    return broken


def in_collection(link: dict, root: Path) -> Path | None:
    """The file the collection holds for a link, or None when it holds none.

    The longest tail of the link that names a file under the root is the file
    the link meant. A longer tail leaves less of the answer to guesswork. A
    tail too short to carry the layout is thus not searched for at all.
    """
    parts = PurePosixPath(link["target"]).parts
    for start in range(len(parts) - COLLECTION_TAIL_PARTS + 1):
        tail = parts[start:]
        if any(part in (".", "..") for part in tail):
            # A step out of a directory is how a link reaches the collection
            # from the report. It says nothing about where a file sits inside
            # the collection, so a tail that carries one is not a tail.
            continue
        candidate = root.joinpath(*tail)
        if candidate.is_file():
            return candidate
    return None


def elsewhere(link: dict, root: Path) -> dict:
    """A broken link, told apart by what the collection holds for it."""
    found = in_collection(link, root)
    if found is None:
        return {"link": link["link"], "why": "no such file"}
    broken = {
        "link": link["link"],
        "why": "the collection holds this file, the link does not reach it",
        "in_collection": str(found.relative_to(root)),
    }
    if link["anchor"] and found.suffix.lower() in MARKDOWN_SUFFIXES:
        broken["anchor_in_collection"] = link["anchor"] in anchors_of(found)
    return broken


# --------------------------------------------------------------------------
# what each link cites
# --------------------------------------------------------------------------


def under(path: Path, root: Path) -> tuple[str, ...] | None:
    """The parts of `path` below the collection, or None when it is outside."""
    try:
        return path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return None


def collection_parts(link: dict, root: Path) -> tuple[str, ...] | None:
    """Where in a collection a link points, whichever collection that is.

    A link that misses this collection still names the work its writer read.
    Three rules read a link as a place in a collection, in this order:

    1. the link lands under the root.
    2. the root holds a file at a tail of the link.
    3. the shape of the link is the shape of the layout.

    Rule 3 answers for a work that nothing here holds. That is what lets the
    report count such a work and name it, rather than drop it.
    """
    inside = under(link["path"], root)
    if inside is not None:
        return inside
    found = in_collection(link, root)
    if found is not None:
        return found.relative_to(root).parts
    return by_layout(PurePosixPath(link["target"]).parts)


def by_layout(parts: tuple[str, ...]) -> tuple[str, ...] | None:
    """The tail of a written path that names a place in a collection.

    The last directory of the layout wins, so a project whose own directory
    carries one of these names does not take the link away from the paper.
    """
    for index in range(len(parts) - 1, 0, -1):
        if parts[index] == paths.RECORDS_DIR and index == len(parts) - 2:
            return parts[index:]
        if parts[index] in PAPER_SUBDIRS and parts[index - 1] not in (".", ".."):
            return parts[index - 1 :]
    if len(parts) > 1 and parts[-1] == PAPER_INDEX and parts[-2] not in (".", ".."):
        return parts[-2:]
    return None


def cited_work(link: dict, root: Path) -> tuple[str, str] | None:
    """What publication a link cites, as (kind, name), or None for anything else.

    A citation reaches a work two ways, and both must count as the same work.
    A paper the collection holds is cited at the chapter the claim is in, which
    names the paper by its directory; a work known only from a bibliography is
    cited at its reference page, which names it by its tag.
    """
    parts = collection_parts(link, root)
    if parts is None:
        return None
    if (
        parts[0] == paths.RECORDS_DIR
        and len(parts) == 2
        and parts[1].lower().endswith(".md")
    ):
        return ("tag", parts[1][: -len(".md")])
    if len(parts) > 1:
        return ("slug", parts[0])
    return None


def held_slugs(store: list[dict], root: Path) -> dict[str, str]:
    """tag -> the directory holding that work in full, for the works held here.

    Read from the INDEX.md of every paper rather than from the `held_as` of
    each record, so a store that has not been written since the paper was
    ingested still answers correctly. A directory named after the tag is that
    work as well: a paper already known as a reference keeps its tag as its
    directory name, which is what makes one work carry one identifier.
    """
    held = reference_store.held_index(root)
    mapping = {}
    for record in store:
        tag = record.get("tag", "")
        if not tag:
            continue
        slug = record.get("held_as")
        if not slug:
            keys = reference_store.identity_keys(record)
            slug = next((held[key] for key in keys if key in held), None)
        if not slug and (root / tag).is_dir():
            slug = tag
        if slug:
            mapping[tag] = slug
    return mapping


def canonical(work: tuple[str, str], slugs: dict[str, str]) -> str:
    """One name for one publication, whichever way it was cited.

    A tag whose work the collection holds in full answers as that paper, so a
    claim cited at a chapter and an entry listing the record are not reported
    as two different works.
    """
    kind, name = work
    if kind == "tag" and name in slugs:
        return "slug:%s" % slugs[name]
    return "%s:%s" % (kind, name)


def is_held(name: str, root: Path) -> bool:
    """Whether the collection holds the work that a canonical name names."""
    kind, _, rest = name.partition(":")
    if kind == "tag":
        return (root / paths.RECORDS_DIR / ("%s.md" % rest)).is_file()
    return (root / rest).is_dir()


def split_bibliography(text: str) -> tuple[str, str]:
    """The report's prose and its references, apart."""
    matches = list(BIBLIOGRAPHY.finditer(text))
    if not matches:
        return text, ""
    start = matches[-1].start()
    return text[:start], text[start:]


def entry_of(bibliography: str, needle: str) -> str:
    """The one list item of the references that carries this link.

    An entry wraps over several lines, so it runs from its own bullet to the
    next one; the ⚠ that marks an unconfirmed work may sit anywhere in it.
    """
    items = re.split(r"^(?=[-*+]\s)", bibliography, flags=re.MULTILINE)
    for item in items:
        if needle in item:
            return item
    return ""


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------


def check(report_path: Path, root: Path) -> dict:
    text = report_path.read_text(encoding="utf-8", errors="replace")
    store = reference_store.load(root)
    tags = {record.get("tag", ""): record for record in store}

    body_text, bibliography_text = split_bibliography(text)
    links = local_links(text, report_path)
    body_links = local_links(body_text, report_path)
    bibliography_links = local_links(bibliography_text, report_path)
    slugs = held_slugs(store, root)

    def works(of: list[dict]) -> dict[str, tuple[str, str]]:
        found = {}
        for link in of:
            work = cited_work(link, root)
            if work:
                found[canonical(work, slugs)] = work
        return found

    body_works = works(body_links)
    bibliography_works = works(bibliography_links)
    absent = sorted(name for name in works(links) if not is_held(name, root))

    cited_tags = sorted(
        {
            work[1]
            for link in links
            for work in [cited_work(link, root)]
            if work and work[0] == "tag"
        }
    )

    unflagged = []
    for tag in cited_tags:
        record = tags.get(tag)
        if record is None or record.get("verified"):
            continue
        entry = entry_of(bibliography_text, "%s.md" % tag)
        if UNVERIFIED_MARK not in entry:
            unflagged.append(tag)

    markers = sorted(
        {
            collapse_whitespace(tag)
            for match in reference_store.CITE_TAG.finditer(text)
            for tag in match.group(1).split(",")
            if collapse_whitespace(tag)
        }
    )

    return {
        "report": str(report_path),
        "literature_root": str(root),
        # What the report cites, whether or not the collection holds it, and
        # whether or not the link opens. A report that names twelve papers
        # cites twelve papers. `works_not_in_collection` says which of them
        # this collection holds, and `broken_links` which of them open.
        "citations": len(body_works),
        "works_not_in_collection": absent,
        "broken_links": check_links(links, root),
        "unknown_tags": sorted(tag for tag in cited_tags if tag not in tags),
        "cite_markers": markers,
        "cited_but_not_listed": sorted(set(body_works) - set(bibliography_works)),
        "listed_but_not_cited": sorted(set(bibliography_works) - set(body_works)),
        "unflagged_unverified": unflagged,
        # The log says how the report was reached: what was searched, what was
        # read, and what the search never answered. A reader auditing a claim
        # the report does not make has nowhere else to look.
        "research_log": next(
            (
                str(candidate.name)
                for candidate in [report_path.with_suffix(".research-log.md")]
                if candidate.is_file()
            ),
            None,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = cli.parser(__doc__)
    parser.add_argument("report", type=Path, help="the report to check")
    cli.add_root_argument(parser)
    args = cli.parse(parser, argv)

    if not args.report.is_file():
        return cli.fail("%s is not a file" % args.report, cli.ABSENT)

    try:
        report = check(args.report, args.literature_root)
    except RuntimeError as error:
        return cli.fail(str(error), cli.ABSENT)

    report["ok"] = not (
        report["broken_links"]
        or report["unknown_tags"]
        or report["cite_markers"]
        or report["cited_but_not_listed"]
        or report["listed_but_not_cited"]
        or report["unflagged_unverified"]
        # A report that attributes nothing to anything has nothing to audit,
        # and a claim about the literature that names no paper is the failure
        # every other check here is a special case of.
        or not report["citations"]
    )
    cli.emit(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
