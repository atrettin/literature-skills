"""The scout contract, asserted against the text that states it.

An agent instruction is prose, and prose carries no unit test. What it can carry
is a check that the contract still says what the caller relies on. A scout
reports `chapters/03_results.md:181`, and the caller discards a quotation that
carries no line number. Both halves live in Markdown, in more than one file, so
a change to one file can leave another stating the old contract. These cases
read the files and assert the strings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

EXAMPLE = "chapters/03_results.md:181"

# The contract as it read before a line number was required. A copy of it
# anywhere is a file that step 1 to step 4 of the change missed.
WITHOUT_LINE = "chapters/03_results.md | #sec-axialff"

# Every place that states the contract, or could restate it.
CONTRACT_FILES = (
    [ROOT / "README.md"]
    + sorted((ROOT / "docs").glob("*.md"))
    + sorted((ROOT / ".claude" / "agents").glob("*.md"))
    + sorted((ROOT / "research-report").rglob("*.md"))
    + sorted((ROOT / "use-literature").rglob("*.md"))
)


def read(relative: str) -> str:
    """The text of a file, with each run of whitespace joined into one space.

    Markdown wraps a sentence across lines, so a phrase that these cases search
    for is often split by a newline and an indent. That is the same false
    negative the line-number contract exists to prevent, and the fix is the
    same: normalise the whitespace, then match.
    """
    return " ".join((ROOT / relative).read_text(encoding="utf-8").split())


def test_scout_example_line_carries_a_line_number() -> None:
    assert EXAMPLE in read(".claude/agents/paper-scout.md")


def test_scout_table_names_the_file_line_field() -> None:
    text = (ROOT / ".claude" / "agents" / "paper-scout.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| file:line |")]
    assert len(rows) == 1


def test_scout_states_that_the_caller_discards_a_quotation() -> None:
    assert "discards a quotation that carries no line number" in read(
        ".claude/agents/paper-scout.md"
    )


def test_research_report_tells_the_caller_to_discard() -> None:
    assert "Discard a quotation that carries no line number" in read(
        "research-report/SKILL.md"
    )


def test_literature_researcher_states_the_rule() -> None:
    assert "no line number" in read(".claude/agents/literature-researcher.md")


def test_the_research_document_shows_the_address_form() -> None:
    assert EXAMPLE in read("docs/research.md")


@pytest.mark.parametrize("path", CONTRACT_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_no_file_shows_a_location_without_a_line_number(path: Path) -> None:
    assert WITHOUT_LINE not in path.read_text(encoding="utf-8")
