"""The scout contract, asserted against the text that states it.

An agent instruction is prose, and prose carries no unit test. What it can carry
is a check that the contract still says what the caller relies on. A scout
reports `<slug>/<stem>#<anchor>`, and the caller opens exactly that. Both halves
live in Markdown, in more than one file, so a change to one file can leave
another stating the old contract. These cases read the files and assert the
strings.

The contract is the anchor and nothing else. A line number describes the file
that holds a paper rather than the paper — it moves whenever the paper is
ingested again, and a reader cannot see that it has moved. So the negative case
below is the important one: it fails on any file anywhere that still hands a
caller a line to open.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

EXAMPLE = "andreopoulos_2015_genie/03_results#p9"

# A location of the form the store no longer offers: a file, then a line. Any
# copy of it is a file that the change to the anchor contract did not reach.
WITH_LINE = re.compile(r"\.jsonl:\d+")

# Every place that states the contract, or could restate it.
CONTRACT_FILES = (
    [ROOT / "README.md"]
    + sorted((ROOT / "docs").glob("*.md"))
    + sorted((ROOT / "agents").glob("*.md"))
    + sorted((ROOT / "research-report").rglob("*.md"))
    + sorted((ROOT / "use-literature").rglob("*.md"))
)


def read(relative: str) -> str:
    """The text of a file, with each run of whitespace joined into one space.

    Markdown wraps a sentence across lines, so a phrase that these cases search
    for is often split by a newline and an indent. That is the same false
    negative the search command exists to prevent, and the fix is the same:
    normalise the whitespace, then match.
    """
    return " ".join((ROOT / relative).read_text(encoding="utf-8").split())


def test_the_scout_example_is_an_anchor() -> None:
    assert EXAMPLE in read("agents/paper-scout.md")


def test_the_scout_table_names_the_address_field() -> None:
    text = (ROOT / "agents" / "paper-scout.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| address |")]
    assert len(rows) == 1


def test_the_scout_is_told_to_give_the_anchor_of_the_block() -> None:
    assert "Give the anchor of the block the quotation is in" in read(
        "agents/paper-scout.md"
    )


def test_the_scout_is_told_not_to_report_a_line_number() -> None:
    assert "Report no line numbers" in read("agents/paper-scout.md")


def test_the_scout_is_told_it_is_the_reader_that_can_report_absence() -> None:
    """Only a scout reads a paper end to end, so only a scout can say it is silent."""
    text = read("agents/paper-scout.md")
    assert "Nothing relevant" in text
    assert "end to end" in text


def test_the_research_document_shows_the_address_form() -> None:
    assert EXAMPLE in read("docs/research.md")


@pytest.mark.parametrize(
    "path", CONTRACT_FILES, ids=lambda path: str(path.relative_to(ROOT))
)
def test_no_file_hands_a_caller_a_line_to_open(path: Path) -> None:
    """The one that catches a half-finished change to the contract."""
    found = WITH_LINE.search(path.read_text(encoding="utf-8"))
    assert found is None, "%s still gives a location as %s" % (
        path.relative_to(ROOT), found.group(0) if found else "",
    )
