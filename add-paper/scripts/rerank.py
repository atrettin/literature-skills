#!/usr/bin/env python3
"""Order candidate papers by how well each one answers a research question.

Two signals, and the caller gets both:

    coverage    which of the question's terms the paper's text carries, and
                which it does not. Always computed. It is also the order used
                when no cross-encoder is installed.
    relevance   a cross-encoder reads the question and the abstract together
                and scores the pair. Needs `flashrank`, which is optional.

Coverage is what makes an answer auditable. A cross-encoder returns one number
and cannot say which half of a question a paper leaves alone; `missing_terms`
says exactly that, and a reader can check it against the abstract. So coverage
is not a fallback bolted on beside the model — it is the explanation, and the
model only reorders what coverage has already described.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arxiv_search import normalize_title  # noqa: E402

MODEL_NAME = "ms-marco-MiniLM-L-12-v2"

# flashrank caches a downloaded model under `cache_dir`, and its own default is
# /tmp — which macOS and most Linux distributions clear, so the model would be
# fetched again every few days. Keep it where a cache belongs.
MODEL_CACHE = Path.home() / ".cache" / "flashrank"

# An abstract runs to about 250 words, and the question is added in front of it.
# The model truncates whatever exceeds this, and what it truncates it cannot
# rank on.
MAX_TOKENS = 512

# Two words count as the same term when one is a prefix of the other and the
# shorter reaches this length: `scatter` for `scattering`, `neutrino` for
# `neutrinos`. Below it, prefixes stop being evidence — `ion` would take
# `ionisation`.
MIN_PREFIX = 4

# A candidate carrying less than this share of the question goes to the
# cross-encoder only if there is room to spare. The broad rung asks for any term
# and returns papers that carry one, and scoring those costs most of the run:
# 100 pairs take about 8 seconds, and a search reports 15. Measured over four
# real questions, the lowest coverage among the 15 the model actually chose was
# 0.56, so this leaves a wide margin. Raise it and the model reads fewer papers;
# above about 0.6 it stops reading papers it would have chosen.
MIN_COVERAGE = 0.34

# Fetching 21 MB. Long enough for a slow line, short enough that a stalled
# download reports a reason instead of holding the search open.
DOWNLOAD_TIMEOUT_S = 300.0


def say(message: str) -> None:
    """Tell a person at a terminal what is happening.

    Ranking a hundred abstracts takes several seconds and the first run also
    fetches a model, and stdout carries one JSON report and nothing else. So
    progress goes to stderr, and only when a person is there to read it: a
    caller that redirects the report into a file or another program gets the
    quiet output it expects.
    """
    if sys.stderr.isatty():
        print(message, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# coverage
# --------------------------------------------------------------------------


def document_words(*parts: str) -> set[str]:
    """The distinct words of a title and an abstract, normalized as terms are."""
    return set(normalize_title(" ".join(part for part in parts if part)).split())


def term_matches(term: str, words: set[str]) -> bool:
    """Does this term appear among these words, allowing for either stemming?

    arXiv stems its index, so a search for `scattering` returns a paper whose
    abstract only ever says `scatter`. Matching those two as unequal strings
    would report a term missing that the paper does in fact carry, and the
    caller shows `missing_terms` to a reader as fact.
    """
    if term in words:
        return True
    for word in words:
        shorter, longer = sorted((term, word), key=len)
        if len(shorter) >= MIN_PREFIX and longer.startswith(shorter):
            return True
    return False


def coverage(terms: list[str], title: str, abstract: str) -> tuple[float, list[str]]:
    """Return the share of terms the paper carries, and the ones it does not."""
    if not terms:
        return 0.0, []
    words = document_words(title, abstract)
    missing = [term for term in terms if not term_matches(term, words)]
    return (len(terms) - len(missing)) / len(terms), missing


# --------------------------------------------------------------------------
# the cross-encoder
# --------------------------------------------------------------------------


def model_is_cached() -> bool:
    return (MODEL_CACHE / MODEL_NAME).is_dir()


def download_model(timeout_s: float = DOWNLOAD_TIMEOUT_S) -> str | None:
    """Fetch the model in a process of its own. Returns a reason on failure.

    The download must not happen in the process that goes on to search, and the
    reason is a macOS fault rather than tidiness. Downloading starts a progress
    bar, whose lock is a multiprocessing semaphore, whose resource tracker
    starts by fork and exec. The model and its tokenizer have already put native
    threads in the process by then, and on macOS a fork from a multi-threaded
    process crashes the child before it reaches exec:

        *** multi-threaded process forked ***
        crashed on child side of fork pre-exec

    Loading a model that is already on disk starts neither the progress bar nor
    the semaphore, so a warm process is safe. Doing the download somewhere else
    is what makes every process warm.
    """
    program = (
        "from flashrank import Ranker; "
        "Ranker(model_name=%r, cache_dir=%r, max_length=%d, log_level='ERROR')"
        % (MODEL_NAME, str(MODEL_CACHE), MAX_TOKENS)
    )
    try:
        finished = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return "downloading the %s model took longer than %ds" % (MODEL_NAME, timeout_s)
    except OSError as error:
        return "the %s model could not be downloaded (%s)" % (MODEL_NAME, error)

    if finished.returncode != 0 or not model_is_cached():
        detail = (finished.stderr or "").strip().splitlines()
        return "downloading the %s model failed (%s)" % (
            MODEL_NAME,
            detail[-1] if detail else "exit %d" % finished.returncode,
        )
    return None


def load_ranker():  # noqa: ANN201 - the type belongs to an optional dependency
    """Build the cross-encoder, or explain why there is none.

    Returns (ranker, note). A note means no ranker: the dependency is absent,
    or the model could not be fetched. Neither is a failure of the search —
    the caller still has coverage — so nothing raises, and every reason is
    reported rather than swallowed.
    """
    try:
        from flashrank import Ranker  # pyright: ignore[reportMissingImports]
    except ImportError:
        return None, (
            "flashrank is not installed; ordered by term coverage. "
            "Install it with: pip install -r find-papers/requirements.txt"
        )

    if not model_is_cached():
        say("fetching the %s model; this happens once" % MODEL_NAME)
        failure = download_model()
        if failure:
            return None, "%s; ordered by term coverage" % failure

    try:
        MODEL_CACHE.mkdir(parents=True, exist_ok=True)
        ranker = Ranker(
            model_name=MODEL_NAME,
            cache_dir=str(MODEL_CACHE),
            max_length=MAX_TOKENS,
            # The default is INFO, and flashrank calls logging.basicConfig with
            # it, which turns on logging for everything else in the process too.
            log_level="ERROR",
        )
    except Exception as error:  # noqa: BLE001 - any failure here means no model
        return None, "the %s model could not be loaded (%s); ordered by term coverage" % (
            MODEL_NAME,
            error,
        )
    return ranker, None


def relevance_scores(ranker, topic: str, entries: list[dict]) -> list[float] | None:  # noqa: ANN001
    """Score each entry against the question. None when the model fails mid-run."""
    from flashrank import RerankRequest  # pyright: ignore[reportMissingImports]

    passages = [
        {"id": position, "text": "%s. %s" % (entry["title"], entry["summary"])}
        for position, entry in enumerate(entries)
    ]
    try:
        ranked = ranker.rerank(RerankRequest(query=topic, passages=passages))
    except Exception:  # noqa: BLE001 - a model that fails mid-run is not fatal
        return None

    scores = [0.0] * len(entries)
    for item in ranked:
        scores[int(item["id"])] = float(item["score"])
    return scores


# --------------------------------------------------------------------------
# the order
# --------------------------------------------------------------------------


def rank(topic: str, terms: list[str], entries: list[dict]) -> tuple[list[dict], str, str | None]:
    """Score and order the candidates. Returns (entries, backend, note).

    Every entry comes back carrying `coverage` and `missing_terms`, whichever
    backend ordered it, and `score` is the number the order was made on. The
    caller reports the backend, because a reader has to know whether a rank
    means "this paper answers the question" or only "this paper repeats its
    words".
    """
    for entry in entries:
        share, missing = coverage(terms, entry.get("title", ""), entry.get("summary", ""))
        entry["coverage"] = round(share, 4)
        entry["missing_terms"] = missing
        entry["ranked"] = share >= MIN_COVERAGE

    ranker, note = load_ranker()

    worth_reading = [entry for entry in entries if entry["ranked"]]
    scores = None
    if ranker is not None and worth_reading:
        say("ranking %d of %d candidates" % (len(worth_reading), len(entries)))
        scores = relevance_scores(ranker, topic, worth_reading)
        if scores is None:
            note = "the %s model failed while scoring; ordered by term coverage" % MODEL_NAME

    if scores is None:
        for entry in entries:
            entry["score"] = entry["coverage"]
        backend = "coverage"
    else:
        for entry, score in zip(worth_reading, scores):
            entry["score"] = round(score, 4)
        # A candidate the model never read keeps its coverage as a score. The
        # sort below puts every one of them after every paper the model did
        # read, so the two numbers are never compared against each other.
        for entry in entries:
            if not entry["ranked"]:
                entry["score"] = entry["coverage"]
        backend = "flashrank:%s" % MODEL_NAME

    # arXiv returned these in its own relevance order, which carries full text
    # and citation information this has no other access to. Keeping it as the
    # tie-break costs nothing and beats an arbitrary order among equal scores.
    ordered = sorted(
        enumerate(entries),
        key=lambda pair: (not pair[1]["ranked"], -pair[1]["score"], pair[0]),
    )
    return [entry for _, entry in ordered], backend, note
