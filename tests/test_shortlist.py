"""What one search costs at INSPIRE, and how the shortlist is described and ordered.

Nothing here calls arXiv or INSPIRE. `FakeFetch` answers the arXiv requests and
`FakeInspire` answers the one INSPIRE request, so every assertion below is about
the script and never about what a source held on the day.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import arxiv_discover
import inspire_lookup
import references
from arxiv_discover import Options
from conftest import DATA, FakeFetch, FakeInspire


def options(topic: str = "meson exchange in the quasielastic peak", **kwargs) -> Options:  # noqa: ANN003
    kwargs.setdefault("literature_root", Path("nowhere"))
    kwargs.setdefault("max_results", 15)
    return Options(topic=topic, **kwargs)


@pytest.fixture
def shortlist_payload() -> dict:
    return json.loads((DATA / "inspire_shortlist.json").read_text(encoding="utf-8"))


@pytest.fixture
def inspire(
    monkeypatch: pytest.MonkeyPatch, shortlist_payload: dict, no_pace: None
) -> FakeInspire:
    stub = FakeInspire({"literature?": shortlist_payload})
    monkeypatch.setattr(inspire_lookup, "fetch_record", stub)
    monkeypatch.setattr(references.inspire_lookup, "fetch_record", stub)
    return stub


@pytest.fixture
def silent_inspire(monkeypatch: pytest.MonkeyPatch, no_pace: None) -> FakeInspire:
    """INSPIRE holding no record for any candidate: every search answers 404."""
    stub = FakeInspire({})
    monkeypatch.setattr(inspire_lookup, "fetch_record", stub)
    monkeypatch.setattr(references.inspire_lookup, "fetch_record", stub)
    return stub


# --------------------------------------------------------------------------
# the cost
# --------------------------------------------------------------------------


def test_the_shortlist_costs_one_inspire_request(
    feed_quasielastic: str, no_sleep: None, inspire: FakeInspire
) -> None:
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(), fetch=fetch)
    query = inspire.query()

    assert len(inspire.paths) == 1
    for result in report["results"]:
        assert 'arxiv:"%s"' % result["arxiv_id"] in query
    assert report["enrichment"]["requested"] == 8


def test_a_silent_inspire_leaves_the_counts_null(
    feed_quasielastic: str, no_sleep: None, silent_inspire: FakeInspire
) -> None:
    """A source that says nothing is not a count of zero."""
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(), fetch=fetch)

    assert report["results"]
    assert all(result["citation_count"] is None for result in report["results"])
    assert report["enrichment"]["matched"] == 0
    assert report["enrichment"]["note"]


def test_a_candidate_inspire_does_not_hold_keeps_its_arxiv_facts(
    feed_quasielastic: str, no_sleep: None, inspire: FakeInspire
) -> None:
    """1902.06338 is absent from the payload, and still carries its own length."""
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(max_results=50), fetch=fetch)
    absent = next(
        result for result in report["results"] if result["arxiv_id"] == "1902.06338"
    )

    assert absent["citation_count"] is None
    assert absent["inspire_id"] is None
    assert absent["pages"] == 6
    assert absent["pages_source"] == "arxiv_comment"
    assert report["enrichment"]["matched"] == 7


# --------------------------------------------------------------------------
# the order
# --------------------------------------------------------------------------


def test_sort_cited_orders_by_the_citation_count(
    feed_quasielastic: str, no_sleep: None, inspire: FakeInspire
) -> None:
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(sort="cited", max_results=50), fetch=fetch)
    counts = [result["citation_count"] for result in report["results"]]

    assert counts[0] == 645
    assert [count for count in counts if count is not None] == sorted(
        (count for count in counts if count is not None), reverse=True
    )
    assert counts[-1] is None


def test_sort_recent_orders_by_the_date(
    feed_quasielastic: str, no_sleep: None, inspire: FakeInspire
) -> None:
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(sort="recent", max_results=50), fetch=fetch)
    years = [result["year"] for result in report["results"]]

    assert years == sorted(years, reverse=True)
    assert years[0] == 2021


def test_sort_cited_without_inspire_keeps_the_relevance_order(
    feed_quasielastic: str, no_sleep: None, silent_inspire: FakeInspire
) -> None:
    fetch = FakeFetch([feed_quasielastic])

    relevance = arxiv_discover.search(options(max_results=50), fetch=FakeFetch([feed_quasielastic]))
    report = arxiv_discover.search(options(sort="cited", max_results=50), fetch=fetch)

    assert [result["arxiv_id"] for result in report["results"]] == [
        result["arxiv_id"] for result in relevance["results"]
    ]
    assert report["ranking"]["sort"] == "relevance"
    assert "citation count" in (report["ranking"]["note"] or "")


def test_every_result_keeps_its_relevance_rank(
    feed_quasielastic: str, no_sleep: None, inspire: FakeInspire
) -> None:
    """A re-sort re-orders the shortlist. It never renumbers it."""
    fetch = FakeFetch([feed_quasielastic])

    relevance = arxiv_discover.search(
        options(max_results=50), fetch=FakeFetch([feed_quasielastic])
    )
    report = arxiv_discover.search(options(sort="cited", max_results=50), fetch=fetch)

    ranks = {result["arxiv_id"]: result["relevance_rank"] for result in relevance["results"]}
    assert ranks == {
        result["arxiv_id"]: result["relevance_rank"] for result in report["results"]
    }
    assert sorted(ranks.values()) == list(range(1, len(ranks) + 1))


# --------------------------------------------------------------------------
# the kind
# --------------------------------------------------------------------------


def test_kind_review_keeps_the_review_and_counts_what_it_dropped(
    feed_quasielastic: str, no_sleep: None, inspire: FakeInspire
) -> None:
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(kind="review", max_results=50), fetch=fetch)
    filtered = report["kind_filter"]

    assert {result["arxiv_id"] for result in report["results"]} == {"1201.3673", "1010.1708"}
    assert all(result["kind"] == "review" for result in report["results"])
    assert filtered["requested"] == "review"
    assert filtered["kept"] == 2
    assert filtered["dropped_not_review"] + filtered["dropped_unknown"] == 6


def test_kind_any_drops_nothing(
    feed_quasielastic: str, no_sleep: None, inspire: FakeInspire
) -> None:
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(max_results=50), fetch=fetch)

    assert report["kind_filter"] is None
    assert len(report["results"]) == 8


def test_a_review_preprint_escapes_the_filter(
    feed_quasielastic: str, no_sleep: None, silent_inspire: FakeInspire
) -> None:
    """No venue and no document type means unknown, and the filter drops it.

    This is why the skill tells the agent to run the search again with
    `--kind any` before reporting that the field holds no review.
    """
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(kind="review", max_results=50), fetch=fetch)

    assert report["results"] == []
    assert report["kind_filter"]["dropped_unknown"] > 0
