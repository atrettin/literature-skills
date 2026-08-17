"""`litdb remove`: the undo an ingest never had.

An identifier recalled rather than read resolves to a real paper, and every
stage of the ingest succeeds on it. These cases are about the two ways that
mistake gets corrected — the guard that stops it, and the removal that undoes
it — and about the one thing removal must not do quietly, which is leave another
paper's citations pointing at a paper the collection no longer holds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lit import collection_index, paths, reference_store, remove_paper

PAPER = "jeong_2023_shallow_deep_inelastic"
OTHER = "juszczak_2003_recoil_nucleon_spectrum"


def as_ingested(collection: Path) -> list[dict]:
    """Point the store at the papers on disk, as an ingest leaves it.

    The `collection` fixture stores and renders but never merges references, so
    `held_as` is null until this runs. A removal has to undo what an ingest did,
    so the state it undoes is the state these cases start from.
    """
    records = reference_store.load(collection)
    reference_store.mark_held(records, collection)
    reference_store.save(collection, records)
    return records


def run(collection: Path, *arguments: str, capsys) -> tuple[int, dict]:
    status = remove_paper.main([*arguments, "--literature-root", str(collection)])
    return status, json.loads(capsys.readouterr().out)


def test_a_dry_run_says_what_would_go_and_removes_nothing(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, report = run(collection, PAPER, "--dry-run", capsys=capsys)

    assert status == 0
    assert report["removed"] is False
    assert (collection / PAPER).is_dir()


def test_removing_takes_the_directory_and_the_index_row(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert PAPER in (collection / "README.md").read_text(encoding="utf-8")

    status, report = run(collection, PAPER, "--force", capsys=capsys)

    assert status == 0
    assert report["removed"] is True
    assert not (collection / PAPER).exists()
    assert PAPER not in paths.papers_on_disk(collection)
    # The index lists what the collection holds. A row for a directory that is
    # gone sends a reader to a page that does not open.
    assert report["index_row"] == "removed"
    assert PAPER not in (collection / "README.md").read_text(encoding="utf-8")


def test_a_record_stops_claiming_to_be_held_here(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The record itself stays: another paper may cite that work, and it still exists."""
    before = as_ingested(collection)
    assert any(record.get("held_as") == PAPER for record in before)

    run(collection, PAPER, "--force", capsys=capsys)

    after = reference_store.load(collection)
    assert not any(record.get("held_as") == PAPER for record in after)
    assert len(after) == len(before)


def test_a_paper_another_paper_cites_needs_the_caller_to_decide(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Removing it turns a citation of a held paper into one of a work only named."""
    records = as_ingested(collection)
    for record in records:
        if record.get("held_as") == PAPER:
            record["cited_by"] = [{"slug": OTHER, "tag": record.get("tag", "")}]
            break
    else:
        pytest.skip("the fixture holds no record for this paper")
    reference_store.save(collection, records)

    status, report = run(collection, PAPER, capsys=capsys)

    assert status == 2
    assert report["removed"] is False
    assert report["cited_by"] == [OTHER]
    assert (collection / PAPER).is_dir()

    status, forced = run(collection, PAPER, "--force", capsys=capsys)
    assert status == 0
    assert forced["removed"] is True


def test_removing_a_paper_that_is_not_there_is_absent_and_not_a_judgement(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, report = run(collection, "no_such_paper", capsys=capsys)
    assert status == 1
    assert report["unknown_paper"] == "no_such_paper"
    assert PAPER in report["papers"]
