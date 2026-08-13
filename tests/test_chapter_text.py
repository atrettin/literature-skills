"""What a chapter file has to be, as text and as an address.

Two readers use these files, and they ask different things of them. A human
reads the rendered page, and a search — an agent's or a reader's — reads the
raw bytes. So a chapter has to hold no character that hides it from `grep`, it
has to keep each paragraph on one line so that a phrase search finds a phrase,
and it has to carry an anchor at every heading and every paragraph so that a
citation can lead to the sentence carrying the claim.
"""

from __future__ import annotations

import re
from pathlib import Path

from lit import arxiv_fetch
from lit import check_references
from lit import reference_store
from lit import update_references
from lit.text import slugify

TABLE_WITH_MATHS = r"""
Some opening prose.

\begin{table}[t]
\begin{tabular}{lc}
mass & $m_A = 1.03 \pm 0.02$ GeV \\
\end{tabular}
\caption{Fitted values, about $\sim 13$\% of the total.}
\label{tab:fit}
\end{table}
"""


# --------------------------------------------------------------------------
# nothing below U+0020 reaches the disk
# --------------------------------------------------------------------------


def test_a_payload_holding_another_key_is_restored_whole() -> None:
    """The nested stash is the defect: a table holds the maths of its cells."""
    holder = arxiv_fetch.Placeholder()
    inner = holder.stash("$m_A$")
    outer = holder.stash("| mass | %s |" % inner)

    restored = holder.restore("A row: %s" % outer)

    assert restored == "A row: | mass | $m_A$ |"
    assert arxiv_fetch.SENTINEL_OPEN not in restored
    assert arxiv_fetch.SENTINEL_CLOSE not in restored
    assert not arxiv_fetch.RESIDUE.search(restored)


def test_sanitise_drops_a_nul_byte_and_keeps_a_newline_and_a_tab() -> None:
    assert arxiv_fetch.sanitise("a\x00b\nc\td") == "ab\nc\td"


def test_maths_inside_a_table_leaves_no_control_character() -> None:
    numbering = arxiv_fetch.Numbering()
    numbering.start_chapter(1, "Results")

    text, _ = arxiv_fetch.clean_text(TABLE_WITH_MATHS, [], "Results", numbering)

    assert "13" in text
    assert not arxiv_fetch.RESIDUE.search(text)
    assert [character for character in text if ord(character) < 0x20
            and character not in "\n\t"] == []


# --------------------------------------------------------------------------
# one paragraph is one line
# --------------------------------------------------------------------------


def test_reflow_joins_a_wrapped_paragraph_and_keeps_it_apart_from_the_next() -> None:
    text = arxiv_fetch.reflow(
        "The cross section rises\nwith energy, and the\nmodel follows it.\n"
        "\n"
        "A second paragraph\nof two lines.\n"
    )

    assert text.split("\n") == [
        "The cross section rises with energy, and the model follows it.",
        "",
        "A second paragraph of two lines.",
        "",
    ]


def test_reflow_keeps_the_breaks_that_carry_meaning() -> None:
    source = (
        "```tex\nrow one\nrow two\n```\n"
        "\n"
        "$$\nE = mc^2\n\\tag{1}\n$$\n"
        "\n"
        "- first item\n- second item\n"
        "\n"
        "| a | b |\n| - | - |\n"
    )

    assert arxiv_fetch.reflow(source) == source


# --------------------------------------------------------------------------
# an anchor at every heading
# --------------------------------------------------------------------------


def test_an_unlabelled_subsection_still_gets_an_anchor() -> None:
    numbering = arxiv_fetch.Numbering()
    numbering.start_chapter(2, "Method")

    text = arxiv_fetch.number_headings(
        r"\subsection{Nuclear effects} prose \subsection{Nuclear effects} more",
        numbering,
    )

    anchors = check_references.ANCHOR.findall(text)
    assert anchors == ["sec-nuclear-effects", "sec-nuclear-effects-2"]
    # No `\ref` names a reserved anchor, so no label answers for one.
    assert numbering.labels == {}


def test_a_labelled_subsection_keeps_the_anchor_named_after_its_label() -> None:
    """Every anchor a report cites today is named after a label."""
    numbering = arxiv_fetch.Numbering()
    numbering.start_chapter(2, "Method")

    text = arxiv_fetch.number_headings(
        r"\subsection{Nuclear effects}\label{sec:nuc} prose", numbering
    )

    assert check_references.ANCHOR.findall(text) == ["sec-nuc"]


# --------------------------------------------------------------------------
# an anchor at every paragraph
# --------------------------------------------------------------------------

PARAGRAPH = (
    "The measured cross section rises with the energy of the beam, and the "
    "model reproduces that rise over the whole range considered here."
)


def test_paragraph_anchors_number_the_prose_in_order() -> None:
    text = arxiv_fetch.paragraph_anchors(
        "# 1. Introduction\n\n%s\n\n## 1.1 Method\n\n%s\n" % (PARAGRAPH, PARAGRAPH)
    )

    assert check_references.ANCHOR.findall(text) == ["p1", "p2"]
    assert text.count('<a id="p1"></a>') == 1
    assert "<a id=\"p1\"></a>\n\n%s" % PARAGRAPH in text


def test_paragraph_anchors_stay_out_of_a_fence_and_out_of_display_maths() -> None:
    text = arxiv_fetch.paragraph_anchors(
        "```tex\n%s\n\n%s\n```\n\n$$\n%s\n\n%s\n$$\n" % ((PARAGRAPH,) * 4)
    )

    assert check_references.ANCHOR.findall(text) == []


def test_a_chapter_that_went_through_the_anchors_answers_a_paragraph_link() -> None:
    numbering = arxiv_fetch.Numbering()
    numbering.start_chapter(1, "Introduction")
    text, _ = arxiv_fetch.clean_text(
        "%s\n\n%s\n" % (PARAGRAPH, PARAGRAPH), [], "Introduction", numbering
    )

    written = arxiv_fetch.sanitise(arxiv_fetch.paragraph_anchors(text))

    assert "p2" in set(check_references.ANCHOR.findall(written))


def test_each_piece_of_a_split_chapter_counts_from_p1() -> None:
    """The anchors run after the split, so a number addresses its own file."""
    chapter = "# 1. Results\n\n%s\n\n## 1.1 Second part\n\n%s\n" % (
        PARAGRAPH, PARAGRAPH
    )

    pieces = arxiv_fetch.split_long_chapter(chapter, limit=10)

    assert [title for title, _ in pieces] == ["opening", "Second part"]
    for _, piece in pieces:
        assert check_references.ANCHOR.findall(
            arxiv_fetch.paragraph_anchors(piece)
        ) == ["p1"]


# --------------------------------------------------------------------------
# a file name that ends where a word ends
# --------------------------------------------------------------------------

LONG_TITLE = "Neutrino oscillations with more than three neutrinos"


def test_whole_words_cuts_a_file_name_at_a_word_boundary() -> None:
    assert slugify(LONG_TITLE, whole_words=True) == (
        "neutrino_oscillations_with_more_than_three"
    )


def test_the_default_cut_is_unchanged_so_every_reference_tag_holds() -> None:
    assert slugify(LONG_TITLE) == "neutrino_oscillations_with_more_than_three_neutr"


def test_a_name_that_would_say_too_little_keeps_its_cut_word() -> None:
    """Below SLUG_MIN_CHARS the shorter name loses more than the cut costs."""
    assert slugify("Phenomenology electroweakinos", limit=20, whole_words=True) == (
        "phenomenology_electr"
    )


# --------------------------------------------------------------------------
# and what check_references.py makes of a chapter that carries residue
# --------------------------------------------------------------------------


def test_residue_is_reported_and_leaves_the_citations_alone(collection: Path) -> None:
    store = reference_store.load(collection)
    update_references.relink_citations(collection, "", store)
    update_references.write_records(collection, store)
    verdict = check_references.main(["--literature-root", str(collection)])
    damaged = collection / "juszczak_2003_recoil_nucleon_spectrum" / "chapters"
    damaged.mkdir(parents=True, exist_ok=True)
    # Written here rather than into tests/data: a fixture file holding a NUL
    # byte is a fixture no editor and no `grep` can read.
    (damaged / "01_broken.md").write_text(
        "A fraction of $\\sim PH7 13$% \x00 of the sample.\n", encoding="utf-8"
    )

    report = check_references.check(collection)

    assert report["residue"] == [
        {
            "in": "juszczak_2003_recoil_nucleon_spectrum/chapters/01_broken.md",
            "placeholders": 1,
            "control_characters": 1,
        }
    ]
    # The verdict is what it was: `ok` answers whether the citations resolve,
    # and residue is a defect of the text that a re-ingest removes.
    assert check_references.main(["--literature-root", str(collection)]) == verdict


def test_a_collection_with_no_residue_reports_none(collection: Path) -> None:
    assert check_references.check(collection)["residue"] == []


def test_no_fixture_file_holds_a_control_character() -> None:
    fixture = Path(__file__).resolve().parent / "data" / "collection_fixture"
    for path in fixture.rglob("*.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not re.search(r"[\x00-\x08\x0b-\x1f]", text), path
