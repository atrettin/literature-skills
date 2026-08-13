"""The shape of the compact report, and the codes it carries.

The report is the whole of what an agent reads after an ingest. Every field is
always there, so a reader never has to tell a missing value from an unknown one,
and no field grows with the size of a bibliography — that is what keeps the
report cheap however many works the paper cites.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lit import add_paper

SCHEMA_FIELDS = {
    "schema", "status", "arxiv_id", "slug", "paper_dir", "index", "title",
    "authors", "authors_total", "submitted_year", "publication", "abs_url",
    "parser", "ingested", "chapters", "figures", "figures_missing",
    "references", "checks", "collection_row", "manifest",
    "warnings", "exception", "next_action",
}

WARNING_CODES = {
    "PARSER_FALLBACK", "INSPIRE_NO_RECORD", "INSPIRE_NO_JOURNAL",
    "INSPIRE_LOOKUP_FAILED", "BIBLIOGRAPHY_FAILED", "UNRESOLVED_REFS",
    "FIGURE_SOURCE_MISSING", "FIGURE_CONVERTER_MISSING", "UNVERIFIED_REFERENCES",
    "PLACEHOLDER_RESIDUE", "RATE_GATE_LOCAL", "OTHER",
}

EXCEPTION_CODES = {
    "AMBIGUOUS_TITLE", "NO_ARXIV_SOURCE", "TAG_COLLISION", "PARSER_FAILURE",
    "SLUG_EXISTS", "REFERENCE_CHECK_FAILED", "COLLECTION_INDEX_UNREADABLE",
    "NETWORK_UNAVAILABLE",
}


# --------------------------------------------------------------------------
# the schema
# --------------------------------------------------------------------------


def test_the_report_holds_every_field_of_the_schema() -> None:
    assert set(add_paper.blank_report()) == SCHEMA_FIELDS


def test_the_schema_names_its_own_version() -> None:
    assert add_paper.blank_report()["schema"] == "add-paper/report/1"


def test_nothing_is_an_answer() -> None:
    """`null` and `[]` say "nothing", where a missing key would say nothing at all."""
    report = add_paper.blank_report()

    assert report["submitted_year"] is None
    assert report["exception"] is None
    assert report["authors"] == []
    assert report["chapters"] == []
    assert report["warnings"] == []


def test_the_report_carries_no_bibliography() -> None:
    """A paper citing five hundred works must not cost five hundred rows here."""
    report = add_paper.blank_report()

    assert isinstance(report["references"], dict)
    assert set(report["references"]) == {
        "cited", "added", "updated", "unchanged", "retagged", "relinked",
        "unverified", "held",
    }
    assert all(isinstance(value, int) for value in report["references"].values())


def test_the_checks_block_holds_the_scoped_verdict() -> None:
    assert set(add_paper.blank_report()["checks"]) == {
        "unresolved", "duplicates", "missing_pages", "residue", "elsewhere",
        "dangling_refs", "pre_existing", "ok",
    }


# --------------------------------------------------------------------------
# the warnings
# --------------------------------------------------------------------------


def test_each_warning_carries_a_code_from_the_enum() -> None:
    warnings = [
        "TexSoup could not parse this source; sections were found by regex",
        "INSPIRE-HEP gave no record for this paper (404)",
        "INSPIRE-HEP holds this paper but reports no journal publication",
        "the INSPIRE-HEP lookup failed (timeout)",
        "the bibliography could not be resolved (offline)",
        "3 cross-reference label(s) had no target in the source",
        "figure source not found: fig7.eps",
        "figure not converted (ghostscript is not installed): fig1.pdf",
        "4 of 74 references could not be confirmed against INSPIRE or Crossref",
    ]

    entries = add_paper.classify(warnings, {})

    assert [entry["code"] for entry in entries] == [
        "PARSER_FALLBACK", "INSPIRE_NO_RECORD", "INSPIRE_NO_JOURNAL",
        "INSPIRE_LOOKUP_FAILED", "BIBLIOGRAPHY_FAILED", "UNRESOLVED_REFS",
        "FIGURE_SOURCE_MISSING", "FIGURE_CONVERTER_MISSING",
        "UNVERIFIED_REFERENCES",
    ]
    assert all(entry["code"] in WARNING_CODES for entry in entries)


def test_a_string_nothing_matches_becomes_other() -> None:
    """A warning that fell out of the report silently is one nobody ever meets."""
    entries = add_paper.classify(["something nobody has a pattern for"], {})

    assert entries[0]["code"] == "OTHER"
    assert entries[0]["detail"] == "something nobody has a pattern for"


def test_a_counted_code_carries_its_count() -> None:
    entries = add_paper.classify(
        ["3 cross-reference label(s) had no target"], {"UNRESOLVED_REFS": 3}
    )

    assert entries[0]["count"] == 3


def test_an_uncounted_code_counts_one() -> None:
    entries = add_paper.classify(["TexSoup could not parse this source"], {})

    assert entries[0]["count"] == 1


def test_the_residue_warning_of_the_conversion_is_dropped() -> None:
    """One definition of residue, and it is the scoped check's `residue` field."""
    entries = add_paper.classify(
        ["7 placeholder residue match(es) in 3 chapter(s)"], {}
    )

    assert entries == []


# --------------------------------------------------------------------------
# the exceptions
# --------------------------------------------------------------------------


def test_an_exception_sets_the_status_and_the_next_action() -> None:
    report = add_paper.failed(
        add_paper.blank_report("2501.00001"),
        add_paper.Exception2("SLUG_EXISTS", "it is there", slug="a_2020_b",
                             existing_arxiv_id="2501.00001"),
    )

    assert report["status"] == "exception"
    assert report["next_action"] == "handle_exception"
    assert report["exception"]["code"] == "SLUG_EXISTS"


@pytest.mark.parametrize("code,extra", [
    ("AMBIGUOUS_TITLE", {"candidates": []}),
    ("NO_ARXIV_SOURCE", {"http_status": 403, "reason": "a PDF"}),
    ("TAG_COLLISION", {"slug": "a_2020_b", "held_by": "the paper directory",
                       "held_arxiv_id": "1111.11111", "suggested_slug": "a_2020_b_c"}),
    ("PARSER_FAILURE", {"main_tex": "main.tex", "sections_found": 0}),
    ("SLUG_EXISTS", {"slug": "a_2020_b", "existing_arxiv_id": "2501.00001"}),
    ("REFERENCE_CHECK_FAILED", {"unresolved": [], "duplicates": [],
                                "missing_pages": [], "residue": [], "elsewhere": {}}),
    ("COLLECTION_INDEX_UNREADABLE", {"path": "literature/README.md",
                                     "reason": "no table"}),
    ("NETWORK_UNAVAILABLE", {"host": "arxiv.org", "reason": "no answer"}),
])
def test_every_exception_code_carries_its_extra_fields(code: str, extra: dict) -> None:
    error = add_paper.Exception2(code, "why", **extra)
    found = error.as_object()

    assert code in EXCEPTION_CODES
    assert found["code"] == code
    assert found["detail"] == "why"
    for name, value in extra.items():
        assert found[name] == value


def test_a_report_is_one_json_object_on_one_line(capsys: pytest.CaptureFixture) -> None:
    """One line per paper, so a caller ingesting several reads them apart."""
    add_paper.emit(add_paper.blank_report("2501.00001"))
    add_paper.emit(add_paper.blank_report("1706.03621"))

    lines = capsys.readouterr().out.splitlines()

    assert len(lines) == 2
    assert [json.loads(line)["arxiv_id"] for line in lines] == ["2501.00001", "1706.03621"]


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------


def test_two_commands_at_once_is_a_usage_error(capsys: pytest.CaptureFixture) -> None:
    assert add_paper.main(["--auto", "2501.00001", "--index-only", "a_2020_b"]) == 1


def test_no_command_at_all_is_a_usage_error(capsys: pytest.CaptureFixture) -> None:
    assert add_paper.main(["2501.00001"]) == 1


def test_auto_with_nothing_to_ingest_is_a_usage_error() -> None:
    assert add_paper.main(["--auto"]) == 1


def test_a_slug_and_several_papers_is_a_usage_error(tmp_path: Path) -> None:
    """`--slug` names one directory, so it cannot answer for two papers."""
    status = add_paper.main(
        ["--auto", "2501.00001", "1706.03621", "--slug", "a_2020_b",
         "--literature-root", str(tmp_path)]
    )

    assert status == 1


def test_an_argument_that_is_not_an_identifier_is_an_exception(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    status = add_paper.main(
        ["--auto", "not-an-identifier", "--literature-root", str(tmp_path)]
    )
    report = json.loads(capsys.readouterr().out.splitlines()[0])

    assert status == 2
    assert report["exception"]["code"] == "AMBIGUOUS_TITLE"
