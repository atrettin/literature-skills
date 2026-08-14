#!/usr/bin/env python3
"""Check that every citation in the collection still points at something.

Tags are written into chapter files — as the fragment of the link a citation
is — and answered by `.references.jsonl`. The two are separate files that
nothing keeps in step automatically, so this reads every citation in the
collection and asks the store to account for it.

Run it after adding a paper. It is cheap, it touches nothing, and it is the
only thing that notices when a citation has quietly stopped resolving.

What it reports:

    unresolved   a chapter cites a tag no record answers to
    duplicate    one work holds two records, so its citations are split
    stale        a record points at a paper directory that is not there
    missing page a cited work has no page under references/ to open
    dangling ref a link to an equation, figure or section that is not there
    residue      a chapter holds PH<number> text, or a control character

Exit status is 1 when anything unresolved, duplicated, stale or missing a page
was found.
Unverified rows, dangling cross-references and residue are reported but do not
fail: an unverified row is honest about itself, and a cross-reference the
paper's own source never defined cannot be made to resolve. `ok` answers whether the citations resolve,
and residue is a defect of the text: a fetch of that paper again, with --force,
is what removes it.

`--paper <slug>` says which paper the caller ingested. The read stays
collection-wide either way — a citation in one paper is answered by a store the
whole collection shares. The flag scopes the answer. Every list at the top level
then holds only what belongs to that paper, `elsewhere` counts what belongs to
the rest of the collection, and `ok` and the exit status speak for that paper
alone. Without the flag, the report answers for the whole collection, which is
what a person auditing the collection wants.

Usage:
    check_references.py
    check_references.py --literature-root literature
    check_references.py --paper jeong_2023_shallow_deep_inelastic
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

from lit import blocks, cli, paths, reference_store
from lit.paths import stored_files
from lit.text import collapse_whitespace

# A cross-reference the conversion could not resolve keeps its marker.
REF_TAG = re.compile(r"\[ref:\s*([^\]]*)\]")
# What a placeholder key left behind when the conversion failed to restore it.
RESIDUE = re.compile(r"PH\d+")
# Every C0 control character other than the newline and the tab. A NUL byte
# makes `grep` read the whole file as binary, and report nothing at all.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f]")


def read_text(root: Path) -> dict[Path, str]:
    """The stored text of every paper, read once for every check below.

    The store is what is checked, and never a render: every rendered file is
    written again from these, so a defect found here is the defect, and one
    found in a render would be a defect in the renderer.

    `errors="replace"` rather than a failure: a file holding a byte no decoder
    answers is exactly the file this has something to report about.
    """
    return {
        path: path.read_text(encoding="utf-8", errors="replace")
        for path in stored_files(root)
    }


def read_citations(
    root: Path, texts: dict[Path, str] | None = None
) -> dict[str, list[str]]:
    """tag -> the files citing it, over every paper in the collection.

    A citation is stored as a `[cite: tag]` marker, and becomes a link only when
    the collection is rendered. So the marker is what carries the tag, and this
    is where a tag no record answers is found.
    """
    found: dict[str, list[str]] = collections.defaultdict(list)
    texts = texts if texts is not None else read_text(root)
    for path, text in texts.items():
        where = str(path.relative_to(root))
        for match in reference_store.CITE_TAG.finditer(text):
            for tag in match.group(1).split(","):
                tag = collapse_whitespace(tag)
                if tag:
                    found[tag].append(where)
    return found


def read_residue(root: Path, texts: dict[Path, str]) -> list[dict]:
    """Every file whose text carries the marks of a conversion that went wrong.

    A `PH<number>` stands where the paper wrote something else, and a control
    character hides the file from `grep`. Neither can be repaired in the file:
    only a fetch of the paper again writes the text the paper actually holds.
    """
    found = []
    for path, text in sorted(texts.items()):
        placeholders = len(RESIDUE.findall(text))
        controls = len(CONTROL_CHARACTERS.findall(text))
        if placeholders or controls:
            found.append({
                "in": str(path.relative_to(root)),
                "placeholders": placeholders,
                "control_characters": controls,
            })
    return found


def read_cross_references(root: Path) -> list[dict]:
    """Every cross-reference in the collection that lands nowhere.

    A paper refers to its own equations, figures and sections by a `[ref: label]`
    marker, and `paper.json` says which chapter and anchor each label resolves
    to. A marker no label answers had no target when the paper was converted; a
    label whose chapter or anchor is not there is one the store lost.
    """
    broken = []
    for slug in paths.papers_on_disk(root):
        paper = paths.read_paper(root, slug)
        labels = paper.get("labels") or {}
        anchors = {
            chapter.get("stem", ""): set(chapter.get("anchors") or [])
            for chapter in paper.get("chapters") or []
        }
        for path in paths.text_of(root, slug):
            where = str(path.relative_to(root))
            text = path.read_text(encoding="utf-8", errors="replace")
            for label in REF_TAG.findall(text):
                label = collapse_whitespace(label)
                entry = labels.get(label)
                if not entry:
                    broken.append({"in": where, "label": label, "why": "no target"})
                    continue
                stem, anchor = entry.get("file") or "", entry.get("anchor") or ""
                if stem not in anchors:
                    broken.append({"in": where, "label": label,
                                   "link": stem + "#" + anchor,
                                   "why": "no such file"})
                elif anchor and anchor not in anchors[stem]:
                    broken.append({"in": where, "label": label,
                                   "link": stem + "#" + anchor,
                                   "why": "no such anchor"})
    return broken


def belongs_to(where: str, paper: str) -> bool:
    """Whether a path in the collection is one of the paper's own files."""
    return where == paper or where.startswith(paper + "/")


def scope_report(report: dict, paper: str, store: list[dict],
                 cited: dict[str, list[str]]) -> dict:
    """The same findings, answering for one paper.

    Each list keeps the entries that belong to `paper` and hands the count of
    the rest to `elsewhere`. A citation defect belongs to the paper whose file
    carries the citation; a store defect belongs to the paper the record is
    held as, or the paper that cites it.

    The partition reads the full file list of `cited`, never the `cited_in`
    field of the report: that field keeps the first five files, so a tag ten
    papers cite can lose this paper's own file in the cut.
    """
    records = {record.get("tag", ""): record for record in store}

    def cites(tag: str) -> bool:
        """Whether any file of the paper cites the tag."""
        return any(belongs_to(where, paper) for where in cited.get(tag, []))

    def cited_by_paper(tag: str) -> bool:
        """Whether the record's own `cited_by` names the paper."""
        record = records.get(tag) or {}
        return any(entry.get("slug") == paper for entry in record.get("cited_by") or [])

    def held_as_paper(tag: str) -> bool:
        return (records.get(tag) or {}).get("held_as") == paper

    mine: dict = {}
    elsewhere: dict = {}
    for field, belongs in (
        ("unresolved", lambda item: cites(item["tag"])),
        ("missing_pages", cites),
        ("dangling_refs", lambda item: belongs_to(item["in"], paper)),
        ("residue", lambda item: belongs_to(item["in"], paper)),
        ("duplicates", lambda item: any(
            cites(tag) or held_as_paper(tag) for tag in item["tags"])),
        ("stale", lambda tag: held_as_paper(tag) or cites(tag)),
    ):
        mine[field] = [item for item in report[field] if belongs(item)]
        elsewhere[field] = len(report[field]) - len(mine[field])

    unverified = sum(
        1
        for record in store
        if not record.get("verified") and cited_by_paper(record.get("tag", ""))
    )

    scoped = {"scope": paper, "records": report["records"],
              "cited_tags": report["cited_tags"]}
    for field in ("unresolved", "duplicates", "missing_pages", "stale"):
        scoped[field] = mine[field]
    scoped["unverified"] = unverified
    scoped["dangling_refs"] = mine["dangling_refs"]
    scoped["residue"] = mine["residue"]
    elsewhere["unverified"] = report["unverified"] - unverified
    scoped["elsewhere"] = {
        field: elsewhere[field]
        for field in ("unresolved", "duplicates", "missing_pages", "stale",
                      "unverified", "dangling_refs", "residue")
    }
    return scoped


def check(root: Path, paper: str | None = None) -> dict:
    store = reference_store.load(root)
    tags = {record.get("tag", "") for record in store}
    texts = read_text(root)
    cited = read_citations(root, texts)

    duplicates = []
    seen: dict[str, str] = {}
    for record in store:
        for key in reference_store.identity_keys(record):
            # Only the strong handles prove two records are one work; a shared
            # title and year can be a paper and its own proceedings version.
            if key.startswith("title:"):
                continue
            if key in seen and seen[key] != record.get("tag"):
                duplicates.append({"identity": key, "tags": sorted([seen[key], record.get("tag", "")])})
            seen.setdefault(key, record.get("tag", ""))

    report = {
        "records": len(store),
        "cited_tags": len(cited),
        "unresolved": sorted(
            ({"tag": tag, "cited_in": sorted(set(files))[:5]} for tag, files in cited.items() if tag not in tags),
            key=lambda item: item["tag"],
        ),
        "duplicates": duplicates,
        # A tag the store answers still needs the page its citation opens. The
        # store cannot say whether that file is on disk, and a reader clicking
        # a citation is the only other thing that would find out.
        "missing_pages": sorted(
            tag
            for tag in cited
            if tag in tags and not (root / paths.RECORDS_DIR / ("%s.md" % tag)).is_file()
        ),
        "stale": sorted(
            record.get("tag", "")
            for record in store
            if record.get("held_as") and not (root / record["held_as"]).is_dir()
        ),
        "unverified": sum(1 for record in store if not record.get("verified")),
        "dangling_refs": read_cross_references(root),
        # Reported, and it leaves `ok` true: `ok` answers for the citations.
        "residue": read_residue(root, texts),
    }
    if paper is None:
        return report
    return scope_report(report, paper, store, cited)


def main(argv: list[str] | None = None) -> int:
    parser = cli.parser(__doc__)
    cli.add_root_argument(parser)
    parser.add_argument(
        "--paper",
        help="slug of the paper the answer is about; the read stays collection-wide",
    )
    args = cli.parse(parser, argv)

    if not args.literature_root.exists():
        return cli.fail("%s does not exist" % args.literature_root, cli.ABSENT)

    try:
        report = check(args.literature_root, args.paper)
    except RuntimeError as error:
        return cli.fail(str(error), cli.ABSENT)

    report["ok"] = not (
        report["unresolved"]
        or report["duplicates"]
        or report["stale"]
        or report["missing_pages"]
    )
    cli.emit(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
