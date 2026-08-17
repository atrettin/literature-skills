#!/usr/bin/env python3
"""Check that every citation in a report still points at something.

A report answers a question in its own words and attributes each claim to the
place in the literature the claim came from. The attribution is a `lit:` marker,
and a marker is easy to write and easy to get wrong: the chapter is renamed, the
anchor never existed, the work is cited in the text and missing from the
references. A reader finds out by clicking. This finds out first.

It checks the report **source**, the file holding the markers, against the
store — the paper, the chapter and the anchor a marker names. The rendered
report is written from a checked source by `litdb render-report`, so its links
resolve by construction, and checking the store rather than a rendered file
means one check answers for every flavor the collection is ever rendered in.

What it reports:

    broken marker   a marker naming a paper, a chapter or an anchor that the
                    collection does not hold
    unknown tag     a marker naming a record no entry in the store answers
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
    check_report.py reports/axial-mass.source.md
    check_report.py reports/axial-mass.source.md --literature-root ~/literature
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lit import cli, paths, reference_store
from lit.text import collapse_whitespace

# A `lit:` marker, as the target of a Markdown link. Three forms, matching the
# three things a report cites: `lit:<slug>` for a paper, `lit:<slug>/<chapter>
# #<anchor>` for a place in one, and `lit:ref/<tag>` for a work the collection
# knows but does not hold.
MARKER = re.compile(r"\(lit:([^)\s]*)\)")

# Where the references of the report begin. The last one wins: a body section
# may well discuss the word.
BIBLIOGRAPHY = re.compile(r"^#{1,6}\s+References\s*$", re.IGNORECASE | re.MULTILINE)

# What marks a work the collection could not confirm, wherever it is written.
UNVERIFIED_MARK = "\u26a0"


# --------------------------------------------------------------------------
# markers
# --------------------------------------------------------------------------


def markers_in(text: str) -> list[str]:
    """Every `lit:` marker of a report, in the order it makes them."""
    return MARKER.findall(text)


def research_log(report_path: Path) -> str | None:
    """The name of the log beside this report, or None where there is none.

    A report is written as `<task>.source.md`, and its log as
    `<task>.research-log.source.md`. Both suffixes come from `render_report`,
    which decides them, so the audit looks for the file that command writes
    rather than for a name spelled again here. Either form counts: the source is
    the master, and the rendered log is what a reader opens.
    """
    from lit import render_report

    name = report_path.name
    if name.endswith(render_report.SOURCE_SUFFIX):
        stem = name[: -len(render_report.SOURCE_SUFFIX)]
    else:
        stem = report_path.stem

    for suffix in (render_report.LOG_SOURCE_SUFFIX, render_report.LOG_SUFFIX):
        candidate = report_path.with_name(stem + suffix)
        if candidate.is_file():
            return candidate.name
    return None


def check_markers(found: list[str], root: Path) -> list[dict]:
    """Every marker that names nothing the collection holds, and why.

    The store is what answers, and never a rendered file. A marker is checked
    once and holds for every flavor the collection is ever rendered in, which is
    the whole reason a report cites one rather than a path.
    """
    papers: dict[str, dict] = {}
    broken = []
    for target in found:
        if target.startswith("ref/"):
            tag = target[len("ref/"):]
            if not (root / paths.RECORDS_DIR / ("%s.md" % tag)).is_file():
                broken.append({"marker": "lit:" + target, "why": "no such record"})
            continue

        path_part, _, anchor = target.partition("#")
        slug, _, stem = path_part.partition("/")
        if slug not in papers:
            try:
                papers[slug] = paths.read_paper(root, slug)
            except RuntimeError:
                papers[slug] = {}
        paper = papers[slug]
        if not paper:
            broken.append({"marker": "lit:" + target, "why": "no such paper"})
            continue
        if not stem:
            continue
        chapters = {
            chapter.get("stem", ""): set(chapter.get("anchors") or [])
            for chapter in paper.get("chapters") or []
        }
        if stem not in chapters:
            broken.append({"marker": "lit:" + target, "why": "no such chapter"})
        elif anchor and anchor not in chapters[stem]:
            broken.append({"marker": "lit:" + target, "why": "no such anchor"})
    return broken


def cited_work(target: str) -> tuple[str, str] | None:
    """What publication a marker cites, as (kind, name).

    A citation reaches a work two ways, and both must count as the same work. A
    paper the collection holds is cited at the chapter the claim is in, which
    names the paper by its slug; a work known only from a bibliography is cited
    at its record, which names it by its tag.
    """
    if target.startswith("ref/"):
        tag = target[len("ref/"):]
        return ("tag", tag) if tag else None
    slug = target.partition("#")[0].partition("/")[0]
    return ("slug", slug) if slug else None


# --------------------------------------------------------------------------
# one name per publication
# --------------------------------------------------------------------------


def held_slugs(store: list[dict], root: Path) -> dict[str, str]:
    """tag -> the directory holding that work in full, for the works held here.

    Read from the `paper.json` of every paper rather than from the `held_as` of
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
    markers = markers_in(text)
    slugs = held_slugs(store, root)

    def works(of: list[str]) -> dict[str, tuple[str, str]]:
        found = {}
        for target in of:
            work = cited_work(target)
            if work:
                found[canonical(work, slugs)] = work
        return found

    body_works = works(markers_in(body_text))
    bibliography_works = works(markers_in(bibliography_text))
    absent = sorted(name for name in works(markers) if not is_held(name, root))

    cited_tags = sorted(
        {
            work[1]
            for target in markers
            for work in [cited_work(target)]
            if work and work[0] == "tag"
        }
    )

    unflagged = []
    for tag in cited_tags:
        record = tags.get(tag)
        if record is None or record.get("verified"):
            continue
        entry = entry_of(bibliography_text, "lit:ref/%s" % tag)
        if UNVERIFIED_MARK not in entry:
            unflagged.append(tag)

    cite_markers = sorted(
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
        # this collection holds, and `broken_markers` which of them resolve.
        "citations": len(body_works),
        "works_not_in_collection": absent,
        "broken_markers": check_markers(markers, root),
        "unknown_tags": sorted(tag for tag in cited_tags if tag not in tags),
        "cite_markers": cite_markers,
        "cited_but_not_listed": sorted(set(body_works) - set(bibliography_works)),
        "listed_but_not_cited": sorted(set(bibliography_works) - set(body_works)),
        "unflagged_unverified": unflagged,
        # The log says how the report was reached: what was searched, what was
        # read, and what the search never answered. A reader auditing a claim
        # the report does not make has nowhere else to look.
        "research_log": research_log(report_path),
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
        report["broken_markers"]
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
