#!/usr/bin/env python3
"""Find a phrase in the text of the papers, and say where it stands.

A quotation is checked against the paper it came from. `grep` cannot do that
here. A phrase is copied out of a rendered chapter, where the reader's viewer
wrapped it, so the phrase arrives carrying a line break the paper never had; a
file that holds a NUL byte reads as binary, and `grep` then prints nothing for
the whole file. Both failures make text that is present look absent, and a
reader of a report cannot see that error.

This matches the phrase and the stored block against each other in the same flat
form: no control characters, ASCII quotation marks, and one space for each run
of whitespace. The answer gives the paper, the chapter, the anchor of the block
that matched and the sentence, as `location` — the one address, which is what a
report cites, what `litdb show` opens, and what the next `--scope` accepts.

Every result also carries `prev`, `next` and `parent`, because an argument in a
paper is not one block: prose runs into an equation and out again. `--context`
brings those neighbouring blocks back with the match, which is the only way an
equation reaches the caller at all — mathematics is not words, so no search
matches it.

When the full phrase matches nothing, the search drops the last word and tries
again, down to MIN_BACKOFF_WORDS. `partial_matches` then says which shorter
phrase the papers do carry, so an absent phrase says which of its words is the
one the paper never wrote. `--approx` asks a different question: not which
papers carry these words, but which blocks answer this phrase.

Prints JSON on stdout. Reads only; nothing is written or downloaded.

Exit status is 0 when the full phrase matched, 1 when it matched nothing, and 2
when the search never ran — an unknown slug, or a collection that is not there.

Usage:
    search_literature.py "the phrase to find"
    search_literature.py "axial mass" --scope jeong_2023_shallow_deep_inelastic
    search_literature.py "form factor" --scope <slug>/06_cross_section#sec-transition
    search_literature.py "M_A\\s*=\\s*1.03" --regex
    search_literature.py "what limits the resolution" --scope <slug> --approx
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from lit import blocks, cli, rerank, scope
from lit import text

# The longest sentence the answer prints. Enough to see the words around the
# match; short enough that twenty matches do not fill a context window.
CONTEXT_CHARS = 300
# The default cap on the number of matches. A common word matches hundreds of
# times, and `matches` still reports the full count.
MAX_RESULTS = 20
# The shortest phrase the backoff tries. Two words match almost any paper, and
# such a match says nothing about the quotation.
MIN_BACKOFF_WORDS = 3
# The default cap on the words the whole answer carries. `--max-results` counts
# matches and cannot see this: twenty matches at `--context 2` is a hundred
# blocks, and the cap that bounds an answer has to bound what an answer holds.
MAX_WORDS = 2000

ELLIPSIS = "…"
# A curly mark and its ASCII form. A paper writes the curly one; a person
# quoting it types the straight one.
QUOTES = {
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‘": "'", "’": "'", "‚": "'",
}
# A character that takes no width: a zero-width space, a joiner, a byte-order
# mark. It stands inside a word, so it is dropped rather than made a space.
# Every character that is really a space, `str.isspace` reports.
ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff\u00ad"
# Every C0 control character other than the tab. None of them belongs inside a
# stored string, and a NUL byte stops the line being JSON at all.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0a-\x1f]")


def flatten(value: str) -> str:
    """The words of a block, as a phrase copied out of it would be typed.

    A block is already one flat string, so nothing here has to track where a
    character came from — the block is the address. What is left is the
    difference between what a paper prints and what a person types: a curly
    quotation mark, a zero-width character standing inside a word, and a run of
    whitespace that a copy across two lines turned into a newline.
    """
    kept = (char for char in value if char != "\x00" and char not in ZERO_WIDTH)
    return " ".join("".join(QUOTES.get(char, char) for char in kept).split())


def clip(sentence: str, start: int, end: int) -> str:
    """The sentence at CONTEXT_CHARS at most, keeping the match inside it."""
    if len(sentence) <= CONTEXT_CHARS:
        return sentence.strip()
    slack = max(CONTEXT_CHARS - (end - start), 0)
    left = max(0, start - slack // 2)
    right = min(len(sentence), left + CONTEXT_CHARS)
    left = max(0, right - CONTEXT_CHARS)
    piece = sentence[left:right]
    if left > 0:
        piece = ELLIPSIS + piece[1:]
    if right < len(sentence):
        piece = piece[:-1] + ELLIPSIS
    return piece.strip()


def sentence_around(flat: str, start: int, end: int) -> str:
    """The sentence of the flat text that holds the match."""
    begin, finish = text.span_around(flat, start, end)
    return clip(flat[begin:finish], start - begin, end - begin)


def word_count(value: str) -> int:
    return len(value.split())


# --------------------------------------------------------------------------
# what one match reports
# --------------------------------------------------------------------------


def surroundings(selection: scope.Selection, index: int, width: int) -> dict:
    """The blocks either side of a match, as a reader would step to them.

    Mathematics never matches a search, so a paragraph that says "substituting
    into (12)" arrives without (12) unless this brings it. The window stops at
    the chapter's edges rather than running into the chapter beside it: the two
    are different sections of the paper, and a block from the next chapter is
    not context for this one.
    """
    if width <= 0:
        return {}
    chapter = selection.blocks
    before = range(max(0, index - width), index)
    after = range(index + 1, min(len(chapter), index + width + 1))

    def described(positions) -> list[dict]:
        return [
            {
                "location": selection.location(position),
                "kind": chapter[position].get("kind", ""),
                "text": blocks.display(chapter[position]),
            }
            for position in positions
        ]

    return {"before": described(before), "after": described(after)}


def report_match(selection: scope.Selection, index: int, sentence: str,
                 width: int) -> dict:
    """One match, at the one address a caller can act on."""
    chapter = selection.blocks
    block = chapter[index]
    anchor = block.get("anchor") or ""
    near = blocks.neighbours(chapter, index)

    found = {
        "paper": selection.slug,
        "chapter": selection.stem,
        "anchor": anchor or None,
        # What a report cites, what `litdb show` opens, and what the next
        # `--scope` accepts. One address, and no second one to keep in step
        # with it.
        "location": scope.location(selection.slug, selection.stem, anchor),
        "kind": block.get("kind", ""),
        "sentence": sentence,
        # Where a reader goes from here without searching again.
        "prev": _address(selection, near["prev"]),
        "next": _address(selection, near["next"]),
        "parent": _address(selection, near["parent"]),
    }
    context = surroundings(selection, index, width)
    if context:
        found["context"] = context
    return found


def _address(selection: scope.Selection, anchor: str | None) -> str | None:
    if not anchor:
        return None
    return scope.location(selection.slug, selection.stem, anchor)


def answer_words(found: dict) -> int:
    """Everything one result would put in front of a caller."""
    total = word_count(found.get("sentence", ""))
    context = found.get("context") or {}
    for side in ("before", "after"):
        for entry in context.get(side) or []:
            total += word_count(entry["text"])
    return total


# --------------------------------------------------------------------------
# the exact search
# --------------------------------------------------------------------------


def read_flat(selection: scope.Selection) -> list[tuple[int, str]]:
    """Each block of the selection, with its words flattened for matching.

    The control characters go before the parse, not after it: a NUL byte inside
    a stored string is not JSON, and a file carrying one would otherwise refuse
    to be searched at all — which is the failure this command exists to
    prevent, arriving by another route. `blocks.read` has already parsed the
    file, so what is stripped here is stripped from the copy that is matched
    against and never from the store.
    """
    flat = []
    for index in range(selection.start, selection.end):
        words = blocks.words(selection.blocks[index])
        if not words:
            continue
        cleaned = flatten(CONTROL_CHARACTERS.sub("", words))
        if cleaned:
            flat.append((index, cleaned))
    return flat


def search_selection(selection: scope.Selection, pattern: re.Pattern[str],
                     width: int) -> list[dict]:
    """Every match inside one chapter's selection."""
    results = []
    for index, flat in read_flat(selection):
        for match in pattern.finditer(flat):
            results.append(report_match(
                selection, index,
                sentence_around(flat, match.start(), match.end()), width,
            ))
    return results


def build_pattern(phrase: str, as_regex: bool, case_sensitive: bool) -> re.Pattern[str]:
    """The phrase as a pattern over the flat text.

    A literal phrase is flattened the same way a block is, so a phrase copied
    out of a rendered chapter matches the block it was rendered from.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    if as_regex:
        return re.compile(phrase, flags)
    return re.compile(re.escape(" ".join(phrase.split())), flags)


def has_nul(selections: list[scope.Selection]) -> list[str]:
    """The chapters holding a NUL byte. A defect must stay visible."""
    warnings = []
    for selection in selections:
        if "\x00" in selection.path.read_text(encoding="utf-8", errors="replace"):
            warnings.append("%s/%s holds a NUL byte" % (selection.slug, selection.stem))
    return warnings


def bounded(results: list[dict], limit: int, max_words: int) -> tuple[list[dict], bool]:
    """The results that fit, under both caps, and whether anything was cut."""
    kept: list[dict] = []
    spent = 0
    for found in results:
        if len(kept) >= limit:
            return kept, True
        cost = answer_words(found)
        if kept and spent + cost > max_words:
            return kept, True
        kept.append(found)
        spent += cost
    return kept, False


def collect(selections: list[scope.Selection], pattern: re.Pattern[str],
            width: int) -> list[dict]:
    results: list[dict] = []
    for selection in selections:
        results.extend(search_selection(selection, pattern, width))
    return results


def shorter_phrases(phrase: str) -> list[str]:
    """The phrase with its last word dropped, again and again, longest first."""
    words = phrase.split()
    return [" ".join(words[:count])
            for count in range(len(words) - 1, MIN_BACKOFF_WORDS - 1, -1)]


# --------------------------------------------------------------------------
# the approximate search
# --------------------------------------------------------------------------

# A block carrying less than this share of the phrase never reaches the
# cross-encoder. The prefilter is what keeps an approximate search over a whole
# paper affordable, and coverage is the same measure `litdb find` uses to choose
# which abstracts a model reads.
APPROX_MIN_COVERAGE = 0.34

# How many blocks the cross-encoder reads. A model scores about 100 passages in
# 8 seconds, so this is the difference between an answer and a command that
# looks hung. The prefilter decides which blocks these are, and the report says
# how many of how many were ranked.
APPROX_MAX_BLOCKS = 300


def approximate(selections: list[scope.Selection], phrase: str, width: int,
                ) -> tuple[list[dict], str, str | None, dict]:
    """Rank the blocks in scope against the phrase. Returns (results, backend, note, counts).

    Coverage first, over the blocks in scope as the corpus, then a cross-encoder
    over what survives. That is the same two stages `litdb find` runs over
    abstracts, and for the same reason: coverage is cheap and explains itself,
    and the model reorders only what coverage has already described.
    """
    terms = text.query_words(phrase).split()
    entries: list[dict] = []
    for selection in selections:
        for index, flat in read_flat(selection):
            near = blocks.neighbours(selection.blocks, index)
            entries.append({
                "selection": selection,
                "index": index,
                "flat": flat,
                "title": _heading_title(selection.blocks, near["parent"]),
                "summary": flat,
            })

    if not entries:
        return [], "coverage", None, {"in_scope": 0, "ranked": 0}

    weights = rerank.term_weights(terms, entries)
    for entry in entries:
        share, missing = rerank.coverage(terms, entry["title"], entry["flat"], weights)
        entry["coverage"] = round(share, 4)
        entry["missing_terms"] = missing

    considered = sorted(
        (entry for entry in entries if entry["coverage"] >= APPROX_MIN_COVERAGE),
        key=lambda entry: -entry["coverage"],
    )[:APPROX_MAX_BLOCKS]

    counts = {"in_scope": len(entries), "ranked": len(considered)}
    if not considered:
        return [], "coverage", None, counts

    ordered, backend, note = rerank.rank(phrase, terms, considered, weights)

    results = []
    for entry in ordered:
        selection = entry["selection"]
        found = report_match(
            selection, entry["index"],
            clip(entry["flat"], 0, min(len(entry["flat"]), CONTEXT_CHARS)), width,
        )
        found["score"] = entry.get("score")
        found["coverage"] = entry["coverage"]
        found["missing_terms"] = entry["missing_terms"]
        results.append(found)
    return results, backend, note, counts


def _heading_title(chapter: list[dict], anchor: str | None) -> str:
    if not anchor:
        return ""
    block = blocks.find_anchor(chapter, anchor)
    return (block or {}).get("title", "") if block else ""


# --------------------------------------------------------------------------
# the whole answer
# --------------------------------------------------------------------------


def search(root: Path, phrase: str, scopes: list[scope.Scope], limit: int,
           as_regex: bool = False, case_sensitive: bool = False,
           width: int = 0, max_words: int = MAX_WORDS,
           approx: bool = False) -> dict:
    """The whole answer, for one phrase over the blocks in scope."""
    selections = scope.resolve(root, scopes)

    report = {
        "phrase": phrase,
        "literature_root": str(root),
        "scope": scope.described(scopes, selections),
        "warnings": has_nul(selections),
    }

    if approx:
        results, backend, note, counts = approximate(selections, phrase, width)
        kept, cut = bounded(results, limit, max_words)
        report.update({
            "matches": len(results),
            "truncated": cut,
            "results": kept,
            "ranking": {"backend": backend, "note": note, **counts},
            "partial_matches": [],
        })
        return report

    pattern = build_pattern(phrase, as_regex, case_sensitive)
    results = collect(selections, pattern, width)
    kept, cut = bounded(results, limit, max_words)

    partial: list[dict] = []
    if not results and not as_regex:
        for shorter in shorter_phrases(phrase):
            found = collect(selections, build_pattern(shorter, False, case_sensitive), 0)
            if found:
                shown, _ = bounded(found, limit, max_words)
                partial.append({"phrase": shorter, "matches": len(found),
                                "results": shown})
                break

    report.update({
        "matches": len(results),
        "truncated": cut,
        "results": kept,
        "partial_matches": partial,
    })
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = cli.parser(__doc__)
    parser.add_argument("phrase", help="the text to find; literal unless --regex")
    parser.add_argument("--regex", action="store_true",
                        help="read the phrase as a Python regular expression")
    parser.add_argument("--case-sensitive", action="store_true",
                        help="match the case of the phrase")
    parser.add_argument("--approx", action="store_true",
                        help="rank the blocks in scope against the phrase, "
                             "rather than matching it")
    parser.add_argument("--context", type=int, default=0, metavar="N",
                        help="report N blocks either side of each match")
    parser.add_argument("--max-results", type=int, default=MAX_RESULTS, metavar="N",
                        help="report at most N matches (default %d)" % MAX_RESULTS)
    parser.add_argument("--max-words", type=int, default=MAX_WORDS, metavar="N",
                        help="report at most N words in all (default %d)" % MAX_WORDS)
    parser.add_argument("--force", action="store_true",
                        help="let --approx read the whole collection")
    scope.add_scope_argument(parser)
    cli.add_root_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = cli.parse(build_parser(), argv)
    root = args.literature_root

    if not root.is_dir():
        return cli.fail("%s does not exist" % root, cli.JUDGEMENT,
                        results=[], matches=0)

    try:
        scopes = scope.parse_all(args.scope)
    except scope.ScopeError as error:
        return cli.fail(str(error), cli.JUDGEMENT, results=[], matches=0,
                        **error.fields)

    # An approximate search reads every block in scope and scores it. Over the
    # whole collection that is tens of thousands of blocks and minutes of
    # model time, and a command that looks hung is worse than one that refuses.
    if args.approx and not args.force and any(one.whole_collection for one in scopes):
        return cli.fail(
            "--approx needs a scope narrower than the whole collection; give "
            "--scope <slug> or a chapter, or --force to read everything",
            cli.JUDGEMENT, results=[], matches=0,
        )

    try:
        report = search(
            root, args.phrase, scopes, max(args.max_results, 1),
            as_regex=args.regex, case_sensitive=args.case_sensitive,
            width=max(args.context, 0), max_words=max(args.max_words, 1),
            approx=args.approx,
        )
    except scope.ScopeError as error:
        # Never ABSENT. That status says the phrase is absent, and this phrase
        # was never searched for.
        return cli.fail(str(error), cli.JUDGEMENT, results=[], matches=0,
                        **error.fields)

    cli.emit(report)
    # 1 says the papers in scope do not carry the phrase. `partial_matches`
    # says which of its words they do carry.
    return 0 if report["matches"] else 1


if __name__ == "__main__":
    sys.exit(main())
