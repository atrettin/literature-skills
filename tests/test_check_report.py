"""Checking that the citations of a report still point at something.

The report under test is written into a project directory beside the
collection, because that is where a report lives and because the links it
carries are relative to itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import check_report
import update_references

GOOD = """\
# What the axial mass is

**Literature root:** {root}

## Summary

Deuterium fits and nuclear-target fits do not agree.

## Findings

The shallow-inelastic region is where neither description holds
(Jeong 2023, Phys.Rev.D 108 (2023) 113010,
[§2]({root}/jeong_2023_shallow_deep_inelastic/chapters/02_introduction.md#sec-introduction)).

The duality-constrained parameterisation is the source of the value
([Bodek et al., 2008]({root}/references/bodek_2008_axial_mass_quasielastic.md)).

## References

- **jeong_2023_shallow_deep_inelastic** — Jeong, Reno (2023). *Neutrino Cross
  Sections*. Phys.Rev.D 108 (2023) 113010.
  [record]({root}/references/jeong_2023_shallow_deep_inelastic.md)
- **bodek_2008_axial_mass_quasielastic** — Bodek et al. (2008). *Vector and
  Axial Nucleon Form Factors*. Eur.Phys.J.C 53 (2008) 349-354.
  [record]({root}/references/bodek_2008_axial_mass_quasielastic.md)
"""


@pytest.fixture
def project(collection: Path) -> Path:
    """A project with a reports directory, beside a collection with its pages.

    The pages under `references/` are what a citation opens, and they are
    rendered from the store rather than kept in the fixture, so this renders
    them the way `add-paper` does.
    """
    update_references.main(["--render-only", "--literature-root", str(collection)])
    reports = collection.parent / "project" / "reports"
    reports.mkdir(parents=True)
    return reports


def write(reports: Path, text: str, collection: Path, name: str = "axial-mass.md") -> Path:
    """Write a report whose links reach the collection from where it sits."""
    import os

    root = os.path.relpath(collection, reports)
    path = reports / name
    path.write_text(text.format(root=root), encoding="utf-8")
    return path


def test_a_report_whose_citations_resolve_passes(project: Path, collection: Path) -> None:
    report = check_report.check(write(project, GOOD, collection), collection)

    assert report["broken_links"] == []
    assert report["unknown_tags"] == []
    assert report["citations"] == 2


def test_the_links_are_relative_and_reach_a_collection_outside_the_project(
    project: Path, collection: Path
) -> None:
    """A shared collection is not under the project, and a citation still opens."""
    path = write(project, GOOD, collection)

    assert "../" in path.read_text(encoding="utf-8")
    assert check_report.main([str(path), "--literature-root", str(collection)]) == 0


def test_an_anchor_that_is_not_in_the_chapter_is_reported(
    project: Path, collection: Path
) -> None:
    broken = GOOD.replace("#sec-introduction", "#sec-conclusions")
    report = check_report.check(write(project, broken, collection), collection)

    assert [item["why"] for item in report["broken_links"]] == ["no such anchor"]


def test_a_chapter_that_is_not_there_is_reported(project: Path, collection: Path) -> None:
    broken = GOOD.replace("02_introduction.md", "09_conclusions.md")
    report = check_report.check(write(project, broken, collection), collection)

    assert [item["why"] for item in report["broken_links"]] == ["no such file"]


def test_a_tag_no_record_answers_is_reported(project: Path, collection: Path) -> None:
    """A reference page can be missing and the link still look right."""
    broken = GOOD.replace(
        "bodek_2008_axial_mass_quasielastic", "bodek_2008_axial_mass_quasi_elastic"
    )
    report = check_report.check(write(project, broken, collection), collection)

    assert report["unknown_tags"] == ["bodek_2008_axial_mass_quasi_elastic"]


def test_a_marker_copied_out_of_a_chapter_is_reported(
    project: Path, collection: Path
) -> None:
    """`[cite: tag]` is the form a chapter carries, and it opens nothing."""
    broken = GOOD.replace(
        "## References",
        "One more claim [cite: lipari_2002_neutrino_oscillation_neutrino_cross].\n\n## References",
    )
    report = check_report.check(write(project, broken, collection), collection)

    assert report["cite_markers"] == ["lipari_2002_neutrino_oscillation_neutrino_cross"]


def test_a_work_cited_in_the_text_and_missing_from_the_references_is_reported(
    project: Path, collection: Path
) -> None:
    broken = GOOD.replace(
        "- **bodek_2008_axial_mass_quasielastic** — Bodek et al. (2008). *Vector and\n"
        "  Axial Nucleon Form Factors*. Eur.Phys.J.C 53 (2008) 349-354.\n"
        "  [record]({root}/references/bodek_2008_axial_mass_quasielastic.md)\n",
        "",
    )
    report = check_report.check(write(project, broken, collection), collection)

    assert report["uncited_in_references"] == ["tag:bodek_2008_axial_mass_quasielastic"]


def test_a_work_listed_in_the_references_and_cited_nowhere_is_reported(
    project: Path, collection: Path
) -> None:
    broken = GOOD.replace(
        "## References",
        "## References\n\n- **lipari_2002_neutrino_oscillation_neutrino_cross** — Lipari (2002).\n"
        "  [record]({root}/references/lipari_2002_neutrino_oscillation_neutrino_cross.md)",
    )
    report = check_report.check(write(project, broken, collection), collection)

    assert report["unlisted_in_references"] == [
        "tag:lipari_2002_neutrino_oscillation_neutrino_cross"
    ]


def test_one_work_cited_two_ways_is_one_work(project: Path, collection: Path) -> None:
    """A held paper cited at a chapter, and listed by its record, is not two papers."""
    report = check_report.check(write(project, GOOD, collection), collection)

    assert report["uncited_in_references"] == []
    assert report["unlisted_in_references"] == []


def test_a_held_paper_is_listed_by_its_index(project: Path, collection: Path) -> None:
    """A page under references/ exists for a work that a paper here cites.

    A paper the collection holds and that nothing here cites has no such page.
    Its INDEX.md is the page that names it, and an entry that opens that is the
    same work as a claim cited at one of its chapters.
    """
    by_index = GOOD.replace(
        "[record]({root}/references/jeong_2023_shallow_deep_inelastic.md)",
        "[paper]({root}/jeong_2023_shallow_deep_inelastic/INDEX.md)",
    )
    report = check_report.check(write(project, by_index, collection), collection)

    assert report["broken_links"] == []
    assert report["uncited_in_references"] == []
    assert report["unlisted_in_references"] == []


def test_a_work_the_collection_could_not_confirm_must_carry_its_mark(
    project: Path, collection: Path
) -> None:
    unconfirmed = GOOD.replace(
        "([Bodek et al., 2008]({root}/references/bodek_2008_axial_mass_quasielastic.md))",
        "([Smith, 2020]({root}/references/smith_2020_private_communication.md))",
    ).replace(
        "- **bodek_2008_axial_mass_quasielastic** — Bodek et al. (2008). *Vector and\n"
        "  Axial Nucleon Form Factors*. Eur.Phys.J.C 53 (2008) 349-354.\n"
        "  [record]({root}/references/bodek_2008_axial_mass_quasielastic.md)",
        "- **smith_2020_private_communication** — Smith (2020).\n"
        "  [record]({root}/references/smith_2020_private_communication.md)",
    )
    report = check_report.check(write(project, unconfirmed, collection), collection)

    assert report["unflagged_unverified"] == ["smith_2020_private_communication"]


def test_the_mark_settles_it(project: Path, collection: Path) -> None:
    marked = GOOD.replace(
        "([Bodek et al., 2008]({root}/references/bodek_2008_axial_mass_quasielastic.md))",
        "([Smith, 2020]({root}/references/smith_2020_private_communication.md))",
    ).replace(
        "- **bodek_2008_axial_mass_quasielastic** — Bodek et al. (2008). *Vector and\n"
        "  Axial Nucleon Form Factors*. Eur.Phys.J.C 53 (2008) 349-354.\n"
        "  [record]({root}/references/bodek_2008_axial_mass_quasielastic.md)",
        "- **smith_2020_private_communication** — Smith (2020). ⚠ unverified: no\n"
        "  lookup confirmed this work, so the attribution is the citing paper's own.\n"
        "  [record]({root}/references/smith_2020_private_communication.md)",
    )
    report = check_report.check(write(project, marked, collection), collection)

    assert report["unflagged_unverified"] == []


def test_a_report_that_attributes_nothing_fails(project: Path, collection: Path) -> None:
    """A claim about the literature that names no paper is what this exists to catch."""
    path = project / "empty.md"
    path.write_text("# What the axial mass is\n\nIt is about one GeV.\n", encoding="utf-8")

    assert check_report.main([str(path), "--literature-root", str(collection)]) == 1


def test_a_link_to_somebody_else_s_site_is_left_alone(
    project: Path, collection: Path
) -> None:
    """Nothing here can say whether a URL resolves, and guessing would be worse."""
    external = GOOD.replace(
        "## References",
        "The preprint is at [arXiv:2307.09241](https://arxiv.org/abs/2307.09241#abstract).\n\n"
        "## References",
    )
    report = check_report.check(write(project, external, collection), collection)

    assert report["broken_links"] == []


def test_a_link_to_a_project_file_is_checked_too(project: Path, collection: Path) -> None:
    """A claim-check report points at the file whose claims it checked."""
    claims = GOOD.replace(
        "## References", "Checked against [the model](../model.py#L42).\n\n## References"
    )
    report = check_report.check(write(project, claims, collection), collection)

    assert [item["why"] for item in report["broken_links"]] == ["no such file"]

    (project.parent / "model.py").write_text("# a model\n", encoding="utf-8")
    again = check_report.check(project / "axial-mass.md", collection)

    # The line number is the editor's business; there is no anchor to look for.
    assert again["broken_links"] == []


def test_a_missing_log_is_reported_and_does_not_fail(
    project: Path, collection: Path
) -> None:
    path = write(project, GOOD, collection)
    report = check_report.check(path, collection)
    assert report["research_log"] is None

    path.with_suffix(".research-log.md").write_text("# log\n", encoding="utf-8")
    assert check_report.check(path, collection)["research_log"] == "axial-mass.research-log.md"
    assert check_report.main([str(path), "--literature-root", str(collection)]) == 0
