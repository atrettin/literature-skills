#!/usr/bin/env python3
"""Check that every citation in a report still points at something.

A report answers a question in its own words and attributes each claim to the
place in the literature the claim came from. The attribution is a link, and a
link is easy to write and easy to get wrong: the chapter is renamed, the anchor
never existed, the work is cited in the text and missing from the references.
A reader finds out by clicking. This finds out first.

What it reports:

    broken link     a link whose file is not there, or whose anchor is not in it
    unknown tag     a link to a reference page no record in the store answers
    cite marker     a `[cite: tag]` marker copied out of a chapter, unresolved
    bibliography    a work cited in the text and absent from the references, or
                    listed in the references and cited nowhere
    unflagged       a work the collection could not confirm, cited without the
                    ⚠ that says so
    no citations    a report that attributes nothing to anything

Exit status is 1 when any of those was found.

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference_store  # noqa: E402
from arxiv_search import collapse_whitespace  # noqa: E402
from check_references import ANCHOR  # noqa: E402

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


def check_links(links: list[dict]) -> list[dict]:
    """Every link that leads nowhere, and why."""
    broken = []
    anchors: dict[Path, set[str]] = {}
    for link in links:
        path = link["path"]
        if not path.is_file():
            broken.append({"link": link["link"], "why": "no such file"})
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


# --------------------------------------------------------------------------
# what each link cites
# --------------------------------------------------------------------------


def under(path: Path, root: Path) -> Path | None:
    """The part of `path` below the collection, or None when it is outside."""
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None


def cited_work(link: dict, root: Path) -> tuple[str, str] | None:
    """What publication a link cites, as (kind, name), or None for anything else.

    A citation reaches a work two ways, and both must count as the same work.
    A paper the collection holds is cited at the chapter the claim is in, which
    names the paper by its directory; a work known only from a bibliography is
    cited at its reference page, which names it by its tag.
    """
    inside = under(link["path"], root)
    if inside is None:
        return None
    parts = inside.parts
    if parts[0] == reference_store.RECORDS_DIR and inside.suffix.lower() == ".md":
        return ("tag", inside.stem)
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
        "citations": len(body_works),
        "broken_links": check_links(links),
        "unknown_tags": sorted(tag for tag in cited_tags if tag not in tags),
        "cite_markers": markers,
        "uncited_in_references": sorted(set(body_works) - set(bibliography_works)),
        "unlisted_in_references": sorted(set(bibliography_works) - set(body_works)),
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
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("report", type=Path, help="the report to check")
    parser.add_argument(
        "--literature-root", type=Path, default=reference_store.default_root()
    )
    args = parser.parse_args(argv)

    if not args.report.is_file():
        print(json.dumps({"error": "%s is not a file" % args.report}, indent=2))
        return 1

    try:
        report = check(args.report, args.literature_root)
    except RuntimeError as error:
        print(json.dumps({"error": str(error)}, indent=2))
        return 1

    report["ok"] = not (
        report["broken_links"]
        or report["unknown_tags"]
        or report["cite_markers"]
        or report["uncited_in_references"]
        or report["unlisted_in_references"]
        or report["unflagged_unverified"]
        # A report that attributes nothing to anything has nothing to audit,
        # and a claim about the literature that names no paper is the failure
        # every other check here is a special case of.
        or not report["citations"]
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
