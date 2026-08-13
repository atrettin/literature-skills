"""What `INDEX.md` says about a paper, and what it counts."""

from __future__ import annotations

import re
from pathlib import Path

from lit import write_index

CHAPTER = """# 2. Introduction

<a id="sec-introduction"></a>

<a id="p1"></a>
The first paragraph of prose, which carries eight words here.

<a id="eq-model"></a>

$$\\sigma = A E^2 \\tag{1}$$

<a id="p2"></a>
The second paragraph.

<a id="fig-xsec"></a>
<a id="tab-values"></a>
"""


def manifest_for(paper_dir: Path, **overrides) -> dict:
    base = {
        "arxiv_id": "2501.00001",
        "slug": paper_dir.name,
        "paper_dir": str(paper_dir),
        "title": "A Small Paper on Quasielastic Scattering",
        "authors": ["Ada Lovelace", "Grace Hopper"],
        "submitted_year": 2025,
        "abstract": "This paper measures a cross section.",
        "ingested": "2026-08-11",
        "parser": "texsoup",
        "publication": {"source": "none", "journal": "", "published_year": None,
                        "doi": "", "errata": [], "inspire_url": ""},
        "chapters": [
            {"file": "02_introduction.md", "number": "2", "title": "Introduction",
             "subsections": ["Fitting"]},
        ],
        "figures": [{"file": "fig1.png"}],
    }
    base.update(overrides)
    return base


def build(tmp_path: Path, text: str = CHAPTER, **overrides) -> tuple[Path, dict]:
    paper_dir = tmp_path / "lovelace_2025_small_paper"
    (paper_dir / "chapters").mkdir(parents=True)
    (paper_dir / "chapters" / "02_introduction.md").write_text(text, encoding="utf-8")
    return paper_dir, manifest_for(paper_dir, **overrides)


def chapter_row(text: str) -> list[str]:
    """The cells of the chapter row. An escaped pipe stays inside its cell."""
    line = next(line for line in text.splitlines() if line.startswith("| 2 |"))
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip("|"))]


# --------------------------------------------------------------------------
# the counts
# --------------------------------------------------------------------------


def test_the_word_count_counts_the_file(tmp_path: Path) -> None:
    paper_dir, manifest = build(tmp_path)

    row = chapter_row(write_index.render(manifest))

    assert int(row[2]) == len(CHAPTER.split())


def test_paragraph_anchors_are_not_named_anchors(tmp_path: Path) -> None:
    """`pN` counts the paragraphs, which the word count beside it already says."""
    paper_dir, manifest = build(tmp_path)

    row = chapter_row(write_index.render(manifest))

    # sec-introduction, eq-model, fig-xsec, tab-values. Not p1, not p2.
    assert int(row[3]) == 4


def test_a_chapter_of_plain_prose_names_nothing(tmp_path: Path) -> None:
    plain = '# 2. Introduction\n\n<a id="p1"></a>\nJust prose, and more of it.\n'
    paper_dir, manifest = build(tmp_path, text=plain)

    row = chapter_row(write_index.render(manifest))

    assert int(row[3]) == 0


def test_a_missing_file_counts_zero(tmp_path: Path) -> None:
    paper_dir, manifest = build(tmp_path)
    (paper_dir / "chapters" / "02_introduction.md").unlink()

    row = chapter_row(write_index.render(manifest))

    assert int(row[2]) == 0


def test_subsections_are_cut_at_the_limit(tmp_path: Path) -> None:
    many = ["Section %d" % number for number in range(write_index.INDEX_SUBSECTIONS_SHOWN + 3)]
    paper_dir, manifest = build(tmp_path)
    manifest["chapters"][0]["subsections"] = many

    row = chapter_row(write_index.render(manifest))

    assert row[4].endswith("…")
    assert row[4].count(";") == write_index.INDEX_SUBSECTIONS_SHOWN - 1


# --------------------------------------------------------------------------
# the identity table
# --------------------------------------------------------------------------


def test_a_preprint_says_preprint_and_two_dashes(tmp_path: Path) -> None:
    paper_dir, manifest = build(tmp_path)

    text = write_index.render(manifest)

    assert "| Published | preprint |" in text
    assert "| Journal | — |" in text
    assert "| DOI | — |" in text


def test_a_published_paper_says_where(tmp_path: Path) -> None:
    paper_dir, manifest = build(tmp_path, publication={
        "source": "inspire", "journal": "Phys.Rev.D 108 (2023) 113010",
        "published_year": 2023, "doi": "10.1103/PhysRevD.108.113010",
        "errata": [], "inspire_url": "",
    })

    text = write_index.render(manifest)

    assert "| Published | 2023 |" in text
    assert "| Journal | Phys.Rev.D 108 (2023) 113010 |" in text
    assert "https://doi.org/10.1103/PhysRevD.108.113010" in text


def test_an_erratum_gets_its_own_row_under_journal(tmp_path: Path) -> None:
    paper_dir, manifest = build(tmp_path, publication={
        "source": "inspire", "journal": "Phys.Rev.D 108 (2023) 113010",
        "published_year": 2023, "doi": "", "errata": ["Phys.Rev.D 109 (2024) 019902"],
        "inspire_url": "",
    })

    lines = write_index.render(manifest).splitlines()
    journal = next(number for number, line in enumerate(lines) if line.startswith("| Journal |"))

    assert lines[journal + 1].startswith("| Erratum |")
    assert "Phys.Rev.D 109 (2024) 019902" in lines[journal + 1]


def test_more_than_three_authors_become_et_al(tmp_path: Path) -> None:
    paper_dir, manifest = build(tmp_path, authors=["A One", "B Two", "C Three", "D Four"])

    assert "| Authors | A One, B Two, C Three et al. |" in write_index.render(manifest)


# --------------------------------------------------------------------------
# the subsection titles
# --------------------------------------------------------------------------


def test_a_subsection_title_carries_no_reference_marker(tmp_path: Path) -> None:
    """A `[ref: …]` addresses a label of the TeX. `INDEX.md` cannot reach one."""
    paper_dir, manifest = build(tmp_path)
    manifest["chapters"][0]["subsections"] = [
        "Challenges: Oscillation Parameters (Section [ref: expt_motive])",
        "How the generators work [ref: generators]",
    ]

    row = chapter_row(write_index.render(manifest))

    assert "ref:" not in row[4]
    assert row[4] == (
        "Challenges: Oscillation Parameters; How the generators work"
    )


def test_a_title_that_is_only_a_marker_is_dropped(tmp_path: Path) -> None:
    paper_dir, manifest = build(tmp_path)
    manifest["chapters"][0]["subsections"] = ["[ref: nothing]"]

    assert chapter_row(write_index.render(manifest))[4] == "—"

