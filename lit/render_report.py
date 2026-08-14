#!/usr/bin/env python3
"""Turn the `lit:` markers of a report into links that open the collection.

A report is written twice. `reports/<task>.source.md` is what the agent writes,
and it cites the collection with markers:

    ([§6.5](lit:formaggio_2013_ev_eev/06-05_coherent_pion_production#p2))

`reports/<task>.md` is what a person reads, and it carries the link that flavor
resolves to. The marker names the paper and not any rendering of it, so the
agent writing the report never has to know what the collection is rendered as,
and a flavor change re-renders every report rather than breaking every link.

Three forms of marker, matching the three things a report cites:

    lit:<slug>                        the paper's own page
    lit:<slug>/<chapter>#<anchor>     a place in a chapter
    lit:ref/<tag>                     a work the collection knows but does not hold

A marker that names nothing the collection holds is left as it stands, and
`lit check-report` is what reports it. Rewriting it into a link would turn a
citation that leads nowhere into one that merely looks as if it does.

Usage:
    render_report.py reports/axial-mass.source.md
    render_report.py reports/ --literature-root literature
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from lit import blocks, cli, paths
from lit.render import Context

# `lit:` as the target of a Markdown link. The tail runs to the closing bracket
# or to whitespace, so a marker inside a sentence ends where the link does.
MARKER = re.compile(r"\(lit:([^)\s]*)\)")

SOURCE_SUFFIX = ".source.md"
LOG_SUFFIX = ".research-log.md"
LOG_SOURCE_SUFFIX = ".research-log.source.md"


def rendered_name(source: Path) -> Path:
    """Where the readable form of one source goes."""
    name = source.name
    if name.endswith(LOG_SOURCE_SUFFIX):
        return source.with_name(name[: -len(LOG_SOURCE_SUFFIX)] + LOG_SUFFIX)
    if name.endswith(SOURCE_SUFFIX):
        return source.with_name(name[: -len(SOURCE_SUFFIX)] + ".md")
    return source.with_name(source.stem + ".rendered.md")


# --------------------------------------------------------------------------
# what a marker resolves to
# --------------------------------------------------------------------------


class Collection:
    """What the collection holds, as a report's markers ask about it.

    Read once per run: a report cites the same paper many times, and a marker
    that is checked against the store must be checked against the same store
    every time it appears.
    """

    def __init__(self, root: Path, flavor: str) -> None:
        self.root = root
        self.flavor = flavor
        self.papers: dict[str, dict] = {}
        self.headings: dict[str, dict[str, str]] = {}
        for slug in paths.papers_on_disk(root):
            self.papers[slug] = paths.read_paper(root, slug)
        self.tags = {path.stem for path in (root / paths.RECORDS_DIR).glob("*.md")}

    def anchors(self, slug: str, stem: str) -> set[str]:
        paper = self.papers.get(slug)
        if not paper:
            return set()
        for chapter in paper.get("chapters") or []:
            if chapter.get("stem") == stem:
                return set(chapter.get("anchors") or [])
        return set()

    def heading_text(self, slug: str, anchor: str) -> str | None:
        """The words of the heading an anchor sits on, if it sits on one.

        Obsidian resolves a section by its heading and by nothing else, so this
        is read out of the stored blocks the one time a slug needs it.
        """
        if slug not in self.headings:
            found: dict[str, str] = {}
            for path in paths.text_of(self.root, slug):
                for block in blocks.read(path):
                    if block.get("kind") == "heading" and block.get("anchor"):
                        found[block["anchor"]] = " ".join(
                            part for part in (
                                block.get("number") or "", block.get("title") or ""
                            ) if part
                        )
            self.headings[slug] = found
        return self.headings[slug].get(anchor)


def resolve(target: str, collection: Collection, report_dir: Path) -> str | None:
    """One marker's tail as a path relative to the report, or None for unknown."""
    root = os.path.relpath(collection.root.resolve(), report_dir.resolve())

    if target.startswith("ref/"):
        tag = target[len("ref/"):]
        if tag not in collection.tags:
            return None
        return "%s/%s/%s.md" % (root, paths.RECORDS_DIR, tag)

    path, _, anchor = target.partition("#")
    slug, _, stem = path.partition("/")
    if slug not in collection.papers:
        return None

    if not stem:
        return "%s/%s/%s" % (root, slug, paths.INDEX_NAME)

    anchors = collection.anchors(slug, stem)
    if not anchors and stem not in {
        chapter.get("stem") for chapter in collection.papers[slug].get("chapters") or []
    }:
        return None
    if anchor and anchor not in anchors:
        return None

    fragment = ""
    if anchor:
        context = Context(collection.flavor, {}, {}, {}, "")
        heading = collection.heading_text(slug, anchor)
        if heading is not None:
            context.headings = {anchor: heading}
        fragment = context.fragment(anchor)
    return "%s/%s/%s/%s.md%s" % (root, slug, paths.CHAPTERS_DIR, stem, fragment)


# --------------------------------------------------------------------------
# one report
# --------------------------------------------------------------------------


def render_text(text: str, collection: Collection, report_dir: Path) -> tuple[str, list[str]]:
    """The report with every marker resolved, and the markers that were not."""
    unresolved: list[str] = []

    def replace(match: re.Match) -> str:
        target = match.group(1)
        resolved = resolve(target, collection, report_dir)
        if resolved is None:
            unresolved.append(target)
            return match.group(0)
        return "(%s)" % resolved

    return MARKER.sub(replace, text), unresolved


def render_file(source: Path, collection: Collection) -> dict:
    text = source.read_text(encoding="utf-8")
    rendered, unresolved = render_text(text, collection, source.parent)
    target = rendered_name(source)
    target.write_text(rendered, encoding="utf-8")
    return {
        "source": str(source),
        "rendered": str(target),
        "unresolved": sorted(set(unresolved)),
    }


def sources_in(directory: Path) -> list[Path]:
    """Every report source under a directory, the log beside its report."""
    if directory.is_file():
        return [directory]
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.rglob("*" + SOURCE_SUFFIX) if path.is_file()
    )


def render_directory(directory: Path, root: Path, flavor: str) -> list[dict]:
    """Render every report source under `directory`. Returns one entry each."""
    sources = sources_in(directory)
    if not sources:
        return []
    collection = Collection(root, flavor)
    return [render_file(source, collection) for source in sources]


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = cli.parser(__doc__)
    parser.add_argument(
        "report", type=Path, help="a report source, or a directory holding them"
    )
    cli.add_root_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = cli.parse(build_parser(), argv)
    root = args.literature_root
    if not root.is_dir():
        cli.emit({"error": "%s is not a collection" % root})
        return cli.JUDGEMENT

    flavor = paths.flavor(root)
    reports = render_directory(args.report, root, flavor)
    if not reports:
        cli.emit({"error": "%s holds no report source" % args.report,
                  "expected": "a file ending in %s" % SOURCE_SUFFIX})
        return cli.ABSENT

    cli.emit({"flavor": flavor, "reports": reports})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
