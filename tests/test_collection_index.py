"""The row a paper gets in the collection's own index."""

from __future__ import annotations

from pathlib import Path

import pytest

from lit import collection_index

FIVE_COLUMN = """# Literature

## Papers

| Title | Authors | Year | Journal | What it is about |
|---|---|---|---|---|
| [Old Paper](old_2002_thing/INDEX.md) | P. Lipari | 2002 | Nucl.Phys.B 112 | an early look |
| [Later Paper](later_2023_thing/INDEX.md) | Y. Jeong et al. | 2023 | Phys.Rev.D 108 | the later one |
"""

def report(year: int = 2015, journal: str = "", slug: str = "lovelace_2015_small_paper") -> dict:
    return {
        "slug": slug,
        "title": "A Small Paper on Quasielastic Scattering",
        "authors": ["Ada Lovelace", "Grace Hopper"],
        "submitted_year": year,
        "publication": {"journal": journal},
    }


def rows(root: Path) -> list[str]:
    return [line for line in (root / "README.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("| [")]


def build(tmp_path: Path, text: str | None = None) -> Path:
    root = tmp_path / "collection"
    root.mkdir()
    if text is not None:
        (root / "README.md").write_text(text, encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# order
# --------------------------------------------------------------------------


def test_the_row_lands_in_year_order(tmp_path: Path) -> None:
    root = build(tmp_path, FIVE_COLUMN)

    assert collection_index.add_row(root, report(year=2015)) == "added"

    assert [collection_index.row_year(line) for line in rows(root)] == [2002, 2015, 2023]


def test_the_newest_paper_goes_last(tmp_path: Path) -> None:
    root = build(tmp_path, FIVE_COLUMN)

    collection_index.add_row(root, report(year=2030))

    assert collection_index.row_year(rows(root)[-1]) == 2030


def test_a_paper_of_a_year_already_there_goes_after_it(tmp_path: Path) -> None:
    root = build(tmp_path, FIVE_COLUMN)

    collection_index.add_row(root, report(year=2002))

    assert collection_index.row_slug(rows(root)[1]) == "lovelace_2015_small_paper"


# --------------------------------------------------------------------------
# the Journal column
# --------------------------------------------------------------------------


def test_a_second_run_writes_only_the_journal_cell(tmp_path: Path) -> None:
    """A preprint that has since been published is why a re-run is worth doing."""
    root = build(tmp_path, FIVE_COLUMN)
    collection_index.add_row(root, report(year=2015), "what somebody wrote")

    assert collection_index.add_row(
        root, report(year=2015, journal="Phys.Rev.D 92 011301"), "the abstract again"
    ) == "present"

    row = next(line for line in rows(root)
               if collection_index.row_slug(line) == "lovelace_2015_small_paper")
    assert collection_index.cells(row)[3] == "Phys.Rev.D 92 011301"
    assert collection_index.cells(row)[4] == "what somebody wrote"
    assert len(rows(root)) == 3


# --------------------------------------------------------------------------
# the description
# --------------------------------------------------------------------------


def test_the_description_is_the_first_sentence_of_the_abstract() -> None:
    text = "This paper measures a cross section. It then compares that with a model."

    assert collection_index.first_sentence(text) == "This paper measures a cross section."


def test_a_long_first_sentence_is_cut() -> None:
    long = "A " + "very " * 80 + "long sentence."

    cut = collection_index.first_sentence(long)

    assert len(cut) <= collection_index.ROW_DESCRIPTION_CHARS
    assert cut.endswith("…")


def test_no_abstract_gives_no_description(tmp_path: Path) -> None:
    root = build(tmp_path, FIVE_COLUMN)
    collection_index.add_row(root, report(), collection_index.first_sentence(""))

    row = next(line for line in rows(root)
               if collection_index.row_slug(line) == "lovelace_2015_small_paper")
    assert collection_index.cells(row)[4] == "—"


# --------------------------------------------------------------------------
# the failures
# --------------------------------------------------------------------------


def test_an_unreadable_table_raises(tmp_path: Path) -> None:
    root = build(tmp_path, "# Literature\n\nNo table here at all.\n")

    with pytest.raises(collection_index.CollectionIndexUnreadable):
        collection_index.add_row(root, report())


def test_a_header_with_no_separator_is_not_a_table(tmp_path: Path) -> None:
    root = build(tmp_path, "# Literature\n\n| Title | Year |\nnot a separator\n")

    with pytest.raises(collection_index.CollectionIndexUnreadable):
        collection_index.add_row(root, report())


def test_a_collection_with_no_index_gets_one(tmp_path: Path) -> None:
    root = build(tmp_path)

    assert collection_index.add_row(root, report()) == "added"
    assert len(rows(root)) == 1


def test_a_pipe_in_a_title_does_not_split_the_row(tmp_path: Path) -> None:
    root = build(tmp_path, FIVE_COLUMN)
    paper = report()
    paper["title"] = "Measuring | and rho"

    collection_index.add_row(root, paper)

    row = next(line for line in rows(root)
               if collection_index.row_slug(line) == "lovelace_2015_small_paper")
    assert len(collection_index.cells(row)) == len(collection_index.COLUMNS)
