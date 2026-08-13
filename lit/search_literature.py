#!/usr/bin/env python3
"""Find a phrase in the text of the papers, and say where it stands.

A quotation is checked against the paper it came from. `grep` cannot do that
here. Chapter text wraps, so a line break splits a phrase and the search finds
nothing; a file that holds a NUL byte reads as binary, and `grep` then prints
nothing for the whole file. Both failures make text that is present look absent,
and a reader of a report cannot see that error.

This matches against a flat copy of the text: no NUL bytes, ASCII quotation
marks, and one space for each run of whitespace. A match therefore carries
across a line break. The answer gives the paper, the chapter, the anchor above
the match, the line number and the sentence, so the passage can be opened and
read.

When the full phrase matches nothing, the search drops the last word and tries
again, down to MIN_BACKOFF_WORDS. `partial_matches` then says which shorter
phrase the papers do carry, so an absent phrase says which of its words is the
one the paper never wrote.

Prints JSON on stdout. Reads only; nothing is written or downloaded.

Exit status is 0 when the full phrase matched, 1 when it matched nothing, and 2
when the search never ran — an unknown slug, or a collection that is not there.

Usage:
    search_literature.py "the phrase to find"
    search_literature.py "axial mass" --paper jeong_2023_shallow_deep_inelastic
    search_literature.py "M_A\\s*=\\s*1.03" --regex
    search_literature.py "myocardial infarction" --case-sensitive --max-results 50
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lit import reference_store
from lit.check_references import ANCHOR, written_files

# The longest sentence the answer prints. Enough to see the words around the
# match; short enough that twenty matches do not fill a context window.
CONTEXT_CHARS = 300
# The default cap on the number of matches. A common word matches hundreds of
# times, and `matches` still reports the full count.
MAX_RESULTS = 20
# The shortest phrase the backoff tries. Two words match almost any paper, and
# such a match says nothing about the quotation.
MIN_BACKOFF_WORDS = 3

ELLIPSIS = "…"
# The end of a sentence, as the flat text writes it: one space follows.
SENTENCE_ENDS = (". ", "! ", "? ")
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


def flatten(text: str) -> tuple[str, list[int]]:
    """The text as one line, and the offset of each of its characters.

    The offsets are what makes a match addressable: the flat text has lost the
    line breaks, and `offsets[i]` says where character `i` stands in the file.
    """
    flat: list[str] = []
    offsets: list[int] = []
    in_space = False
    for index, char in enumerate(text):
        if char == "\x00" or char in ZERO_WIDTH:
            continue
        if char.isspace():
            if not in_space:
                in_space = True
                flat.append(" ")
                offsets.append(index)
            continue
        in_space = False
        flat.append(QUOTES.get(char, char))
        offsets.append(index)
    return "".join(flat), offsets


def line_of(text: str, offset: int) -> int:
    """The 1-based line of the file that holds this offset."""
    return text.count("\n", 0, offset) + 1


def anchor_above(text: str, offset: int) -> str | None:
    """The id of the last `<a id="…"></a>` at or before this offset.

    The anchor is what a citation can point at, and it outlives an edit that
    moves the line. A match above the first anchor of the file has none.
    """
    found = None
    for match in ANCHOR.finditer(text):
        if match.start() > offset:
            break
        found = match.group(1)
    return found


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
    begin = 0
    for mark in SENTENCE_ENDS:
        found = flat.rfind(mark, 0, start)
        if found != -1:
            begin = max(begin, found + len(mark))
    finish = len(flat)
    for mark in SENTENCE_ENDS:
        found = flat.find(mark, end)
        if found != -1:
            finish = min(finish, found + 1)
    return clip(flat[begin:finish], start - begin, end - begin)


def search_file(
    path: Path, pattern: re.Pattern[str], root: Path
) -> tuple[list[dict], bool]:
    """Every match in one file, and whether the file held a NUL byte.

    The byte is dropped from the copy this matches against, and reported: a
    defect in the collection must stay visible.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    flat, offsets = flatten(text)
    where = str(path.relative_to(root))
    slug = path.relative_to(root).parts[0]

    results = []
    for match in pattern.finditer(flat):
        offset = offsets[match.start()] if match.start() < len(offsets) else len(text)
        anchor = anchor_above(text, offset)
        line = line_of(text, offset)
        results.append({
            "paper": slug,
            "file": where,
            "anchor": anchor,
            "location": where + ("#" + anchor if anchor else ""),
            "line": line,
            # A scout reports `chapters/03_results.md:181`. The same form here
            # lets a caller compare the two answers without building a string.
            "line_location": "%s:%d" % (where, line),
            "sentence": sentence_around(flat, match.start(), match.end()),
        })
    return results, "\x00" in text


def build_pattern(phrase: str, as_regex: bool, case_sensitive: bool) -> re.Pattern[str]:
    """The phrase as a pattern over the flat text.

    A literal phrase is flattened the same way the text is, so a phrase copied
    out of a wrapped chapter matches the chapter it was copied from.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    if as_regex:
        return re.compile(phrase, flags)
    return re.compile(re.escape(" ".join(phrase.split())), flags)


def collect(
    files: list[Path], pattern: re.Pattern[str], root: Path, limit: int
) -> tuple[list[dict], int, list[str]]:
    """The capped results, the full count of matches, and the files with a NUL."""
    results: list[dict] = []
    matches = 0
    warnings: list[str] = []
    for path in files:
        found, has_nul = search_file(path, pattern, root)
        if has_nul:
            warnings.append("%s holds a NUL byte" % path.relative_to(root))
        matches += len(found)
        results.extend(found[: max(limit - len(results), 0)])
    return results, matches, warnings


def shorter_phrases(phrase: str) -> list[str]:
    """The phrase with its last word dropped, again and again, longest first."""
    words = phrase.split()
    return [" ".join(words[:count]) for count in range(len(words) - 1, MIN_BACKOFF_WORDS - 1, -1)]


def search(
    root: Path,
    phrase: str,
    papers: list[str],
    limit: int,
    as_regex: bool = False,
    case_sensitive: bool = False,
) -> dict:
    """The whole answer, for one phrase over the papers in scope."""
    files = written_files(root)
    slugs = sorted({path.relative_to(root).parts[0] for path in files})
    if papers:
        wanted = set(papers)
        files = [path for path in files if path.relative_to(root).parts[0] in wanted]

    pattern = build_pattern(phrase, as_regex, case_sensitive)
    results, matches, warnings = collect(files, pattern, root, limit)

    partial: list[dict] = []
    if not matches and not as_regex:
        for shorter in shorter_phrases(phrase):
            found, count, _ = collect(
                files, build_pattern(shorter, False, case_sensitive), root, limit
            )
            if count:
                partial.append({"phrase": shorter, "matches": count, "results": found})
                break

    return {
        "phrase": phrase,
        "literature_root": str(root),
        "scope": {
            "papers": sorted(papers) if papers else slugs,
            "papers_in_collection": len(slugs),
            "files_read": len(files),
        },
        "matches": matches,
        "truncated": matches > len(results),
        "results": results,
        "partial_matches": partial,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("phrase", help="the text to find; literal unless --regex")
    parser.add_argument("--regex", action="store_true",
                        help="read the phrase as a Python regular expression")
    parser.add_argument("--case-sensitive", action="store_true",
                        help="match the case of the phrase")
    parser.add_argument("--paper", action="append", metavar="SLUG", default=[],
                        help="search this paper only; repeat for more than one")
    parser.add_argument("--max-results", type=int, default=MAX_RESULTS, metavar="N",
                        help="report at most N matches (default %d)" % MAX_RESULTS)
    parser.add_argument("--literature-root", type=Path,
                        default=reference_store.default_root())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.literature_root

    if not root.is_dir():
        print(json.dumps({"error": "%s does not exist" % root}, indent=2))
        return 2

    held = {path.relative_to(root).parts[0] for path in written_files(root)}
    unknown = sorted(slug for slug in args.paper if slug not in held)
    if unknown:
        # Never 1. Status 1 says the phrase is absent, and this phrase was
        # never searched for.
        print(json.dumps({"error": "no such paper in the collection",
                          "unknown_papers": unknown,
                          "papers": sorted(held)}, indent=2))
        return 2

    report = search(
        root, args.phrase, args.paper, max(args.max_results, 1),
        as_regex=args.regex, case_sensitive=args.case_sensitive,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # 1 says the papers in scope do not carry the phrase. `partial_matches`
    # says which of its words they do carry.
    return 0 if report["matches"] else 1


if __name__ == "__main__":
    sys.exit(main())
