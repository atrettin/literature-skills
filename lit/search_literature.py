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
that matched, the line it sits on and the sentence, so the passage can be opened
and read. `location` is what a report cites and `line_location` what a caller
checking a quotation opens.

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

from lit import blocks, cli, paths, reference_store
from lit import text
from lit.paths import stored_files

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


def flatten(text: str) -> str:
    """The words of a block, as a phrase copied out of it would be typed.

    A block is already one flat string, so nothing here has to track where a
    character came from — the block is the address. What is left is the
    difference between what a paper prints and what a person types: a curly
    quotation mark, a zero-width character standing inside a word, and a run of
    whitespace that a copy across two lines turned into a newline.
    """
    kept = (
        char for char in text if char != "\x00" and char not in ZERO_WIDTH
    )
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


def search_file(
    path: Path, pattern: re.Pattern[str], root: Path
) -> tuple[list[dict], bool]:
    """Every match in one stored chapter, and whether it held a NUL byte.

    A match is reported against the block that holds it: the anchor of that
    block is what a report cites, and the line the block sits on is what a
    caller checking a quotation opens. One block is one line, so the two say the
    same thing in the two forms each is used in.

    The NUL byte is dropped from the copy this matches against, and reported: a
    defect in the collection must stay visible.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    where = str(path.relative_to(root))
    slug = path.relative_to(root).parts[0]
    stem = path.stem

    results = []
    for line, stored in enumerate(raw.splitlines(), 1):
        if not stored.strip():
            continue
        # The control characters go before the parse, not after it. A NUL byte
        # inside a stored string is not JSON, and a file carrying one would
        # otherwise refuse to be searched at all — which is the failure this
        # command exists to prevent, arriving by another route.
        block = json.loads(CONTROL_CHARACTERS.sub("", stored))
        flat = flatten(blocks.words(block))
        if not flat:
            continue
        anchor = block.get("anchor") or None
        for match in pattern.finditer(flat):
            results.append({
                "paper": slug,
                "file": where,
                "chapter": stem,
                "anchor": anchor,
                # What a report cites: the chapter and the anchor, with no
                # extension, so it names the paper and not one rendering of it.
                "location": "%s/%s%s" % (slug, stem, "#" + anchor if anchor else ""),
                "line": line,
                # A scout reports `text/03_results.jsonl:181`. The same form
                # here lets a caller compare the two answers without building a
                # string.
                "line_location": "%s:%d" % (where, line),
                "kind": block.get("kind", ""),
                "sentence": sentence_around(flat, match.start(), match.end()),
            })
    return results, "\x00" in raw


def build_pattern(phrase: str, as_regex: bool, case_sensitive: bool) -> re.Pattern[str]:
    """The phrase as a pattern over the flat text.

    A literal phrase is flattened the same way a block is, so a phrase copied
    out of a rendered chapter matches the block it was rendered from.
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
    files = stored_files(root)
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
    parser = cli.parser(__doc__)
    parser.add_argument("phrase", help="the text to find; literal unless --regex")
    parser.add_argument("--regex", action="store_true",
                        help="read the phrase as a Python regular expression")
    parser.add_argument("--case-sensitive", action="store_true",
                        help="match the case of the phrase")
    parser.add_argument("--paper", action="append", metavar="SLUG", default=[],
                        help="search this paper only; repeat for more than one")
    parser.add_argument("--max-results", type=int, default=MAX_RESULTS, metavar="N",
                        help="report at most N matches (default %d)" % MAX_RESULTS)
    cli.add_root_argument(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = cli.parse(build_parser(), argv)
    root = args.literature_root

    if not root.is_dir():
        return cli.fail("%s does not exist" % root, cli.JUDGEMENT)

    held = set(paths.papers_on_disk(root))
    unknown = sorted(slug for slug in args.paper if slug not in held)
    if unknown:
        # Never ABSENT. That status says the phrase is absent, and this phrase
        # was never searched for.
        return cli.fail("no such paper in the collection", cli.JUDGEMENT,
                        unknown_papers=unknown, papers=sorted(held))

    report = search(
        root, args.phrase, args.paper, max(args.max_results, 1),
        as_regex=args.regex, case_sensitive=args.case_sensitive,
    )
    cli.emit(report)
    # 1 says the papers in scope do not carry the phrase. `partial_matches`
    # says which of its words they do carry.
    return 0 if report["matches"] else 1


if __name__ == "__main__":
    sys.exit(main())
