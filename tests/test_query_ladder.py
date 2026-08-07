"""The queries the ladder builds, and when it climbs.

Every assertion on a query string here guards a way that arXiv answers a wrong
query with silence rather than an error: a mis-scoped term, a double-escaped
parenthesis and an unknown category all return results, or none, without ever
saying that the query was wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import arxiv_discover
from arxiv_discover import Options
from conftest import FakeFetch, first_entry_only


def options(topic: str = "meson exchange in the quasielastic peak", **kwargs) -> Options:  # noqa: ANN003
    kwargs.setdefault("literature_root", Path("nowhere"))
    return Options(topic=topic, **kwargs)


# --------------------------------------------------------------------------
# terms
# --------------------------------------------------------------------------


def test_terms_keep_the_words_that_choose_a_paper() -> None:
    """`measurement` and `effect` are stopwords for a tag and not for a search.

    `reference_store.TAG_STOPWORDS` drops them to keep a directory name short.
    Reusing that set here would delete the part of the question that says what
    kind of paper to look for.
    """
    terms = arxiv_discover.topic_terms("the measurement of nuclear effects")

    assert "measurement" in terms
    assert "effects" in terms


def test_terms_drop_the_words_of_a_question() -> None:
    terms = arxiv_discover.topic_terms("how does the axial mass change between targets")

    assert terms == ["axial", "mass", "change", "targets"]


def test_terms_drop_latex_and_punctuation() -> None:
    terms = arxiv_discover.topic_terms(r"the $C_5^A$ form factor, \emph{revisited}")

    assert "emph" not in terms
    assert "form" in terms and "factor" in terms


def test_terms_keep_their_order_and_drop_repeats() -> None:
    terms = arxiv_discover.topic_terms("neutrino scattering and neutrino oscillation")

    assert terms == ["neutrino", "scattering", "oscillation"]


def test_terms_stop_at_twelve() -> None:
    terms = arxiv_discover.topic_terms(" ".join("word%d" % number for number in range(30)))

    assert len(terms) == arxiv_discover.MAX_TERMS


# --------------------------------------------------------------------------
# the strict query
# --------------------------------------------------------------------------


def test_every_term_carries_its_own_scope() -> None:
    """A bare space ends the scope, and the rest of the query goes unscoped.

    `abs:quasielastic neutrino` finds 41 649 papers where the scoped form finds
    a few thousand, and arXiv reports no error for either.
    """
    query = arxiv_discover.build_strict_query(["meson", "exchange"], options())

    assert query == "abs:meson AND abs:exchange"


def test_the_strict_query_never_quotes_a_phrase() -> None:
    """A quoted abstract phrase finds 6 papers where the AND finds 135."""
    query = arxiv_discover.build_strict_query(["quasielastic", "neutrino"], options())

    assert '"' not in query


def test_one_category_needs_no_group() -> None:
    query = arxiv_discover.build_strict_query(["meson"], options(categories=["hep-ph"]))

    assert query == "abs:meson AND cat:hep-ph"


def test_several_categories_are_an_or_group() -> None:
    query = arxiv_discover.build_strict_query(
        ["meson"], options(categories=["hep-ph", "nucl-th"])
    )

    assert query == "abs:meson AND (cat:hep-ph OR cat:nucl-th)"


def test_parentheses_go_in_as_characters() -> None:
    """urlencode escapes them on the way out.

    The API manual writes `%28`, which arrives double-escaped and matches almost
    nothing: 4 papers against 1 494 for the same query with characters.
    """
    query = arxiv_discover.build_broad_query(["meson", "exchange"], options())

    assert query.startswith("(all:meson OR all:exchange)")
    assert "%28" not in query


def test_since_opens_at_that_year_and_runs_to_now() -> None:
    query = arxiv_discover.build_strict_query(["meson"], options(since=2015))

    assert "submittedDate:[201501010000 TO " in query


def test_since_is_not_widened_by_a_year() -> None:
    """`arxiv_search` widens its --year; a chosen window is not a guess."""
    query = arxiv_discover.build_strict_query(["meson"], options(since=2015))

    assert "201401010000" not in query


# --------------------------------------------------------------------------
# climbing the ladder
# --------------------------------------------------------------------------


def test_a_good_topic_stops_at_the_strict_rung(
    feed_quasielastic: str, no_sleep: None
) -> None:
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(), fetch=fetch)

    assert len(fetch.queries) == 1
    assert fetch.queries[0].startswith("abs:")
    assert all(result["found_by"] == "strict" for result in report["results"])


def test_a_narrow_topic_climbs_to_the_broad_rung(
    feed_empty: str, feed_quasielastic: str, no_sleep: None
) -> None:
    fetch = FakeFetch([feed_empty, feed_quasielastic])

    report = arxiv_discover.search(options(), fetch=fetch)

    assert len(fetch.queries) == 2
    assert fetch.queries[1].startswith("(all:")
    assert report["results"]
    assert all(result["found_by"] == "broad" for result in report["results"])


def test_the_broad_rung_adds_to_the_strict_one_rather_than_replacing_it(
    feed_quasielastic: str, no_sleep: None
) -> None:
    """A paper that carried every term stays, and keeps its rung."""
    fetch = FakeFetch([first_entry_only(feed_quasielastic), feed_quasielastic])

    report = arxiv_discover.search(options(), fetch=fetch)
    rungs = {result["arxiv_id"]: result["found_by"] for result in report["results"]}

    assert len(fetch.queries) == 2
    assert list(rungs.values()).count("strict") == 1
    assert len(rungs) > 1


def test_a_paper_is_never_reported_twice(
    feed_quasielastic: str, no_sleep: None
) -> None:
    """Both rungs return the same feed; the merge must not duplicate it."""
    fetch = FakeFetch([feed_quasielastic, feed_quasielastic])
    fetch.feeds = [feed_quasielastic]

    report = arxiv_discover.search(options(max_results=50), fetch=fetch)
    identifiers = [result["arxiv_id"] for result in report["results"]]

    assert len(identifiers) == len(set(identifiers))


def test_the_ladder_asks_arxiv_for_more_than_it_returns(
    feed_quasielastic: str, no_sleep: None
) -> None:
    fetch = FakeFetch([feed_quasielastic])

    arxiv_discover.search(options(max_results=3), fetch=fetch)

    assert fetch.max_results == [arxiv_discover.CANDIDATES]


def test_max_results_trims_the_report(feed_quasielastic: str, no_sleep: None) -> None:
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(max_results=2), fetch=fetch)

    assert len(report["results"]) == 2
    assert report["ranking"]["candidates"] == 8


def test_nothing_found_is_a_report_and_not_an_error(
    feed_empty: str, no_sleep: None
) -> None:
    fetch = FakeFetch([feed_empty])

    report = arxiv_discover.search(options(), fetch=fetch)

    assert report["results"] == []
    assert report["counts"]["total"] == 0


def test_a_topic_of_only_stopwords_is_refused() -> None:
    with pytest.raises(ValueError, match="no word to search for"):
        arxiv_discover.search(options(topic="what is it about"), fetch=FakeFetch([""]))


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------


def test_the_abstract_is_cut_only_for_the_reader(
    feed_quasielastic: str, no_sleep: None
) -> None:
    """The ranking reads the whole abstract; the report shows 400 characters."""
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(), fetch=fetch)

    assert all(len(result["summary"]) <= 400 for result in report["results"])
    assert any(result["summary"].endswith("…") for result in report["results"])


def test_a_long_author_list_collapses_with_its_count(
    feed_quasielastic: str, no_sleep: None
) -> None:
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(), fetch=fetch)

    for result in report["results"]:
        assert len(result["authors"]) <= arxiv_discover.AUTHORS_SHOWN
        assert result["authors_total"] >= len(result["authors"])


def test_the_report_names_every_query_that_ran(
    feed_quasielastic: str, no_sleep: None
) -> None:
    fetch = FakeFetch([feed_quasielastic])

    report = arxiv_discover.search(options(), fetch=fetch)

    assert [item["search_query"] for item in report["query"]["queries"]] == fetch.queries
    assert report["query"]["terms"]


def test_both_rungs_are_reported_when_both_ran(
    feed_empty: str, feed_quasielastic: str, no_sleep: None
) -> None:
    """A result says which rung found it, so both rungs must be on the record."""
    fetch = FakeFetch([feed_empty, feed_quasielastic])

    report = arxiv_discover.search(options(), fetch=fetch)

    assert [item["rung"] for item in report["query"]["queries"]] == ["strict", "broad"]
    assert [item["search_query"] for item in report["query"]["queries"]] == fetch.queries
