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
from lit import blocks
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

    anchors = anchors_in(text)
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

    assert anchors_in(text) == ["sec-nuc"]


# --------------------------------------------------------------------------
# an anchor at every paragraph
# --------------------------------------------------------------------------

def anchors_in(text: str) -> list[str]:
    """The anchors of a piece of the intermediate text, in order."""
    return [found.group(1) for found in re.finditer(r'<a id="([^"]*)"></a>', text)]


PARAGRAPH = (
    "The measured cross section rises with the energy of the beam, and the "
    "model reproduces that rise over the whole range considered here."
)


def test_paragraph_anchors_number_the_prose_in_order() -> None:
    numbered = arxiv_fetch.paragraph_anchors(
        blocks.parse(
            "# 1. Introduction\n\n%s\n\n## 1.1 Method\n\n%s\n" % (PARAGRAPH, PARAGRAPH)
        )
    )

    assert blocks.anchors(numbered) == ["p1", "p2"]
    assert [block["text"] for block in numbered if block["kind"] == "paragraph"] == [
        PARAGRAPH, PARAGRAPH
    ]


def test_only_prose_is_numbered() -> None:
    """A fence and a maths block are not paragraphs, so neither is counted."""
    numbered = arxiv_fetch.paragraph_anchors(
        blocks.parse("```tex\n%s\n```\n\n%s\n" % (PARAGRAPH, PARAGRAPH))
    )

    assert blocks.anchors(numbered) == ["p1"]
    assert [block["kind"] for block in numbered] == ["code", "paragraph"]


def test_a_chapter_that_went_through_the_anchors_answers_a_paragraph_link() -> None:
    numbering = arxiv_fetch.Numbering()
    numbering.start_chapter(1, "Introduction")
    text, _ = arxiv_fetch.clean_text(
        "%s\n\n%s\n" % (PARAGRAPH, PARAGRAPH), [], "Introduction", numbering
    )

    # As `convert` builds a chapter: the heading, then what `clean_text` made.
    stored = arxiv_fetch.paragraph_anchors(
        blocks.parse(arxiv_fetch.sanitise("# 1. Introduction\n\n" + text))
    )

    assert blocks.anchors(stored) == ["sec-introduction", "p1", "p2"]
    # The chapter's anchor names its heading, and not the paragraph under it.
    assert stored[0]["kind"] == "heading"


def test_each_piece_of_a_split_chapter_counts_from_p1() -> None:
    """The anchors run after the split, so a number addresses its own file."""
    chapter = "# 1. Results\n\n%s\n\n## 1.1 Second part\n\n%s\n" % (
        PARAGRAPH, PARAGRAPH
    )

    pieces = arxiv_fetch.split_long_chapter(chapter, limit=10)

    assert [title for title, _ in pieces] == ["opening", "Second part"]
    for _, piece in pieces:
        assert blocks.anchors(
            arxiv_fetch.paragraph_anchors(blocks.parse(piece))
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
    update_references.write_records(collection, store)
    verdict = check_references.main(["--literature-root", str(collection)])
    damaged = collection / "juszczak_2003_recoil_nucleon_spectrum" / "text"
    damaged.mkdir(parents=True, exist_ok=True)
    # Written here rather than into tests/data: a fixture file holding a NUL
    # byte is a fixture no editor and no `grep` can read.
    (damaged / "01_broken.jsonl").write_text(
        '{"kind": "paragraph", "anchor": "p1", '
        '"text": "A fraction of $\\\\sim PH7 13$% \x00 of the sample."}\n',
        encoding="utf-8",
    )

    report = check_references.check(collection)

    assert report["residue"] == [
        {
            "in": "juszczak_2003_recoil_nucleon_spectrum/text/01_broken.jsonl",
            "placeholders": 1,
            "control_characters": 1,
        }
    ]
    # The verdict is what it was: `ok` answers whether the citations resolve,
    # and residue is a defect of the text that a re-ingest removes.
    assert check_references.main(["--literature-root", str(collection)]) == verdict


def test_a_collection_with_no_residue_reports_none(collection: Path) -> None:
    assert check_references.check(collection)["residue"] == []


# --------------------------------------------------------------------------
# drop_definitions takes the definitions, never the paper around them
# --------------------------------------------------------------------------


NATBIB_PREAMBLE = r"""
\begin{thebibliography}{60}%
\makeatletter
\providecommand \@ifxundefined [1]{%
 \@ifx{#1\undefined}
}%
\providecommand \@secondoftwo [1]{}%
\providecommand \bibitemStop [0]{}%
\end{thebibliography}
"""


def test_the_preamble_after_the_last_section_keeps_the_body() -> None:
    """The natbib preamble follows the last section, and it is what bit.

    A definition there that this could not read advanced the cursor without
    handing the prose to `pieces`, so the whole document went and the
    reference list stood for the paper.
    """
    body = (
        "\\section{Introduction}\n"
        "The cross section grows with energy.\n"
        "\n"
        "\\section{Results}\n"
        "The data are described.\n"
    )

    kept = arxiv_fetch.drop_definitions(body + NATBIB_PREAMBLE)

    assert "\\section{Introduction}" in kept
    assert "The cross section grows with energy." in kept
    assert "The data are described." in kept


def test_a_name_carrying_an_at_sign_is_read_whole() -> None:
    text = "Prose before.\n\\providecommand \\@secondoftwo [1]{}\nProse after.\n"

    kept = arxiv_fetch.drop_definitions(text)

    assert "@secondoftwo" not in kept
    assert "Prose before." in kept
    assert "Prose after." in kept


def test_a_definition_this_cannot_read_stays_whole_and_loses_nothing_before_it() -> None:
    text = "Prose before.\n\\providecommand \\x [1] without a body\nProse after.\n"

    kept = arxiv_fetch.drop_definitions(text)

    assert "Prose before." in kept
    # Left in place, and not half-cut: the keyword is still on it.
    assert "\\providecommand" in kept
    assert "Prose after." in kept


def test_no_fixture_file_holds_a_control_character() -> None:
    fixture = Path(__file__).resolve().parent / "data" / "collection_fixture"
    for path in fixture.rglob("*.jsonl"):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not re.search(r"[\x00-\x08\x0b-\x1f]", text), path


# --------------------------------------------------------------------------
# a bibliography is found by what it holds, not by what it is called
# --------------------------------------------------------------------------

REVTEX_BIBLIOGRAPHY = (
    "\\section{Data Access}\n"
    "The tables are downloadable.\n"
    "\n"
    "\\begin{references}\n"
    "\\bibitem{barone} V. Barone, Eur. Phys. J. {\\bf C12} (2000) 243.\n"
    "\n"
    "\\bibitem{nmc} M. Arneodo, Nucl. Phys. {\\bf B483} (1997) 3.\n"
    "\\end{references}\n"
    "\n"
    "\\section*{Appendix}\n"
    "The model is described here.\n"
)


def test_a_bibliography_named_references_is_taken_out() -> None:
    """revtex calls the list `references`, and the parser knew only `thebibliography`.

    Left in, the list is the paper's last chapter, and the check that refuses a
    document whose references survived fails the whole ingest.
    """
    kept = arxiv_fetch.drop_bibliography(REVTEX_BIBLIOGRAPHY)

    assert "\\bibitem" not in kept
    assert "The tables are downloadable." in kept


def test_the_appendix_after_a_references_list_survives() -> None:
    kept = arxiv_fetch.drop_bibliography(REVTEX_BIBLIOGRAPHY)

    assert "\\section*{Appendix}" in kept
    assert "The model is described here." in kept


def test_the_last_entry_of_a_list_ends_where_the_environment_does() -> None:
    """Without the closing boundary the last entry runs into the appendix.

    The appendix was read as part of the last work cited, so the store held a
    reference whose text was a table of fit parameters.
    """
    from lit import references

    items = references.split_bibitems(REVTEX_BIBLIOGRAPHY)

    assert [key for key, _ in items] == ["barone", "nmc"]
    assert "The model is described here" not in items[-1][1]
    assert "Appendix" not in items[-1][1]


def test_a_thebibliography_list_is_still_taken_out() -> None:
    body = (
        "\\section{Results}\n"
        "The data are described.\n"
        "\n"
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{a} A. Author, J. Phys. 1 (2000) 1.\n"
        "\\end{thebibliography}\n"
    )

    kept = arxiv_fetch.drop_bibliography(body)

    assert "\\bibitem" not in kept
    assert "The data are described." in kept


def test_an_environment_inside_the_list_does_not_cut_the_entry_after_it() -> None:
    """A closed environment before an entry is not that entry's boundary.

    Taking its end as the boundary cut the entry back to nothing, and a work
    with no text is dropped from the store with no error.
    """
    from lit import references

    body = (
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{a} A. Author, J. Phys. 1 (2000) 1.\n"
        "\\begin{center}\\rule{1in}{0.4pt}\\end{center}\n"
        "\\bibitem{b} B. Author, Nucl. Phys. 2 (2001) 2.\n"
        "\\end{thebibliography}\n"
    )

    items = references.split_bibitems(body)

    assert [key for key, _ in items] == ["a", "b"]
    assert "B. Author" in dict(items)["b"]


def test_each_list_is_split_on_its_own() -> None:
    """Joining two lists lets the second one's environments bound the first's entries."""
    from lit import references

    body = (
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{a} A. Author, J. Phys. 1 (2000) 1.\n"
        "\\end{thebibliography}\n"
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{b} B. Author, Nucl. Phys. 2 (2001) 2.\n"
        "\\end{thebibliography}\n"
    )

    items = [item for block in references.bibliography_blocks(body)
             for item in references.split_bibitems(block)]

    assert [key for key, _ in items] == ["a", "b"]
    assert "B. Author" in dict(items)["b"]


def test_a_list_that_is_never_closed_is_still_taken_out() -> None:
    """A truncated submission is malformed, and failing it would be a new refusal.

    The environment ran to the end of the file before this was found by name,
    and it still does: an unclosed list is the last thing in the document.
    """
    body = (
        "\\section{Data}\n"
        "The tables are downloadable.\n"
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{a} A. Author, J. Phys. 1 (2000) 1.\n"
    )

    kept = arxiv_fetch.drop_bibliography(body)

    assert "\\bibitem" not in kept
    assert "The tables are downloadable." in kept


def test_a_wrapper_around_the_list_keeps_what_the_wrapper_holds() -> None:
    """The list is the innermost environment that holds the entries.

    Taking the outermost span removed the wrapper whole, and with it the
    appendix prose that sat beside the list.
    """
    body = (
        "\\begin{appendices}\n"
        "\\section*{Appendix}\n"
        "The model is described here.\n"
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{a} A. Author, J. Phys. 1 (2000) 1.\n"
        "\\end{thebibliography}\n"
        "\\end{appendices}\n"
    )

    kept = arxiv_fetch.drop_bibliography(body)

    assert "\\bibitem" not in kept
    assert "The model is described here." in kept
