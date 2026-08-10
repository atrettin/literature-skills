"""Following the citations of a paper, forwards and backwards.

Nothing here calls INSPIRE. `FakeInspire` stands in for the one function every
request goes through, so a test can read the query that was sent and choose
what came back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import inspire_citations
import inspire_lookup
import references
from conftest import FakeInspire


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, inspire_payloads: dict, no_pace: None) -> FakeInspire:
    """INSPIRE answering the paper, its citers, its references and their records."""
    answers = {
        "arxiv/1706.03621": inspire_payloads["inspire_record"],
        "doi/10.1016": inspire_payloads["inspire_record"],
        "literature/1599542": inspire_payloads["inspire_record"],
        "refersto": inspire_payloads["inspire_refersto"],
        "fields=references": inspire_payloads["inspire_references"],
        "recid+590543": inspire_payloads["inspire_recids"],
    }
    stub = FakeInspire(answers)
    monkeypatch.setattr(inspire_lookup, "fetch_record", stub)
    monkeypatch.setattr(references.inspire_lookup, "fetch_record", stub)
    return stub


# --------------------------------------------------------------------------
# the papers that cite this one
# --------------------------------------------------------------------------


def test_the_citing_search_asks_inspire_who_refers_to_the_record(
    fake: FakeInspire, collection: Path
) -> None:
    report = inspire_citations.citing("1599542", "mostcited", 20, collection)

    assert fake.query() == "refersto recid 1599542"
    assert fake.params()["sort"] == "mostcited"
    assert fake.params()["size"] == "20"
    assert report["source"] == "inspire"


def test_the_sort_is_the_caller_s(fake: FakeInspire, collection: Path) -> None:
    inspire_citations.citing("1599542", "mostrecent", 5, collection)

    assert fake.params()["sort"] == "mostrecent"


def test_the_total_says_how_many_were_left_behind(
    fake: FakeInspire, collection: Path
) -> None:
    """Three of three thousand is a different answer from three of three."""
    report = inspire_citations.citing("1599542", "mostcited", 20, collection)

    assert report["total"] == 3141
    assert report["returned"] == 3


def test_each_citing_paper_says_what_the_collection_knows_of_it(
    fake: FakeInspire, collection: Path
) -> None:
    report = inspire_citations.citing("1599542", "mostcited", 20, collection)
    by_title = {result["arxiv_id"]: result for result in report["results"]}

    # Held in full: the collection has its chapters on disk.
    assert by_title["2307.09241"]["held_as"] == "jeong_2023_shallow_deep_inelastic"
    # Cited by a paper here, but not held: a tag answers for it.
    assert by_title["hep-ph/0207172"]["held_as"] is None
    assert by_title["hep-ph/0207172"]["known_as"] == (
        "lipari_2002_neutrino_oscillation_neutrino_cross"
    )
    # Neither: a paper the collection does not know at all.
    assert by_title["2501.00001"]["held_as"] is None
    assert by_title["2501.00001"]["known_as"] is None

    assert report["counts"] == {"held": 1, "cited": 1, "new": 1}


def test_an_author_list_is_collapsed(fake: FakeInspire, collection: Path) -> None:
    """A high-energy physics paper can carry three thousand authors."""
    report = inspire_citations.citing("1599542", "mostcited", 20, collection)
    many = next(item for item in report["results"] if item["arxiv_id"] == "2501.00001")

    assert len(many["authors"]) == inspire_citations.AUTHORS_SHOWN
    assert many["authors_total"] == 4


def test_an_abstract_is_cut_to_what_triage_needs(
    fake: FakeInspire, collection: Path
) -> None:
    """Enough of the abstract to choose a paper, never enough to cite it."""
    report = inspire_citations.citing("1599542", "mostcited", 20, collection)
    long_one = next(item for item in report["results"] if item["arxiv_id"] == "hep-ph/0207172")

    assert len(long_one["summary"]) <= inspire_citations.SUMMARY_CHARS
    assert long_one["summary"].endswith("…")


# --------------------------------------------------------------------------
# the works a paper draws on
# --------------------------------------------------------------------------


def test_a_held_paper_answers_out_of_the_store(
    fake: FakeInspire, collection: Path
) -> None:
    """What a held paper cites is already on disk. Asking INSPIRE buys nothing."""
    report = inspire_citations.cited_from_store(
        "jeong_2023_shallow_deep_inelastic", collection, 20
    )
    tags = {result["known_as"] for result in report["results"]}

    assert report["source"] == "store"
    assert fake.paths == []
    assert "lipari_2002_neutrino_oscillation_neutrino_cross" in tags
    assert "bodek_2008_axial_mass_quasielastic" in tags


def test_the_store_answers_for_a_work_no_identifier_reaches(
    fake: FakeInspire, collection: Path
) -> None:
    """A private communication has no DOI and no arXiv identifier, and is still cited."""
    report = inspire_citations.cited_from_store(
        "jeong_2023_shallow_deep_inelastic", collection, 20
    )
    tags = {result["known_as"] for result in report["results"]}

    assert "smith_2020_private_communication" in tags
    unconfirmed = next(
        item for item in report["results"] if item["known_as"] == "smith_2020_private_communication"
    )
    assert unconfirmed["verified"] is False


def test_a_paper_the_collection_does_not_hold_costs_its_reference_list(
    fake: FakeInspire, collection: Path
) -> None:
    report = inspire_citations.cited_from_inspire("1599542", collection, 20)

    assert fake.query(0) == "recid 1599542"
    assert "references" in fake.params(0)["fields"]
    # Two of the three entries name a record; the third is a bibliography line
    # the citing paper never keyed to one, and nothing can be looked up for it.
    assert report["total"] == 3
    assert report["returned"] == 2
    assert report["counts"]["held"] == 1


def test_the_references_come_back_most_cited_first(
    fake: FakeInspire, collection: Path
) -> None:
    """A paper prints its references in its own order, which ranks nothing."""
    report = inspire_citations.cited_from_inspire("1599542", collection, 20)

    counts = [result["citation_count"] for result in report["results"]]
    assert counts == sorted(counts, reverse=True)


def test_a_review_s_reference_list_is_capped(
    fake: FakeInspire, collection: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One batch of lookups, however many works the paper cites."""
    monkeypatch.setattr(inspire_citations, "CITED_FETCH_CAP", 1)
    fetched: list[list[str]] = []
    monkeypatch.setattr(
        inspire_citations.references,
        "fetch_by_recid",
        lambda recids: fetched.append(recids) or {},
    )

    inspire_citations.cited_from_inspire("1599542", collection, 20)

    assert fetched == [["590543"]]


# --------------------------------------------------------------------------
# the whole run
# --------------------------------------------------------------------------


def test_a_run_names_the_paper_and_answers_one_direction(
    fake: FakeInspire, collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    code = inspire_citations.main(
        ["1706.03621", "--literature-root", str(collection)]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["paper"]["recid"] == 1599542
    assert report["paper"]["citation_count"] == 812
    assert report["paper"]["held_as"] is None
    assert "citing" in report
    assert "cited" not in report


def test_both_directions_answer_separately(
    fake: FakeInspire, collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    inspire_citations.main(
        ["1706.03621", "--direction", "both", "--literature-root", str(collection)]
    )
    report = json.loads(capsys.readouterr().out)

    assert report["citing"]["source"] == "inspire"
    assert report["cited"]["source"] == "inspire"
    assert report["citing"]["results"] != report["cited"]["results"]


def test_a_paper_inspire_does_not_hold_fails_and_says_why(
    monkeypatch: pytest.MonkeyPatch, collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    monkeypatch.setattr(inspire_lookup, "fetch_record", FakeInspire({}))

    code = inspire_citations.main(["9999.99999", "--literature-root", str(collection)])
    report = json.loads(capsys.readouterr().out)

    assert code == 1
    assert report["found"] is False
    assert "9999.99999" in report["reason"]


def test_a_run_without_a_paper_is_refused(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert inspire_citations.main(["--literature-root", str(collection)]) == 2
