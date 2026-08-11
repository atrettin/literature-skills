#!/usr/bin/env python3
"""Write a paper's INDEX.md from its manifest and the files on disk.

`INDEX.md` is what an agent reads before it decides whether to open a chapter.
Everything in it above the chapter table is a fact the manifest already holds,
and every column of that table but the last is a count of the file itself. All
of it is written here, so no agent spends context reading a paper to restate
what a script can measure.

Two numbers describe each chapter:

  * **Words** says where the substance of the paper is. A chapter of 200 words
    is a page of definitions; one of 4000 is the argument.
  * **Named anchors** counts the `sec-`, `eq-`, `fig-` and `tab-` anchors, and
    leaves the `pN` paragraph anchors out. Ingest writes a paragraph anchor
    above every long paragraph, so counting those would count the paragraphs and
    rise with the word count beside it. A count of the named anchors separates a
    chapter that labels its equations and figures from a chapter of plain prose,
    and that is the difference a reader deciding where to cite from needs.

The last column, **What it covers**, holds `—` until somebody writes it. That
pass is opt-in, and `add_paper.py --summarize <slug>` runs it. A summary earns
its cost when somebody returns to the collection, and it earns nothing at ingest
for a paper that nobody ever cites.

Usage:
    write_index.py literature/<slug>
    write_index.py literature/<slug> --summaries summaries.json --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arxiv_search import collapse_whitespace  # noqa: E402

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

# A row of the chapter table, as this script writes it. Reading it back is how
# a rebuild keeps a summary somebody already wrote.
CHAPTER_ROW = re.compile(r"^\|[^|]*\|\s*\[([^\]]+)\]\([^)]*\)\s*\|(.*)\|\s*$")

# What a cell holds when nothing has filled it in.
EMPTY = "—"

# A cross-reference the conversion could not resolve keeps this marker. A
# subsection title can carry one, usually inside its own brackets, as
# "Challenges (Section [ref: expt_motive])". The first pattern takes the
# brackets with it, and the second takes a bare marker.
REF_IN_BRACKETS = re.compile(
    r"\s*\(\s*(?:Section|Sec\.?|Chapter|Chap\.?|Figure|Fig\.?|Table|Tab\.?"
    r"|Equation|Eq\.?)?\s*\[ref:[^\]]*\]\s*\)"
)
REF_MARKER = re.compile(r"\s*\[ref:[^\]]*\]")


def escape(text: str) -> str:
    """Make a value safe to sit in a Markdown table cell.

    Only the pipe has to go: it splits the row into further columns, and every
    cell after it then sits under the wrong heading.
    """
    return collapse_whitespace(str(text or "")).replace("|", "\\|")


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


def show_authors(authors: list[str]) -> str:
    names = [collapse_whitespace(name) for name in authors or [] if collapse_whitespace(name)]
    if not names:
        return EMPTY
    if len(names) > AUTHORS_SHOWN:
        return escape(", ".join(names[:AUTHORS_SHOWN]) + " et al.")
    return escape(", ".join(names))


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
        ("Authors", show_authors(manifest.get("authors") or [])),
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


def render(manifest: dict, summaries: dict[str, str] | None = None) -> str:
    """The whole of `INDEX.md`, as text.

    `summaries` maps a chapter file name to what it covers. A chapter with no
    entry gets `—`, which is what says the summary pass has not run for it.
    """
    summaries = summaries or {}
    paper_dir = Path(manifest.get("paper_dir") or ".")
    rows = chapter_rows(manifest, paper_dir)

    lines = ["# %s" % collapse_whitespace(manifest.get("title") or manifest.get("slug") or ""), ""]
    lines += ["| Field | Value |", "|---|---|"]
    lines += ["| %s | %s |" % row for row in identity_rows(manifest)]
    lines += ["", "## Abstract", ""]
    lines += [collapse_whitespace(manifest.get("abstract") or "") or
              "The source carried no abstract.", ""]

    lines += ["## Chapters", ""]
    lines += ["| # | File | Words | Named anchors | Subsections | What it covers |",
              "|---|---|---|---|---|---|"]
    for row in rows:
        lines.append("| %s | [%s](chapters/%s) | %d | %d | %s | %s |" % (
            escape(row["number"]),
            escape(row["file"]),
            row["file"],
            row["words"],
            row["named_anchors"],
            show_subsections(row["subsections"]),
            escape(summaries.get(row["file"], "")) or EMPTY,
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
# reading back what somebody wrote
# --------------------------------------------------------------------------


def read_summaries(index_path: Path) -> dict[str, str]:
    """The `What it covers` cell of each chapter row already on disk.

    A rebuild recomputes every count and keeps every summary. Nothing else in
    the file survives, because everything else is derived.
    """
    if not index_path.is_file():
        return {}
    found: dict[str, str] = {}
    for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = CHAPTER_ROW.match(line)
        if not match:
            continue
        # An escaped pipe is a character of the summary, not a column break.
        # Splitting on it would cut the summary at the first one, and a rebuild
        # would then write back less than the file already held.
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", match.group(2))]
        summary = cells[-1] if cells else ""
        if summary and summary != EMPTY:
            # Unescaped, because `escape` puts the backslash back when the row
            # is written again. Without this a rebuild doubles it each time.
            found[match.group(1).strip()] = summary.replace("\\|", "|")
    return found


def pending(index_path: Path, manifest: dict) -> list[dict]:
    """The chapters whose summary is still `—`, for the summary pass to write."""
    written = read_summaries(index_path)
    return [
        {"file": chapter.get("file", ""), "title": chapter.get("title", "")}
        for chapter in manifest.get("chapters") or []
        if chapter.get("file") not in written
    ]


def load_manifest(paper_dir: Path) -> dict:
    path = paper_dir / MANIFEST_NAME
    if not path.is_file():
        raise RuntimeError(
            "%s holds no %s; the paper was ingested before the manifest was kept, "
            "or by hand. Fetch it again with --force." % (paper_dir, MANIFEST_NAME)
        )
    return json.loads(path.read_text(encoding="utf-8"))


def write(paper_dir: Path, manifest: dict, summaries: dict[str, str] | None = None) -> Path:
    """Write `INDEX.md`, keeping every summary the file already holds."""
    index_path = paper_dir / INDEX_NAME
    kept = read_summaries(index_path)
    kept.update(summaries or {})
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(render(manifest, kept), encoding="utf-8")
    return index_path


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("paper_dir", type=Path, help="the directory of one paper")
    parser.add_argument(
        "--summaries",
        type=Path,
        help='JSON mapping a chapter file name to what it covers, for --apply',
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the summaries of --summaries into the file",
    )
    parser.add_argument(
        "--pending",
        action="store_true",
        help="print the chapters whose summary is still empty, and write nothing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        manifest = load_manifest(args.paper_dir)
    except (RuntimeError, ValueError) as error:
        print(json.dumps({"error": str(error)}, indent=2))
        return 1

    if args.pending:
        print(json.dumps({
            "slug": manifest.get("slug", ""),
            "index": str(args.paper_dir / INDEX_NAME),
            "pending": pending(args.paper_dir / INDEX_NAME, manifest),
        }, indent=2, ensure_ascii=False))
        return 0

    summaries: dict[str, str] = {}
    if args.apply:
        if not args.summaries:
            print(json.dumps({"error": "--apply needs --summaries"}, indent=2))
            return 1
        summaries = json.loads(args.summaries.read_text(encoding="utf-8"))

    index_path = write(args.paper_dir, manifest, summaries)
    print(json.dumps({
        "slug": manifest.get("slug", ""),
        "index": str(index_path),
        "chapters": len(manifest.get("chapters") or []),
        "summaries_written": len(summaries),
        "pending": len(pending(index_path, manifest)),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
