"""Coverage, and the order the cross-encoder puts the candidates in."""

from __future__ import annotations

import builtins
import sys
import types

import pytest

from lit import rerank


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


def test_the_prefix_match_begins_at_four_letters() -> None:
    """The boundary `MIN_PREFIX` names, stated as a relationship and not a value.

    Four letters are a stem worth trusting; three are a coincidence. Both halves
    are here so that changing `MIN_PREFIX` fails a test that says what changed.
    """
    assert rerank.MIN_PREFIX == 4

    _, four = rerank.coverage(["kaon"], "", "kaons in the final state")
    _, three = rerank.coverage(["pio"], "", "pion production")

    assert four == []
    assert three == ["pio"]


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

    _, backend, note = rerank.rank("q", ["term"], [entry("term", "term")])

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
# what the cross-encoder is asked to read
# --------------------------------------------------------------------------


def test_a_candidate_carrying_almost_nothing_is_not_scored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scoring is the whole cost of a search: 100 pairs take about 8 seconds.

    The broad rung asks arXiv for any term and gets back papers that carry one.
    Reading those is most of the work and none of the answer.
    """
    seen = []

    def record(ranker, topic, entries):  # noqa: ANN001, ANN202
        seen.extend(entry["title"] for entry in entries)
        return [0.5] * len(entries)

    monkeypatch.setattr(rerank, "load_ranker", lambda: (object(), None))
    monkeypatch.setattr(rerank, "relevance_scores", record)

    entries = [
        entry("meson exchange quasielastic", "all three terms"),
        entry("cosmology", "one term only: meson"),
    ]
    rerank.rank("meson exchange quasielastic", ["meson", "exchange", "quasielastic"], entries)

    assert seen == ["meson exchange quasielastic"]


def test_an_unscored_candidate_is_still_reported_and_ranks_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skipping the model must not drop the paper from the answer.

    Its coverage and its score are on different scales, so it sorts after every
    paper the model read rather than being compared against one.
    """
    monkeypatch.setattr(rerank, "load_ranker", lambda: (object(), None))
    monkeypatch.setattr(rerank, "relevance_scores", lambda ranker, topic, entries: [0.01])

    entries = [
        entry("thin", "meson"),
        entry("meson exchange quasielastic", "all three"),
    ]
    ordered, _, _ = rerank.rank(
        "meson exchange quasielastic", ["meson", "exchange", "quasielastic"], entries
    )

    assert [item["title"] for item in ordered] == ["meson exchange quasielastic", "thin"]
    assert ordered[0]["score"] == 0.01
    assert len(ordered) == 2


def test_nothing_worth_reading_falls_back_rather_than_calling_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args):  # noqa: ANN002, ANN202
        raise AssertionError("the model must not be called with an empty batch")

    monkeypatch.setattr(rerank, "load_ranker", lambda: (object(), None))
    monkeypatch.setattr(rerank, "relevance_scores", explode)

    ordered, backend, _ = rerank.rank("meson exchange", ["meson", "exchange"], [entry("x", "y")])

    assert backend == "coverage"
    assert len(ordered) == 1


# --------------------------------------------------------------------------
# fetching the model
# --------------------------------------------------------------------------


def test_the_model_is_fetched_in_a_separate_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """macOS crashes a fork from a process that already holds native threads.

    Downloading starts a progress bar whose lock is a multiprocessing
    semaphore, and its resource tracker starts by fork and exec. The tokenizer
    and the model have put native threads in the process by then, so the child
    dies before exec: "crashed on child side of fork pre-exec". Loading a model
    already on disk starts neither, so the fetch has to happen elsewhere.
    """
    calls = []
    monkeypatch.setattr(rerank, "model_is_cached", lambda: False)
    monkeypatch.setattr(rerank, "download_model", lambda: calls.append("fetched"))

    class Ranker:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            calls.append("loaded")

    monkeypatch.setitem(sys.modules, "flashrank", types.SimpleNamespace(Ranker=Ranker))

    ranker, note = rerank.load_ranker()

    assert calls == ["fetched", "loaded"], "the fetch must finish before the load"
    assert ranker is not None
    assert note is None


def test_a_cached_model_is_not_fetched_again(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> None:
        raise AssertionError("a cached model must not be downloaded again")

    monkeypatch.setattr(rerank, "model_is_cached", lambda: True)
    monkeypatch.setattr(rerank, "download_model", explode)
    monkeypatch.setitem(
        sys.modules, "flashrank", types.SimpleNamespace(Ranker=lambda **kwargs: object())
    )

    ranker, note = rerank.load_ranker()

    assert ranker is not None and note is None


def test_a_failed_download_falls_back_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rerank, "model_is_cached", lambda: False)
    monkeypatch.setattr(rerank, "download_model", lambda: "the network is unreachable")
    monkeypatch.setitem(
        sys.modules, "flashrank", types.SimpleNamespace(Ranker=lambda **kwargs: object())
    )

    ranker, note = rerank.load_ranker()

    assert ranker is None
    assert note is not None
    assert "network is unreachable" in note and "coverage" in note


def test_a_download_that_stalls_reports_rather_than_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    def timeout(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise subprocess.TimeoutExpired(cmd="python", timeout=1)

    monkeypatch.setattr(rerank.subprocess, "run", timeout)

    reason = rerank.download_model(timeout_s=1)

    assert reason is not None and "longer than" in reason


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
