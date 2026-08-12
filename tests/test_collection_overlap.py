"""Weighing a candidate paper against the papers of one question.

Nothing here calls INSPIRE. `FakeInspire` stands in for the one function every
request goes through, so a test can read what was asked and choose what came
back. A candidate the collection holds must reach no request at all, and one
test asserts exactly that.

The stores these tests build are synthetic. A record's DOI is derived from its
tag, so a reference list and a store can be written from the same list of names
and the arithmetic under test stays readable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import collection_overlap
import inspire_lookup
import reference_store
import references
from conftest import DATA, FakeInspire


# --------------------------------------------------------------------------
# a store and a reference list, from the same names
# --------------------------------------------------------------------------


def doi_of(tag: str) -> str:
    return "10.0000/%s" % tag


def write_store(root: Path, papers: dict[str, list[str]]) -> None:
    """A store in which each named paper cites the works listed under it."""
    records: dict[str, dict] = {}
    for slug, tags in papers.items():
        for tag in tags:
            record = records.setdefault(
                tag,
                {"tag": tag, "title": tag, "doi": doi_of(tag), "cited_by": []},
            )
            record["cited_by"].append({"slug": slug, "key": tag})
    root.mkdir(parents=True, exist_ok=True)
    reference_store.save(root, list(records.values()))


def reference_payload(tags: list[str], nameless: int = 0) -> dict:
    """An INSPIRE reference list that cites each tag by its DOI.

    `nameless` adds entries that carry no handle of any kind. Those can never be
    recognised, so they leave every set and are counted on their own.
    """
    entries = [
        {
            "record": {"$ref": "https://inspirehep.net/api/literature/%d" % (900000 + number)},
            "reference": {"label": str(number + 1), "dois": [doi_of(tag)]},
        }
        for number, tag in enumerate(tags)
    ]
    entries += [
        {"reference": {"label": "x%d" % number, "misc": ["a line keyed to no record"]}}
        for number in range(nameless)
    ]
    return {"hits": {"total": 1, "hits": [{"metadata": {"references": entries}}]}}


@pytest.fixture
def overlap_references() -> dict:
    """A reference list whose entries name works of the fixture collection."""
    return json.loads(
        (DATA / "inspire_references_overlap.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def fake(
    monkeypatch: pytest.MonkeyPatch,
    inspire_payloads: dict,
    overlap_references: dict,
    no_pace: None,
) -> FakeInspire:
    """INSPIRE answering the candidate and its reference list."""
    stub = FakeInspire({
        "fields=references": overlap_references,
        "arxiv/1706.03621": inspire_payloads["inspire_record"],
        "doi/10.1016": inspire_payloads["inspire_record"],
        "literature/1599542": inspire_payloads["inspire_record"],
    })
    monkeypatch.setattr(inspire_lookup, "fetch_record", stub)
    return stub


def run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    code = collection_overlap.main(argv)
    return code, json.loads(capsys.readouterr().out)


# --------------------------------------------------------------------------
# where the candidate's reference list comes from
# --------------------------------------------------------------------------


def test_a_held_paper_answers_from_the_store_with_no_request(
    fake: FakeInspire, collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ingest resolved this bibliography already. Asking again buys nothing."""
    code, report = run(
        ["2307.09241", "--scope", "juszczak_2003_recoil_nucleon_spectrum",
         "--literature-root", str(collection)],
        capsys,
    )

    assert code == 0
    assert fake.paths == []
    assert report["source"] == "store"
    assert report["paper"]["held_as"] == "jeong_2023_shallow_deep_inelastic"
    assert report["candidate_references"]["listed"] == 3
    assert report["candidate_references"]["unidentified"] == 0


def test_a_held_candidate_is_not_compared_with_itself(
    fake: FakeInspire, collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A coefficient of 1.0 against itself would read as a second paper."""
    _, report = run(
        ["2307.09241", "--all-papers", "--literature-root", str(collection)], capsys
    )

    held = report["paper"]["held_as"]
    assert held == "jeong_2023_shallow_deep_inelastic"
    assert held not in [row["slug"] for row in report["closest"]]
    assert held not in [row["slug"] for row in report["outside_scope"]]
    assert held not in report["scope"]["papers"]


def test_a_reference_matches_the_store_by_doi_and_by_arxiv_identifier(
    collection: Path, overlap_references: dict
) -> None:
    entries = overlap_references["hits"]["hits"][0]["metadata"]["references"]
    index = reference_store.build_index(reference_store.load(collection))

    by_doi = reference_store.find_match(index, collection_overlap.probe_of(entries[0]))
    by_arxiv = reference_store.find_match(index, collection_overlap.probe_of(entries[1]))

    assert by_doi is not None and by_doi["tag"] == (
        "lipari_2002_neutrino_oscillation_neutrino_cross"
    )
    assert by_arxiv is not None and by_arxiv["tag"] == "jeong_2023_shallow_deep_inelastic"


def test_a_reference_with_no_handle_stays_out_of_every_ratio(
    fake: FakeInspire, collection: Path
) -> None:
    store = reference_store.load(collection)
    tags, listed, unidentified = collection_overlap.candidate_from_inspire("1599542", store)

    assert listed == 5
    assert unidentified == 1
    # The identified base is what every ratio divides by, and the counts behind
    # it add up, so a reader can check the base by hand.
    assert listed - unidentified == 4
    assert "smith_2020_private_communication" not in tags


# --------------------------------------------------------------------------
# the measure
# --------------------------------------------------------------------------


def test_the_coefficient_divides_by_the_shorter_list() -> None:
    """A letter that sits wholly inside a review is not unrelated to it."""
    letter = {"w%02d" % number for number in range(10)}
    review = {"w%02d" % number for number in range(8)} | {
        "x%03d" % number for number in range(92)
    }

    result = collection_overlap.score(
        {"tags": letter, "identified": 10}, {"review": review}
    )

    assert result["overlap"] == 0.8
    assert result["jaccard"] < 0.1


def test_a_short_reference_list_gives_counts_and_no_band(
    fake: FakeInspire, collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report = run(
        ["1706.03621", "--all-papers", "--literature-root", str(collection)], capsys
    )

    assert code == 0
    assert report["candidate_references"]["identified"] < collection_overlap.MIN_COMPARABLE_REFS
    assert report["comparable"] is False
    assert report["band"] is None
    assert isinstance(report["shared_with_scope"], int)
    assert report["reading"] == collection_overlap.THIN_READING


def build_case(coefficient: float, size: int = 100) -> dict:
    """A candidate and one held paper whose coefficient is about `coefficient`."""
    shared = round(coefficient * size)
    works = {"w%03d" % number for number in range(size)}
    tags = {"w%03d" % number for number in range(shared)}
    return collection_overlap.score({"tags": tags, "identified": size}, {"held": works})


def test_a_coefficient_above_the_high_threshold_reads_as_held_ground() -> None:
    result = build_case(collection_overlap.HIGH_OVERLAP + 0.05)

    assert result["overlap"] >= collection_overlap.HIGH_OVERLAP
    assert result["band"] == "high"
    assert result["reading"] == collection_overlap.READINGS["high"]


def test_a_coefficient_below_the_low_threshold_reads_as_new_ground() -> None:
    result = build_case(collection_overlap.LOW_OVERLAP - 0.05)

    assert result["overlap"] < collection_overlap.LOW_OVERLAP
    assert result["band"] == "low"
    assert result["reading"] == collection_overlap.READINGS["low"]


def test_the_closest_paper_sorts_first() -> None:
    tags = {"w%03d" % number for number in range(20)}
    sets = {
        "far": {"w000", "z001", "z002"},
        "near": {"w%03d" % number for number in range(15)},
    }

    result = collection_overlap.score({"tags": tags, "identified": 20}, sets)

    assert result["closest"][0]["slug"] == "near"
    assert result["closest"][0]["overlap"] == result["overlap"]
    assert [row["overlap"] for row in result["closest"]] == sorted(
        (row["overlap"] for row in result["closest"]), reverse=True
    )


def test_an_empty_collection_answers_zero_and_not_an_error(
    fake: FakeInspire, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A project can hold no papers yet, and that is an answer."""
    code, report = run(
        ["1706.03621", "--all-papers", "--literature-root", str(tmp_path)], capsys
    )

    assert code == 0
    assert "error" not in report
    assert report["comparable"] is False
    assert report["closest"] == []
    assert report["shared_with_scope"] == 0
    assert report["reading"] == collection_overlap.EMPTY_SCOPE_READING


# --------------------------------------------------------------------------
# the second pass
# --------------------------------------------------------------------------


def test_the_resolve_pass_batches_by_the_inspire_batch_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_pace: None,
    capsys: pytest.CaptureFixture[str], inspire_payloads: dict,
) -> None:
    """A reference no store record answers by number can still answer by DOI."""
    entries = [
        {"record": {"$ref": "https://inspirehep.net/api/literature/%d" % (700000 + number)},
         "reference": {"label": str(number + 1)}}
        for number in range(45)
    ]
    stub = FakeInspire({
        "fields=references": {"hits": {"total": 1, "hits": [{"metadata": {"references": entries}}]}},
        "arxiv/1706.03621": inspire_payloads["inspire_record"],
    })
    monkeypatch.setattr(inspire_lookup, "fetch_record", stub)
    write_store(tmp_path, {"a_paper": ["w00", "w01"]})

    run(["1706.03621", "--all-papers", "--resolve", "--literature-root", str(tmp_path)], capsys)

    lookups = [path for path in stub.paths if "or+recid" in path]
    # 45 unmatched references, one batch of `BATCH_SIZE` per request.
    assert len(lookups) == -(-45 // references.BATCH_SIZE) == 2
    numbers = sum(path.count("recid") for path in lookups)
    assert numbers <= collection_overlap.RESOLVE_CAP


# --------------------------------------------------------------------------
# the scope
# --------------------------------------------------------------------------


def test_the_script_refuses_to_run_with_no_scope(collection: Path) -> None:
    """A default of "the whole collection" would band the second task wrongly."""
    with pytest.raises(SystemExit) as raised:
        collection_overlap.main(["1706.03621", "--literature-root", str(collection)])

    assert raised.value.code == 2


def test_a_paper_of_another_task_does_not_change_the_band(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_pace: None,
    capsys: pytest.CaptureFixture[str], inspire_payloads: dict,
) -> None:
    """The band answers for the working set, whatever else is on disk."""
    mine = ["w%02d" % number for number in range(20)]
    theirs = ["x%02d" % number for number in range(20)]
    cites = mine[:12] + ["u%02d" % number for number in range(8)]

    stub = FakeInspire({
        "fields=references": reference_payload(cites),
        "arxiv/1706.03621": inspire_payloads["inspire_record"],
    })
    monkeypatch.setattr(inspire_lookup, "fetch_record", stub)

    alone = tmp_path / "alone"
    shared = tmp_path / "shared"
    write_store(alone, {"mine": mine})
    write_store(shared, {"mine": mine, "theirs": theirs})

    _, one = run(["1706.03621", "--scope", "mine", "--literature-root", str(alone)], capsys)
    _, two = run(["1706.03621", "--scope", "mine", "--literature-root", str(shared)], capsys)

    assert one["band"] == two["band"]
    assert one["overlap"] == two["overlap"] == 0.6
    assert one["containment"] == two["containment"]


def test_a_paper_of_another_task_appears_under_outside_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_pace: None,
    capsys: pytest.CaptureFixture[str], inspire_payloads: dict,
) -> None:
    """It is on disk, so it is worth reading. It is not evidence of coverage."""
    mine = ["w%02d" % number for number in range(20)]
    theirs = ["x%02d" % number for number in range(20)]
    cites = mine[:12] + theirs[:8]

    stub = FakeInspire({
        "fields=references": reference_payload(cites),
        "arxiv/1706.03621": inspire_payloads["inspire_record"],
    })
    monkeypatch.setattr(inspire_lookup, "fetch_record", stub)
    write_store(tmp_path, {"mine": mine, "theirs": theirs})

    _, report = run(["1706.03621", "--scope", "mine", "--literature-root", str(tmp_path)], capsys)

    assert [row["slug"] for row in report["closest"]] == ["mine"]
    outside = report["outside_scope"]
    assert [row["slug"] for row in outside] == ["theirs"]
    assert outside[0]["overlap"] > 0
    assert "band" not in outside[0]
    assert report["outside_scope_reading"] == collection_overlap.OUTSIDE_SCOPE_READING


def test_outside_scope_is_empty_under_all_papers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_pace: None,
    capsys: pytest.CaptureFixture[str], inspire_payloads: dict,
) -> None:
    mine = ["w%02d" % number for number in range(20)]
    theirs = ["x%02d" % number for number in range(20)]

    stub = FakeInspire({
        "fields=references": reference_payload(mine[:12] + theirs[:8]),
        "arxiv/1706.03621": inspire_payloads["inspire_record"],
    })
    monkeypatch.setattr(inspire_lookup, "fetch_record", stub)
    write_store(tmp_path, {"mine": mine, "theirs": theirs})

    _, report = run(["1706.03621", "--all-papers", "--literature-root", str(tmp_path)], capsys)

    assert report["scope"]["mode"] == "all_papers"
    assert report["outside_scope"] == []
    assert report["scope"]["outside_scope_papers"] == 0


def test_an_unknown_scope_slug_exits_rather_than_scoring_an_empty_scope(
    fake: FakeInspire, collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A typo would empty the scope, and every candidate would then read `low`."""
    code, report = run(
        ["1706.03621", "--scope", "no_such_paper", "--literature-root", str(collection)],
        capsys,
    )

    assert code == 2
    assert report["band"] is None
    assert report["unknown_papers"] == ["no_such_paper"]
    # The check runs before anything is sent, so a typo costs no request.
    assert fake.paths == []


def test_the_report_names_its_own_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, no_pace: None,
    capsys: pytest.CaptureFixture[str], inspire_payloads: dict,
) -> None:
    """A band with no scope beside it cannot be checked later."""
    stub = FakeInspire({
        "fields=references": reference_payload(["w00", "w01"]),
        "arxiv/1706.03621": inspire_payloads["inspire_record"],
    })
    monkeypatch.setattr(inspire_lookup, "fetch_record", stub)
    write_store(tmp_path, {"mine": ["w00", "w01"], "theirs": ["x00"]})

    _, report = run(["1706.03621", "--scope", "mine", "--literature-root", str(tmp_path)], capsys)

    assert report["scope"] == {
        "mode": "working_set",
        "papers": ["mine"],
        "papers_in_collection": 2,
        "outside_scope_papers": 1,
    }
