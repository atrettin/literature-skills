"""Checking that the citations of a report still point at something.

A report cites the collection with `lit:` markers, and this checks the report
source — the file holding them — against the store. Nothing here reads a
rendered file: the rendered report is written from a checked source, and a
marker that resolves against the store resolves in every flavor the collection
is ever rendered in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lit import check_report
from lit import update_references

GOOD = """\
# What the axial mass is

## Summary

Deuterium fits and nuclear-target fits do not agree.

## Findings

The shallow-inelastic region is where neither description holds
(Jeong 2023, Phys.Rev.D 108 (2023) 113010,
[§2](lit:jeong_2023_shallow_deep_inelastic/02_introduction#sec-introduction)).

The duality-constrained parameterisation is the source of the value
([Bodek et al., 2008](lit:ref/bodek_2008_axial_mass_quasielastic)).

## References

- **jeong_2023_shallow_deep_inelastic** — Jeong, Reno (2023). *Neutrino Cross
  Sections*. Phys.Rev.D 108 (2023) 113010.
  [paper](lit:jeong_2023_shallow_deep_inelastic)
- **bodek_2008_axial_mass_quasielastic** — Bodek et al. (2008). *Vector and
  Axial Nucleon Form Factors*. Eur.Phys.J.C 53 (2008) 349-354.
  [record](lit:ref/bodek_2008_axial_mass_quasielastic)
"""


@pytest.fixture
def project(collection: Path) -> Path:
    """A project with a reports directory, beside a collection with its pages.

    The pages under `references/` are what a `lit:ref/` marker names, and they
    are rendered from the store rather than kept in the fixture, so this renders
    them the way `add-paper` does.
    """
    update_references.main(["--render-only", "--literature-root", str(collection)])
    reports = collection.parent / "project" / "reports"
    reports.mkdir(parents=True)
    return reports


def write(reports: Path, text: str, name: str = "axial-mass.source.md") -> Path:
    path = reports / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# a marker that resolves, and one that does not
# --------------------------------------------------------------------------


def test_a_report_whose_citations_resolve_passes(project: Path, collection: Path) -> None:
    report = check_report.check(write(project, GOOD), collection)

    assert report["broken_markers"] == []
    assert report["unknown_tags"] == []
    assert report["citations"] == 2


def test_a_marker_needs_no_path_and_so_survives_a_move(
    project: Path, collection: Path
) -> None:
    """The marker names the paper, not one rendering of it in one place."""
    path = write(project, GOOD)

    assert "../" not in path.read_text(encoding="utf-8")
    assert check_report.main([str(path), "--literature-root", str(collection)]) == 0


def test_an_anchor_that_is_not_in_the_chapter_is_reported(
    project: Path, collection: Path
) -> None:
    broken = GOOD.replace("#sec-introduction", "#sec-conclusions")
    report = check_report.check(write(project, broken), collection)

    assert [item["why"] for item in report["broken_markers"]] == ["no such anchor"]


def test_a_chapter_that_is_not_there_is_reported(project: Path, collection: Path) -> None:
    broken = GOOD.replace("02_introduction", "09_conclusions")
    report = check_report.check(write(project, broken), collection)

    assert [item["why"] for item in report["broken_markers"]] == ["no such chapter"]


def test_a_paper_the_collection_does_not_hold_is_reported(
    project: Path, collection: Path
) -> None:
    broken = GOOD.replace("jeong_2023_shallow_deep_inelastic/02_introduction",
                          "reno_2050_z/02_introduction")
    report = check_report.check(write(project, broken), collection)

    assert [item["why"] for item in report["broken_markers"]] == ["no such paper"]
    assert "slug:reno_2050_z" in report["works_not_in_collection"]


def test_a_tag_no_record_answers_is_reported(project: Path, collection: Path) -> None:
    """A record can be missing and the marker still look right."""
    broken = GOOD.replace(
        "bodek_2008_axial_mass_quasielastic", "bodek_2008_axial_mass_quasi_elastic"
    )
    report = check_report.check(write(project, broken), collection)

    assert report["unknown_tags"] == ["bodek_2008_axial_mass_quasi_elastic"]
    assert [item["why"] for item in report["broken_markers"]] == [
        "no such record", "no such record"
    ]


def test_a_marker_copied_out_of_a_chapter_is_reported(
    project: Path, collection: Path
) -> None:
    """`[cite: tag]` is the form the store carries, and it opens nothing."""
    broken = GOOD.replace(
        "## References",
        "One more claim [cite: lipari_2002_neutrino_oscillation_neutrino_cross].\n\n"
        "## References",
    )
    report = check_report.check(write(project, broken), collection)

    assert report["cite_markers"] == ["lipari_2002_neutrino_oscillation_neutrino_cross"]


def test_a_link_to_somebody_else_s_site_is_left_alone(
    project: Path, collection: Path
) -> None:
    """Nothing here can say whether a URL resolves, and guessing would be worse."""
    external = GOOD.replace(
        "## References",
        "The preprint is at [arXiv:2307.09241](https://arxiv.org/abs/2307.09241).\n\n"
        "## References",
    )
    report = check_report.check(write(project, external), collection)

    assert report["broken_markers"] == []


# --------------------------------------------------------------------------
# the body against the references
# --------------------------------------------------------------------------


def test_a_work_the_body_cites_and_the_references_omit_is_cited_but_not_listed(
    project: Path, collection: Path
) -> None:
    broken = GOOD.replace(
        "- **bodek_2008_axial_mass_quasielastic** — Bodek et al. (2008). *Vector and\n"
        "  Axial Nucleon Form Factors*. Eur.Phys.J.C 53 (2008) 349-354.\n"
        "  [record](lit:ref/bodek_2008_axial_mass_quasielastic)\n",
        "",
    )
    report = check_report.check(write(project, broken), collection)

    assert report["cited_but_not_listed"] == ["tag:bodek_2008_axial_mass_quasielastic"]


def test_a_work_the_references_list_and_the_body_omits_is_listed_but_not_cited(
    project: Path, collection: Path
) -> None:
    broken = GOOD.replace(
        "## References",
        "## References\n\n"
        "- **lipari_2002_neutrino_oscillation_neutrino_cross** — Lipari (2002).\n"
        "  [record](lit:ref/lipari_2002_neutrino_oscillation_neutrino_cross)",
    )
    report = check_report.check(write(project, broken), collection)

    assert report["listed_but_not_cited"] == [
        "tag:lipari_2002_neutrino_oscillation_neutrino_cross"
    ]


def test_one_work_cited_two_ways_is_one_work(project: Path, collection: Path) -> None:
    """A held paper cited at a chapter, and listed by its paper, is not two works."""
    report = check_report.check(write(project, GOOD), collection)

    assert report["cited_but_not_listed"] == []
    assert report["listed_but_not_cited"] == []


def test_a_held_paper_listed_by_its_record_is_the_same_work(
    project: Path, collection: Path
) -> None:
    """The collection holds Jeong, and also knows it as a cited work.

    A claim cited at one of its chapters and an entry naming its record are the
    same publication, and a report that lists it once has listed it.
    """
    by_record = GOOD.replace(
        "[paper](lit:jeong_2023_shallow_deep_inelastic)",
        "[record](lit:ref/jeong_2023_shallow_deep_inelastic)",
    )
    report = check_report.check(write(project, by_record), collection)

    assert report["broken_markers"] == []
    assert report["cited_but_not_listed"] == []
    assert report["listed_but_not_cited"] == []


# --------------------------------------------------------------------------
# the mark on a work nothing confirmed
# --------------------------------------------------------------------------

UNCONFIRMED = (
    "([Bodek et al., 2008](lit:ref/bodek_2008_axial_mass_quasielastic))",
    "([Smith, 2020](lit:ref/smith_2020_private_communication))",
)
UNCONFIRMED_ENTRY = (
    "- **bodek_2008_axial_mass_quasielastic** — Bodek et al. (2008). *Vector and\n"
    "  Axial Nucleon Form Factors*. Eur.Phys.J.C 53 (2008) 349-354.\n"
    "  [record](lit:ref/bodek_2008_axial_mass_quasielastic)"
)


def test_a_work_the_collection_could_not_confirm_must_carry_its_mark(
    project: Path, collection: Path
) -> None:
    unconfirmed = GOOD.replace(*UNCONFIRMED).replace(
        UNCONFIRMED_ENTRY,
        "- **smith_2020_private_communication** — Smith (2020).\n"
        "  [record](lit:ref/smith_2020_private_communication)",
    )
    report = check_report.check(write(project, unconfirmed), collection)

    assert report["unflagged_unverified"] == ["smith_2020_private_communication"]


def test_the_mark_settles_it(project: Path, collection: Path) -> None:
    marked = GOOD.replace(*UNCONFIRMED).replace(
        UNCONFIRMED_ENTRY,
        "- **smith_2020_private_communication** — Smith (2020). ⚠ unverified: no\n"
        "  lookup confirmed this work, so the attribution is the citing paper's own.\n"
        "  [record](lit:ref/smith_2020_private_communication)",
    )
    report = check_report.check(write(project, marked), collection)

    assert report["unflagged_unverified"] == []


# --------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------


def test_a_report_that_attributes_nothing_fails(project: Path, collection: Path) -> None:
    """A claim about the literature that names no paper is what this exists to catch."""
    path = project / "empty.source.md"
    path.write_text("# What the axial mass is\n\nIt is about one GeV.\n",
                    encoding="utf-8")

    assert check_report.main([str(path), "--literature-root", str(collection)]) == 1


def test_a_missing_log_is_reported_and_does_not_fail(
    project: Path, collection: Path
) -> None:
    path = write(project, GOOD)

    assert check_report.check(path, collection)["research_log"] is None
    assert check_report.main([str(path), "--literature-root", str(collection)]) == 0
