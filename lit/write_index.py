#!/usr/bin/env python3
"""Render a paper's INDEX.md from what the collection stores about it.

`INDEX.md` is what a person reads before deciding whether to open a chapter, and
every number in it was counted when the paper was ingested and written into
`paper.json`. Nothing here reads a chapter to restate what is already known.

Two numbers describe each chapter:

  * **Words** says where the substance of the paper is. A chapter of 200 words
    is a page of definitions; one of 4000 is the argument. Maths and the raw TeX
    of a table are not words; a caption is.
  * **Named anchors** counts the `sec-`, `eq-`, `fig-` and `tab-` anchors, and
    leaves the `pN` paragraph anchors out. Every long paragraph carries one, so
    counting those would count the paragraphs and rise with the word count
    beside it. A count of the named anchors separates a chapter that labels its
    equations and figures from a chapter of plain prose, and that is the
    difference a reader deciding where to cite from needs.
"""

from __future__ import annotations

import re
from pathlib import Path

from lit import text
from lit.text import EMPTY, collapse_whitespace, escape_cell as escape

INDEX_NAME = "INDEX.md"

# How many subsection titles one chapter row lists. A higher value says more
# about a long chapter, and makes the table harder to read.
INDEX_SUBSECTIONS_SHOWN = 6

# How many authors the identity table names before "et al.".
AUTHORS_SHOWN = 3

# The anchors that name something the paper labelled. `pN` is deliberately not
# here: it addresses a paragraph, and every long paragraph has one.
NAMED_ANCHOR = re.compile(r"\A(?:sec|eq|fig|tab)-")

# A cross-reference the conversion could not resolve keeps this marker. A
# subsection title can carry one, usually inside its own brackets, as
# "Challenges (Section [ref: expt_motive])". The first pattern takes the
# brackets with it, and the second takes a bare marker.
REF_IN_BRACKETS = re.compile(
    r"\s*\(\s*(?:Section|Sec\.?|Chapter|Chap\.?|Figure|Fig\.?|Table|Tab\.?"
    r"|Equation|Eq\.?)?\s*\[ref:[^\]]*\]\s*\)"
)
REF_MARKER = re.compile(r"\s*\[ref:[^\]]*\]")


# --------------------------------------------------------------------------
# measuring a chapter
# --------------------------------------------------------------------------


def chapter_rows(paper: dict) -> list[dict]:
    """One entry per chapter, all of it counted when the paper was stored."""
    rows = []
    for chapter in paper.get("chapters") or []:
        anchors = chapter.get("anchors") or []
        rows.append(
            {
                "stem": chapter.get("stem", ""),
                "number": chapter.get("number", ""),
                "title": chapter.get("title", ""),
                "subsections": chapter.get("subsections") or [],
                "words": chapter.get("words", 0),
                "named_anchors": len([a for a in anchors if NAMED_ANCHOR.match(a)]),
            }
        )
    return rows


def plain_title(title: str) -> str:
    """A subsection title with no cross-reference marker left in it.

    A heading of the source can refer to another section, and a reference the
    conversion could not resolve keeps its `[ref: label]` marker. That marker
    addresses a label of the TeX source, which is nothing `INDEX.md` can reach,
    so carrying it here would put a reference that leads nowhere into a file
    that had none. The words of the title are what names the subsection.
    """
    return collapse_whitespace(REF_MARKER.sub("", REF_IN_BRACKETS.sub("", title)))


def show_subsections(titles: list[str]) -> str:
    shown = [plain_title(title) for title in titles]
    shown = [title for title in shown if title]
    if not shown:
        return EMPTY
    text = "; ".join(escape(title) for title in shown[:INDEX_SUBSECTIONS_SHOWN])
    if len(shown) > INDEX_SUBSECTIONS_SHOWN:
        text += " …"
    return text


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def identity_rows(manifest: dict) -> list[tuple[str, str]]:
    """The two-column table at the top: what this paper is.

    `Submitted` and `Published` answer different questions and are both written
    even when they agree. `Submitted` is the arXiv date and always has a value;
    a paper INSPIRE reports no publication for is a preprint, and says so.
    """
    publication = manifest.get("publication") or {}
    doi = collapse_whitespace(publication.get("doi") or manifest.get("doi") or "")
    arxiv_id = collapse_whitespace(manifest.get("arxiv_id") or "")
    published = publication.get("published_year")

    rows = [
        ("Authors", text.display_authors(manifest.get("authors") or [],
                                        AUTHORS_SHOWN, initials=False)),
        ("Submitted", str(manifest.get("submitted_year") or EMPTY)),
        ("Published", str(published) if published else "preprint"),
        ("Journal", escape(publication.get("journal") or "") or EMPTY),
    ]
    errata = [entry for entry in publication.get("errata") or [] if collapse_whitespace(entry)]
    if errata:
        # Directly beneath Journal: an erratum is published separately from the
        # paper it corrects, and it is not the paper's own reference.
        rows.append(("Erratum", "<br>".join(escape(entry) for entry in errata)))
    rows += [
        ("DOI", "[%s](https://doi.org/%s)" % (escape(doi), doi) if doi else EMPTY),
        ("arXiv", "[%s](https://arxiv.org/abs/%s)" % (escape(arxiv_id), arxiv_id)
         if arxiv_id else EMPTY),
        ("Ingested", escape(manifest.get("ingested") or "")),
        ("Parser", escape(manifest.get("parser") or "")),
    ]
    return rows


def render(paper: dict, context=None) -> str:
    """The whole of `INDEX.md`, as text.

    `context` carries the flavor and the reference store, so the abstract's own
    citations resolve. Without one the abstract is written as it is stored,
    which is what a caller wanting the facts and not the links gets.
    """
    from lit import render as render_module

    rows = chapter_rows(paper)
    abstract = collapse_whitespace(paper.get("abstract") or "")
    if context is not None and abstract:
        abstract = render_module.prose(abstract, context)

    lines = ["# %s" % collapse_whitespace(paper.get("title") or paper.get("slug") or ""), ""]
    lines += ["| Field | Value |", "|---|---|"]
    lines += ["| %s | %s |" % row for row in identity_rows(paper)]
    lines += ["", "## Abstract", ""]
    lines += [abstract or "The source carried no abstract.", ""]

    lines += ["## Chapters", ""]
    lines += ["| # | File | Words | Named anchors | Subsections |",
              "|---|---|---|---|---|"]
    for row in rows:
        name = row["stem"] + ".md"
        lines.append("| %s | [%s](chapters/%s) | %d | %d | %s |" % (
            escape(row["number"]),
            escape(name),
            name,
            row["words"],
            row["named_anchors"],
            show_subsections(row["subsections"]),
        ))
    lines.append("")
    lines.append("%d chapters, %d words." % (
        len(rows), sum(row["words"] for row in rows)
    ))
    lines.append("")

    figures = paper.get("figures") or []
    lines += ["## Figures", ""]
    if figures:
        lines.append("%d figures. See [figures/FIGURES.md](figures/FIGURES.md) for "
                     "the captions." % len(figures))
    else:
        lines.append("This paper carries no figure.")
    lines.append("")
    return "\n".join(lines)


def write(paper_dir: Path, paper: dict, context=None) -> Path:
    """Write `INDEX.md`. Every value in it is derived, so a rebuild is safe."""
    index_path = paper_dir / INDEX_NAME
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(render(paper, context), encoding="utf-8")
    return index_path
