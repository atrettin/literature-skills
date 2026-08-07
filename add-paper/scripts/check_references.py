#!/usr/bin/env python3
"""Check that every citation in the collection still points at something.

Tags are written into chapter files and answered by `.references.jsonl`. The
two are separate files that nothing keeps in step automatically, so this reads
every `[cite: ...]` in the collection and asks the store to account for it.

Run it after adding a paper. It is cheap, it touches nothing, and it is the
only thing that notices when a citation has quietly stopped resolving.

What it reports:

    unresolved   a chapter cites a tag no record answers to
    duplicate    one work holds two records, so its citations are split
    orphan       a record nothing cites any more
    stale        a record points at a paper directory that is not there
    dangling ref a link to an equation, figure or section that is not there

Exit status is 1 when anything unresolved, duplicated or stale was found.
Orphans, unverified rows and dangling cross-references are reported but do not
fail: an orphan is what a re-ingested paper leaves behind, an unverified row is
honest about itself, and a cross-reference the paper's own source never defined
cannot be made to resolve.

Usage:
    check_references.py
    check_references.py --literature-root literature
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference_store  # noqa: E402
from arxiv_search import collapse_whitespace  # noqa: E402

CITE_TAG = re.compile(r"\[cite:\s*([^\]]*)\]")
# A cross-reference the conversion could not resolve keeps its marker.
REF_TAG = re.compile(r"\[ref:\s*([^\]]*)\]")
# `[5](03_model.md#eq-ckmt)` and `[5](#eq-ckmt)` for a target in the same file.
REF_LINK = re.compile(r"\]\(([^)#]*)#([^)\s]+)\)")
ANCHOR = re.compile(r'<a id="([^"]*)"></a>')


def read_citations(root: Path) -> dict[str, list[str]]:
    """tag -> the files citing it, over every paper in the collection."""
    found: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted(root.rglob("*.md")):
        if path.parent == root:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in CITE_TAG.finditer(text):
            for tag in match.group(1).split(","):
                tag = collapse_whitespace(tag)
                if tag:
                    found[tag].append(str(path.relative_to(root)))
    return found


def read_cross_references(root: Path) -> list[dict]:
    """Every cross-reference in the collection that lands nowhere.

    A chapter links to its own equations, figures and sections by anchor:
    `eq. ([5](03_model.md#eq-ckmt))`. Nothing keeps a link and the anchor it
    names in step, and a `[ref: label]` marker still standing means the label
    had no target when the paper was converted.
    """
    anchors: dict[Path, set[str]] = {}
    texts: dict[Path, str] = {}
    for path in sorted(root.rglob("*.md")):
        if path.parent == root:
            continue
        texts[path] = path.read_text(encoding="utf-8", errors="replace")
        anchors[path.resolve()] = set(ANCHOR.findall(texts[path]))

    broken = []
    for path, text in texts.items():
        where = str(path.relative_to(root))
        for label in REF_TAG.findall(text):
            broken.append(
                {"in": where, "label": collapse_whitespace(label), "why": "no target"}
            )
        for target, anchor in REF_LINK.findall(text):
            if "://" in target:
                continue  # a fragment on someone else's site
            destination = (path.parent / target).resolve() if target else path.resolve()
            if destination not in anchors:
                broken.append({"in": where, "link": target + "#" + anchor,
                               "why": "no such file"})
            elif anchor not in anchors[destination]:
                broken.append({"in": where, "link": target + "#" + anchor,
                               "why": "no such anchor"})
    return broken


def check(root: Path) -> dict:
    store = reference_store.load(root)
    tags = {record.get("tag", "") for record in store}
    cited = read_citations(root)

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

    return {
        "records": len(store),
        "cited_tags": len(cited),
        "unresolved": sorted(
            ({"tag": tag, "cited_in": sorted(set(files))[:5]} for tag, files in cited.items() if tag not in tags),
            key=lambda item: item["tag"],
        ),
        "duplicates": duplicates,
        "stale": sorted(
            record.get("tag", "")
            for record in store
            if record.get("held_as") and not (root / record["held_as"]).is_dir()
        ),
        "orphans": sorted(tag for tag in tags if tag and tag not in cited),
        "unverified": sum(1 for record in store if not record.get("verified")),
        "dangling_refs": read_cross_references(root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--literature-root", type=Path, default=Path("literature"))
    args = parser.parse_args()

    if not args.literature_root.exists():
        print(json.dumps({"error": "%s does not exist" % args.literature_root}, indent=2))
        return 1

    try:
        report = check(args.literature_root)
    except RuntimeError as error:
        print(json.dumps({"error": str(error)}, indent=2))
        return 1

    report["ok"] = not (report["unresolved"] or report["duplicates"] or report["stale"])
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
