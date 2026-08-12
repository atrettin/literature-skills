"""Where a figure row of `FIGURES.md` sends the reader.

A row names a chapter file and an anchor in it. The two have to agree: a link
to a file that does not carry the anchor lands the reader at the top of some
other part of the paper, with nothing to say the target was missed.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

import arxiv_fetch


def chapter(file: str, title: str, text: str) -> dict:
    return {"file": file, "title": title, "text": text, "subsections": []}


def numbering_for(chapter_title: str, labels: dict[str, str]) -> arxiv_fetch.Numbering:
    """A numbering that registered each label of `labels` in one chapter."""
    numbering = arxiv_fetch.Numbering()
    numbering.start_chapter(1, chapter_title)
    for label, kind in labels.items():
        numbering.register(label, kind, numbering.next_number(kind))
    return numbering


def test_a_figure_in_a_later_piece_of_a_split_chapter() -> None:
    """The anchor decides the file, not the title of the chapter.

    A chapter too long for one file is written as several, all carrying the
    same section title. A figure in the second half has its anchor there, and
    the first piece holds nothing to jump to.
    """
    title = "Neutrinos in Cosmology"
    numbering = numbering_for(title, {"fig:neff": "figure"})
    anchor = numbering.labels["fig:neff"]["anchor"]
    chapters = [
        chapter("14-01_opening.md", "%s \u2014 Opening" % title, "Nothing to see."),
        chapter(
            "14-02_observables.md",
            "%s \u2014 Observables" % title,
            '<a id="%s"></a>\n\nThe figure.' % anchor,
        ),
    ]
    records = [{"label": "fig:neff", "chapter": title, "caption": ""}]

    arxiv_fetch.apply_ref_links(chapters, numbering)
    arxiv_fetch.apply_figure_targets(records, chapters, numbering)

    assert records[0]["chapter_file"] == "14-02_observables.md"
    assert records[0]["anchor"] == anchor
    text = {one["file"]: one["text"] for one in chapters}[records[0]["chapter_file"]]
    assert '<a id="%s"></a>' % records[0]["anchor"] in text


def test_a_figure_in_a_chapter_of_one_file() -> None:
    title = "The Reactor Anomaly"
    numbering = numbering_for(title, {"fig:raa": "figure"})
    anchor = numbering.labels["fig:raa"]["anchor"]
    chapters = [chapter("04_the_reactor_anomaly.md", title, '<a id="%s"></a>' % anchor)]
    records = [{"label": "fig:raa", "chapter": title, "caption": ""}]

    arxiv_fetch.apply_ref_links(chapters, numbering)
    arxiv_fetch.apply_figure_targets(records, chapters, numbering)

    assert records[0]["chapter_file"] == "04_the_reactor_anomaly.md"
    assert records[0]["anchor"] == anchor


def test_a_figure_whose_label_names_nothing_falls_back_to_the_chapter() -> None:
    """A record with no label still names the chapter it was found in.

    The row then links the file and no anchor, which opens the chapter at its
    top. That is where a reader looks for a figure the numbering never saw.
    """
    title = "Standard Cosmology"
    numbering = numbering_for(title, {})
    chapters = [chapter("13_standard_cosmology.md", title, "Text of the chapter.")]
    records = [{"label": "", "chapter": title, "caption": ""}]

    arxiv_fetch.apply_figure_targets(records, chapters, numbering)

    assert records[0]["chapter_file"] == "13_standard_cosmology.md"
    assert records[0]["anchor"] == ""


def test_a_label_whose_anchor_reached_no_chapter_falls_back_to_the_chapter() -> None:
    """A label the conversion numbered and then dropped from the text.

    `apply_ref_links` answers such a label with the first file of the chapter
    it was numbered in, and the figure row follows it there.
    """
    title = "Standard Leptogenesis"
    numbering = numbering_for(title, {"fig:lepto": "figure"})
    chapters = [chapter("18_standard_leptogenesis.md", title, "No anchor in here.")]
    records = [{"label": "fig:lepto", "chapter": title, "caption": ""}]

    arxiv_fetch.apply_ref_links(chapters, numbering)
    arxiv_fetch.apply_figure_targets(records, chapters, numbering)

    assert records[0]["chapter_file"] == "18_standard_leptogenesis.md"


def test_a_caption_links_a_reference_across_the_chapters_directory() -> None:
    """The caption is read one directory away from the chapters."""
    title = "Neutrinos in Cosmology"
    numbering = numbering_for(title, {"fig:neff": "figure", "eq:rate": "equation"})
    anchors = {label: entry["anchor"] for label, entry in numbering.labels.items()}
    chapters = [
        chapter("14-01_opening.md", "%s \u2014 Opening" % title, "Nothing to see."),
        chapter(
            "14-02_observables.md",
            "%s \u2014 Observables" % title,
            '<a id="%s"></a>\n<a id="%s"></a>'
            % (anchors["fig:neff"], anchors["eq:rate"]),
        ),
    ]
    records = [
        {
            "label": "fig:neff",
            "chapter": title,
            "caption": "The rate of [ref: eq:rate] against the data.",
        }
    ]

    arxiv_fetch.apply_ref_links(chapters, numbering)
    arxiv_fetch.apply_figure_targets(records, chapters, numbering)

    assert (
        "(../chapters/14-02_observables.md#%s)" % anchors["eq:rate"]
        in records[0]["caption"]
    )


# --------------------------------------------------------------------------
# the whole conversion, against a source built for the split
# --------------------------------------------------------------------------

FILLER = "The chapter says the same thing again and again to make it long. "

SOURCE = r"""\documentclass{article}
\begin{document}
\title{Neutrinos in Cosmology}
\begin{abstract}
A paper whose one section is too long for a single file.
\end{abstract}

\section{Neutrinos in Cosmology}
\label{sec:cosmology}
\subsection{Opening}
FILLER_TEXT

\subsection{Observables}
FILLER_TEXT
\begin{figure}
\includegraphics{fig1.png}
\caption{The effective number of neutrino species against the multipole.}
\label{fig:neff}
\end{figure}
Figure~\ref{fig:neff} shows the effect.

\end{document}
""".replace("FILLER_TEXT", FILLER * 20)

# A 1x1 PNG. The conversion copies a PNG as it stands, so nothing here needs an
# image tool to be installed.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)


def convert_the_split_paper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the conversion over a source of one long section. Returns its dir."""
    source_dir = tmp_path / "tex"
    source_dir.mkdir()
    (source_dir / "main.tex").write_text(SOURCE, encoding="utf-8")
    (source_dir / "fig1.png").write_bytes(PNG)

    monkeypatch.setattr(
        arxiv_fetch,
        "fetch_metadata_by_id",
        lambda arxiv_id: {
            "arxiv_id": arxiv_id,
            "version": "v1",
            "title": "Neutrinos in Cosmology",
            "authors": ["Ada Lovelace"],
            "year": 2025,
            "published": "2025-01-02T00:00:00Z",
            "summary": "A paper whose one section is too long for a single file.",
            "doi": "",
            "journal_ref": "",
            "comment": "",
            "pdf_url": "",
            "abs_url": "https://arxiv.org/abs/%s" % arxiv_id,
        },
    )
    monkeypatch.setattr(
        arxiv_fetch, "download_source", lambda arxiv_id, work_dir: source_dir
    )

    root = tmp_path / "collection"
    root.mkdir()
    arguments = [
        "2501.00002",
        "--slug", "lovelace_2025_neutrinos_in_cosmology",
        "--literature-root", str(root),
        "--max-chapter-bytes", "900",
        "--no-inspire",
        "--no-references",
    ]
    arxiv_fetch.convert(arxiv_fetch.build_parser().parse_args(arguments))
    return root / "lovelace_2025_neutrinos_in_cosmology"


CHAPTER_LINK = re.compile(r"\]\(\.\./chapters/([^)#\s]+)#([^)\s]+)\)")


def test_every_figure_row_links_a_file_that_holds_its_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate_off: None
) -> None:
    """The end of the pipeline, over a section that the length split.

    The figure sits in the second half of the one section of this paper, so
    the file its row names is a later piece and not the first one.
    """
    paper_dir = convert_the_split_paper(tmp_path, monkeypatch)
    rows = [
        line
        for line in (paper_dir / "figures" / "FIGURES.md").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.startswith("| ") and "../chapters/" in line
    ]
    assert rows, "the paper wrote no figure row with a chapter link"

    pieces = sorted(path.name for path in (paper_dir / "chapters").glob("*.md"))
    assert len(pieces) > 1, "the section was not split, so nothing here is tested"

    for row in rows:
        found = CHAPTER_LINK.search(row)
        assert found is not None
        target = paper_dir / "chapters" / found.group(1)
        assert target.is_file(), "%s names a file that is not there" % row
        assert '<a id="%s"></a>' % found.group(2) in target.read_text(encoding="utf-8")

    # The figure is in a later piece, which is what makes this a test: the
    # title of the section alone would send the reader to the first one.
    first = CHAPTER_LINK.search(rows[0])
    assert first is not None
    assert first.group(1) != pieces[0]
