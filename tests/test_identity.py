"""Which paper this is, and what the collection calls it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lit import arxiv_search
from lit import identity
from lit import reference_store


def metadata(**overrides) -> dict:
    base = {
        "arxiv_id": "2501.00001",
        "title": "A Small Paper on Quasielastic Scattering",
        "authors": ["Ada Lovelace", "Grace Hopper"],
        "submitted_year": 2025,
        "publication": {"doi": ""},
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# resolving the identifier
# --------------------------------------------------------------------------


def test_an_identifier_resolves_with_no_search(monkeypatch: pytest.MonkeyPatch) -> None:
    def never(*arguments, **keywords):
        raise AssertionError("an identifier needs no search")

    monkeypatch.setattr(arxiv_search, "run_search", never)

    assert identity.resolve("2307.09241") == "2307.09241"
    assert identity.resolve("arXiv:2307.09241v3") == "2307.09241"
    assert identity.resolve("hep-ph/0207172") == "hep-ph/0207172"


def hits(*matches: str) -> dict:
    return {
        "match": "exact" if matches.count("exact") == 1 else "approximate",
        "results": [
            {"arxiv_id": "2501.0000%d" % number, "title": "Paper %d" % number,
             "authors": ["A. Author"], "year": 2025, "doi": "", "journal_ref": "",
             "score": 1.0, "match": match}
            for number, match in enumerate(matches, start=1)
        ],
    }


def test_one_exact_hit_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arxiv_search, "run_search",
                        lambda *a, **k: hits("exact", "approximate"))

    assert identity.resolve(None, title="Paper 1") == "2501.00001"


def test_no_exact_hit_raises_with_the_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arxiv_search, "run_search",
                        lambda *a, **k: hits("approximate", "approximate"))

    with pytest.raises(identity.AmbiguousTitle) as raised:
        identity.resolve(None, title="Paper 1")

    assert len(raised.value.candidates) == 2
    assert raised.value.candidates[0]["arxiv_id"] == "2501.00001"


def test_two_exact_hits_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arxiv_search, "run_search", lambda *a, **k: hits("exact", "exact"))

    with pytest.raises(identity.AmbiguousTitle):
        identity.resolve(None, title="Paper 1")


def test_nothing_found_raises_with_no_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arxiv_search, "run_search",
                        lambda *a, **k: {"match": "none", "results": []})

    with pytest.raises(identity.AmbiguousTitle) as raised:
        identity.resolve(None, title="Nothing")

    assert raised.value.candidates == []


# --------------------------------------------------------------------------
# the slug
# --------------------------------------------------------------------------


def test_the_slug_takes_the_submission_year(collection: Path) -> None:
    """The identifier reads as a year and is not one. The submission date is."""
    slug = identity.derive_slug(metadata(arxiv_id="2004.06601"), collection)

    assert slug == "lovelace_2025_small_paper"


def test_the_slug_drops_the_stopwords_of_a_tag(collection: Path) -> None:
    slug = identity.derive_slug(
        metadata(title="A Study of the Effects on Neutrino Scattering"), collection
    )

    assert slug == "lovelace_2025_neutrino_scattering"


def test_a_store_record_gives_its_tag_as_the_slug(collection: Path) -> None:
    """A work the collection already cites keeps the name its citations use."""
    slug = identity.derive_slug(metadata(arxiv_id="hep-ph/0207172"), collection)

    assert slug == "lipari_2002_neutrino_oscillation_neutrino_cross"


def test_a_doi_finds_the_record_when_the_identifier_does_not(collection: Path) -> None:
    store = reference_store.load(collection)
    record = next(record for record in store
                  if record["tag"] == "lipari_2002_neutrino_oscillation_neutrino_cross")
    known = record["doi"]

    slug = identity.derive_slug(
        metadata(arxiv_id="2501.99999", publication={"doi": known}), collection
    )

    assert slug == "lipari_2002_neutrino_oscillation_neutrino_cross"


def test_a_name_another_work_holds_is_a_collision(collection: Path) -> None:
    taken = collection / "lovelace_2025_small_paper"
    (taken / "chapters").mkdir(parents=True)
    (taken / "INDEX.md").write_text(
        "| Field | Value |\n|---|---|\n"
        "| arXiv | [1111.11111](https://arxiv.org/abs/1111.11111) |\n",
        encoding="utf-8",
    )

    with pytest.raises(identity.TagCollision) as raised:
        identity.derive_slug(metadata(), collection)

    assert raised.value.slug == "lovelace_2025_small_paper"
    assert raised.value.held_arxiv_id == "1111.11111"
    # The suggestion carries one more title word, so it names a different paper.
    assert raised.value.suggested_slug == "lovelace_2025_small_paper_quasielastic"


def test_the_same_paper_again_is_not_a_collision(collection: Path) -> None:
    """A directory holding this same paper is a re-ingest, which --force answers."""
    taken = collection / "lovelace_2025_small_paper"
    taken.mkdir()
    (taken / "INDEX.md").write_text(
        "| Field | Value |\n|---|---|\n"
        "| arXiv | [2501.00001](https://arxiv.org/abs/2501.00001) |\n",
        encoding="utf-8",
    )

    assert identity.derive_slug(metadata(), collection) == "lovelace_2025_small_paper"
