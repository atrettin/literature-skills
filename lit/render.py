#!/usr/bin/env python3
"""Write the collection a person reads, from the store that holds it.

The store carries markers and no links, because a link's shape belongs to the
tool that opens it. This resolves those markers into one flavor:

  * **vscode** — what the KaTeX preview built into VS Code renders. Anchors are
    HTML, `<a id="p2"></a>` above the block they name, and a link names one with
    `#p2`.
  * **obsidian** — what Obsidian renders. It resolves a fragment to a heading or
    to a block ID and never to an HTML anchor, so a block carries `^p2` at its
    end and a link names it with `#^p2`. Its maths is MathJax, which accepts
    `eqnarray` and `\\tag` where KaTeX accepts neither.

One flavor is rendered at a time, in place, and `literature/.collection.json`
records which. Nothing here is a source of truth: a render can be thrown away
and written again from `<slug>/text/` and the reference store.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from lit import blocks, cli, collection_index, paths, reference_store, update_references
from lit import write_index
from lit.paths import FLAVORS
from lit.arxiv_fetch import (
    ALIGNED_MATH_ENVIRONMENTS,
    BARE_MATH_ENVIRONMENTS,
    FIGURE_WIDTH_PX,
    ROW_NUMBERED_ENVIRONMENTS,
    sanitize_math,
    split_math_rows,
)
from lit.text import collapse_whitespace

# How long an alt attribute runs before it is cut. It repeats the caption, which
# sits under the image in full, so it exists for a reader who cannot see the
# image at all and not as a second copy of the text.
ALT_MAX_CHARS = 120

REF_TAG = re.compile(r"\[ref:\s*([^\]]*)\]")
INLINE_MATH = re.compile(r"(?<!\\)\$([^$]+)(?<!\\)\$")


# --------------------------------------------------------------------------
# the context one chapter is rendered against
# --------------------------------------------------------------------------


class Context:
    """What a chapter needs beyond its own blocks: the paper, and the store.

    `labels` maps a LaTeX label to the object it names, so `[ref: eq:ckmt]`
    becomes a link. `citations` maps a tag to the words a citation reads by, so
    `[cite: lipari_2002]` becomes one. `headings` maps an anchor to the heading
    text that carries it, which is the only fragment Obsidian resolves for a
    section.
    """

    def __init__(self, flavor: str, labels: dict, citations: dict, headings: dict,
                 references_prefix: str, current_stem: str = "") -> None:
        self.flavor = flavor
        self.labels = labels
        self.citations = citations
        self.headings = headings
        self.references_prefix = references_prefix
        self.current_stem = current_stem

    def fragment(self, anchor: str) -> str:
        """How a link names an anchor in this flavor."""
        if not anchor:
            return ""
        if self.flavor == "obsidian":
            heading = self.headings.get(anchor)
            if heading is not None:
                # Obsidian resolves a section by its heading text. A block ID is
                # not allowed on a heading, so this is the only address it has.
                return "#" + heading
            return "#^" + anchor
        return "#" + anchor


# --------------------------------------------------------------------------
# anchors
# --------------------------------------------------------------------------


def anchor_before(block: dict, flavor: str) -> str:
    """What goes above a block to give it its address, if anything."""
    anchor = block.get("anchor") or ""
    if not anchor or flavor != "vscode":
        return ""
    return '<a id="%s"></a>\n\n' % anchor


def anchor_after(block: dict, flavor: str) -> str:
    """What goes below a block to give it its address, if anything.

    Obsidian's block ID sits at the end of the block it names. It goes on the
    same line for a paragraph, and on the line under anything whose own syntax
    owns its last line — a fence, an HTML block, an image. A heading takes none
    at all: Obsidian rejects a block ID there and resolves the heading text
    instead.
    """
    anchor = block.get("anchor") or ""
    if not anchor or flavor != "obsidian" or block.get("kind") == "heading":
        return ""
    if block.get("kind") == "paragraph":
        return " ^%s" % anchor
    return "\n^%s" % anchor


# --------------------------------------------------------------------------
# the markers inside prose
# --------------------------------------------------------------------------


def resolve_citations(text: str, context: Context) -> str:
    """`[cite: tag]` becomes the link a reader follows to the work's page.

    A group of tags becomes one pair of parentheses. A tag no record answers
    leaves the whole marker standing: half-linking it would hide the one thing
    `litdb check-references` has to report.
    """

    def replace(match: re.Match) -> str:
        tags = [collapse_whitespace(tag) for tag in match.group(1).split(",")]
        tags = [tag for tag in tags if tag]
        if not tags or any(tag not in context.citations for tag in tags):
            return match.group(0)
        return "(%s)" % "; ".join(
            "[%s](%s/%s.md)" % (context.citations[tag], context.references_prefix, tag)
            for tag in tags
        )

    return reference_store.CITE_TAG.sub(replace, text)


def resolve_refs(text: str, context: Context, prefix: str = "") -> str:
    """`[ref: label]` becomes a link to the object the paper labelled.

    The link text is the number alone: the paper's prose already supplies the
    word and the brackets, so `eq.~(\\ref{eq:ckmt})` reads as `eq. ([5](#eq-5))`.
    A label with no target keeps its marker, which is how a reference the source
    never defined stays visible.
    """

    def replace(match: re.Match) -> str:
        label = collapse_whitespace(match.group(1))
        entry = context.labels.get(label)
        if not entry:
            return match.group(0)
        stem = entry.get("file") or ""
        same_file = stem == context.current_stem and not prefix
        target = "" if same_file else "%s%s.md" % (prefix, stem)
        return "[%s](%s%s)" % (
            entry.get("number", ""), target, context.fragment(entry.get("anchor", ""))
        )

    return REF_TAG.sub(replace, text)


def resolve_math(text: str, flavor: str) -> str:
    """Rewrite the inline maths of a prose block for the flavor's renderer.

    Both renderers need the same commands rewritten — neither KaTeX nor MathJax
    knows `\\alt` or `\\isotope`. They differ over environments and numbering,
    which is display maths and is handled where that is rendered.
    """
    return INLINE_MATH.sub(lambda m: "$%s$" % sanitize_math(m.group(1)), text)


def prose(text: str, context: Context, prefix: str = "") -> str:
    """One passage, with every marker in it resolved.

    `prefix` is what a cross-reference has to walk to reach the chapters. It is
    empty inside a chapter, where a link names a sibling file, and
    `../chapters/` in `FIGURES.md`, which is read one directory away.
    """
    return resolve_math(
        resolve_refs(resolve_citations(text, context), context, prefix),
        context.flavor,
    )


# --------------------------------------------------------------------------
# one block, per kind
# --------------------------------------------------------------------------


def render_math(block: dict, flavor: str) -> str:
    """A display-maths block, wrapped so the flavor's renderer draws it.

    The numbers were settled at ingest and are written back into the maths so
    the chapter reads as the paper does. KaTeX rejects `\\tag` inside an
    environment and has no `eqnarray`, so a row-numbered block gets `\\qquad (5)`
    per row and a re-wrapped `aligned` body. MathJax takes what the paper wrote.
    """
    name = block.get("env") or ""
    body = sanitize_math(block.get("tex") or "")
    numbers = block.get("numbers") or []

    if name in ROW_NUMBERED_ENVIRONMENTS and numbers:
        rows = split_math_rows(body)
        pieces = []
        for index, row in enumerate(rows):
            number = numbers[index] if index < len(numbers) else ""
            if number and row.strip():
                if flavor == "obsidian":
                    row = "%s \\tag{%s}" % (row.rstrip(), number)
                else:
                    row = "%s \\qquad (%s)" % (row.rstrip(), number)
            pieces.append(row)
        body = " \\\\ ".join(pieces)
        tag = ""
    else:
        # A single number sits outside the environment the body is wrapped in:
        # KaTeX rejects \tag inside one. The body is closed up first, so the
        # number stands at the end of the last row and not under it.
        tag = ""
        if numbers and numbers[0]:
            body = body.rstrip()
            tag = " \\tag{%s}" % numbers[0]

    if name in BARE_MATH_ENVIRONMENTS or not name:
        inner = body
    elif flavor == "vscode" and name in ALIGNED_MATH_ENVIRONMENTS:
        inner = "\\begin{aligned}%s\\end{aligned}" % body
    else:
        inner = "\\begin{%s}%s\\end{%s}" % (name, body, name)

    inner = re.sub(r"\n[ \t]*\n+", "\n", (inner + tag).strip("\n").strip())
    return "$$\n%s\n$$" % inner


def alt_text(caption: str) -> str:
    """What an image says to a reader who cannot see it.

    The maths reads as noise here and the caption below the image keeps it. A
    citation marker goes before the cut, because a tag cut in half leaves an
    unclosed bracket that the citation reader then runs past to the next `]`.
    """
    alt = re.sub(r"\$[^$]*\$", "", caption)
    alt = reference_store.CITE_TAG.sub("", alt)
    alt = REF_TAG.sub("", alt)
    alt = collapse_whitespace(re.sub(r'["\\<>|\[\]]', " ", alt))
    alt = re.sub(r"\s+([,.;:])", r"\1", alt).strip(" ,;:") or "figure"
    if len(alt) > ALT_MAX_CHARS:
        alt = alt[: ALT_MAX_CHARS - 3].rstrip() + "..."
    return alt


def render_figure(block: dict, context: Context, images_prefix: str = "../figures/") -> str:
    """An embedded figure with its caption beneath.

    Markdown's own image syntax cannot set a width and the figures are far too
    large at full size. VS Code's preview needs HTML for that; Obsidian sizes an
    image with `|500` inside the alt text, which is the shorter of the two and
    the one it documents.
    """
    caption = block.get("caption") or ""
    file_name = block.get("file") or ""
    alt = alt_text(caption)
    if context.flavor == "obsidian":
        image = "![%s|%d](%s%s)" % (alt, FIGURE_WIDTH_PX, images_prefix, file_name)
    else:
        image = (
            '<p align="center">\n'
            '<img src="%s%s" alt="%s" width="%d"/>\n'
            "</p>" % (images_prefix, file_name, alt, FIGURE_WIDTH_PX)
        )
    if caption:
        number = block.get("number") or ""
        image += "\n\n**Figure%s.** %s" % (
            " " + number if number else "", prose(caption, context)
        )
    return image


def render_table(block: dict, context: Context) -> str:
    """A table, kept as the TeX the paper wrote, with its caption beneath.

    Neither renderer draws LaTeX tabular material, and converting it would lose
    the multi-column and multi-row structure that carries the meaning. The fence
    keeps it readable and keeps it out of the prose.
    """
    out = "```tex\n%s\n```" % (block.get("tex") or "").strip("\n")
    caption = block.get("caption") or ""
    if caption:
        number = block.get("number") or ""
        out += "\n\n**Table%s.** %s" % (
            " " + number if number else "", prose(caption, context)
        )
    return out


def render_block(block: dict, context: Context) -> str:
    kind = block.get("kind")
    if kind == "paragraph":
        return prose(block.get("text") or "", context)
    if kind == "heading":
        number = block.get("number") or ""
        title = prose(block.get("title") or "", context)
        # A chapter reads "1. Introduction" and a subsection "1.1 Fitting",
        # which is how a paper prints its own headings.
        level = int(block.get("level") or 1)
        if number and level == 1:
            number += "."
        return "%s %s" % ("#" * level, ("%s %s" % (number, title)).strip())
    if kind == "math":
        return render_math(block, context.flavor)
    if kind == "figure":
        return render_figure(block, context)
    if kind == "table":
        return render_table(block, context)
    if kind == "code":
        return "```%s\n%s\n```" % (block.get("language") or "", block.get("text") or "")
    return block.get("text") or ""


def render_chapter(chapter_blocks: list[dict], context: Context) -> str:
    """One chapter file, as text."""
    out = []
    for block in chapter_blocks:
        body = render_block(block, context)
        if not body.strip():
            continue
        out.append(
            anchor_before(block, context.flavor)
            + body
            + anchor_after(block, context.flavor)
        )
    return "\n\n".join(out) + "\n"


# --------------------------------------------------------------------------
# one paper
# --------------------------------------------------------------------------


def headings_by_anchor(paper: dict, root: Path, slug: str) -> dict[str, str]:
    """The heading text each section anchor sits on, for Obsidian's fragments.

    Obsidian addresses a section by the words of its heading. The number is part
    of those words, since the heading is rendered with it.
    """
    found: dict[str, str] = {}
    for chapter in paper.get("chapters") or []:
        path = paths.text_path(root, slug, chapter.get("stem", ""))
        if not path.is_file():
            continue
        for block in blocks.read(path):
            if block.get("kind") == "heading" and block.get("anchor"):
                found[block["anchor"]] = collapse_whitespace(
                    "%s %s" % (block.get("number") or "", block.get("title") or "")
                )
    return found


def citation_texts(store: list[dict]) -> dict[str, str]:
    return {
        record["tag"]: update_references.citation_text(record)
        for record in store
        if record.get("tag")
    }


def render_figures_index(paper: dict, context: Context) -> str:
    """`figures/FIGURES.md`: one row per figure, with the chapter it sits in.

    It is read from beside the chapters directory, so its links carry that
    prefix rather than the one a chapter uses.
    """
    rows = [
        "| # | File | Label | Chapter | Caption |",
        "|---|---|---|---|---|",
    ]
    for figure in paper.get("figures") or []:
        stem = figure.get("chapter_stem") or ""
        anchor = figure.get("anchor") or ""
        where = ""
        if stem:
            where = "[%s](../chapters/%s.md%s)" % (
                figure.get("chapter") or stem, stem, context.fragment(anchor)
            )
        rows.append(
            "| %s | %s | %s | %s | %s |"
            % (
                figure.get("number") or "",
                figure.get("file") or "",
                figure.get("label") or "",
                where,
                update_references.escape(
                    prose(figure.get("caption") or "", context, "../chapters/")
                ),
            )
        )
    return "# Figures\n\n" + "\n".join(rows) + "\n"


def render_paper(root: Path, slug: str, flavor: str, store: list[dict],
                 out_root: Path | None = None) -> list[Path]:
    """Write every rendered file of one paper. Returns what it wrote."""
    out_root = out_root or root
    paper = paths.read_paper(root, slug)
    citations = citation_texts(store)
    headings = headings_by_anchor(paper, root, slug)

    written: list[Path] = []
    chapters_dir = out_root / slug / paths.CHAPTERS_DIR
    chapters_dir.mkdir(parents=True, exist_ok=True)

    for chapter in paper.get("chapters") or []:
        stem = chapter.get("stem") or ""
        source = paths.text_path(root, slug, stem)
        if not source.is_file():
            continue
        context = Context(
            flavor, paper.get("labels") or {}, citations, headings,
            "../../" + paths.RECORDS_DIR, stem,
        )
        target = chapters_dir / (stem + ".md")
        target.write_text(render_chapter(blocks.read(source), context), encoding="utf-8")
        written.append(target)

    index_context = Context(
        flavor, paper.get("labels") or {}, citations, headings,
        "../" + paths.RECORDS_DIR,
    )
    written.append(write_index.write(out_root / slug, paper, index_context))

    if paper.get("figures"):
        figures_context = Context(
            flavor, paper.get("labels") or {}, citations, headings,
            "../../" + paths.RECORDS_DIR,
        )
        figures_dir = out_root / slug / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)
        target = figures_dir / "FIGURES.md"
        target.write_text(render_figures_index(paper, figures_context), encoding="utf-8")
        written.append(target)

    return written


# --------------------------------------------------------------------------
# the whole collection
# --------------------------------------------------------------------------


def sweep(root: Path, slug: str, keep: set[Path]) -> list[Path]:
    """Delete the rendered files of a paper that this render did not write.

    A flavor change renames nothing, but a re-ingest that drops a chapter, or a
    paper whose figures went away, leaves a file behind that still reads as part
    of the paper. Only what a render writes is ever deleted: `text/`, the
    figures and `paper.json` are never touched.
    """
    dropped = []
    for path in sorted((root / slug).rglob("*.md")):
        if path in keep:
            continue
        path.unlink()
        dropped.append(path)
    return dropped


def render_collection(root: Path, flavor: str, out_root: Path | None = None) -> dict:
    """Render every paper, the reference views and the collection index."""
    store = reference_store.load(root)
    slugs = paths.papers_on_disk(root)

    papers = []
    for slug in slugs:
        written = render_paper(root, slug, flavor, store, out_root)
        dropped = []
        if out_root is None:
            dropped = sweep(root, slug, set(written))
        papers.append(
            {"slug": slug, "files": len(written), "dropped": [str(p) for p in dropped]}
        )

    target_root = out_root or root
    update_references.render_views(target_root, store)
    for slug in slugs:
        paper = paths.read_paper(root, slug)
        row = dict(paper, slug=slug)
        collection_index.add_row(
            target_root, row,
            collection_index.first_sentence(paper.get("abstract") or ""),
        )

    return {"flavor": flavor, "papers": papers, "root": str(target_root)}


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = cli.parser(__doc__)
    cli.add_root_argument(parser)
    parser.add_argument(
        "--flavor",
        choices=FLAVORS,
        help="the flavor to render, and to record as the collection's own; "
        "without it the recorded flavor is used",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="write the render below this directory instead of in place; "
        "records nothing and deletes nothing",
    )
    parser.add_argument(
        "--reports",
        type=Path,
        default=Path("reports"),
        help="where the reports are, so a flavor change re-renders them too",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = cli.parse(build_parser(), argv)
    root = args.literature_root
    if not root.is_dir():
        cli.emit({"error": "%s is not a collection" % root})
        return cli.JUDGEMENT

    flavor = args.flavor or paths.flavor(root)
    report = render_collection(root, flavor, args.out)

    if args.out is None:
        paths.set_flavor(root, flavor)
        from lit import render_report

        report["reports"] = render_report.render_directory(args.reports, root, flavor)

    cli.emit(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
