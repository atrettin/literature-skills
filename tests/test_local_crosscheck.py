"""What the collection already holds, and what it already cites.

`test_mark_held_*` describe `reference_store.mark_held` as it behaves. They are
here so that moving the INDEX.md scan into `held_index` cannot change it: every
`held_as` in a real collection was written by that function, and a change would
silently unlink papers from the works that cite them.
"""

from __future__ import annotations

from pathlib import Path

import arxiv_discover
import reference_store


# --------------------------------------------------------------------------
# the INDEX.md scan
# --------------------------------------------------------------------------


def test_held_index_reads_arxiv_and_doi(collection: Path) -> None:
    index = reference_store.held_index(collection)

    assert index["arxiv:2307.09241"] == "jeong_2023_shallow_deep_inelastic"
    assert index["doi:10.1103/physrevd.108.113010"] == "jeong_2023_shallow_deep_inelastic"


def test_held_index_handles_a_paper_with_no_doi(collection: Path) -> None:
    """A preprint has an arXiv row and no DOI row. It is still held."""
    index = reference_store.held_index(collection)

    assert index["arxiv:nucl-th/0512004"] == "juszczak_2003_recoil_nucleon_spectrum"
    assert not any(value == "juszczak_2003_recoil_nucleon_spectrum"
                   for key, value in index.items() if key.startswith("doi:"))


def test_held_index_of_a_missing_root_is_empty(tmp_path: Path) -> None:
    assert reference_store.held_index(tmp_path / "nowhere") == {}


# --------------------------------------------------------------------------
# mark_held, unchanged by the move
# --------------------------------------------------------------------------


def test_mark_held_points_a_record_at_the_paper_holding_it(collection: Path) -> None:
    records = reference_store.load(collection)
    changed = reference_store.mark_held(records, collection)

    by_tag = {record["tag"]: record for record in records}
    assert by_tag["jeong_2023_shallow_deep_inelastic"]["held_as"] == (
        "jeong_2023_shallow_deep_inelastic"
    )
    assert changed == 1


def test_mark_held_leaves_a_work_the_collection_lacks(collection: Path) -> None:
    records = reference_store.load(collection)
    reference_store.mark_held(records, collection)

    by_tag = {record["tag"]: record for record in records}
    assert by_tag["lipari_2002_neutrino_oscillation_neutrino_cross"]["held_as"] is None
    assert by_tag["bodek_2008_axial_mass_quasielastic"]["held_as"] is None


def test_mark_held_survives_a_record_with_no_identifiers(collection: Path) -> None:
    """A private communication has no DOI, no arXiv id and no title."""
    records = reference_store.load(collection)
    reference_store.mark_held(records, collection)

    by_tag = {record["tag"]: record for record in records}
    assert by_tag["smith_2020_private_communication"]["held_as"] is None


def test_mark_held_of_a_missing_root_marks_nothing(collection: Path, tmp_path: Path) -> None:
    records = reference_store.load(collection)
    reference_store.mark_held(records, tmp_path / "nowhere")

    assert all(record["held_as"] is None for record in records)


# --------------------------------------------------------------------------
# what a search result is told about the collection
# --------------------------------------------------------------------------


def hit(arxiv_id: str = "", doi: str = "") -> dict:
    return {"arxiv_id": arxiv_id, "doi": doi}


def test_a_paper_the_collection_holds_is_named_by_its_directory(collection: Path) -> None:
    entries = [hit(arxiv_id="2307.09241")]

    counts = arxiv_discover.annotate_local(entries, collection)

    assert entries[0]["held_as"] == "jeong_2023_shallow_deep_inelastic"
    assert counts["held"] == 1


def test_a_paper_is_recognised_by_its_doi_alone(collection: Path) -> None:
    """arXiv gives a DOI for a published paper and no arXiv id for its match."""
    entries = [hit(doi="10.1103/PhysRevD.108.113010")]

    arxiv_discover.annotate_local(entries, collection)

    assert entries[0]["held_as"] == "jeong_2023_shallow_deep_inelastic"


def test_a_work_the_collection_only_cites_carries_its_tag(collection: Path) -> None:
    entries = [hit(arxiv_id="hep-ph/0207172")]

    counts = arxiv_discover.annotate_local(entries, collection)

    assert entries[0]["held_as"] is None
    assert entries[0]["known_as"] == "lipari_2002_neutrino_oscillation_neutrino_cross"
    assert entries[0]["cited_by"] == ["jeong_2023_shallow_deep_inelastic"]
    assert counts["cited"] == 1


def test_a_paper_nothing_here_knows_is_new(collection: Path) -> None:
    entries = [hit(arxiv_id="2501.00001", doi="10.1000/nothing")]

    counts = arxiv_discover.annotate_local(entries, collection)

    assert entries[0]["held_as"] is None
    assert entries[0]["known_as"] is None
    assert counts["new"] == 1


def test_a_version_suffix_still_matches(collection: Path) -> None:
    """`2307.09241v3` and `2307.09241` are one paper."""
    entries = [hit(arxiv_id="2307.09241v3")]

    arxiv_discover.annotate_local(entries, collection)

    assert entries[0]["held_as"] == "jeong_2023_shallow_deep_inelastic"


def test_a_project_with_no_collection_calls_everything_new(tmp_path: Path) -> None:
    """A project that has not started a collection is not an error."""
    entries = [hit(arxiv_id="2307.09241")]

    counts = arxiv_discover.annotate_local(entries, tmp_path / "nowhere")

    assert counts == {"held": 0, "cited": 0, "new": 1}


def test_a_damaged_store_does_not_cost_the_search(collection: Path) -> None:
    """A broken line in the store must not throw away the arXiv results.

    `reference_store.load` raises rather than skipping the line, which is right
    for a tool that writes the store. This one only reads it.
    """
    (collection / ".references.jsonl").write_text("{not json\n", encoding="utf-8")
    entries = [hit(arxiv_id="2307.09241")]

    counts = arxiv_discover.annotate_local(entries, collection)

    assert entries[0]["held_as"] == "jeong_2023_shallow_deep_inelastic"
    assert counts["held"] == 1
