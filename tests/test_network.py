"""The assumptions about arXiv that the query builder rests on.

Every one of these can change at arXiv rather than here, and each fails
silently when it does: arXiv answers a wrong query with results, or with none,
and never with an error. Deselected by default, because they call a live API
that asks for three seconds between requests:

    .venv/bin/python -m pytest -m network
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from lit import arxiv_discover
from lit import rerank
from lit.arxiv_search import fetch_by_ids, fetch_feed

pytestmark = pytest.mark.network

TOTAL = re.compile(r"totalResults>(\d+)<")


@pytest.fixture(autouse=True)
def courtesy() -> None:
    """arXiv asks for three seconds between calls. Wait it out, every test."""
    time.sleep(3.0)


def total(search_query: str) -> int:
    found = TOTAL.search(fetch_feed(search_query, 1))
    assert found is not None, "arXiv did not report a result count"
    return int(found.group(1))


def test_a_quoted_phrase_is_far_narrower_than_the_same_words_anded() -> None:
    """The reason the strict rung never quotes a phrase.

    When these two converge, a quoted phrase becomes the better query and the
    strict rung should be reconsidered.
    """
    phrase = total('abs:"quasielastic neutrino scattering" AND cat:hep-ph')
    anded = total("abs:quasielastic AND abs:neutrino AND abs:scattering AND cat:hep-ph")

    assert phrase * 5 < anded


def test_a_space_in_a_field_scope_unscopes_the_rest() -> None:
    """The reason every term carries its own `abs:` prefix."""
    scoped = total("abs:quasielastic AND abs:neutrino")
    unscoped = total("abs:quasielastic neutrino")

    assert unscoped > scoped * 5


def test_an_unknown_field_gives_no_results_and_no_error() -> None:
    """The reason a category is checked here before it is sent."""
    assert total("abstract:neutrino") == 0


def test_a_category_does_not_include_its_subcategories() -> None:
    """The reason `--category` is documented as exact."""
    parent = total("abs:neutrino AND cat:astro-ph")
    child = total("abs:neutrino AND cat:astro-ph.HE")

    assert parent > 0 and child > 0
    assert parent != child


def test_arxiv_states_the_year_that_a_number_does_not() -> None:
    """The reason `fill_from_arxiv` asks, rather than reading the digits.

    2004.06601 opens with 2004 and is from 2020. hep-ph/0207172 opens with 02
    and is from 2002. Only the date that arXiv reports says either.
    """
    records = {entry["arxiv_id"]: entry for entry in fetch_by_ids(["2004.06601", "hep-ph/0207172"])}

    assert records["2004.06601"]["year"] == 2020
    assert records["hep-ph/0207172"]["year"] == 2002


def test_arxiv_answers_an_unknown_number_with_no_record() -> None:
    """The reason a caller gets fewer records than it asked for, and no wrong one."""
    assert fetch_by_ids(["9999.99999"]) == []


def test_the_index_stems_its_terms() -> None:
    """The reason `term_matches` accepts a prefix, and no plural is ever added."""
    assert total("abs:neutrino") == total("abs:neutrinos")


def test_a_real_search_answers_and_ranks(tmp_path: Path) -> None:
    """End to end against the live API, with no collection to check against."""
    report = arxiv_discover.search(
        arxiv_discover.Options(
            topic="how meson exchange currents change the quasielastic neutrino cross section",
            categories=["hep-ph"],
            max_results=5,
            literature_root=tmp_path / "nowhere",
        )
    )

    assert report["results"]
    assert report["counts"]["new"] == len(report["results"])
    assert report["ranking"]["backend"].startswith("flashrank:")
    assert report["results"][0]["score"] > report["results"][-1]["score"]


def test_the_cross_encoder_reads_the_question_and_not_the_words() -> None:
    """The real model, on a pair coverage alone cannot separate.

    Both carry every term. Only one answers the question.
    """
    ranker, note = rerank.load_ranker()
    assert ranker is not None, note

    entries = [
        {"title": "Meson exchange currents: a bibliography",
         "summary": "A list of papers on meson exchange currents in nuclei."},
        {"title": "Meson exchange currents in quasielastic neutrino scattering",
         "summary": "We compute how meson exchange currents change the cross section."},
    ]
    ordered, backend, _ = rerank.rank(
        "how do meson exchange currents change the cross section",
        ["meson", "exchange", "currents"],
        entries,
    )

    assert backend.startswith("flashrank:")
    assert all(entry["coverage"] == 1.0 for entry in ordered)
    assert ordered[0]["title"].endswith("quasielastic neutrino scattering")
