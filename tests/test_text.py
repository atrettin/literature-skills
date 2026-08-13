"""The text work that every module shares.

The sentence splitter is what these mostly guard. Three modules used to split
sentences three different ways, and the one that answers now has to hold for
all of them: a scan reading one clause at a time, a search quoting a whole
sentence, and a collection row taking the first one.
"""

from __future__ import annotations

import pytest

from lit import text

# --------------------------------------------------------------------------
# sentences
# --------------------------------------------------------------------------


def test_a_full_stop_and_a_space_end_a_sentence() -> None:
    assert text.sentences("The model fails. A better one exists.") == [
        "The model fails.",
        "A better one exists.",
    ]


@pytest.mark.parametrize(
    "passage",
    [
        "We cite Phys. Rev. D 108 (2023) 113010 for this.",
        "The result follows Bodek et al. and the dipole form.",
        "The value is shown in Fig. 3 of that paper.",
        "Any nucleus, e.g. carbon, behaves this way.",
        "The axial mass is 1.03 GeV in that fit.",
    ],
)
def test_an_abbreviation_or_a_decimal_ends_nothing(passage: str) -> None:
    """A journal name, a shorthand and a number all carry a full stop."""
    assert text.sentences(passage) == [passage]


def test_a_semicolon_divides_a_clause_and_not_a_sentence() -> None:
    passage = "The value is 1.03 GeV; the error is 0.02 GeV. Both are quoted."

    assert len(text.sentences(passage)) == 2
    assert len(text.sentences(passage, clauses=True)) == 3


def test_the_span_holds_the_offsets_of_the_sentence() -> None:
    passage = "Alpha beta. Gamma delta. Epsilon."

    start, end = text.span_around(passage, 12, 17)

    assert passage[start:end] == "Gamma delta."


def test_a_match_across_a_break_keeps_both_sentences() -> None:
    """Half a quotation is worse than a long one: it is not what the paper said."""
    passage = "The cross section falls. Above that it rises."

    start, end = text.span_around(passage, 20, 30)

    assert passage[start:end] == passage


def test_text_with_no_sentence_end_is_one_sentence() -> None:
    assert text.sentences("a title with no full stop") == ["a title with no full stop"]
    assert text.span_around("no full stop here", 3, 7) == (0, 17)


def test_the_first_sentence_is_cut_at_the_limit() -> None:
    assert text.first_sentence("Short one. Second one.", 160) == "Short one."
    assert text.first_sentence("", 160) == ""
    assert text.first_sentence("A very long opening sentence indeed.", 12) == "A very long…"


# --------------------------------------------------------------------------
# names on disk, and cells in a table
# --------------------------------------------------------------------------


def test_an_accent_folds_onto_its_letter_rather_than_vanishing() -> None:
    """`gl_ck` reads as damage. `gluck` reads as a name."""
    assert text.slugify("Glück") == "gluck"
    assert text.slugify("Argüelles") == "arguelles"


def test_a_whole_word_slug_cuts_back_to_the_last_underscore() -> None:
    long_title = "measurement_of_the_axial_mass_in_quasielastic_scattering"

    assert not text.slugify(long_title, limit=30, whole_words=True).endswith("_")
    assert "quasi" not in text.slugify(long_title, limit=30, whole_words=True)


def test_a_pipe_in_a_cell_does_not_split_the_row() -> None:
    escaped = text.escape_cell("sigma | rho")

    assert escaped == "sigma \\| rho"
    assert text.split_cells("| a | %s | b |" % escaped) == ["a", escaped, "b"]


def test_a_surname_survives_every_way_of_writing_it() -> None:
    assert text.surname("Lipari, Paolo") == "Lipari"
    assert text.surname("P. Lipari") == "Lipari"
    assert text.surname("Lipari") == "Lipari"
    # Trailing initials happen in a bibliography.
    assert text.surname("Brieva F.A.") == "Brieva"


def test_the_author_list_is_cut_where_the_column_is_narrow() -> None:
    four = ["Lovelace, Ada", "Hopper, Grace", "Noether, Emmy", "Curie, Marie"]

    assert text.display_authors(four, 1) == "A. Lovelace et al."
    assert text.display_authors(four, 3) == "A. Lovelace, G. Hopper, E. Noether et al."
    assert text.display_authors(["Ada Lovelace"], 3, initials=False) == "Ada Lovelace"
    assert text.display_authors([], 3) == text.EMPTY
