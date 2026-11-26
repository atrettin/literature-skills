"""Which paper this is, and what the collection calls it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def test_an_identifier_resolves_normalised() -> None:
    assert identity.resolve("2307.09241") == "2307.09241"
    assert identity.resolve("arXiv:2307.09241v3") == "2307.09241"
    assert identity.resolve("hep-ph/0207172") == "hep-ph/0207172"


def test_anything_but_an_identifier_is_refused() -> None:
    """A title is settled with `litdb find --title`, before anything is added."""
    with pytest.raises(ValueError, match="find --title"):
        identity.resolve("A Small Paper on Quasielastic Scattering")


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
    taken.mkdir(parents=True)
    (taken / "paper.json").write_text(
        '{"slug": "lovelace_2025_small_paper", "arxiv_id": "1111.11111"}',
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
