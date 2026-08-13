#!/usr/bin/env python3
"""Write a paper's INDEX.md from its manifest and the files on disk.

`INDEX.md` is what an agent reads before it decides whether to open a chapter.
Everything in it above the chapter table is a fact the manifest already holds,
and every column of that table is a count of the file itself. All of it is
written here, so no agent spends context reading a paper to restate what a
script can measure.

Two numbers describe each chapter:

  * **Words** says where the substance of the paper is. A chapter of 200 words
    is a page of definitions; one of 4000 is the argument.
  * **Named anchors** counts the `sec-`, `eq-`, `fig-` and `tab-` anchors, and
    leaves the `pN` paragraph anchors out. Ingest writes a paragraph anchor
    above every long paragraph, so counting those would count the paragraphs and
    rise with the word count beside it. A count of the named anchors separates a
    chapter that labels its equations and figures from a chapter of plain prose,
    and that is the difference a reader deciding where to cite from needs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lit import text
from lit.text import EMPTY, collapse_whitespace, escape_cell as escape

MANIFEST_NAME = ".ingest-manifest.json"
INDEX_NAME = "INDEX.md"

# How many subsection titles one chapter row lists. A higher value says more
# about a long chapter, and makes the table harder to read.
INDEX_SUBSECTIONS_SHOWN = 6

# How many authors the identity table names before "et al.".
AUTHORS_SHOWN = 3

# The anchors that name something the paper labelled. `pN` is deliberately not
# here: it addresses a paragraph, and every long paragraph has one.
NAMED_ANCHOR = re.compile(r'<a id="((?:sec|eq|fig|tab)-[^"]*)"></a>')

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


def measure(path: Path) -> dict:
    """The counts of one chapter file. A file that is not there counts zero.

    `errors="replace"` rather than a failure: a chapter holding a byte no
    decoder answers is still a chapter, and `check_references.py` is what
    reports it.
    """
    if not path.is_file():
        return {"words": 0, "named_anchors": 0, "bytes": 0}
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    return {
        "words": len(text.split()),
        "named_anchors": len(NAMED_ANCHOR.findall(text)),
        "bytes": len(raw),
    }


def chapter_rows(manifest: dict, paper_dir: Path) -> list[dict]:
    """One entry per chapter: what the manifest says, plus what the file says."""
    rows = []
    for chapter in manifest.get("chapters") or []:
        entry = {
            "file": chapter.get("file", ""),
            "number": chapter.get("number", ""),
            "title": chapter.get("title", ""),
            "subsections": chapter.get("subsections") or [],
        }
        entry.update(measure(paper_dir / "chapters" / entry["file"]))
        rows.append(entry)
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


def render(manifest: dict) -> str:
    """The whole of `INDEX.md`, as text."""
    paper_dir = Path(manifest.get("paper_dir") or ".")
    rows = chapter_rows(manifest, paper_dir)

    lines = ["# %s" % collapse_whitespace(manifest.get("title") or manifest.get("slug") or ""), ""]
    lines += ["| Field | Value |", "|---|---|"]
    lines += ["| %s | %s |" % row for row in identity_rows(manifest)]
    lines += ["", "## Abstract", ""]
    lines += [collapse_whitespace(manifest.get("abstract") or "") or
              "The source carried no abstract.", ""]

    lines += ["## Chapters", ""]
    lines += ["| # | File | Words | Named anchors | Subsections |",
              "|---|---|---|---|---|"]
    for row in rows:
        lines.append("| %s | [%s](chapters/%s) | %d | %d | %s |" % (
            escape(row["number"]),
            escape(row["file"]),
            row["file"],
            row["words"],
            row["named_anchors"],
            show_subsections(row["subsections"]),
        ))
    lines.append("")
    lines.append("%d chapters, %d words." % (
        len(rows), sum(row["words"] for row in rows)
    ))
    lines.append("")

    figures = manifest.get("figures") or []
    lines += ["## Figures", ""]
    if figures:
        lines.append("%d figures. See [figures/FIGURES.md](figures/FIGURES.md) for "
                     "the captions." % len(figures))
    else:
        lines.append("This paper carries no figure.")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# the manifest, and the file
# --------------------------------------------------------------------------


def load_manifest(paper_dir: Path) -> dict:
    path = paper_dir / MANIFEST_NAME
    if not path.is_file():
        raise RuntimeError(
            "%s holds no %s. Fetch the paper again with --force."
            % (paper_dir, MANIFEST_NAME)
        )
    return json.loads(path.read_text(encoding="utf-8"))


def write(paper_dir: Path, manifest: dict) -> Path:
    """Write `INDEX.md`. Every value in it is derived, so a rebuild is safe."""
    index_path = paper_dir / INDEX_NAME
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(render(manifest), encoding="utf-8")
    return index_path
