"""Turning the `lit:` markers of a report into links that open the collection.

The agent writes a source and never learns the flavor. This is what puts the
flavor in, so a report is re-rendered rather than repaired when the collection
is rendered another way.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lit import paths
from lit import render
from lit import render_report
from lit import update_references

SLUG = "jeong_2023_shallow_deep_inelastic"
BODEK = "bodek_2008_axial_mass_quasielastic"

SOURCE = """\
# What the axial mass is

Neither description holds in the shallow-inelastic region
([§2](lit:%s/02_introduction#sec-introduction)), and the paragraph under it
says why ([§2](lit:%s/02_introduction#p1)).

The value comes from a duality-constrained fit
([Bodek et al., 2008](lit:ref/%s)), reported in [the paper](lit:%s).

The preprint is at [arXiv:2307.09241](https://arxiv.org/abs/2307.09241).
""" % (SLUG, SLUG, BODEK, SLUG)


@pytest.fixture
def project(collection: Path) -> Path:
    update_references.main(["--render-only", "--literature-root", str(collection)])
    reports = collection.parent / "project" / "reports"
    reports.mkdir(parents=True)
    (reports / "axial-mass.source.md").write_text(SOURCE, encoding="utf-8")
    return reports


def rendered(reports: Path, root: Path, flavor: str) -> str:
    render_report.render_directory(reports, root, flavor)
    return (reports / "axial-mass.md").read_text(encoding="utf-8")


def test_a_marker_becomes_a_link_relative_to_the_report(
    project: Path, collection: Path
) -> None:
    text = rendered(project, collection, "vscode")

    assert "(../../collection/%s/chapters/02_introduction.md#p1)" % SLUG in text
    assert "(../../collection/%s/INDEX.md)" % SLUG in text
    assert "(../../collection/references/%s.md)" % BODEK in text


def test_the_flavor_decides_the_fragment(project: Path, collection: Path) -> None:
    """Obsidian resolves a block ID, and a section by its heading text."""
    vscode = rendered(project, collection, "vscode")
    obsidian = rendered(project, collection, "obsidian")

    assert "02_introduction.md#p1)" in vscode
    assert "02_introduction.md#sec-introduction)" in vscode
    assert "02_introduction.md#^p1)" in obsidian
    assert "02_introduction.md#2 Introduction)" in obsidian


def test_the_source_is_left_as_it_was(project: Path, collection: Path) -> None:
    """It is the master. A flavor change re-renders it and never edits it."""
    rendered(project, collection, "obsidian")

    assert (project / "axial-mass.source.md").read_text(encoding="utf-8") == SOURCE


def test_a_second_flavor_is_rendered_from_the_source_and_not_the_last_render(
    project: Path, collection: Path
) -> None:
    first = rendered(project, collection, "vscode")
    back = rendered(project, collection, "obsidian")
    again = rendered(project, collection, "vscode")

    assert back != first
    assert again == first


def test_a_url_is_left_alone(project: Path, collection: Path) -> None:
    assert "https://arxiv.org/abs/2307.09241" in rendered(project, collection, "vscode")


def test_a_marker_that_names_nothing_keeps_its_marker(
    project: Path, collection: Path
) -> None:
    """Turning it into a link would make a dead citation look like a live one."""
    source = project / "broken.source.md"
    source.write_text("A claim ([§9](lit:%s/09_absent#p1)).\n" % SLUG, encoding="utf-8")

    entries = render_report.render_directory(project, collection, "vscode")
    broken = next(entry for entry in entries if entry["source"] == str(source))

    assert broken["unresolved"] == ["%s/09_absent#p1" % SLUG]
    assert "(lit:%s/09_absent#p1)" % SLUG in (
        project / "broken.md"
    ).read_text(encoding="utf-8")


def test_the_log_is_rendered_beside_its_report(project: Path, collection: Path) -> None:
    (project / "axial-mass.research-log.source.md").write_text(
        "Read [§2](lit:%s/02_introduction#p1).\n" % SLUG, encoding="utf-8"
    )

    render_report.render_directory(project, collection, "vscode")

    log = (project / "axial-mass.research-log.md").read_text(encoding="utf-8")
    assert "chapters/02_introduction.md#p1)" in log


def test_rendering_the_collection_re_renders_the_reports(
    project: Path, collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A flavor change must not leave a report pointing at anchors that went."""
    render_report.render_directory(project, collection, "vscode")

    render.main(["--flavor", "obsidian", "--literature-root", str(collection),
                 "--reports", str(project)])
    capsys.readouterr()

    assert "#^p1)" in (project / "axial-mass.md").read_text(encoding="utf-8")


def test_the_command_says_what_it_wrote(
    project: Path, collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = render_report.main([str(project), "--literature-root", str(collection)])
    report = json.loads(capsys.readouterr().out)

    assert status == 0
    assert report["flavor"] == paths.flavor(collection)
    assert [entry["unresolved"] for entry in report["reports"]] == [[]]
