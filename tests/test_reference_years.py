"""Where the year of a reference comes from, and where it must not come from.

An arXiv number opens with four digits that read as a year and are not one:
2004.06601 is from April 2020, and hep-ph/0207172 is from July 2002. A DOI and
a URL carry digits of their own. A bibliography entry that no lookup resolves
keeps whatever its own line said, so a number read as a year there stays in the
store, and `base_tag` writes it into a tag that no later lookup rewrites.

The rule is one sentence: only a date says a year. A number that identifies a
work says nothing about when the work appeared.
"""

from __future__ import annotations

import datetime

import references
import reference_store


# --------------------------------------------------------------------------
# an identifier is not a year
# --------------------------------------------------------------------------


def test_a_new_style_arxiv_number_is_not_a_year() -> None:
    line = r"S. Author, \emph{Comment on the measurement}, arXiv:2004.06601 [hep-ph]"

    assert references.find_year(line) is None


def test_a_version_on_the_arxiv_number_changes_nothing() -> None:
    assert references.find_year("S. Author, Comment on X, arXiv:2004.06601v2") is None


def test_an_old_style_arxiv_number_is_not_a_year() -> None:
    """hep-ph/0207172 is from 2002, and 0207 is not a year at all."""
    assert references.find_year("S. Author, A note, hep-ph/0207172") is None


def test_a_doi_is_not_a_year() -> None:
    assert references.find_year("S. Author, A note, doi:10.1103/PhysRevD.2004.06601") is None


def test_a_url_is_not_a_year() -> None:
    assert references.find_year("S. Author, https://arxiv.org/abs/2004.06601") is None


def test_a_year_after_next_year_is_not_a_year() -> None:
    """A report number that survives the mask cannot date a work in the future."""
    ahead = datetime.date.today().year + 2

    assert references.find_year("S. Author, Report CERN-%d-001" % ahead) is None


# --------------------------------------------------------------------------
# a date is a year
# --------------------------------------------------------------------------


def test_a_year_in_parentheses_wins() -> None:
    line = "S. Author, Phys. Rev. D 101 (2020) 123456, arXiv:2004.06601"

    assert references.find_year(line) == 2020


def test_a_year_at_the_end_of_the_line_is_found() -> None:
    assert references.find_year("S. Author, A note, arXiv:2004.06601, 2020") == 2020


def test_the_journal_year_survives_an_old_style_number() -> None:
    line = "S. Author, Nucl. Phys. B 641 (2002) 123, hep-ph/0207172"

    assert references.find_year(line) == 2002


def test_a_stated_year_is_read_from_the_bbl_entry() -> None:
    entry = r"\bibitem{Author:2020ab} S. Author, \bibinfo{year}{2020}, arXiv:2004.06601"

    assert references.from_bbl_entry(entry)["year"] == 2020


def test_an_entry_with_only_a_number_keeps_no_year() -> None:
    entry = r"\bibitem{Author:2020ab} S. Author, Comment on X, arXiv:2004.06601"

    assert references.from_bbl_entry(entry)["year"] is None


# --------------------------------------------------------------------------
# what a missing year does to a tag
# --------------------------------------------------------------------------


def test_a_record_with_no_year_is_tagged_nd() -> None:
    """A missing year stays visible. A wrong year would not."""
    record = {"authors": ["Author, S."], "title": "Comment on the measurement", "year": None}

    assert reference_store.base_tag(record) == "author_nd_comment"
