"""The facts that describe a candidate: its length and its kind.

Nothing here calls arXiv or INSPIRE. Both functions are pure, so a test reaches
them with the text a source would have given.
"""

from __future__ import annotations

import paper_facts


# --------------------------------------------------------------------------
# length
# --------------------------------------------------------------------------


def test_page_count_reads_the_arxiv_comment() -> None:
    assert paper_facts.page_count("63 pages, 12 figures") == (63, "arxiv_comment")


def test_page_count_ignores_a_comment_about_a_version() -> None:
    """A comment is free text, and most of it is not a length."""
    comment = "A version published in PRC, with several improvements"

    assert paper_facts.page_count(comment) == (None, None)


def test_page_count_falls_back_to_inspire() -> None:
    assert paper_facts.page_count("", 63) == (63, "inspire")


def test_page_count_rejects_a_number_that_is_not_a_length() -> None:
    """A number above PAGE_COUNT_MAX is a volume or a year, not a length."""
    assert paper_facts.page_count("2000 pages of proceedings") == (None, None)


def test_the_comment_wins_over_inspire() -> None:
    """arXiv answers for every preprint; INSPIRE holds many of them not at all."""
    assert paper_facts.page_count("4 pages, 4 figures", 6) == (4, "arxiv_comment")


# --------------------------------------------------------------------------
# kind
# --------------------------------------------------------------------------


def test_kind_reads_the_venue() -> None:
    assert paper_facts.classify_kind("Phys.Rept. 928 (2021) 1-63") == "review"
    assert paper_facts.classify_kind("Phys. Rept. 928 (2021) 1-63") == "review"
    assert paper_facts.classify_kind("Rev.Mod.Phys. 84 (2012) 1307") == "review"


def test_kind_reads_the_inspire_document_type() -> None:
    assert paper_facts.classify_kind("", ["review"]) == "review"


def test_kind_of_an_unpublished_preprint_is_unknown() -> None:
    """No venue and no document type means that nobody answered."""
    assert paper_facts.classify_kind("", []) == "unknown"
    assert paper_facts.classify_kind("") == "unknown"


def test_kind_of_a_paper_in_another_journal_is_article() -> None:
    assert paper_facts.classify_kind("Phys. Rev. C 104, 025501 (2021)") == "article"


def test_kind_never_reads_the_author_count_or_the_citations() -> None:
    """A large collaboration is not a review, and neither is a much-cited paper.

    Section 4.3a of the methodology review: the three papers that changed the
    conclusions of the example task held 4, 7 and 7 citations, and the paper the
    researcher rejected held 616. An author count and a citation count both
    point the wrong way, so `classify_kind` reads neither. This entry carries
    136 authors and 645 citations, and stays `unknown` because no source says
    where it appeared.
    """
    entry = {
        "authors": ["Author %d" % number for number in range(136)],
        "citation_count": 645,
        "journal_ref": "",
        "comment": "",
    }
    paper_facts.describe(entry)

    assert entry["kind"] == "unknown"


# --------------------------------------------------------------------------
# describe
# --------------------------------------------------------------------------


def test_describe_reads_the_arxiv_fields_when_inspire_gave_none() -> None:
    entry = {"comment": "13 pages, 9 figures", "journal_ref": "Phys.Rept. 928 (2021) 1"}

    paper_facts.describe(entry)

    assert entry["pages"] == 13
    assert entry["pages_source"] == "arxiv_comment"
    assert entry["kind"] == "review"


def test_describe_prefers_the_inspire_journal() -> None:
    """INSPIRE writes a venue the same way every time; an author writes it freely."""
    entry = {"comment": "", "journal_ref": "in press", "journal": "Phys.Rept. 928 (2021) 1-63"}

    paper_facts.describe(entry)

    assert entry["kind"] == "review"
