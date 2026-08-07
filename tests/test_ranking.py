"""Coverage, and the order the cross-encoder puts the candidates in."""

from __future__ import annotations

import builtins

import pytest

import rerank


def entry(title: str, summary: str = "") -> dict:
    return {"title": title, "summary": summary}


# --------------------------------------------------------------------------
# coverage
# --------------------------------------------------------------------------


def test_coverage_counts_the_terms_the_paper_carries() -> None:
    share, missing = rerank.coverage(
        ["meson", "exchange", "quasielastic"],
        "Meson-exchange currents",
        "We compute the quasielastic peak.",
    )

    assert share == 1.0
    assert missing == []


def test_coverage_names_what_the_paper_leaves_alone() -> None:
    share, missing = rerank.coverage(
        ["meson", "exchange", "lattice"],
        "Meson-exchange currents",
        "We compute the quasielastic peak.",
    )

    assert share == pytest.approx(2 / 3)
    assert missing == ["lattice"]


def test_coverage_survives_the_stemming_arxiv_applies() -> None:
    """arXiv returns a paper saying `scatter` for a search on `scattering`.

    Reporting that term as missing would tell a reader something untrue about
    a paper the search itself considered a match.
    """
    _, missing = rerank.coverage(["scattering", "neutrinos"], "", "neutrino scatter data")

    assert missing == []


def test_coverage_does_not_match_on_a_short_prefix() -> None:
    """`ion` must not take `ionisation`; below four letters a prefix is noise."""
    _, missing = rerank.coverage(["ion"], "", "ionisation of the target")

    assert missing == ["ion"]


def test_coverage_of_no_terms_is_zero_rather_than_an_error() -> None:
    assert rerank.coverage([], "a title", "an abstract") == (0.0, [])


# --------------------------------------------------------------------------
# the order, with no cross-encoder
# --------------------------------------------------------------------------


@pytest.fixture
def no_flashrank(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `import flashrank` fail, as it does where it is not installed."""
    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if name == "flashrank":
            raise ImportError("No module named 'flashrank'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_rank_without_flashrank_orders_by_coverage(no_flashrank: None) -> None:
    entries = [
        entry("Neutrino oscillation", "mixing angles"),
        entry("Meson exchange currents", "the quasielastic peak"),
    ]

    ordered, backend, note = rerank.rank(
        "meson exchange quasielastic", ["meson", "exchange", "quasielastic"], entries
    )

    assert backend == "coverage"
    assert note is not None and "not installed" in note
    assert ordered[0]["title"] == "Meson exchange currents"
    assert ordered[0]["score"] == 1.0


def test_rank_without_flashrank_never_raises(no_flashrank: None) -> None:
    ordered, backend, _ = rerank.rank("anything", ["term"], [entry("a", "b")])

    assert backend == "coverage"
    assert len(ordered) == 1


def test_a_failed_model_load_falls_back_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rerank, "load_ranker", lambda: (None, "the model could not be loaded (disk full)")
    )

    _, backend, note = rerank.rank("q", ["term"], [entry("a", "b")])

    assert backend == "coverage"
    assert note is not None and "could not be loaded" in note


def test_a_model_that_fails_while_scoring_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """The model loads, then dies on the batch. Coverage still answers."""
    monkeypatch.setattr(rerank, "load_ranker", lambda: (object(), None))
    monkeypatch.setattr(rerank, "relevance_scores", lambda *args: None)

    _, backend, note = rerank.rank("q", ["term"], [entry("a", "b")])

    assert backend == "coverage"
    assert note is not None and "failed while scoring" in note


def test_every_entry_carries_its_explanation(no_flashrank: None) -> None:
    """Whichever backend ordered them, coverage and missing_terms are there."""
    entries = [entry("Lattice QCD", "form factors")]

    ordered, _, _ = rerank.rank("meson exchange", ["meson", "exchange"], entries)

    assert ordered[0]["coverage"] == 0.0
    assert ordered[0]["missing_terms"] == ["meson", "exchange"]


def test_the_arxiv_order_breaks_a_tie(no_flashrank: None) -> None:
    """Equal coverage keeps the order arXiv returned rather than shuffling."""
    entries = [entry("first", "nothing"), entry("second", "nothing")]

    ordered, _, _ = rerank.rank("meson", ["meson"], entries)

    assert [item["title"] for item in ordered] == ["first", "second"]


# --------------------------------------------------------------------------
# the order, with the cross-encoder
# --------------------------------------------------------------------------


def test_the_cross_encoder_decides_the_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """A paper that answers the question outranks one that repeats its words.

    Coverage cannot make this call: both entries carry every term. That is the
    whole reason the cross-encoder is here, so the test states it directly and
    does not depend on the real model to do so.
    """
    monkeypatch.setattr(rerank, "load_ranker", lambda: (object(), None))
    monkeypatch.setattr(rerank, "relevance_scores", lambda ranker, topic, entries: [0.1, 0.9])

    entries = [
        entry("Meson exchange currents: a bibliography", "meson exchange currents listed"),
        entry("Meson exchange currents in the quasielastic peak", "we compute them"),
    ]

    ordered, backend, note = rerank.rank("meson exchange", ["meson", "exchange"], entries)

    assert backend == "flashrank:ms-marco-MiniLM-L-12-v2"
    assert note is None
    assert ordered[0]["title"].endswith("quasielastic peak")
    assert ordered[0]["score"] == 0.9
    assert ordered[0]["coverage"] == 1.0
