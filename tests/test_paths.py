"""Where things are in a collection, and which files a citation can be in."""

from __future__ import annotations

from pathlib import Path

import pytest

from lit import paths


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "collection"
    (root / "one_2020_paper" / "chapters").mkdir(parents=True)
    (root / "one_2020_paper" / "text").mkdir(parents=True)
    (root / "one_2020_paper" / "paper.json").write_text("{}", encoding="utf-8")
    (root / "one_2020_paper" / "INDEX.md").write_text("# one", encoding="utf-8")
    for name in ("01_intro", "02_method"):
        (root / "one_2020_paper" / "chapters" / (name + ".md")).write_text("a", encoding="utf-8")
        (root / "one_2020_paper" / "text" / (name + ".jsonl")).write_text("{}\n", encoding="utf-8")
    (root / "two_2021_paper").mkdir()
    (root / "two_2021_paper" / "paper.json").write_text("{}", encoding="utf-8")
    (root / "two_2021_paper" / "INDEX.md").write_text("# two", encoding="utf-8")
    (root / paths.RECORDS_DIR).mkdir()
    (root / paths.RECORDS_DIR / "someone_2002_thing.md").write_text("page", encoding="utf-8")
    (root / "README.md").write_text("the index", encoding="utf-8")
    (root / "REFERENCES.md").write_text("the table", encoding="utf-8")
    return root


def test_a_directory_with_a_record_is_a_paper(tree: Path) -> None:
    assert paths.papers_on_disk(tree) == ["one_2020_paper", "two_2021_paper"]


def test_a_root_that_is_not_there_holds_nothing(tmp_path: Path) -> None:
    """A project may have no collection yet. That is an answer, not an error."""
    assert paths.papers_on_disk(tmp_path / "absent") == []


def test_the_rendered_files_are_not_where_a_citation_lives(tree: Path) -> None:
    """`references/` and the files at the root are written from the store."""
    names = [path.name for path in paths.written_files(tree)]

    assert "README.md" not in names
    assert "REFERENCES.md" not in names
    assert "someone_2002_thing.md" not in names
    assert names == ["INDEX.md", "01_intro.md", "02_method.md", "INDEX.md"]


def test_one_slug_narrows_the_files_to_that_paper(tree: Path) -> None:
    found = paths.written_files(tree, "one_2020_paper")

    assert {paths.slug_of(tree, path) for path in found} == {"one_2020_paper"}
    assert len(found) == 3


def test_a_path_outside_the_root_belongs_to_no_paper(tree: Path) -> None:
    assert paths.slug_of(tree, tree.parent / "elsewhere.md") == ""


def test_the_chapters_come_back_in_the_order_of_their_names(tree: Path) -> None:
    assert [path.name for path in paths.chapters_of(tree, "one_2020_paper")] == [
        "01_intro.md",
        "02_method.md",
    ]
    assert paths.chapters_of(tree, "two_2021_paper") == []


def test_the_stored_text_is_what_a_marker_lives_in(tree: Path) -> None:
    """A `*.md` glob reaches no store, and a `*.jsonl` glob reaches no render."""
    assert [path.name for path in paths.stored_files(tree)] == [
        "01_intro.jsonl",
        "02_method.jsonl",
    ]
    assert all(path.suffix == ".jsonl" for path in paths.stored_files(tree))


def test_the_flavor_is_recorded_in_the_collection(tree: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """A render says what it wrote, and every later pass reads that."""
    monkeypatch.delenv("LITERATURE_FLAVOR", raising=False)
    assert paths.flavor(tree) == "vscode"

    paths.set_flavor(tree, "obsidian")

    assert paths.flavor(tree) == "obsidian"
    # The shell does not win over what is on disk: the anchors a render wrote
    # are the anchors that are there.
    monkeypatch.setenv("LITERATURE_FLAVOR", "vscode")
    assert paths.flavor(tree) == "obsidian"


def test_the_root_is_the_variable_or_the_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITERATURE_ROOT", raising=False)
    assert paths.default_root() == Path("literature")

    monkeypatch.setenv("LITERATURE_ROOT", "/shared/papers")
    assert paths.default_root() == Path("/shared/papers")
