"""How a citation reads, and where it lands.

A chapter cites `([Bodek et al., 2008](../../references/bodek_2008_….md))`. Two
things have to hold for that to be worth anything: the label has to name the
work a reader would recognise, and the file has to be there, carrying a tag that
`reference_lookup.py` answers to. Nothing else checks the second — the link is
written in one script and the page in another.

The rules about what is *not* linked matter as much. A marker naming a tag the
store does not have is left exactly as it stands, because it is the only visible
sign that a bibliography entry never resolved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import check_references
import reference_store
import update_references

CHAPTER = "jeong_2023_shallow_deep_inelastic/chapters/02_introduction.md"
LIPARI = "lipari_2002_neutrino_oscillation_neutrino_cross"
BODEK = "bodek_2008_axial_mass_quasielastic"
JEONG = "jeong_2023_shallow_deep_inelastic"
OTHER = "juszczak_2003_recoil_nucleon_spectrum"


def relink(collection: Path) -> tuple[int, str]:
    """Run the pass over the whole collection and hand back the chapter."""
    store = reference_store.load(collection)
    touched = update_references.relink_citations(collection, "", store)
    return touched, (collection / CHAPTER).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# what a citation says
# --------------------------------------------------------------------------


def test_one_author_is_named_alone() -> None:
    record = {"authors": ["Lipari, Paolo"], "year": 2002}

    assert update_references.citation_text(record) == "Lipari, 2002"


def test_several_authors_become_et_al() -> None:
    record = {"authors": ["Bodek, A.", "Avvakumov, S.", "Bradford, R."], "year": 2008}

    assert update_references.citation_text(record) == "Bodek et al., 2008"


def test_an_initial_before_the_surname_is_handled() -> None:
    """Bibliographies print a name either way round; both give the surname."""
    assert update_references.citation_text({"authors": ["P. Lipari"], "year": 2002}) == (
        "Lipari, 2002"
    )


def test_a_record_with_no_year_says_so() -> None:
    record = {"authors": ["Lipari, Paolo"]}

    assert update_references.citation_text(record) == "Lipari, n.d."


def test_a_record_with_no_author_says_so() -> None:
    """A blank where the author goes reads as a bug in the conversion."""
    assert update_references.citation_text({"year": 2002}) == "Anon, 2002"
    assert update_references.citation_text({"authors": [" "]}) == "Anon, n.d."


# --------------------------------------------------------------------------
# writing them into the chapters
# --------------------------------------------------------------------------


def test_a_marker_becomes_a_link_a_reader_can_read(collection: Path) -> None:
    _, text = relink(collection)

    assert "([Lipari, 2002](../../references/%s.md))" % LIPARI in text
    assert "([Bodek et al., 2008](../../references/%s.md))" % BODEK in text


def test_several_works_share_one_pair_of_brackets(collection: Path) -> None:
    _, text = relink(collection)

    assert (
        "([Jeong et al., 2023](../../references/%s.md); "
        "[Lipari, 2002](../../references/%s.md))" % (JEONG, LIPARI)
    ) in text


def test_the_link_is_relative_to_the_file_it_is_in(collection: Path) -> None:
    """A chapter sits two levels down, an INDEX.md one. Both must reach it."""
    index = collection / JEONG / "INDEX.md"
    index.write_text(
        index.read_text(encoding="utf-8") + "\nSee [cite: %s].\n" % LIPARI,
        encoding="utf-8",
    )

    _, chapter = relink(collection)

    assert "(../../references/%s.md)" % LIPARI in chapter
    assert "(../references/%s.md)" % LIPARI in index.read_text(encoding="utf-8")


def test_a_citation_written_against_the_old_anchors_is_repointed(collection: Path) -> None:
    """Citations once named a row of the table, which never jumped in VS Code."""
    chapter = collection / CHAPTER
    chapter.write_text(
        "Established elsewhere ([Lipari, 2002](../../REFERENCES.md#%s)).\n" % LIPARI,
        encoding="utf-8",
    )

    relink(collection)

    assert chapter.read_text(encoding="utf-8") == (
        "Established elsewhere ([Lipari, 2002](../../references/%s.md)).\n" % LIPARI
    )


def test_the_pages_are_not_themselves_relinked(collection: Path) -> None:
    """They are rendered from the store, so editing them here achieves nothing."""
    store = reference_store.load(collection)
    update_references.write_records(collection, store)
    page = collection / "references" / ("%s.md" % LIPARI)
    page.write_text(page.read_text(encoding="utf-8") + "\n[cite: %s]\n" % BODEK,
                    encoding="utf-8")

    update_references.relink_citations(collection, "", store)

    assert "[cite: %s]" % BODEK in page.read_text(encoding="utf-8")


def test_a_tag_the_store_does_not_know_is_left_alone(collection: Path) -> None:
    """It is the only sign that a bibliography entry never resolved."""
    _, text = relink(collection)

    assert "[cite: Katori:2016yel]" in text


def test_one_unknown_tag_holds_back_the_whole_marker(collection: Path) -> None:
    """Linking half of it would hide the tag check_references.py must report."""
    _, text = relink(collection)

    assert "[cite: Katori:2016yel, %s]" % BODEK in text


def test_nothing_else_in_the_chapter_moves(collection: Path) -> None:
    _, text = relink(collection)

    assert '<a id="sec-introduction"></a>' in text
    assert "The axial mass extracted from deuterium data is $1.03$ GeV" in text


def test_a_second_run_changes_nothing(collection: Path) -> None:
    touched, first = relink(collection)
    again, second = relink(collection)

    assert touched == 1
    assert again == 0
    assert second == first


def test_one_paper_can_be_relinked_on_its_own(collection: Path) -> None:
    """A --manifest run touches the paper it ingested and nothing else."""
    store = reference_store.load(collection)

    assert update_references.relink_citations(collection, "juszczak_2003_recoil_nucleon_spectrum", store) == 0
    assert "[cite: %s]" % LIPARI in (collection / CHAPTER).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# the page a citation opens
# --------------------------------------------------------------------------


def test_every_cited_work_has_a_page(collection: Path) -> None:
    store = reference_store.load(collection)

    written, removed = update_references.write_records(collection, store)

    assert written == len(store)
    assert removed == 0
    for tag in (LIPARI, BODEK, JEONG):
        assert (collection / "references" / ("%s.md" % tag)).is_file()


def test_the_page_says_what_the_work_is(collection: Path) -> None:
    store = reference_store.load(collection)
    update_references.write_records(collection, store)

    page = (collection / "references" / ("%s.md" % LIPARI)).read_text(encoding="utf-8")

    assert page.startswith("# Lipari, 2002\n")
    assert "**Neutrino oscillation studies and the neutrino cross-section**" in page
    assert "| Journal | Nucl.Phys.B Proc.Suppl. 112 (2002) 274-287 |" in page
    assert "| DOI | [10.1016/s0920-5632(02)01783-8]" in page
    assert "| arXiv | [hep-ph/0207172](https://arxiv.org/abs/hep-ph/0207172) |" in page
    assert "| Cited | 53 times |" in page
    assert "| Tag | `%s` |" % LIPARI in page
    assert "Not held in this collection" in page
    assert "Cited by [%s](../%s/INDEX.md)." % (JEONG, JEONG) in page
    assert "[All references](../REFERENCES.md)" in page


def test_an_unconfirmed_page_leads_with_the_warning(collection: Path) -> None:
    store = reference_store.load(collection)
    update_references.write_records(collection, store)

    page = (collection / "references" / "smith_2020_private_communication.md").read_text(
        encoding="utf-8"
    )

    assert page.startswith("# communication, n.d.\n\n⚠ **Not confirmed.**")
    assert "*R. Smith, private communication (2020)*" in page
    # It has no DOI and no arXiv identifier, so there is nothing to send a
    # reader to, and the page must not pretend otherwise.
    assert "no DOI or arXiv identifier was found for it" in page


def test_a_page_of_a_held_work_points_at_the_paper(collection: Path) -> None:
    store = reference_store.load(collection)
    reference_store.mark_held(store, collection)
    update_references.write_records(collection, store)

    page = (collection / "references" / ("%s.md" % JEONG)).read_text(encoding="utf-8")

    assert "Held here in full: [%s](../%s/INDEX.md)." % (JEONG, JEONG) in page


def test_a_page_whose_work_left_the_store_is_removed(collection: Path) -> None:
    """The directory is rendered from the store, so nothing outlives it there."""
    store = reference_store.load(collection)
    update_references.write_records(collection, store)
    stray = collection / "references" / "gone_1999_forgotten.md"
    stray.write_text("# Gone\n", encoding="utf-8")

    written, removed = update_references.write_records(collection, store)

    assert (written, removed) == (0, 1)
    assert not stray.exists()


def test_writing_the_pages_twice_rewrites_nothing(collection: Path) -> None:
    store = reference_store.load(collection)
    update_references.write_records(collection, store)

    assert update_references.write_records(collection, store) == (0, 0)


def test_the_table_carries_no_anchors(collection: Path) -> None:
    """A citation reaches a work through its page, so the table needs no handle."""
    table = update_references.render_table(reference_store.load(collection))

    assert "<a id=" not in table
    assert "| Neutrino oscillation studies" in table


# --------------------------------------------------------------------------
# and what check_references.py makes of it all
# --------------------------------------------------------------------------


def test_check_references_reads_the_links(collection: Path) -> None:
    store = reference_store.load(collection)
    update_references.relink_citations(collection, "", store)
    update_references.write_records(collection, store)

    report = check_references.check(collection)

    assert report["unresolved"] == [{"tag": "Katori:2016yel", "cited_in": [CHAPTER]}]
    assert report["missing_pages"] == []
    assert report["dangling_refs"] == []
    assert set(check_references.read_citations(collection)) >= {LIPARI, BODEK, JEONG}


def test_a_cited_work_with_no_page_fails_the_check(collection: Path) -> None:
    store = reference_store.load(collection)
    update_references.relink_citations(collection, "", store)
    update_references.write_records(collection, store)
    (collection / "references" / ("%s.md" % LIPARI)).unlink()

    report = check_references.check(collection)

    assert report["missing_pages"] == [LIPARI]
    assert check_references.main(["--literature-root", str(collection)]) == 1


def test_the_pages_do_not_count_as_citing_anything(collection: Path) -> None:
    """A page is rendered from the store; it cannot cite, only be cited."""
    store = reference_store.load(collection)
    update_references.relink_citations(collection, "", store)
    update_references.write_records(collection, store)

    citing = {where for files in check_references.read_citations(collection).values()
              for where in files}

    assert citing == {CHAPTER}


def test_a_scoped_check_ignores_another_papers_dangling_reference(
    collection: Path,
) -> None:
    other = collection / OTHER / "INDEX.md"
    other.write_text(other.read_text(encoding="utf-8") + "\nSee [ref: eq:foo].\n",
                     encoding="utf-8")

    report = check_references.check(collection, paper=JEONG)

    assert report["dangling_refs"] == []
    assert report["elsewhere"]["dangling_refs"] == 1


def test_a_scoped_check_fails_on_the_papers_own_unresolved_tag(collection: Path) -> None:
    report = check_references.check(collection, paper=JEONG)

    assert [item["tag"] for item in report["unresolved"]] == ["Katori:2016yel"]
    assert check_references.main(
        ["--literature-root", str(collection), "--paper", JEONG]
    ) == 1


def test_a_scoped_check_passes_when_the_paper_is_clean(collection: Path) -> None:
    """The Jeong tag stays unresolved; it is not this paper's to answer for."""
    report = check_references.check(collection, paper=OTHER)

    assert report["unresolved"] == []
    assert report["elsewhere"]["unresolved"] == 1
    assert check_references.main(
        ["--literature-root", str(collection), "--paper", OTHER]
    ) == 0


def test_an_unscoped_check_answers_for_the_whole_collection(collection: Path) -> None:
    other = collection / OTHER / "INDEX.md"
    other.write_text(other.read_text(encoding="utf-8") + "\nSee [ref: eq:foo].\n",
                     encoding="utf-8")

    report = check_references.check(collection)

    assert "scope" not in report
    assert "elsewhere" not in report
    assert [item["tag"] for item in report["unresolved"]] == ["Katori:2016yel"]
    assert [item["in"] for item in report["dangling_refs"]] == ["%s/INDEX.md" % OTHER]


def test_a_tag_many_papers_cite_stays_in_scope(collection: Path) -> None:
    """`cited_in` keeps five files; the partition must read all of them.

    The six files sit in a paper whose slug sorts before this one, so this
    paper's own file falls outside the cut.
    """
    chapters = collection / "abbott_1999_earlier_by_name" / "chapters"
    chapters.mkdir(parents=True)
    for number in range(6):
        (chapters / ("%02d_more.md" % number)).write_text(
            "A claim [cite: Katori:2016yel].\n", encoding="utf-8"
        )

    report = check_references.check(collection, paper=JEONG)

    assert [item["tag"] for item in report["unresolved"]] == ["Katori:2016yel"]
    assert CHAPTER not in report["unresolved"][0]["cited_in"]


def test_the_json_says_what_it_wrote(
    collection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = update_references.main(
        ["--literature-root", str(collection), "--render-only"]
    )

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["relinked"] == 1
    assert report["pages_written"] == 4
    assert report["pages_removed"] == 0
