"""Discovering the other names of a subject, in the papers and in the store.

Two failures matter here, and both make an answer look better than it is. A
phrase that no author wrote, reported as a name of the field, sends the next
search nowhere. A scan that reads the whole collection reports the vocabulary of
another task as another name for this one, and that answer is worse than none.

A third failure is the one the text source exists for: a name that the papers
use and the report never reaches. "Sterile neutrino" and "heavy neutral lepton"
share no word, so no ranking built on the words of the query can find the second
from the first.

The cases build their own records. `tests/data/collection_fixture/` stays as it
is: other cases count what is in it. Several cases write a store, or a paper,
into `tmp_path` and run the script, so the read from disk is covered.

Each case asserts a relationship, and not a value. A case that needs
`MIN_WEIGHT` reads the constant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import rerank
import terminology_scan

MINE = "king_2025_right_handed_neutrinos"
THEIRS = "abbott_2016_binary_black_hole"

# The two titles the cases below count. The first gives one term of three words,
# "heavy neutral leptons", and the two-word terms inside it. The second gives
# the two-word term alone, so a case can raise its count on its own.
HNL = "Heavy neutral leptons"
LEPTONS = "Neutral leptons in the early universe"


def record(title: str, tag: str = "", papers: tuple[str, ...] = (MINE,)) -> dict:
    """One record of the store, with the fields that the scan reads."""
    return {
        "tag": tag or "tag_%d" % abs(hash(title)),
        "title": title,
        "cited_by": [{"slug": slug, "key": ""} for slug in papers],
    }


def many(title: str, count: int, **fields) -> list[dict]:
    """The same title, in `count` records, so that a term reaches a threshold."""
    return [
        record(title, tag="tag_%d_%d" % (abs(hash(title)), number), **fields)
        for number in range(count)
    ]


def enough() -> int:
    """The number of titles at which a term reaches the report.

    A cited title weighs `STRUCTURE_WEIGHTS["title"]`, which is 1, so the weight
    a term needs and the number of titles that carry it are the same number.
    """
    return terminology_scan.MIN_WEIGHT


def scan(records: list[dict], topic: str, **options) -> dict:
    """The scan over a list of records, with the whole store as its scope."""
    papers = sorted({
        entry["slug"] for item in records for entry in item.get("cited_by") or []
    })
    return terminology_scan.scan(
        Path("collection"), topic, records, papers, papers, "all_papers", **options
    )


def reported(report: dict) -> list[str]:
    return [item["term"] for item in report["terms"]]


def run(root: Path, *arguments: str, capsys=None) -> tuple[int, dict]:
    """The script as a caller runs it: an exit status and the JSON it printed."""
    status = terminology_scan.main([*arguments, "--literature-root", str(root)])
    assert capsys is not None
    return status, json.loads(capsys.readouterr().out)


def write_store(root: Path, records: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".references.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in records), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# what counts as a term
# --------------------------------------------------------------------------


def test_a_term_never_crosses_punctuation() -> None:
    """No author wrote "sections interface". The colon divides the title."""
    terms = terminology_scan.terms_of(
        "Neutrino cross sections: interface of shallow inelastic scattering"
    )

    assert "sections interface" not in terms
    assert "neutrino cross sections" in terms


def test_a_hyphen_inside_a_word_does_not_divide_the_title() -> None:
    """"Right-handed neutrino" is a name of the field, and a dash writes it."""
    terms = terminology_scan.terms_of("Right-handed neutrino production")

    assert "right handed neutrino" in terms


def test_a_title_counts_one_time_for_a_term_it_repeats() -> None:
    """The count is the number of works that use a term, and not of its uses."""
    counts, _, _ = terminology_scan.count_titles([
        record("Sterile neutrino models and the sterile neutrino mass")
    ])

    assert counts["sterile neutrino"] == 1


def test_a_term_never_begins_or_ends_with_a_function_word() -> None:
    terms = terminology_scan.terms_of("The decay of the pion in the detector")

    assert "of the pion" not in terms
    assert "pion in the" not in terms
    assert "decay of" not in terms
    # A function word inside a term stays: "decay" and "pion" are the ends.
    assert "decay of the pion" in terminology_scan.terms_of(
        "The decay of the pion", sizes=(4,)
    )


def test_a_term_never_begins_or_ends_with_title_furniture() -> None:
    terms = terminology_scan.terms_of("Search for heavy neutral leptons")

    assert "search for heavy" not in terms
    assert "heavy neutral leptons" in terms


def test_a_term_holds_no_bare_number() -> None:
    terms = terminology_scan.terms_of("Neutrino data 2020 release")

    assert not any("2020" in term for term in terms)


# --------------------------------------------------------------------------
# what the topic already holds
# --------------------------------------------------------------------------


def test_a_term_the_topic_holds_is_not_reported() -> None:
    records = many("Sterile neutrino oscillations", enough())

    report = scan(records, "sterile neutrino mass")

    assert "sterile neutrino" not in reported(report)
    # A term that adds one word the topic lacks stays, and it names that word.
    kept = next(item for item in report["terms"] if item["term"].endswith("oscillations"))
    assert kept["new_words"] == ["oscillations"]


def test_a_plural_in_the_topic_answers_a_singular_in_a_title() -> None:
    """The prefix rule of `rerank.MIN_PREFIX`, and nothing shorter than it."""
    _, new = terminology_scan.shared_and_new("sterile neutrino", ["neutrinos"])
    assert "neutrino" not in new

    # A prefix shorter than MIN_PREFIX is no evidence: `ion` must not take
    # `ionisation`.
    short = "ionisation"[: rerank.MIN_PREFIX - 1]
    _, unmatched = terminology_scan.shared_and_new(
        "%s lepton" % short, ["ionisation", "leptons"]
    )
    assert unmatched == [short]


# --------------------------------------------------------------------------
# the thresholds and the order
# --------------------------------------------------------------------------


def test_a_term_below_the_threshold_is_not_reported() -> None:
    scarce = many(HNL, enough() - 1)
    common = many("Right-handed neutrino production", enough())

    report = scan(scarce + common, "sterile neutrino")

    assert "heavy neutral leptons" not in reported(report)
    assert "right handed neutrino" in reported(report)


def test_a_longer_term_removes_the_shorter_one_it_holds() -> None:
    """"Neutral leptons" adds nothing beside "heavy neutral leptons"."""
    report = scan(many(HNL, enough()), "sterile neutrino")

    assert "heavy neutral leptons" in reported(report)
    assert "neutral leptons" not in reported(report)


def test_a_shorter_term_stays_when_it_is_far_more_frequent() -> None:
    """The other side of SUBSUME_RATIO: the shorter term then names its own thing."""
    longer = enough()
    shorter = int(longer / terminology_scan.SUBSUME_RATIO) + longer + 1
    records = many(HNL, longer) + many(LEPTONS, shorter)

    report = scan(records, "sterile neutrino")

    assert "heavy neutral leptons" in reported(report)
    assert "neutral leptons" in reported(report)


def test_a_shared_word_lowers_a_term_below_one_of_the_same_weight() -> None:
    """This is the rule the scan exists for. A name the query could have reached
    is no discovery, so a word the topic holds already costs a term its place."""
    records = many("Right-handed neutrino production", enough()) + many(HNL, enough())

    report = scan(records, "sterile neutrino mixing")
    order = reported(report)

    assert order.index("heavy neutral leptons") < order.index("right handed neutrino")
    lowered = report["terms"][order.index("right handed neutrino")]
    assert lowered["shared_words"] == ["neutrino"]
    assert lowered["new_words"] == ["right", "handed"]
    # The same weight, and the term of no shared word keeps the whole of it.
    whole = report["terms"][order.index("heavy neutral leptons")]
    assert lowered["weight"] == whole["weight"]
    assert lowered["score"] < whole["score"]


def test_max_terms_cuts_the_report() -> None:
    records: list[dict] = []
    for number in range(5):
        records += many("Heavy neutral lepton%d states" % number, enough())

    report = scan(records, "sterile neutrino", max_terms=2)

    assert len(report["terms"]) == 2
    assert report["settings"]["max_terms"] == 2


# --------------------------------------------------------------------------
# the evidence
# --------------------------------------------------------------------------


def test_the_report_names_the_titles_a_term_came_from() -> None:
    count = max(enough(), terminology_scan.EXAMPLES_PER_TERM + 1)

    report = scan(many(HNL, count), "sterile neutrino")
    term = next(
        item for item in report["terms"] if item["term"] == "heavy neutral leptons"
    )

    assert term["weight"] == count
    assert len(term["examples"]) == terminology_scan.EXAMPLES_PER_TERM
    assert all(example["tag"] and example["title"] for example in term["examples"])


def test_a_record_with_no_title_is_counted_and_skipped() -> None:
    records = many(HNL, enough())
    records.append({"tag": "no_title", "cited_by": [{"slug": MINE, "key": ""}]})
    records.append({
        "tag": "raw_only",
        "raw": "J. Smith, private communication, 1998",
        "cited_by": [{"slug": MINE, "key": ""}],
    })

    report = scan(records, "sterile neutrino")

    assert report["scanned"]["without_title"] == 2
    assert report["scanned"]["titles"] == enough()
    assert report["scanned"]["records"] == enough() + 2
    # The words of a bibliography line are not terms.
    assert not any("private" in item["term"] for item in report["terms"])


# --------------------------------------------------------------------------
# the scope
# --------------------------------------------------------------------------


def test_cited_by_counts_the_works_one_paper_cites(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_store(tmp_path, many(HNL, enough(), papers=(MINE,)))

    status, report = run(tmp_path, "--topic", "sterile neutrino",
                         "--cited-by", MINE, capsys=capsys)

    assert status == 0
    assert report["scope"]["mode"] == "cited_by"
    assert "heavy neutral leptons" in reported(report)


def test_cited_by_hides_the_vocabulary_of_another_task(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The collection outlives the query. This is the rule the scope exists for."""
    records = many(HNL, enough(), papers=(MINE,))
    records += many("Binary black hole mergers observed", enough(), papers=(THEIRS,))
    write_store(tmp_path, records)

    _, mine = run(tmp_path, "--topic", "sterile neutrino", "--cited-by", MINE,
                  capsys=capsys)

    assert "heavy neutral leptons" in reported(mine)
    assert not any("black hole" in term for term in reported(mine))

    _, whole = run(tmp_path, "--topic", "sterile neutrino", "--all-papers",
                   capsys=capsys)

    assert any("black hole" in term for term in reported(whole))


def test_all_papers_reads_the_whole_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    records = many(HNL, enough(), papers=(MINE,))
    records += many("Binary black hole mergers observed", enough(), papers=(THEIRS,))
    write_store(tmp_path, records)

    status, report = run(tmp_path, "--topic", "sterile neutrino", "--all-papers",
                         capsys=capsys)

    assert status == 0
    assert report["scope"]["mode"] == "all_papers"
    assert report["scanned"]["records"] == len(records)


def test_the_scan_refuses_to_run_with_no_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No flag is an error. A default would answer somebody else's question."""
    write_store(tmp_path, many(HNL, enough()))
    reads: list[Path] = []
    monkeypatch.setattr(
        terminology_scan.reference_store, "load",
        lambda root: reads.append(root) or [],
    )

    status, report = run(tmp_path, "--topic", "sterile neutrino", capsys=capsys)

    assert status == 2
    assert report["terms"] == []
    assert reads == []


def test_all_papers_combines_with_no_other_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One asks about the collection, one asks about a task. Not both at once."""
    write_store(tmp_path, many(HNL, enough()))

    status, report = run(tmp_path, "--topic", "sterile neutrino", "--all-papers",
                         "--cited-by", MINE, capsys=capsys)

    assert status == 2
    assert report["terms"] == []


def test_an_unknown_slug_exits_rather_than_reporting_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty report would read as "the field has no other name for this"."""
    write_store(tmp_path, many(HNL, enough()))

    status, report = run(tmp_path, "--topic", "sterile neutrino",
                         "--cited-by", "no_such_paper", capsys=capsys)

    assert status == 2
    assert report["unknown_papers"] == ["no_such_paper"]
    assert report["terms"] == []


def test_the_report_names_its_own_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A reader can then see that a scan covered one paper of two."""
    records = many(HNL, enough(), papers=(MINE,))
    records += many("Binary black hole mergers observed", enough(), papers=(THEIRS,))
    write_store(tmp_path, records)

    _, one = run(tmp_path, "--topic", "sterile neutrino", "--cited-by", MINE,
                 capsys=capsys)

    assert one["scope"]["papers"] == [MINE]
    assert one["scope"]["papers_in_collection"] == 2
    assert one["scope"]["titles_read"] == enough()

    _, whole = run(tmp_path, "--topic", "sterile neutrino", "--all-papers",
                   capsys=capsys)

    assert whole["scope"]["papers"] == sorted([MINE, THEIRS])
    assert whole["scope"]["titles_read"] == len(records)


def test_the_scan_reads_a_store_from_disk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One case covers the read from disk, end to end."""
    write_store(tmp_path, many(HNL, enough()))

    status, report = run(tmp_path, "--topic", "the mass of a sterile neutrino",
                         "--all-papers", capsys=capsys)

    assert status == 0
    assert report["literature_root"] == str(tmp_path)
    assert report["topic_terms"] == ["mass", "sterile", "neutrino"]
    assert reported(report) == ["heavy neutral leptons"]


def test_a_broken_store_is_reported_and_not_scanned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".references.jsonl").write_text("{not json\n", encoding="utf-8")

    status, report = run(tmp_path, "--topic", "sterile neutrino", "--all-papers",
                         capsys=capsys)

    assert status == 1
    assert "error" in report


# --------------------------------------------------------------------------
# the text of the papers
# --------------------------------------------------------------------------


def write_paper(
    root: Path, slug: str, title: str, abstract: str, chapters: dict[str, str]
) -> None:
    """One paper on disk, with the parts that `--in-text` reads."""
    paper = root / slug
    (paper / "chapters").mkdir(parents=True, exist_ok=True)
    (paper / "INDEX.md").write_text(
        "# %s\n\n## Abstract\n\n[Abstract] %s\n" % (title, abstract), encoding="utf-8"
    )
    for name, text in chapters.items():
        (paper / "chapters" / name).write_text(text, encoding="utf-8")


def in_text(root: Path, slug: str, topic: str, **options) -> dict:
    """The scan over the text of one paper, and no bibliography."""
    return terminology_scan.scan(
        root, topic, [], [slug], [slug], "in_text",
        units=terminology_scan.units_of(root, slug), **options
    )


def test_a_heading_weighs_more_than_a_paragraph(tmp_path: Path) -> None:
    """A heading is the author naming what a section is about."""
    heading = terminology_scan.STRUCTURE_WEIGHTS["heading"]
    body = terminology_scan.STRUCTURE_WEIGHTS["body"]
    assert heading > body

    write_paper(
        tmp_path, MINE, "A paper", "An abstract.",
        {
            "01.md": "## The Heavy Neutral Lepton\n\n"
                     "<a id=\"p1\"></a>\n\nOne mention of dark radiation here.\n",
        },
    )

    report = in_text(tmp_path, MINE, "sterile neutrinos", min_weight=1)
    named = next(
        item for item in report["terms"] if item["term"] == "heavy neutral lepton"
    )
    passing = [item for item in report["terms"] if "dark" in item["term"]]

    assert named["weight"] == heading
    assert all(named["weight"] > item["weight"] for item in passing)
    assert reported(report)[0] == "heavy neutral lepton"


def test_the_two_plural_forms_of_one_name_count_together(tmp_path: Path) -> None:
    """Counting them apart halves the evidence for both."""
    write_paper(
        tmp_path, MINE, "A paper", "An abstract.",
        {
            "01.md": "<a id=\"p1\"></a>\n\nThe heavy neutral lepton is one state.\n\n"
                     "<a id=\"p2\"></a>\n\nThe heavy neutral leptons are three.\n",
        },
    )

    report = in_text(tmp_path, MINE, "sterile neutrinos", min_weight=1)
    names = reported(report)

    assert names.count("heavy neutral lepton") + names.count("heavy neutral leptons") == 1
    merged = next(item for item in report["terms"] if "heavy neutral" in item["term"])
    assert merged["weight"] == 2 * terminology_scan.STRUCTURE_WEIGHTS["body"]


def test_a_plural_ending_stays_when_the_corpus_attests_no_stem() -> None:
    """Evidence decides, and no rule of English does. Nothing writes "mas"."""
    vocabulary = {"mass", "lepton", "leptons", "masses"}

    assert terminology_scan.singular("leptons", vocabulary) == "lepton"
    assert terminology_scan.singular("masses", vocabulary) == "mass"
    assert terminology_scan.singular("mass", vocabulary) == "mass"


def test_an_alias_reaches_the_report_with_the_passage_that_states_it(
    tmp_path: Path,
) -> None:
    """The claim and its evidence travel together, or the claim is worth nothing."""
    write_paper(
        tmp_path, MINE, "A paper", "An abstract.",
        {
            "06.md": "<a id=\"p10\"></a>\n\nThis comes with a prediction, namely the "
                     "existence of right-handed (sterile) neutrinos or heavy neutral "
                     "leptons $N_a$.\n",
        },
    )

    report = in_text(tmp_path, MINE, "sterile neutrinos", min_weight=1)
    stated = {item["term"]: item for item in report["stated_aliases"]}

    assert "heavy neutral leptons" in stated
    claim = stated["heavy neutral leptons"]
    assert claim["chapter"] == "06.md"
    assert claim["anchor"] == "p10"
    assert claim["cue"] == "or"
    assert "heavy neutral leptons" in claim["quote"]


def test_the_alias_search_anchors_on_the_rarest_word_of_the_topic(
    tmp_path: Path,
) -> None:
    """"Neutrinos" fires on every sentence of a neutrino paper. "Sterile" does not."""
    write_paper(
        tmp_path, MINE, "A paper", "An abstract.",
        {
            "01.md": "<a id=\"p1\"></a>\n\nNeutrinos oscillate between flavours.\n\n"
                     "<a id=\"p2\"></a>\n\nNeutrinos carry a tiny mass.\n\n"
                     "<a id=\"p3\"></a>\n\nRight-handed neutrinos, also called "
                     "sterile neutrinos, are singlets.\n",
        },
    )

    report = in_text(tmp_path, MINE, "sterile neutrinos", min_weight=1)

    assert report["alias_pivot"] == "sterile"
    assert [item["anchor"] for item in report["stated_aliases"]] == ["p3"]


def test_an_alias_names_no_phrase_of_running_prose(tmp_path: Path) -> None:
    """This block reports names. A function word inside means it is not one."""
    write_paper(
        tmp_path, MINE, "A paper", "An abstract.",
        {
            "01.md": "<a id=\"p1\"></a>\n\nIt is possible that sterile neutrino "
                     "masses extend below the GeV scale.\n",
        },
    )

    report = in_text(tmp_path, MINE, "sterile neutrinos", min_weight=1)
    terms = [item["term"] for item in report["stated_aliases"]]

    assert not any(" the " in " %s " % term for term in terms)
    assert "below the gev" not in terms


def test_the_text_source_reads_the_papers_and_the_store_does_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The case the text source exists for, end to end and from disk.

    The bibliography of this paper never says "heavy neutral lepton": a title
    names one thing once, and two names for one thing meet in a sentence.
    """
    write_store(tmp_path, many("Right-handed neutrino production", enough()))
    write_paper(
        tmp_path, MINE, "Right-handed neutrinos", "A pedagogical introduction.",
        {
            "05.md": "## The Heavy Neutral Lepton\n\n<a id=\"p2\"></a>\n\n"
                     "Right-handed neutrinos, sometimes called sterile neutrinos, "
                     "predict heavy neutral leptons.\n",
        },
    )

    _, titles = run(tmp_path, "--topic", "sterile neutrinos",
                    "--cited-by", MINE, capsys=capsys)
    assert "heavy neutral leptons" not in reported(titles)

    status, text = run(tmp_path, "--topic", "sterile neutrinos",
                       "--in-text", MINE, capsys=capsys)

    assert status == 0
    assert text["scope"]["mode"] == "in_text"
    assert text["scope"]["units_read"] > 0
    # The heading carries the singular and outweighs the sentence, so that is
    # the form a reader sees. The two forms are one name and one entry.
    assert "heavy neutral lepton" in reported(text)


def test_in_text_needs_the_paper_on_disk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A slug the store knows only as a citer has no text to read.

    That is a different mistake from a typo, and an empty report would read as
    "this paper offers no other name for the subject".
    """
    write_store(tmp_path, many(HNL, enough()))

    status, report = run(tmp_path, "--topic", "sterile neutrinos",
                         "--in-text", MINE, capsys=capsys)

    assert status == 2
    assert report["papers_without_text"] == [MINE]
    assert report["terms"] == []


def test_the_two_sources_combine(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One working set, read from two sides, in one report."""
    write_store(tmp_path, many(LEPTONS, enough()))
    write_paper(
        tmp_path, MINE, "A paper", "An abstract.",
        {"01.md": "<a id=\"p1\"></a>\n\nWe discuss the inverse seesaw mechanism.\n"},
    )

    status, report = run(tmp_path, "--topic", "sterile neutrinos",
                         "--in-text", MINE, "--cited-by", MINE,
                         "--min-count", "1", capsys=capsys)

    assert status == 0
    assert report["scope"]["mode"] == "in_text+cited_by"
    assert report["scope"]["titles_read"] == enough()
    assert report["scope"]["units_read"] > 0
    # One term from the bibliography, one from the paper's own sentence.
    assert "neutral leptons" in reported(report)
    assert "inverse seesaw mechanism" in reported(report)


def test_a_citation_bracket_is_no_alias_cue(tmp_path: Path) -> None:
    """A paper puts a citation beside almost every claim it makes.

    Without this rule the block reports the words near every such bracket, and
    a list of everything a paper says about its subject is not a list of names
    for it.
    """
    write_paper(
        tmp_path, MINE, "A paper", "An abstract.",
        {
            # "Sterile" has to be the rarer word of the topic, as it is in a
            # real paper, or the alias search anchors on "neutrinos" instead.
            "01.md": "<a id=\"p0\"></a>\n\nNeutrinos oscillate.\n\n"
                     "Neutrinos carry mass.\n\n"
                     "<a id=\"p1\"></a>\n\nA keV sterile neutrino provides warm "
                     "dark matter (Boyarsky et al., 2009).\n\n"
                     "<a id=\"p2\"></a>\n\nThe seesaw predicts right-handed "
                     "(sterile) neutrinos.\n",
        },
    )

    report = in_text(tmp_path, MINE, "sterile neutrinos", min_weight=1)
    assert report["alias_pivot"] == "sterile"
    anchors = {item["anchor"] for item in report["stated_aliases"]}

    # The bracket that holds the subject is a cue. The one that holds a
    # citation is not.
    assert anchors == {"p2"}
    # The brackets sit between "handed" and "neutrinos", so the name the window
    # offers is the phrase that stands beside the subject there.
    assert "right handed sterile" in [
        item["term"] for item in report["stated_aliases"]
    ]


def test_the_markup_of_a_chapter_is_not_a_name(tmp_path: Path) -> None:
    """`<p align="center">` would otherwise report "p align" as a term."""
    write_paper(
        tmp_path, MINE, "A paper", "An abstract.",
        {
            "01.md": "<a id=\"p1\"></a>\n\n<p align=\"center\"> The heavy neutral "
                     "lepton is a state. </p>\n",
        },
    )

    report = in_text(tmp_path, MINE, "sterile neutrinos", min_weight=1)

    assert "p align" not in reported(report)
    assert "heavy neutral lepton" in reported(report)
