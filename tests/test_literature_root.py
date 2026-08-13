"""Where the scripts look for the collection.

One collection can serve many projects, and `LITERATURE_ROOT` is what says so.
Every script reads it as the default of `--literature-root`, so a project that
sets it needs no flag and a caller that passes the flag still wins.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lit import arxiv_discover
from lit import check_references
from lit import collection_overlap
from lit import inspire_citations
from lit import reference_lookup
from lit import paths
from lit import search_literature


def test_default_root_is_the_project_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITERATURE_ROOT", raising=False)
    assert paths.default_root() == Path("literature")


def test_the_variable_names_the_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITERATURE_ROOT", "/shared/papers")
    assert paths.default_root() == Path("/shared/papers")


def test_an_empty_variable_is_no_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A variable set to nothing must not send every script to the root of the disk."""
    monkeypatch.setenv("LITERATURE_ROOT", "")
    assert paths.default_root() == Path("literature")


@pytest.mark.parametrize(
    "build, arguments",
    [
        (lambda: arxiv_discover.build_parser(), ["--topic", "quasielastic"]),
        (lambda: reference_lookup.build_parser(), ["some_tag"]),
        (lambda: inspire_citations.build_parser(), ["1706.03621"]),
        (lambda: collection_overlap.build_parser(), ["1706.03621", "--all-papers"]),
        (lambda: search_literature.build_parser(), ["axial mass"]),
    ],
)
def test_each_parser_reads_the_variable(
    monkeypatch: pytest.MonkeyPatch, build, arguments: list[str]
) -> None:
    monkeypatch.setenv("LITERATURE_ROOT", "/shared/papers")
    parsed = build().parse_args(arguments)
    assert parsed.literature_root == Path("/shared/papers")


def test_the_flag_wins_over_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LITERATURE_ROOT", "/shared/papers")
    parsed = arxiv_discover.build_parser().parse_args(
        ["--topic", "quasielastic", "--literature-root", "elsewhere"]
    )
    assert parsed.literature_root == Path("elsewhere")


def test_a_search_reads_the_collection_the_variable_names(
    monkeypatch: pytest.MonkeyPatch, collection: Path
) -> None:
    """The variable reaches the answer, not only the parser."""
    monkeypatch.setenv("LITERATURE_ROOT", str(collection))
    options = arxiv_discover.Options(topic="quasielastic")
    entries = [{"arxiv_id": "2307.09241", "doi": ""}]
    counts = arxiv_discover.annotate_local(entries, options.literature_root)

    assert counts["held"] == 1
    assert entries[0]["held_as"] == "jeong_2023_shallow_deep_inelastic"


def test_a_phrase_search_reads_the_collection_the_variable_names(
    monkeypatch: pytest.MonkeyPatch, collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The variable reaches the search itself, and the flag still wins over it."""
    monkeypatch.setenv("LITERATURE_ROOT", str(collection))

    assert search_literature.main(["axial mass extracted"]) == 0
    assert "jeong_2023_shallow_deep_inelastic" in capsys.readouterr().out

    elsewhere = collection.parent / "nothing"
    assert search_literature.main(
        ["axial mass extracted", "--literature-root", str(elsewhere)]
    ) == 2
    assert str(elsewhere) in capsys.readouterr().out


def test_a_check_names_the_collection_it_could_not_find(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The variable reaches the check itself, and the report says which path failed."""
    missing = tmp_path / "nothing"
    monkeypatch.setenv("LITERATURE_ROOT", str(missing))

    assert check_references.main([]) == 1
    assert str(missing) in capsys.readouterr().out
