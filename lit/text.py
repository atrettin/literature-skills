#!/usr/bin/env python3
"""The text work that every other module does the same way.

A title becomes a name on disk here, a name becomes a table cell here, and a
passage becomes sentences here. Each of those has one answer, so a work held in
full and the same work cited by another paper reach the same tag, and a
quotation a search returns ends where a scan reading the same file says it
ends.
"""

from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------------
# the markup that shows up in more than one module
# --------------------------------------------------------------------------

# The command name of LaTeX markup: the `emph` of `\emph{...}`, the `rm` of
# `$m^{\rm eff}$`. Dropping the name and keeping the argument is what stops
# "emph" being read as a word of a title.
LATEX_COMMAND = re.compile(r"\\[a-zA-Z]+")

# A placeholder the conversion writes where it could not resolve something.
RESIDUE = re.compile(r"PH\d+")

# A character no decoder should have left in a chapter. The tab, the newline
# and the carriage return are deliberately not here.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f]")

# `[ref: label]`, a cross-reference the conversion could not resolve.
REF_TAG = re.compile(r"\[ref:\s*([^\]]*)\]")

# `<a id="sec-introduction"></a>`, an address a citation can reach.
ANCHOR = re.compile(r'<a id="([^"]+)"></a>')

# A Markdown heading, and the text after its hashes.
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

# What a table cell holds when nothing has filled it in.
EMPTY = "—"


# --------------------------------------------------------------------------
# normalising
# --------------------------------------------------------------------------


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def normalize_title(text: str) -> str:
    """Case-fold, drop LaTeX markup and punctuation, collapse whitespace."""
    # Drop the command names of LaTeX markup ("$C_5^A$", "\emph{...}"). The
    # punctuation rule below would otherwise leave "emph" in the title and
    # push a true match under `arxiv_search.EXACT_TITLE_RATIO`.
    text = LATEX_COMMAND.sub(" ", text)
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text.lower())
    return " ".join(text.split())


def query_words(text: str) -> str:
    """Reduce a title to the bare words that arXiv's phrase search accepts."""
    text = LATEX_COMMAND.sub(" ", text)
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text)
    return " ".join(text.split())


# The length under which a name keeps a cut word rather than lose more of the
# title. A name that says too little is worse than a name ending in half a word.
SLUG_MIN_CHARS = 24


def slugify(
    text: str, limit: int = 48, default: str = "section", whole_words: bool = False
) -> str:
    """Reduce text to the lower-case underscore form used for names on disk.

    Directory names, chapter file names and reference tags all pass through
    here, so a work held in full and the same work cited by another paper end
    up under one identifier. Callers naming something other than a section
    should say so: `default` is what comes back when nothing survives.

    `whole_words` cuts back to the last `_` when the cut at `limit` falls
    inside a word. It is off by default, and only a chapter file name asks for
    it: a reference tag sits inside the chapters of every paper citing the
    work, so a tag that moves breaks citations across the whole collection.
    """
    text = LATEX_COMMAND.sub(" ", text)
    # Fold accents onto their base letter first. Stripping them as punctuation
    # instead turns Glück into gl_ck and Argüelles into arg_elles, which read
    # as damage rather than as names.
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    cut = text[:limit]
    if whole_words and len(text) > limit and text[limit] != "_":
        # The cut fell inside a word. The last `_` is where that word began.
        shorter = cut.rsplit("_", 1)[0] if "_" in cut else cut
        if len(shorter) >= SLUG_MIN_CHARS:
            cut = shorter
    return cut.rstrip("_") or default


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------
# Markdown table cells
# --------------------------------------------------------------------------


def escape_cell(text: str) -> str:
    """Make a value safe to sit in a Markdown table cell.

    Only the pipe has to go: it splits the row into extra columns and every
    cell after it lands under the wrong heading, which stops the table being a
    lookup. Nothing else is touched. Titles in this field carry maths, and
    escaping `$` and `\\` turns a readable formula into backslash soup — worse
    to read than the emphasis it would prevent.
    """
    return collapse_whitespace(str(text or "")).replace("|", "\\|")


def split_cells(line: str) -> list[str]:
    """The cells of one table row, without the outer pipes.

    A pipe the writer escaped stays inside its cell: it is a character of the
    title, and splitting on it would give the row a column that is not there.
    """
    inner = line.strip()
    inner = inner[1:] if inner.startswith("|") else inner
    inner = inner[:-1] if inner.endswith("|") else inner
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", inner)]


# --------------------------------------------------------------------------
# names
# --------------------------------------------------------------------------


def surname(author: str) -> str:
    """The family name out of 'Lipari, Paolo' or 'P. Lipari' or 'Lipari'."""
    author = collapse_whitespace(LATEX_COMMAND.sub(" ", str(author or "")))
    if "," in author:
        return author.split(",", 1)[0].strip()
    parts = [part for part in author.split() if part]
    # Trailing initials happen ("Brieva F.A."); the name is what is left.
    while len(parts) > 1 and re.fullmatch(r"(?:[A-Z]\.?){1,3}", parts[-1]):
        parts.pop()
    return parts[-1] if parts else ""


def display_name(author: str) -> str:
    """'Lipari, Paolo' -> 'P. Lipari', which is how a reader expects to see it."""
    author = collapse_whitespace(author)
    if "," not in author:
        return author
    family, _, given = author.partition(",")
    initials = " ".join(
        "%s." % part[0] for part in re.split(r"[\s.]+", given) if part and part[0].isalpha()
    )
    return collapse_whitespace("%s %s" % (initials, family))


def display_authors(authors: list[str], shown: int, initials: bool = True) -> str:
    """The author list of one row, cut to `shown` names before `et al.`.

    `shown` differs by the row it is written into: a collection row has one
    column for the whole author list and names one author, and an identity
    table has the width for three. `initials` is off where the source already
    writes 'First Last' and turning that into 'F. Last' would lose nothing but
    gain nothing either.
    """
    names = [
        display_name(name) if initials else collapse_whitespace(name)
        for name in authors or []
        if collapse_whitespace(name)
    ]
    if not names:
        return EMPTY
    if len(names) > shown:
        return escape_cell(", ".join(names[:shown]) + " et al.")
    return escape_cell(", ".join(names))


# --------------------------------------------------------------------------
# sentences
# --------------------------------------------------------------------------

# A word that ends in a full stop without ending a sentence. Journal names and
# the shorthands of a citation are what a paper writes most: "Phys. Rev. D 108"
# is one reference and not three sentences. Matched without its full stop, and
# case-sensitively, so "we ate" keeps "at" out of it.
ABBREVIATIONS = frozenset(
    """Phys Rev Lett Nucl Astropart Eur Mod Ann Prog Rept J Int Suppl Conf Proc
    Fig Figs Eq Eqs Sec Secs Chap App Ref Refs Tab Vol No Ed Eds pp
    al cf vs e.g i.e resp approx ca et Dr Prof Univ Inst Collab""".split()
)

# The end of a sentence: one of these marks, then space. A mark with no space
# after it is inside a number or a name, as the 1.03 of an axial mass is.
_SENTENCE_END = re.compile(r"([.!?;])(\s+)")

# The word right before the mark, which decides whether the mark ends anything.
_LAST_WORD = re.compile(r"([A-Za-z][A-Za-z.]*)$")


def sentence_spans(text: str, clauses: bool = False) -> list[tuple[int, int]]:
    """Where each sentence of the text starts and ends.

    Spans rather than strings, so a caller holding an offset into the text —
    the position of a search match — can ask which sentence holds it.

    A break needs a mark, whitespace after it, and a word before it that is not
    an abbreviation. `clauses` breaks at a semicolon too, which is what a scan
    reading one clause at a time wants and a reader quoting a whole sentence
    does not.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        mark = match.group(1)
        if mark == ";" and not clauses:
            continue
        word = _LAST_WORD.search(text[start:match.start()])
        if word and word.group(1).rstrip(".") in ABBREVIATIONS:
            continue
        end = match.end(1)
        if text[start:end].strip():
            spans.append((start, end))
        start = match.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def sentences(text: str, clauses: bool = False) -> list[str]:
    """The sentences themselves, stripped."""
    return [text[start:end].strip() for start, end in sentence_spans(text, clauses)]


def span_around(text: str, start: int, end: int) -> tuple[int, int]:
    """The span of the sentence holding the range, or the whole text.

    A match that straddles a sentence break keeps every sentence it touches,
    because cutting it at the break would return half a quotation.
    """
    spans = sentence_spans(text)
    touched = [span for span in spans if span[0] < end and span[1] > start]
    if not touched:
        return 0, len(text)
    return touched[0][0], touched[-1][1]


def first_sentence(text: str, limit: int) -> str:
    """The opening of an abstract, as the description of a paper.

    An abstract's first sentence says what the paper is about more often than
    not, and it is the only description available at ingest that nobody had to
    invent.
    """
    text = collapse_whitespace(text)
    if not text:
        return ""
    spans = sentence_spans(text)
    sentence = text[spans[0][0]:spans[0][1]].strip() if spans else text
    return truncate(sentence, limit)
