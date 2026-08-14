#!/usr/bin/env python3
"""Report the multiword terms of the literature that a topic phrase does not hold.

A subject can have a second name that shares no word with the first. "Heart
attack" and "myocardial infarction" name closely related objects, and the two
phrases have no word in common. A query that holds one name never finds the
papers that use the other name.

Two sources answer that, and a scan can read either or both.

`--in-text` reads the papers themselves. Two names for one object almost never
share a title, because a title names one thing once. They share a sentence,
where an author writes the equation between them: "an acute coronary event, or
myocardial infarction". A heading counts for more than a paragraph,
because a heading is the author naming what the section is about.

`--cited-by` reads the titles of the works those papers cite. Those titles are
the field's own words for its subjects, and they cover ground no paper of the
collection holds in full.

A term is scored on the weight of its occurrences, less the share of its words
that the topic already holds. The names worth finding are the ones the query
could not have reached, so a word shared with the query lowers a term rather
than lifting it.

`stated_aliases` is the second block of the report, and a list of claims rather
than a ranking. It holds each place where a paper writes the topic beside
another name, with the cue that joins them and the sentence that says it. A term
that reaches that block already carries the location that justifies it.

The scope is required. A collection serves many tasks, and it keeps the papers
of each. A scan of the whole store therefore reports the vocabulary of somebody
else's subject as another name for yours. `--in-text` and `--cited-by` name the
papers of one task. `--all-papers` is the explicit opt-out, for a question about
the collection itself. There is no default.

Prints one JSON report on stdout. It reads the collection on disk, and calls no
API.

The exit status is 0 whenever the scan ran, 1 when the store does not parse, and
2 when the scope is absent or names a paper the collection does not know. An
empty `terms` list is an answer, and not a failure.

Usage:
    terminology_scan.py --topic "heart attacks" --in-text vogt_2019_infarction
    terminology_scan.py --topic "the clotting cascade" --cited-by vogt_2019_infarction
    terminology_scan.py --topic "coronary risk factors" --all-papers
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lit import arxiv_discover, blocks, cli, paths
from lit import reference_store
from lit import text
from lit.text import collapse_whitespace, normalize_title

# `term_matches` decides when a word of a title is a word the topic already
# holds. It compares two words by prefix, at `rerank.MIN_PREFIX`, thus
# `neutrinos` answers `neutrino`. That constant needs no row of its own in
# TUNING.md: the row for `rerank.MIN_PREFIX` covers it, and the rule here is the
# rule the arXiv search uses.
from lit.rerank import term_matches

# The lengths of a term. A single word is what the topic's own term list already
# holds, and one word is too ambiguous to name a subject. A phrase of four words
# is a title, and its count falls under any useful threshold.
NGRAM_SIZES = (2, 3)

# What one occurrence of a term is worth, by the kind of text that holds it. A
# heading is the author naming what a section is about, and a paragraph is the
# author using the name in passing. A cited title is one work using the name
# once, which is what this scan counted before it could read a paper.
STRUCTURE_WEIGHTS = {
    "heading": 6,
    "abstract": 4,
    "caption": 2,
    "body": 1,
    "title": 1,
}

# How much weight a term must carry before the report keeps it. Under this
# value, a phrase that names nothing reaches the report beside a name that the
# field uses. A cited title weighs 1, so a title-only scan needs this many
# titles.
MIN_WEIGHT = 4

# How many terms the report holds. Each term costs the reader a judgement.
MAX_TERMS = 20

# How many places a term names as evidence. A reader reads these to see what a
# term is about, before it asks an agent about that term.
EXAMPLES_PER_TERM = 3

# A shorter term goes when a longer term that holds it reaches this share of its
# weight. "Myocardial infarction" adds nothing beside "acute myocardial
# infarction" when both weigh 11. The longer term is the name.
SUBSUME_RATIO = 0.8

# How much a word shared with the topic lowers the score of a term. A shared
# word is a word the query held already, and a term built from those words sends
# the next search where the last one went. At 1.0 a term counts only the share
# of its words that are new.
SHARED_WORD_PENALTY = 1.0

# Words that describe a kind of paper, and not a subject. A term never begins or
# ends with one, thus "search for acute" stays out and "acute myocardial
# infarction" comes through. A word of this list inside a term stays.
TITLE_FURNITURE = frozenset(
    """search searches measurement measurements observation observations
    constraint constraints limit limits evidence study studies review overview
    status implications prospects test tests analysis new first precise improved
    report results""".split()
)

# The apparatus of running prose: the words that point at a citation, an
# equation or a figure. A title holds none of them, and a paragraph holds them
# more often than it holds any subject. "Et al" leads the raw count of every
# paper that this scan reads. A word that names something in any field of the
# collection stays out of this list, whatever it points at in a sentence:
# "section" is half of "cross section", and "left" of "left ventricle".
PROSE_FURNITURE = frozenset(
    """et al cf ibid eq eqs eqn fig figs figure figures ref refs appendix
    appendices chapter panel""".split()
)

FURNITURE = TITLE_FURNITURE | PROSE_FURNITURE

# The words that join two names for one thing. A sentence that holds the topic
# within `ALIAS_WINDOW` words of one of these is a sentence where an author may
# be naming the subject twice. A bracket counts as a cue of its own:
# "an acute coronary (heart attack) event" is the same construction with no cue
# word in it.
ALIAS_CUES = frozenset(
    """or also called known termed sometimes often referred namely aka ie
    that is as""".split()
)

# The cues that carry no meaning on their own, and never begin a name.
ALIAS_CUE_PHRASES = (
    "also known as", "sometimes referred to as", "more often referred to as",
    "sometimes also called", "sometimes called", "also called", "referred to as",
    "known as", "namely", "i.e.", "termed", "or",
)

# How far from the topic word a cue and a name may stand. Wider finds a name
# that a long clause separates from the subject, and it reports the words of a
# neighbouring clause as a name.
ALIAS_WINDOW = 6

# How long a bracketed span can be and still be a name. Above this the brackets
# hold a clause, and the sentence is doing something other than naming twice.
MAX_BRACKET_WORDS = 3

# How long a bracketed span can be and still be the topic, written in brackets
# beside its other name: "an acute coronary (heart attack) event". A citation
# carries an author and a year, so it never fits here.
MAX_PIVOT_BRACKET_WORDS = 2

# How many alias claims the report holds. Each one costs the reader a sentence
# to read, and the block exists to be read in full.
MAX_ALIASES = 10

# The name of a LaTeX command in a title. It goes before the title is divided,
# thus `\emph{heart attacks}` gives no term that begins with `emph`.
LATEX_COMMAND = re.compile(r"\\[a-zA-Z]+")

# A hyphen between two alphanumerics belongs to the word. It becomes a space,
# thus "ST-elevation infarction" gives the term "st elevation infarction". Every
# other mark divides the title: without that rule, "Cardiac risk factors:
# interface of diet and exercise" gives the term "factors interface", which no
# author wrote.
IN_WORD_HYPHEN = re.compile(r"(?<=[0-9A-Za-z])[-‐‑](?=[0-9A-Za-z])")
SEPARATOR = re.compile(r"[^0-9A-Za-z ]+")


# --------------------------------------------------------------------------
# a title, as terms
# --------------------------------------------------------------------------


def segments(title: str) -> list[list[str]]:
    """The words of a title, divided at each mark of punctuation.

    An n-gram comes from one segment, thus a term never crosses a colon, a
    comma, a dash or a bracket.
    """
    text = IN_WORD_HYPHEN.sub(" ", LATEX_COMMAND.sub(" ", title))
    divided = []
    for piece in SEPARATOR.split(text):
        words = normalize_title(piece).split()
        if words:
            divided.append(words)
    return divided


def is_a_term(words: list[str]) -> bool:
    """Can this n-gram name a subject?

    "Of the acute" and "infarction in" are not names, "search for acute"
    describes a kind of paper, and "et al" is a citation. A function word inside
    a term stays: "decay of the pion" has "decay" and "pion" as its ends.
    """
    for end in (words[0], words[-1]):
        if end in arxiv_discover.TOPIC_STOPWORDS or end in FURNITURE:
            return False
    return not any(word.isdigit() for word in words)


def terms_of(title: str, sizes: tuple[int, ...] = NGRAM_SIZES) -> set[str]:
    """The distinct terms of one title.

    A set, thus a title that repeats a phrase gives one vote for it. The count
    of a term is then the number of works that use the term.
    """
    found = set()
    for words in segments(title):
        for size in sizes:
            for start in range(len(words) - size + 1):
                gram = words[start:start + size]
                if is_a_term(gram):
                    found.add(" ".join(gram))
    return found


# --------------------------------------------------------------------------
# a paper, as units of text
# --------------------------------------------------------------------------

MATH = re.compile(r"\$[^$]*\$")
CITE_MARKER = re.compile(r"\[(?:cite|ref):[^\]]*\]")


def readable(text: str) -> str:
    """One passage with what is not a word gone, on one line.

    Math goes whole: `$m_{L}^{\\rm eff}$` divides into no name. A citation or
    cross-reference marker goes with it — a tag holds the surname of another
    author and the words of another title, and neither is a term of this paper.
    """
    text = MATH.sub(" ", text)
    text = CITE_MARKER.sub(" ", text)
    return " ".join(text.split())


def sentences_of(passage: str) -> list[str]:
    """One clause at a time. A cue word governs its own clause and no more."""
    return text.sentences(passage, clauses=True)


# Which weight a stored block counts at. A block with no words of its own —
# maths, the raw TeX of a table, a fence — is not here and is not read.
BLOCK_KINDS = {
    "heading": "heading",
    "paragraph": "body",
    "figure": "caption",
    "table": "caption",
}


def units_of(root: Path, slug: str) -> list[dict]:
    """Every unit of text of one paper, with the kind and the place of each.

    A unit carries `kind`, which decides its weight, and `chapter` and `anchor`,
    which are how a reader opens it. The blocks arrive typed, so nothing here
    has to recognise a heading or a caption by the shape of its markup.
    """
    units: list[dict] = []

    paper = paths.read_paper(root, slug)
    title = collapse_whitespace(paper.get("title") or "")
    if title:
        units.append({
            "kind": "heading", "chapter": paths.PAPER_NAME, "anchor": "",
            "text": readable(title),
        })
    for sentence in sentences_of(readable(paper.get("abstract") or "")):
        units.append({
            "kind": "abstract", "chapter": paths.PAPER_NAME, "anchor": "",
            "text": sentence,
        })

    for path in paths.text_of(root, slug):
        for block in blocks.read(path):
            kind = BLOCK_KINDS.get(block.get("kind", ""))
            if not kind:
                continue
            words = readable(blocks.words(block))
            anchor = block.get("anchor") or ""
            if kind == "heading":
                units.append({
                    "kind": kind, "chapter": path.stem, "anchor": anchor,
                    "text": words,
                })
                continue
            for sentence in sentences_of(words):
                units.append({
                    "kind": kind, "chapter": path.stem, "anchor": anchor,
                    "text": sentence,
                })

    return [unit for unit in units if unit["text"]]


# --------------------------------------------------------------------------
# counting, over the units in scope
# --------------------------------------------------------------------------


def count_titles(
    records: list[dict],
) -> tuple[dict[str, int], dict[str, list[dict]], dict]:
    """Count each term by the titles that hold it, and keep a few of those titles.

    A record with no title is counted, and then skipped. `raw` is never read: an
    unresolved bibliography line carries authors, a journal and a page range,
    and those words are not terms.
    """
    weights: dict[str, int] = {}
    examples: dict[str, list[dict]] = {}
    scanned = {"records": len(records), "titles": 0, "without_title": 0}

    for record in records:
        title = str(record.get("title") or "").strip()
        if not title:
            scanned["without_title"] += 1
            continue
        scanned["titles"] += 1
        for term in sorted(terms_of(title)):
            weights[term] = weights.get(term, 0) + STRUCTURE_WEIGHTS["title"]
            seen = examples.setdefault(term, [])
            if len(seen) < EXAMPLES_PER_TERM:
                seen.append({"tag": record.get("tag") or "", "title": title})

    return weights, examples, scanned


def count_text(
    units: list[dict],
) -> tuple[dict[str, int], dict[str, list[dict]], dict]:
    """Weigh each term by the units that hold it, and keep a few of those places.

    A unit is one sentence, or one heading. A term that a sentence repeats
    counts once for that sentence, the way a term that a title repeats counts
    once for that title.
    """
    weights: dict[str, int] = {}
    places: dict[str, list[dict]] = {}
    scanned: dict[str, int] = {"units": len(units)}

    for unit in units:
        scanned[unit["kind"]] = scanned.get(unit["kind"], 0) + 1
        weight = STRUCTURE_WEIGHTS[unit["kind"]]
        for term in sorted(terms_of(unit["text"])):
            weights[term] = weights.get(term, 0) + weight
            seen = places.setdefault(term, [])
            if len(seen) < EXAMPLES_PER_TERM:
                seen.append({
                    "chapter": unit["chapter"],
                    "anchor": unit["anchor"],
                    "kind": unit["kind"],
                    "quote": unit["text"][:240],
                })

    return weights, places, scanned


# --------------------------------------------------------------------------
# one name, written two ways
# --------------------------------------------------------------------------


def singular(word: str, vocabulary: set[str]) -> str:
    """The word without its plural ending, when the corpus attests that word.

    Evidence decides, and no rule of English does. "Infarctions" gives
    "infarction" because the papers write "infarction" too; "stress" keeps its
    `s` because nothing writes "stres", and "bypass" keeps its `s` for the same
    reason.
    """
    for ending in ("es", "s"):
        if word.endswith(ending):
            stem = word[: -len(ending)]
            if stem in vocabulary:
                return stem
    return word


def merge_variants(
    weights: dict[str, int], evidence: dict[str, list[dict]]
) -> tuple[dict[str, int], dict[str, str], dict[str, list[dict]]]:
    """Add the weight of a plural to the weight of its singular, and pick a name.

    "Myocardial infarction" and "myocardial infarctions" are one name written
    two ways, and counting them apart halves the evidence for both. Returns the
    weight of each merged term by its key, the surface form to report for that
    key, and the evidence of every form together.
    """
    vocabulary = {word for term in weights for word in term.split()}

    merged: dict[str, int] = {}
    forms: dict[str, dict[str, int]] = {}
    gathered: dict[str, list[dict]] = {}
    for term, weight in weights.items():
        key = " ".join(singular(word, vocabulary) for word in term.split())
        merged[key] = merged.get(key, 0) + weight
        forms.setdefault(key, {})[term] = weight
        for item in evidence.get(term, []):
            if len(gathered.setdefault(key, [])) < EXAMPLES_PER_TERM:
                gathered[key].append(item)

    # The form a reader sees is the form the papers write most often. A tie goes
    # to the alphabet, so that one collection always gives one report.
    labels = {
        key: sorted(surfaces.items(), key=lambda pair: (-pair[1], pair[0]))[0][0]
        for key, surfaces in forms.items()
    }
    return merged, labels, gathered


# --------------------------------------------------------------------------
# what the topic does not hold
# --------------------------------------------------------------------------


def shared_and_new(term: str, topic_terms: list[str]) -> tuple[list[str], list[str]]:
    """The words of a term that the topic carries, and the words it does not."""
    topic = set(topic_terms)
    shared = [word for word in term.split() if term_matches(word, topic)]
    new = [word for word in term.split() if not term_matches(word, topic)]
    return shared, new


def holds_inside(shorter: str, longer: str) -> bool:
    """Do the words of the shorter term stand together inside the longer one?"""
    short_words = shorter.split()
    long_words = longer.split()
    span = len(short_words)
    return any(
        long_words[start:start + span] == short_words
        for start in range(len(long_words) - span + 1)
    )


def subsumed(weights: dict[str, int], kept: list[str]) -> set[str]:
    """The shorter terms that a longer kept term makes redundant.

    "Myocardial infarction" goes when "acute myocardial infarction" reaches
    `SUBSUME_RATIO` of its weight. A shorter term far heavier than every longer
    term that holds it stays: it then names something of its own.
    """
    gone = set()
    for shorter in kept:
        for longer in kept:
            if len(longer.split()) <= len(shorter.split()):
                continue
            if not holds_inside(shorter, longer):
                continue
            if weights[shorter] * SUBSUME_RATIO <= weights[longer]:
                gone.add(shorter)
                break
    return gone


# --------------------------------------------------------------------------
# the names an author writes beside the subject
# --------------------------------------------------------------------------


def pivot_word(units: list[dict], topic_terms: list[str]) -> str:
    """The topic word that the fewest units hold.

    A search anchored on "heart" fires on nearly every sentence of a cardiology
    paper and reports its whole vocabulary. One anchored on "attack" fires on
    the sentences that are about the subject. The rarest word of the
    topic is the one that separates it, so the text decides this and no
    parameter does.
    """
    if not topic_terms:
        return ""
    counts = {term: 0 for term in topic_terms}
    for unit in units:
        words = set(normalize_title(unit["text"]).split())
        for term in topic_terms:
            if term_matches(term, words):
                counts[term] += 1
    present = {term: count for term, count in counts.items() if count}
    if not present:
        return topic_terms[0]
    return min(present.items(), key=lambda pair: (pair[1], pair[0]))[0]


def alias_tokens(text: str) -> list[str]:
    """The words of a sentence, with a bracket kept as a word of its own.

    "An acute coronary (heart attack) event" is an alias written with brackets
    and no cue word, so the brackets have to survive normalization to be seen at
    all.
    """
    text = IN_WORD_HYPHEN.sub(" ", LATEX_COMMAND.sub(" ", text))
    text = re.sub(r"([()])", r" \1 ", text)
    tokens: list[str] = []
    for piece in text.split():
        if piece in "()":
            tokens.append(piece)
            continue
        tokens.extend(normalize_title(piece).split())
    return tokens


def word_cue(window: list[str]) -> str:
    """The cue phrase that joins two names, written as a reader would quote it.

    The window decides, and not the sentence. A long sentence carries "namely"
    in one clause and "or" in another, and naming the wrong one sends a reader
    to the wrong half of it.
    """
    text = " %s " % " ".join(token for token in window if token not in "()")
    for phrase in ALIAS_CUE_PHRASES:
        if " %s " % " ".join(phrase.replace(".", " ").split()) in text:
            return phrase
    return ""


def bracketed(window: list[str]) -> list[list[str]]:
    """The short spans that a pair of brackets encloses, as lists of words.

    Only the short ones. "An acute coronary (heart attack) event" writes an
    alias with brackets and no cue word, and a bracket that holds a whole clause
    is doing something else.
    """
    spans = []
    open_at = None
    for position, token in enumerate(window):
        if token == "(":
            open_at = position
        elif token == ")" and open_at is not None:
            span = [word for word in window[open_at + 1:position] if word not in "()"]
            if span and len(span) <= MAX_BRACKET_WORDS:
                spans.append(span)
            open_at = None
    return spans


def bracket_joins(spans: list[list[str]], pivot: str, gram: list[str]) -> bool:
    """Do these brackets hold one of the two names, and not a citation?

    A bracket is a cue only where it encloses a name: "an acute coronary (heart
    attack) event", or "heart attacks (myocardial infarctions)". A bracket that
    encloses neither is the apparatus of the sentence — nearly always a
    citation — and a paper puts one beside almost every claim it makes.
    """
    for span in spans:
        if len(span) <= MAX_PIVOT_BRACKET_WORDS and any(
            term_matches(pivot, {word}) for word in span
        ):
            return True
        if holds_inside(" ".join(gram), " ".join(span)):
            return True
    return False


def stated_aliases(
    units: list[dict], topic_terms: list[str], pivot: str, weights: dict[str, int]
) -> list[dict]:
    """Each place where a paper writes another name beside the subject.

    A claim, and not a count. The term, the chapter, the anchor, the cue and the
    sentence go together, so the reader who acts on a term can open the passage
    that offered it.
    """
    if not pivot:
        return []
    topic = set(topic_terms)
    found: dict[str, dict] = {}

    for unit in units:
        tokens = alias_tokens(unit["text"])
        for position, token in enumerate(tokens):
            if not term_matches(pivot, {token}):
                continue
            low = max(0, position - ALIAS_WINDOW)
            high = min(len(tokens), position + ALIAS_WINDOW + 1)
            window = tokens[low:high]
            phrase = word_cue(window)
            spans = bracketed(window)
            if not phrase and not spans:
                continue
            words = [token for token in window if token not in "()"]
            for size in NGRAM_SIZES:
                for start in range(len(words) - size + 1):
                    gram = words[start:start + size]
                    if not is_a_term(gram):
                        continue
                    if any(word in ALIAS_CUES for word in gram):
                        continue
                    # This block reports names, and not phrases. A function
                    # word anywhere inside means the words came from running
                    # prose: "introduce a single", "below the gev". The ranked
                    # list keeps the wider rule, where a long name can carry
                    # one ("decay of the pion").
                    if any(word in arxiv_discover.TOPIC_STOPWORDS for word in gram):
                        continue
                    if all(term_matches(word, topic) for word in gram):
                        continue
                    cue = phrase or (
                        "()" if bracket_joins(spans, pivot, gram) else ""
                    )
                    if not cue:
                        continue
                    term = " ".join(gram)
                    if term in found:
                        continue
                    found[term] = {
                        "term": term,
                        "chapter": unit["chapter"],
                        "anchor": unit["anchor"],
                        "cue": cue,
                        "quote": unit["text"][:240],
                    }

    # "Myocardial infarction" and "acute myocardial" add nothing beside "acute
    # myocardial infarction" when one passage offered all three. The longest is
    # the name.
    kept = [
        item for item in found.values()
        if not any(
            other["chapter"] == item["chapter"]
            and other["anchor"] == item["anchor"]
            and len(other["term"].split()) > len(item["term"].split())
            and holds_inside(item["term"], other["term"])
            for other in found.values()
        )
    ]

    # The heaviest term first. A name that the paper uses throughout is a better
    # lead than a phrase that one clause happened to carry beside the subject.
    ordered = sorted(
        kept, key=lambda item: (-weights.get(item["term"], 0), item["term"])
    )

    # One name, written two ways, is one claim. A reader who is offered
    # "myocardial infarction" and "myocardial infarctions" spends two of its
    # scouts on one question.
    vocabulary = {word for term in weights for word in term.split()}
    said: set[str] = set()
    once = []
    for item in ordered:
        key = " ".join(singular(word, vocabulary) for word in item["term"].split())
        if key in said:
            continue
        said.add(key)
        once.append(item)
    return once[:MAX_ALIASES]


# --------------------------------------------------------------------------
# the scope
# --------------------------------------------------------------------------


def papers_of(root: Path, records: list[dict]) -> list[str]:
    """Every paper slug that the collection knows.

    A directory with an `INDEX.md` is a paper held in full. A slug in the
    `cited_by` of a record names the same kind of paper, from the side of the
    works that it cites. The scan reads both, thus a slug is recognised whether
    or not the caller's root holds the paper directories.
    """
    slugs = set(paths.papers_on_disk(root))
    for record in records:
        for entry in record.get("cited_by") or []:
            slug = str(entry.get("slug") or "")
            if slug:
                slugs.add(slug)
    return sorted(slugs)


def cited_by(records: list[dict], slugs: list[str]) -> list[dict]:
    """The records that one of these papers cites."""
    wanted = set(slugs)
    return [
        record
        for record in records
        if any(entry.get("slug") in wanted for entry in record.get("cited_by") or [])
    ]


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------


def scan(
    root: Path,
    topic: str,
    records: list[dict],
    papers: list[str],
    scope_papers: list[str],
    mode: str,
    units: list[dict] | None = None,
    min_weight: int = MIN_WEIGHT,
    max_terms: int = MAX_TERMS,
) -> dict:
    """The whole answer, for one topic over the text and the titles in scope."""
    terms = arxiv_discover.topic_terms(topic)
    units = units or []

    title_weights, examples, scanned = count_titles(records)
    text_weights, places, read = count_text(units)

    weights = dict(title_weights)
    for term, weight in text_weights.items():
        weights[term] = weights.get(term, 0) + weight
    evidence: dict[str, list[dict]] = {}
    for term in weights:
        evidence[term] = (places.get(term) or []) + (examples.get(term) or [])

    merged, labels, gathered = merge_variants(weights, evidence)

    heavy = [key for key, weight in merged.items() if weight >= min_weight]
    # A term whose every word the topic carries is a term the query searched for
    # already. The report says what the query does not hold.
    described = {key: shared_and_new(labels[key], terms) for key in heavy}
    kept = sorted(key for key in heavy if described[key][1])
    gone = subsumed(merged, kept)
    kept = [key for key in kept if key not in gone]

    reported = []
    for key in kept:
        shared, new = described[key]
        label = labels[key]
        share = len(shared) / len(label.split())
        reported.append({
            "term": label,
            "weight": merged[key],
            "shared_words": shared,
            "new_words": new,
            "score": round(merged[key] * (1 - SHARED_WORD_PENALTY * share), 4),
            "examples": [item for item in gathered.get(key, []) if "title" in item],
            "places": [item for item in gathered.get(key, []) if "chapter" in item],
        })
    reported.sort(key=lambda item: (-item["score"], -item["weight"], item["term"]))

    pivot = pivot_word(units, terms)
    aliases = stated_aliases(units, terms, pivot, weights)

    return {
        "topic": topic,
        "literature_root": str(root),
        "scope": {
            "mode": mode,
            "papers": scope_papers,
            "titles_read": scanned["titles"],
            "units_read": read["units"],
            "papers_in_collection": len(papers),
        },
        "scanned": scanned,
        "read": read,
        "topic_terms": terms,
        "alias_pivot": pivot,
        "settings": {
            "ngram_sizes": list(NGRAM_SIZES),
            "min_weight": min_weight,
            "max_terms": max_terms,
            "structure_weights": dict(STRUCTURE_WEIGHTS),
            "alias_window": ALIAS_WINDOW,
        },
        "terms": reported[:max_terms],
        "stated_aliases": aliases,
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = cli.parser(__doc__)
    parser.add_argument(
        "--topic",
        required=True,
        help="the subject, written as a full phrase; the scan drops each term "
        "that this phrase holds already",
    )
    # The scope, and no default. A scan of the whole store answers a question
    # about the collection, and one collection serves more than one task.
    # `--in-text` and `--cited-by` name the same working set from two sides, so
    # they combine; `--all-papers` is the opt-out and combines with neither.
    parser.add_argument(
        "--in-text",
        action="append",
        default=[],
        metavar="SLUG",
        dest="in_text",
        help="read the text of this paper: its title, abstract, headings, "
        "captions and paragraphs; repeat it for each paper of the working set",
    )
    parser.add_argument(
        "--cited-by",
        action="append",
        default=[],
        metavar="SLUG",
        dest="cited_by",
        help="read the titles of the works that this paper cites; repeat it for "
        "each paper of the working set",
    )
    parser.add_argument(
        "--all-papers",
        action="store_true",
        help="read the titles of the whole store; for a question about the "
        "collection itself",
    )
    parser.add_argument(
        "--min-count", type=int, default=MIN_WEIGHT, metavar="N",
        dest="min_weight",
        help="how much weight a term must carry (default %d)" % MIN_WEIGHT,
    )
    parser.add_argument(
        "--max-terms", type=int, default=MAX_TERMS, metavar="N",
        help="how many terms the report holds (default %d)" % MAX_TERMS,
    )
    cli.add_root_argument(parser)
    return parser


def fail(message: str, code: int, **fields: object) -> int:
    return cli.fail(message, code, terms=[], **fields)


def main(argv: list[str] | None = None) -> int:
    args = cli.parse(build_parser(), argv)
    root = args.literature_root

    if not (args.in_text or args.cited_by or args.all_papers):
        return fail(
            "a scope is required: --in-text, --cited-by or --all-papers", 2
        )
    if args.all_papers and (args.in_text or args.cited_by):
        return fail(
            "--all-papers asks about the collection, and combines with no "
            "other scope", 2
        )

    if not arxiv_discover.topic_terms(args.topic):
        return fail("--topic holds no word to compare against; write it in full", 2)

    try:
        records = reference_store.load(root)
    except RuntimeError as error:
        return fail(str(error), 1)

    papers = papers_of(root, records)
    held = paths.papers_on_disk(root)

    if args.all_papers:
        mode, scope_papers, in_scope, units = "all_papers", papers, records, []
    else:
        unknown = sorted(
            slug for slug in args.cited_by + args.in_text if slug not in papers
        )
        if unknown:
            # Never an empty term list. A slug with a typo would narrow the scan
            # to nothing, and an empty report reads as "the field has no other
            # names for this subject".
            return fail(
                "no such paper in the collection", 2,
                unknown_papers=unknown, papers=papers,
            )
        # A slug the store knows only as a citer has no text on disk to read.
        # That is a different mistake from a typo, and it earns its own message.
        absent = sorted(slug for slug in args.in_text if slug not in held)
        if absent:
            return fail(
                "--in-text needs the paper on disk, and these are known only "
                "as citing papers", 2,
                papers_without_text=absent, papers_on_disk=held,
            )
        mode = "+".join(
            name for name, given in
            (("in_text", args.in_text), ("cited_by", args.cited_by)) if given
        )
        scope_papers = sorted(set(args.cited_by) | set(args.in_text))
        in_scope = cited_by(records, sorted(set(args.cited_by)))
        units = [
            unit for slug in sorted(set(args.in_text)) for unit in units_of(root, slug)
        ]

    report = scan(
        root, args.topic, in_scope, papers, scope_papers, mode,
        units=units,
        min_weight=max(args.min_weight, 1),
        max_terms=max(args.max_terms, 1),
    )
    cli.emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
