#!/usr/bin/env python3
"""Download an arXiv paper's TeX source and write it into the literature database.

Writes, under `<literature-root>/<slug>/`:

    chapters/NN_<title>.md        one file per \\section, long ones split further
    figures/<figure files>        every figure the paper includes
    figures/FIGURES.md            file name, label, chapter and caption per figure

It does **not** write INDEX.md. The calling agent writes that, from the JSON
manifest this script prints on stdout plus its own reading of the chapters.

The manifest's `publication` block says where the paper was published. arXiv
alone cannot answer that, so it comes from INSPIRE-HEP; pass --no-inspire to
skip that lookup.

Usage:
    arxiv_fetch.py 1706.03621 --slug alvarez-ruso_2017_nustec_review
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from lit import cli, convert_figures, http
from lit import inspire_lookup
from lit import rate_gate
from lit import reference_store
from lit import references
from lit.arxiv_search import fetch_feed, parse_entries, read_feed
from lit.text import collapse_whitespace, slugify

EPRINT_URL = "https://arxiv.org/e-print/%s"
EPRINT_HOST = "arxiv.org"
REQUEST_TIMEOUT_S = 120.0
DEFAULT_MAX_CHAPTER_BYTES = 40000

# The sentinel that brackets a placeholder key. Private-use characters, so a
# key that survives the restore stays readable text rather than turning the
# file into something `grep` treats as binary.
SENTINEL_OPEN = "\ue000"
SENTINEL_CLOSE = "\ue001"
# How often restore walks its items. One pass answers a payload that holds a
# key; each further pass answers one more level of nesting.
RESTORE_PASSES = 4
# What a placeholder key leaves behind when the restore misses it. The text
# then reads `$\sim PH5 13$%` where the paper wrote a number, so it is a defect
# to report and not a thing to repair in place.
RESIDUE = re.compile(r"PH\d+")
# Every C0 control character other than the newline and the tab. None of them
# carries meaning in Markdown, and a NUL byte hides the rest of the file from
# `grep`.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f]")
# The length under which a block gets no paragraph anchor and no number. A
# block this short is a stub, a caption line or a fragment the conversion left
# standing, and an anchor line above it costs more noise than the address earns.
# One sentence of prose is longer than this.
PARAGRAPH_ANCHOR_MIN_CHARS = 80

FIGURE_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps", ".gif", ".svg")

# How a figure names its file. \includegraphics carries a star form, and older
# papers reach for the epsf and psfig interfaces instead — a paper using any of
# these would otherwise arrive with no figures at all.
GRAPHIC_COMMAND = re.compile(
    r"\\(?:includegraphics|epsfbox|epsffile|plotone|plottwo)\*?\s*"
    r"(?:\[[^\]]*\])?\s*\{([^}]*)\}"
)
# `psfig` and `epsfig` name the file with a key, and they accept two spellings
# of that key. `figure=` is the older one and the commoner one in a paper of the
# 1990s or 2000s. A pattern that reads `file=` alone drops every such figure
# without a word, and the paper's own \ref commands then point at figures that
# are not there.
GRAPHIC_KEYVALUE = re.compile(
    r"\\(?:psfig|epsfig)\s*\{[^}]*?\b(?:figure|file)\s*=\s*([^,}]+)[^}]*\}"
)
FIGURE_ENVIRONMENTS = ("figure*", "figure", "wrapfigure", "SCfigure")
TABLE_ENVIRONMENTS = ("table*", "table", "longtable", "sidewaystable")
MATH_ENVIRONMENTS = (
    "equation*", "equation", "align*", "align", "eqnarray*", "eqnarray",
    "gather*", "gather", "multline*", "multline", "split", "displaymath",
    "flalign*", "flalign",
)
VERBATIM_ENVIRONMENTS = ("verbatim", "lstlisting", "Verbatim")

# Display maths is written as $$...$$ so that a Markdown preview renders it.
# KaTeX — what VS Code's preview uses — knows some of these environments and
# not others, so the body is unwrapped or re-wrapped accordingly.
BARE_MATH_ENVIRONMENTS = frozenset({"equation", "equation*", "displaymath"})
ALIGNED_MATH_ENVIRONMENTS = frozenset(
    {"eqnarray", "eqnarray*", "flalign", "flalign*", "multline", "multline*"}
)
# Valid LaTeX inside display maths that KaTeX rejects outright, taking the
# whole equation down with it.
# A TeX control word ends at the first non-letter, so "\alt350" is \alt
# followed by 350. \b would not see a boundary there — hence the lookahead.
END = r"(?![a-zA-Z])"
MATH_NOISE = re.compile(
    r"\\label\s*\{[^}]*\}|\\(?:nonumber|notag)%s|\\(?:vspace|hspace)\*?\s*\{[^}]*\}" % END
)
MATH_REWRITES = (
    # \ensuremath{X} is a no-op inside maths; dropping the name leaves {X}.
    (re.compile(r"\\ensuremath\s*(?=\{)"), ""),
    (re.compile(r"\\thinspace" + END), r"\\,"),
    (re.compile(r"\\medspace" + END), r"\\;"),
    (re.compile(r"\\negthinspace" + END), r"\\!"),
    (re.compile(r"\\mbox" + END), r"\\text"),
    (re.compile(r"\\eqref\s*\{[^}]*\}"), ""),
    # Spacing fillers that only mean something to a real typesetter.
    (re.compile(r"\\(?:hfill|hfil|vfill|noindent|protect|nobreak)" + END), ""),
    # REVTeX-era shorthands for "approximately less/greater than".
    (re.compile(r"\\alt" + END), r"\\lesssim"),
    (re.compile(r"\\agt" + END), r"\\gtrsim"),
    # The isotope package, standard in nuclear physics: \isotope[A][Z]{X}.
    (
        re.compile(r"\\isotope\s*\[([^\]]*)\]\s*\[([^\]]*)\]\s*\{([^}]*)\}"),
        r"{}^{\1}_{\2}\\mathrm{\3}",
    ),
    (re.compile(r"\\isotope\s*\[([^\]]*)\]\s*\{([^}]*)\}"), r"{}^{\1}\\mathrm{\2}"),
    (re.compile(r"\\isotope\s*\{([^}]*)\}"), r"\\mathrm{\1}"),
)

# Width in pixels for the figures embedded in the chapters.
FIGURE_WIDTH_PX = 500

# Commands whose whole call (name plus braced arguments) is dropped.
DROP_WITH_ARGS = (
    "label", "index", "vspace", "hspace", "setlength", "addcontentsline",
    "bibliographystyle", "bibliography", "pagestyle", "thispagestyle",
    "hypersetup", "affiliation", "altaffiliation", "thanks", "acknowledgments",
    "color", "definecolor", "colorbox", "pagecolor", "graphicspath",
)
# Commands that are dropped on their own, with no arguments to consume.
DROP_BARE = (
    "noindent", "centering", "bigskip", "medskip", "smallskip", "clearpage",
    "newpage", "hline", "toprule", "midrule", "bottomrule", "par", "raggedright",
    "footnotesize", "scriptsize", "small", "normalsize", "large", "Large",
    "LARGE", "huge", "Huge", "it", "bf", "rm", "sf", "tt", "em", "maketitle",
    "tableofcontents", "linebreak", "newline", "protect", "displaystyle",
)
# Commands replaced by the text of their single braced argument.
UNWRAP = (
    "emph", "textit", "textbf", "textrm", "textsf", "texttt", "textsc",
    "textnormal", "textup", "textsl", "mbox", "hbox", "text", "underline",
    "uppercase", "lowercase", "title", "author", "caption", "footnotesize",
)


# ==========================================================================
# small TeX scanning helpers
# ==========================================================================


def skip_spaces(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\n":
        index += 1
    return index


def match_brace(text: str, open_index: int) -> int:
    """Given the index of '{', return the index just past its matching '}'."""
    depth = 0
    index = open_index
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def read_optional(text: str, index: int) -> int:
    """Skip a '[...]' optional argument if one starts at `index`."""
    index = skip_spaces(text, index)
    if index < len(text) and text[index] == "[":
        depth = 0
        while index < len(text):
            if text[index] == "[":
                depth += 1
            elif text[index] == "]":
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
    return index


def read_group(text: str, index: int) -> tuple[str, int]:
    """Read a '{...}' argument at `index`. Returns (contents, index past it)."""
    index = skip_spaces(text, index)
    if index < len(text) and text[index] == "{":
        end = match_brace(text, index)
        return text[index + 1 : end - 1], end
    return "", index


def find_environment(text: str, name: str, start: int = 0) -> tuple[int, int, str] | None:
    """Find the next \\begin{name}...\\end{name}, respecting nesting.

    Returns (start_index, end_index, body) or None.
    """
    opener = "\\begin{%s}" % name
    closer = "\\end{%s}" % name
    begin = text.find(opener, start)
    if begin < 0:
        return None
    depth = 1
    cursor = begin + len(opener)
    while depth:
        next_open = text.find(opener, cursor)
        next_close = text.find(closer, cursor)
        if next_close < 0:
            return begin, len(text), text[begin + len(opener) :]
        if 0 <= next_open < next_close:
            depth += 1
            cursor = next_open + len(opener)
        else:
            depth -= 1
            cursor = next_close + len(closer)
    body_start = begin + len(opener)
    return begin, cursor, text[body_start : cursor - len(closer)]


def strip_comments(text: str) -> str:
    out = []
    for line in text.split("\n"):
        cleaned = re.sub(r"(?<!\\)((?:\\\\)*)%.*$", r"\1", line)
        out.append(cleaned)
    return "\n".join(out)


# ==========================================================================
# download and extract
# ==========================================================================


class NoSource(RuntimeError):
    """arXiv served no TeX for this paper: a PDF, an empty archive, or an error.

    Carries what the driver reports as `NO_ARXIV_SOURCE`. It is a fact about
    the submission, so no retry and no other paper answers it.
    """

    def __init__(self, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.reason = message


class MetadataUnavailable(RuntimeError):
    """arXiv did not answer for the paper, so its identity is unknown.

    Carries what the driver reports as `NETWORK_UNAVAILABLE`. It says nothing
    about the paper: the same request usually answers a minute later.
    """


class ParserFailure(RuntimeError):
    """The source parsed to no section, or to no chapter holding text.

    Carries what the driver reports as `PARSER_FAILURE`. Such a paper needs a
    conversion by hand, or none.
    """

    def __init__(self, message: str, main_tex: str = "", sections_found: int = 0) -> None:
        super().__init__(message)
        self.main_tex = main_tex
        self.sections_found = sections_found


def download_source(arxiv_id: str, work_dir: Path) -> Path:
    url = EPRINT_URL % arxiv_id
    try:
        payload = http.get(url, EPRINT_HOST, REQUEST_TIMEOUT_S)
    except urllib.error.HTTPError as error:
        raise NoSource(
            "arXiv returned HTTP %s for %s. The submission may be PDF-only, "
            "which carries no TeX source." % (error.code, url),
            http_status=error.code,
        )
    except (urllib.error.URLError, TimeoutError) as error:
        raise NoSource("download of %s failed: %s" % (url, error))

    if not payload:
        raise NoSource("arXiv served an empty source archive for %s" % arxiv_id)

    source_dir = work_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    if payload[:2] == b"\x1f\x8b":
        payload_plain = gzip.decompress(payload)
    else:
        payload_plain = payload

    if payload_plain[:5] == b"%PDF-":
        raise NoSource(
            "arXiv served a PDF for %s, not TeX source. This paper cannot be "
            "ingested automatically." % arxiv_id
        )

    try:
        with tarfile.open(fileobj=io.BytesIO(payload_plain)) as archive:
            extract_safely(archive, source_dir)
        return source_dir
    except tarfile.ReadError:
        pass

    (source_dir / "main.tex").write_bytes(payload_plain)
    return source_dir


def extract_safely(archive: tarfile.TarFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.getmembers():
        if member.issym() or member.islnk():
            continue
        target = (root / member.name).resolve()
        if not str(target).startswith(str(root) + os.sep) and target != root:
            raise RuntimeError("archive member escapes the extraction root: %s" % member.name)
    archive.extractall(destination)


def find_main_tex(source_dir: Path) -> Path:
    candidates = sorted(source_dir.rglob("*.tex"))
    if not candidates:
        raise NoSource("no .tex file in the downloaded source")

    full = []
    for path in candidates:
        text = read_text(path)
        if "\\documentclass" in text and "\\begin{document}" in text:
            full.append(path)
    if not full:
        full = [max(candidates, key=lambda path: path.stat().st_size)]
    if len(full) == 1:
        return full[0]

    # Prefer a file that no other file inputs.
    included = set()
    for path in candidates:
        for match in re.finditer(r"\\(?:input|include)\s*\{([^}]*)\}", read_text(path)):
            included.add(Path(match.group(1)).stem)
    not_included = [path for path in full if path.stem not in included]
    pool = not_included or full
    return max(pool, key=lambda path: path.stat().st_size)


def read_text(path: Path) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, OSError):
            continue
    return ""


def inline_inputs(text: str, base_dir: Path, source_dir: Path, depth: int = 0) -> str:
    """Recursively replace \\input{f} / \\include{f} with the file's content."""
    if depth > 8:
        return text

    def resolve(name: str) -> Path | None:
        name = name.strip()
        for candidate in (base_dir / name, source_dir / name):
            for path in (candidate, candidate.with_suffix(".tex")):
                if path.is_file():
                    return path
        matches = list(source_dir.rglob(Path(name).name + ".tex"))
        return matches[0] if matches else None

    def replace(match: re.Match) -> str:
        path = resolve(match.group(1))
        if path is None:
            return ""
        return "\n" + inline_inputs(
            strip_comments(read_text(path)), path.parent, source_dir, depth + 1
        ) + "\n"

    return re.sub(r"\\(?:input|include)\s*\{([^}]*)\}", replace, text)


# ==========================================================================
# structure: split the body into sections
# ==========================================================================


def collect_macros(preamble: str) -> dict:
    """Collect \\newcommand / \\def shorthands from the preamble.

    Returns `name -> (arity, body)`.

    Physics preambles define many zero-argument shorthands (\\dcp, \\nue,
    \\numu). Left alone they leave holes in the text. Macros that take
    arguments matter just as much: a paper that wraps its figures in
    `\\def\\rys#1#2#3{\\begin{figure}...\\includegraphics{#1}...}` hides every
    figure behind the macro, so the figure scan finds no `figure` environment
    and the paper arrives with no figures at all.

    Only mandatory `{...}` arguments are handled. A macro with an optional
    argument (`\\newcommand{\\x}[2][default]{...}`) or with delimiter tokens in
    its `\\def` parameter text is skipped: expanding those needs a real TeX
    engine, and getting them wrong is worse than leaving them alone.
    """
    macros = {}
    pattern = re.compile(r"\\(?:newcommand|renewcommand|providecommand)\*?\s*")
    cursor = 0
    while True:
        match = pattern.search(preamble, cursor)
        if not match:
            break
        index = match.end()
        name = ""
        if index < len(preamble) and preamble[index] == "{":
            end = match_brace(preamble, index)
            name = preamble[index + 1 : end - 1].strip()
            index = end
        else:
            name_match = re.match(r"\\([a-zA-Z]+)", preamble[index:])
            if name_match:
                name = "\\" + name_match.group(1)
                index += name_match.end()
        cursor = index
        if not name.startswith("\\"):
            continue
        after = skip_spaces(preamble, index)
        arity = 0
        if after < len(preamble) and preamble[after] == "[":
            closing = preamble.find("]", after)
            if closing < 0:
                continue
            digits = preamble[after + 1 : closing].strip()
            if not digits.isdigit():
                continue
            arity = int(digits)
            after = skip_spaces(preamble, closing + 1)
            if after < len(preamble) and preamble[after] == "[":
                continue  # optional argument with a default value
        if after >= len(preamble) or preamble[after] != "{":
            continue
        end = match_brace(preamble, after)
        macros[name[1:]] = (arity, preamble[after + 1 : end - 1])
        cursor = end

    for match in re.finditer(r"\\def\s*\\([a-zA-Z]+)\s*((?:#\d)*)\s*\{", preamble):
        params = match.group(2)
        # "#1#2#3" is a plain parameter list. Anything else is a delimited
        # parameter text, which this expander cannot honour.
        if params and not re.fullmatch(r"(?:#\d)+", params):
            continue
        end = match_brace(preamble, match.end() - 1)
        macros.setdefault(
            match.group(1), (len(params) // 2, preamble[match.end() : end - 1])
        )
    return macros


def substitute_parameters(body: str, args: list[str]) -> str:
    """Replace #1..#9 in a macro body with the arguments it was called with."""

    def replace(match: re.Match) -> str:
        position = int(match.group(1))
        return args[position - 1] if 1 <= position <= len(args) else match.group(0)

    return re.sub(r"(?<!\\)#(\d)", replace, body)


def expand_macros(text: str, macros: dict, passes: int = 4) -> str:
    if not macros:
        return text
    pattern = re.compile(r"\\([a-zA-Z]+)(?![a-zA-Z])")
    for _ in range(passes):
        pieces = []
        cursor = 0
        changed = False
        for match in pattern.finditer(text):
            if match.start() < cursor:
                continue  # inside an argument already consumed
            entry = macros.get(match.group(1))
            if entry is None:
                continue
            arity, body = entry
            index = match.end()
            args = []
            for _ in range(arity):
                index = skip_spaces(text, index)
                if index >= len(text):
                    break
                if text[index] == "{":
                    end = match_brace(text, index)
                    args.append(text[index + 1 : end - 1])
                    index = end
                    continue
                # TeX lets an undelimited argument be a single token, and
                # papers use it: "\n q" passes q to a one-argument \n. Without
                # this the macro is left unexpanded and reaches the reader.
                token = re.match(r"\\[a-zA-Z]+|\\.|[^\\]", text[index:])
                if not token:
                    break
                args.append(token.group(0))
                index += token.end()
            if len(args) != arity:
                continue  # called with too few arguments; leave it alone
            pieces.append(text[cursor : match.start()])
            pieces.append(substitute_parameters(body, args) if arity else body)
            cursor = index
            changed = True
        if not changed:
            break
        pieces.append(text[cursor:])
        text = "".join(pieces)
    return text


def apply_cite_tags(text: str, key_tags: dict[str, list[str]]) -> str:
    """Put reference tags in place of the paper's own LaTeX keys.

    `[cite: Lipari:2002at,Katori:2016yel]` becomes
    `[cite: lipari_2002_..., katori_2018_...]`, each tag naming a row of
    REFERENCES.md. One key can stand for several works, when the bibliography
    packed several into one \\bibitem, so it can expand to several tags.

    The marker is the intermediate form. update_references.py turns it into the
    link a reader follows, once the store has the author and year to label it
    with — see relink_citations there.

    A key the bibliography never defined keeps its original text: there is
    nothing to point it at, and leaving it visible is how that stays known.
    """
    def replace(match: re.Match) -> str:
        tags = []
        for key in match.group(1).split(","):
            key = collapse_whitespace(key)
            if key:
                tags.extend(key_tags.get(key) or [key])
        if not tags:
            return match.group(0)
        return "[cite: %s]" % ", ".join(tags)

    return reference_store.CITE_TAG.sub(replace, text)


def drop_bibliography(body: str) -> str:
    """Take the reference list out of the document.

    A paper that types its bibliography out in the TeX leaves it after the last
    \\section, so left alone it lands in that chapter, and a chapter on cross
    sections ends in "F.A. Brieva and J.R. Rook, Nuclear Physics A291".
    references.py has already read it by the time this runs, and the entries
    live in the reference store where a citation can reach them.
    """
    while True:
        found = find_environment(body, "thebibliography")
        if not found:
            break
        body = body[: found[0]] + body[found[1] :]
    # Only the environment is cut out, never everything after it. A paper that
    # puts its references before its appendices — and plenty do — would
    # otherwise lose every appendix along with them.
    return re.sub(r"\\bibliography\s*\{[^}]*\}", "", body)


def extract_body(text: str) -> str:
    found = find_environment(text, "document")
    return found[2] if found else text


def extract_abstract(text: str) -> str:
    found = find_environment(text, "abstract")
    if found:
        return clean_text(found[2], figures=None, chapter="abstract")[0].strip()
    match = re.search(r"\\abstract\s*\{", text)
    if match:
        end = match_brace(text, match.end() - 1)
        body = text[match.end() : end - 1]
        return clean_text(body, figures=None, chapter="abstract")[0].strip()
    return ""


def section_positions_texsoup(body: str) -> list[int] | None:
    """Offsets of top-level \\section commands, found by TexSoup."""
    try:
        from TexSoup import TexSoup
    except ImportError:
        return None
    try:
        soup = TexSoup(body, tolerance=1)
        positions = []
        for node in soup.find_all(["section", "section*"]):
            position = getattr(node, "position", None)
            if position is None:
                return None
            backslash = body.rfind("\\", 0, position + 1)
            positions.append(backslash if backslash >= 0 else position)
        return sorted(set(positions))
    except Exception:
        return None


def section_positions_regex(body: str) -> list[int]:
    return [match.start() for match in re.finditer(r"\\section\*?\s*(?:\[|\{)", body)]


def split_sections(body: str, positions: list[int]) -> list[tuple[str, str]]:
    """Return [(section title, raw section body)] in document order."""
    sections = []
    if not positions:
        return [("Full text", body)]

    lead = body[: positions[0]].strip()
    if len(lead) > 200:
        sections.append(("Front matter", body[: positions[0]]))

    for index, start in enumerate(positions):
        end = positions[index + 1] if index + 1 < len(positions) else len(body)
        chunk = body[start:end]
        after_star = len("\\section*") if chunk.startswith("\\section*") else len("\\section")
        cursor = read_optional(chunk, after_star)
        title, cursor = read_group(chunk, cursor)
        sections.append((clean_inline(title), chunk[cursor:]))
    return sections


# ==========================================================================
# TeX -> text
# ==========================================================================


class Placeholder:
    """Holds verbatim chunks (math, tables) out of harm's way while cleaning.

    The sentinel around a key is a private-use character, U+E000 and U+E001. A
    key that escapes the restore is then still readable text. A NUL byte in its
    place makes `grep` read the whole file as binary, which hides every line of
    it, including the lines that are correct.
    """

    KEY = "PH%d"

    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.counter = 0

    def stash(self, payload: str) -> str:
        self.counter += 1
        key = self.KEY % self.counter
        self.items[key] = payload
        return key

    def restore(self, text: str) -> str:
        """Put every payload back, the innermost key last.

        A payload holds only the keys of the chunks stashed before it: the
        maths of a table's cells is stashed before the table itself. Reverse
        insertion order therefore restores the outer payload first, and the key
        it carries is then still waiting for its own turn. The loop covers a
        nesting deeper than one level.
        """
        for _ in range(RESTORE_PASSES):
            for key, payload in reversed(list(self.items.items())):
                text = text.replace(key, payload)
            if SENTINEL_OPEN not in text:
                break
        return text


def sanitise(text: str) -> str:
    """Drop every character that has no place in a Markdown file.

    This runs last, just before a write, and it is the guarantee. The sentinel
    decides only what a leaked placeholder key looks like; this decides that
    nothing below U+0020 other than a newline or a tab reaches the disk.
    """
    text = CONTROL_CHARACTERS.sub("", text)
    return text.replace(SENTINEL_OPEN, "").replace(SENTINEL_CLOSE, "")


# A line that opens one of these carries its own break: a heading, a list item,
# a table row, an HTML block, a quote or a maths delimiter.
LINE_BREAK_PREFIXES = ("#", "-", "*", "|", "<", ">", "$$", "```")


def reflow(text: str) -> str:
    """Join the lines of each paragraph with one space.

    TeX hard-wraps its prose at about 70 characters, and the break lands
    wherever the author's editor put it. A phrase that crosses such a break
    answers no search for that phrase, and a reader then concludes, wrongly,
    that the paper does not hold it. The renderer wraps the long line again, so
    the page reads as it did.

    A break stays where it carries meaning: inside a fenced block, inside a
    `$$ ... $$` block, and on a line that opens one of LINE_BREAK_PREFIXES.
    """
    out: list[str] = []
    paragraph: list[str] = []
    in_fence = False
    in_math = False

    def flush() -> None:
        if paragraph:
            out.append(" ".join(paragraph))
            paragraph.clear()

    for line in text.split("\n"):
        stripped = line.strip()
        if in_fence:
            out.append(line)
            in_fence = not stripped.startswith("```")
        elif in_math:
            out.append(line)
            in_math = stripped != "$$"
        elif stripped.startswith("```"):
            flush()
            out.append(line)
            in_fence = True
        elif stripped == "$$":
            flush()
            out.append(line)
            in_math = True
        elif not stripped:
            flush()
            out.append("")
        elif stripped.startswith(LINE_BREAK_PREFIXES):
            flush()
            out.append(line)
        else:
            paragraph.append(stripped)
    flush()
    return "\n".join(out)


# A block that opens with one of these is not prose. `[FIGURE:` names a figure
# the conversion could not resolve, which is a marker and not a sentence.
PARAGRAPH_BLOCK_PREFIXES = ("#", "<", "|", "-", "*", ">", "$$", "```", "[FIGURE:")


def paragraph_anchors(text: str) -> str:
    """Write `<a id="pN"></a>` above every prose paragraph of a chapter.

    A heading anchor addresses a section, and a section runs for pages.
    `chapter.md#p12` addresses the paragraph that carries the claim. The count
    starts at `p1` in every file, so it has to run after a long chapter is
    split, and the anchor is no target of a `\\ref`, so it stays out of the
    label map.
    """
    parts = re.split(r"(\n{2,})", text)
    out: list[str] = []
    number = 0
    in_fence = False
    in_math = False
    for index, part in enumerate(parts):
        if index % 2:
            out.append(part)  # the blank lines between two blocks
            continue
        block = part.strip()
        prose = (
            bool(block)
            and not in_fence
            and not in_math
            and not block.startswith(PARAGRAPH_BLOCK_PREFIXES)
            and len(block) >= PARAGRAPH_ANCHOR_MIN_CHARS
        )
        if prose:
            number += 1
            out.append('<a id="p%d"></a>\n\n%s' % (number, part))
        else:
            out.append(part)
        for line in block.split("\n"):
            stripped = line.strip()
            if in_fence:
                in_fence = not stripped.startswith("```")
            elif in_math:
                in_math = stripped != "$$"
            elif stripped.startswith("```"):
                in_fence = True
            elif stripped == "$$":
                in_math = True
    return "".join(out)


def clean_inline(text: str) -> str:
    """Clean a short fragment such as a section title or a caption."""
    return collapse_whitespace(clean_text(text, figures=None, chapter="")[0])


# ==========================================================================
# cross-references: numbering, anchors and links
# ==========================================================================

REF_TAG = re.compile(r"\[ref:\s*([^\]]*)\]")
# Environments whose rows are numbered one by one, as LaTeX numbers them.
ROW_NUMBERED_ENVIRONMENTS = frozenset(
    {"align", "align*", "eqnarray", "eqnarray*", "gather", "gather*",
     "flalign", "flalign*"}
)
LABEL_COMMAND = re.compile(r"\\label\s*\{([^}]*)\}")
PANEL_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def anchor_slug(label: str) -> str:
    """An HTML id for a LaTeX label: `fig:f2compare` becomes `fig-f2compare`.

    Named after the label rather than the number so that the anchor survives a
    re-fetch that renumbers, and so a reader can grep for it.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug or "ref"


class Numbering:
    """Numbers the objects a paper cross-references, and anchors each one.

    LaTeX resolves `\\ref{eq:ckmt}` against a counter that lives in the
    `\\label` and nowhere else, so a conversion that drops the label leaves the
    reader with `[ref: eq:ckmt]` and nothing anywhere to match it against. This
    walks the paper in the same order LaTeX does, hands each equation, figure,
    table and section its number, and remembers which chapter it landed in.
    `apply_ref_links` then turns every marker into a link.

    The numbers are recomputed, not read off the paper, so a document that
    renumbers by hand can end up one out. The link still lands on the right
    object; only the printed number is a guess.
    """

    def __init__(self) -> None:
        self.counts = {"equation": 0, "figure": 0, "table": 0}
        self.labels: dict[str, dict] = {}
        self.taken: set[str] = set()
        self.chapter_title = ""
        self.chapter_index = 0

    def start_chapter(self, index: int, title: str) -> None:
        self.chapter_index = index
        self.chapter_title = title

    def next_number(self, kind: str) -> str:
        self.counts[kind] += 1
        return str(self.counts[kind])

    def register(self, label: str, kind: str, number: str) -> str:
        """Record a label and return the anchor id to write next to the object."""
        label = collapse_whitespace(label)
        if not label:
            return ""
        if label in self.labels:
            return self.labels[label]["anchor"]
        anchor = anchor_slug(label)
        if anchor in self.taken:
            suffix = 2
            while "%s-%d" % (anchor, suffix) in self.taken:
                suffix += 1
            anchor = "%s-%d" % (anchor, suffix)
        self.taken.add(anchor)
        self.labels[label] = {
            "kind": kind,
            "number": number,
            "anchor": anchor,
            "chapter": self.chapter_title,
            "file": "",
        }
        return anchor

    def reserve(self, anchor: str) -> str:
        """Take an anchor that no label names, and return the unique form of it.

        A heading the source never labelled is no target of a `\\ref`, so it
        gets no entry in `self.labels`. It still needs an address: a citation
        that can name a file alone leaves the reader searching the file.
        """
        if not anchor:
            return ""
        if anchor in self.taken:
            suffix = 2
            while "%s-%d" % (anchor, suffix) in self.taken:
                suffix += 1
            anchor = "%s-%d" % (anchor, suffix)
        self.taken.add(anchor)
        return anchor

    def point_at(self, label: str, kind: str, number: str, anchor: str) -> None:
        """Register a label against an anchor another label already owns.

        A multi-panel figure carries one label for the whole figure and one per
        panel; the prose cites the whole-figure label, which has no block of
        its own to sit next to.
        """
        label = collapse_whitespace(label)
        if not label or label in self.labels:
            return
        self.labels[label] = {
            "kind": kind,
            "number": number,
            "anchor": anchor,
            "chapter": self.chapter_title,
            "file": "",
        }


def anchor_tag(anchor: str) -> str:
    return '\n\n<a id="%s"></a>\n' % anchor if anchor else ""


def split_math_rows(body: str) -> list[str]:
    """Split a multi-row maths body at its top-level `\\\\` row breaks.

    A `\\\\` inside a nested environment — a matrix, a cases block — ends a row
    of that, not of the equation, so nesting is tracked.
    """
    rows = []
    depth = 0
    start = 0
    index = 0
    while index < len(body):
        if body.startswith("\\begin{", index):
            depth += 1
            index += 7
            continue
        if body.startswith("\\end{", index):
            depth -= 1
            index += 5
            continue
        if body.startswith("\\\\", index):
            if depth <= 0:
                rows.append(body[start:index])
                index += 2
                # \\[2mm] carries a spacing argument that belongs to the break.
                index = read_optional(body, index)
                start = index
                continue
            index += 2
            continue
        if body[index] == "\\":
            index += 2
            continue
        index += 1
    rows.append(body[start:])
    return rows


def number_display_math(
    name: str, body: str, numbering: Numbering | None
) -> tuple[str, str, str]:
    """Number a display-maths body. Returns (body, anchor lines, tag).

    A number is written into the maths itself so the chapter reads like the
    paper: `\\tag{5}` for a block with one number, and `\\qquad (5)` per row for
    an `align`, where KaTeX does not accept `\\tag`. The tag comes back
    separately because it has to sit outside the environment the caller wraps
    the body in — KaTeX rejects it inside one.
    """
    if numbering is None:
        return body, "", ""

    starred = name.endswith("*")
    anchors = []

    def take(label: str, unnumbered: bool) -> str:
        """A number for this row, and the anchor for its label."""
        if unnumbered and not label:
            return ""
        number = numbering.next_number("equation")
        if label:
            anchors.append(numbering.register(label, "equation", number))
        return number

    tag = ""
    if name in ROW_NUMBERED_ENVIRONMENTS:
        pieces = []
        for row in split_math_rows(body):
            label_match = LABEL_COMMAND.search(row)
            label = label_match.group(1) if label_match else ""
            silent = bool(re.search(r"\\(?:nonumber|notag)(?![a-zA-Z])", row))
            number = take(label, starred or silent)
            if number and row.strip():
                row = "%s \\qquad (%s)" % (row.rstrip(), number)
            pieces.append(row)
        body = " \\\\ ".join(pieces)
    else:
        label_match = LABEL_COMMAND.search(body)
        label = label_match.group(1) if label_match else ""
        # `displaymath`, `\[...\]` and `$$...$$` are unnumbered in LaTeX, and
        # arrive here with an empty name.
        unnumbered = starred or name in ("", "displaymath", "split")
        number = take(label, unnumbered)
        if number:
            body = body.rstrip()
            tag = " \\tag{%s}" % number

    anchor_lines = "".join(anchor_tag(anchor) for anchor in anchors if anchor)
    return body, anchor_lines, tag


def number_headings(text: str, numbering: Numbering | None) -> str:
    """Turn `\\subsection{T}\\label{L}` into a numbered, anchored heading.

    The label has to be consumed here: by the time the heading rules run it has
    been separated from the heading it names, and `DROP_WITH_ARGS` deletes it.
    """
    if numbering is None:
        return text

    levels = {"subsection": 2, "subsubsection": 3}
    counters = {2: 0, 3: 0}
    pattern = re.compile(r"\\(subsubsection|subsection)\*?\s*(?=[\[{])")
    out = []
    cursor = 0
    while True:
        match = pattern.search(text, cursor)
        if not match:
            out.append(text[cursor:])
            break
        index = read_optional(text, match.end())
        if index >= len(text) or text[index] != "{":
            out.append(text[cursor : match.end()])
            cursor = match.end()
            continue
        end = match_brace(text, index)
        title = clean_inline(text[index + 1 : end - 1])

        level = levels[match.group(1)]
        counters[level] += 1
        if level == 2:
            counters[3] = 0
            number = "%d.%d" % (numbering.chapter_index, counters[2])
        else:
            number = "%d.%d.%d" % (numbering.chapter_index, counters[2], counters[3])

        # A label directly after the heading names the section, not whatever
        # follows it.
        anchor = ""
        after = skip_spaces(text, end)
        label_match = LABEL_COMMAND.match(text, after)
        if label_match:
            anchor = numbering.register(label_match.group(1), "section", number)
            end = label_match.end()
        else:
            # Named after the title, never after the number: an author who adds
            # a section renumbers every section after it, and a re-ingest must
            # not move an anchor a report already cites.
            anchor = numbering.reserve("sec-" + anchor_slug(title))

        out.append(text[cursor : match.start()])
        out.append("%s\n\n%s %s %s\n\n" % (anchor_tag(anchor), "#" * level, number, title))
        cursor = end
    return "".join(out)


def link_refs(
    text: str, labels: dict[str, dict], current_file: str, prefix: str = ""
) -> tuple[str, list[str]]:
    """Turn every `[ref: label]` into a link to the object it names.

    The link text is the number alone: the paper's own prose already supplies
    the word and the brackets around it, so `eq.~(\\ref{eq:ckmt})` reads as
    `eq. ([5](#eq-5))`. A label with no target keeps its marker — that is how a
    reference the source never defined stays visible.
    """
    missing = []

    def replace(match: re.Match) -> str:
        label = collapse_whitespace(match.group(1))
        entry = labels.get(label)
        if not entry:
            missing.append(label)
            return match.group(0)
        target = "" if entry["file"] == current_file and not prefix else (
            prefix + entry["file"]
        )
        return "[%s](%s#%s)" % (entry["number"], target, entry["anchor"])

    return REF_TAG.sub(replace, text), missing


def chapter_files_by_title(chapters: list[dict]) -> dict[str, str]:
    """The file each section title ended up in, first piece wins when it split."""
    by_title: dict[str, str] = {}
    for chapter in chapters:
        by_title.setdefault(chapter["title"].split(" — ")[0], chapter["file"])
    return by_title


def apply_ref_links(chapters: list[dict], numbering: Numbering) -> list[str]:
    """Resolve the cross-references of every chapter. Returns the labels missed.

    Runs once the chapters are settled, because a reference reaches across
    files and the file names are only known after a long chapter is split.
    """
    # Where each anchor actually ended up, which is not always the chapter it
    # was numbered in: a long chapter is split into several files. The chapter
    # it was numbered in answers for a label whose anchor never made it out --
    # one on an object the conversion dropped.
    in_file = {}
    for chapter in chapters:
        for found in re.finditer(r'<a id="([^"]*)"></a>', chapter["text"]):
            in_file.setdefault(found.group(1), chapter["file"])
    by_title = chapter_files_by_title(chapters)
    for entry in numbering.labels.values():
        entry["file"] = in_file.get(entry["anchor"]) or by_title.get(
            entry["chapter"], ""
        )

    missing: list[str] = []
    for chapter in chapters:
        chapter["text"], missed = link_refs(
            chapter["text"], numbering.labels, chapter["file"]
        )
        missing.extend(missed)
    return sorted(set(missing))


def apply_figure_targets(
    figure_records: list[dict], chapters: list[dict], numbering: Numbering
) -> None:
    """Give every figure record the chapter file that holds its anchor.

    Runs after `apply_ref_links`, which resolves each label to the file its
    anchor was written into. That file is not always the first file of the
    chapter the figure was numbered in, because a long chapter is split into
    several files and a figure in its later half lands in a later piece. A
    record whose label resolves to nothing has only the chapter title to go on,
    and the first file of that chapter is where a reader starts to look.

    The captions are resolved here too. A caption is read in `FIGURES.md`,
    which sits beside the chapters directory, so its links carry that prefix.
    """
    by_title = chapter_files_by_title(chapters)
    for record in figure_records:
        record["caption"], _ = link_refs(
            record.get("caption", ""), numbering.labels, "", prefix="../chapters/"
        )
        entry = numbering.labels.get(record.get("label", ""))
        record["anchor"] = entry["anchor"] if entry else ""
        record["chapter_file"] = (entry["file"] if entry else "") or by_title.get(
            record.get("chapter", ""), ""
        )


def sanitize_math(body: str) -> str:
    """Rewrite valid LaTeX that KaTeX cannot parse.

    KaTeX renders a subset of LaTeX, and one unknown control sequence fails the
    whole equation with "Undefined control sequence". These are the constructs
    the papers here actually use that it rejects.
    """
    body = MATH_NOISE.sub("", body)
    for pattern, replacement in MATH_REWRITES:
        body = pattern.sub(replacement, body)
    # \pmatrix{a & b} is plain TeX; KaTeX only knows the pmatrix environment.
    while True:
        found = re.search(r"\\(p|b|v|V|B)?matrix\s*\{", body)
        if not found:
            break
        end = match_brace(body, found.end() - 1)
        name = "%smatrix" % (found.group(1) or "")
        body = (
            body[: found.start()]
            + "\\begin{%s}%s\\end{%s}" % (name, body[found.end() : end - 1], name)
            + body[end:]
        )
    return body


def display_math(body: str) -> str:
    """Wrap a display-maths body so a Markdown preview renders it."""
    body = sanitize_math(body).strip("\n").strip()
    # A blank line ends a paragraph, and with it the maths block: what follows
    # would be printed as TeX. The source is free to leave one anywhere.
    return "\n\n$$\n%s\n$$\n\n" % re.sub(r"\n[ \t]*\n+", "\n", body)


def find_first_environment(
    text: str, names, start: int = 0
) -> tuple[str, int, int, str] | None:
    """The environment among `names` that begins first. Returns (name, ...).

    Figures, tables and equations are numbered as they are met, so they have to
    be met in the order the paper writes them — not one environment name after
    another, which would number every `figure*` before every `figure`.
    """
    best = None
    for name in names:
        found = find_environment(text, name, start)
        if found and (best is None or found[0] < best[1]):
            best = (name,) + found
    return best


def figure_block(
    file_name: str, caption: str, number: str = "", anchor: str = ""
) -> str:
    """Embed a figure so it shows in the preview, with its caption beneath.

    The chapters sit in `chapters/`, so the image is one level up in
    `figures/`. HTML rather than Markdown image syntax, because Markdown has
    no way to set a width and the figures are far too large at full size.
    """
    # Maths reads as noise in an alt attribute, and its backslashes and quotes
    # would have to be escaped anyway. The caption below the image keeps it.
    alt = re.sub(r"\$[^$]*\$", "", caption)
    # A citation marker goes too, and it must go before the cut below. A tag cut
    # in half leaves `[cite: Alvarez-Ru...` with no closing bracket, and the
    # citation reader then matches on to the next `]` anywhere in the file and
    # reports the whole run of text as a tag no record answers. The caption
    # under the image carries the citation, where it resolves.
    alt = reference_store.CITE_TAG.sub("", alt)
    alt = collapse_whitespace(re.sub(r'["\\<>]', " ", alt))
    alt = re.sub(r"\s+([,.;:])", r"\1", alt).strip(" ,;:") or "figure"
    if len(alt) > 120:
        alt = alt[:117].rstrip() + "..."
    block = (
        (anchor_tag(anchor) or "\n")
        + '\n<p align="center">\n'
        '<img src="../figures/%s" alt="%s" width="%d"/>\n'
        "</p>\n" % (file_name, alt, FIGURE_WIDTH_PX)
    )
    if caption:
        block += "\n**Figure%s.** %s\n" % (
            " " + number if number else "", collapse_whitespace(caption)
        )
    return block + "\n"


def clean_text(
    raw: str, figures: list | None, chapter: str, numbering: Numbering | None = None
) -> tuple[str, list[dict]]:
    """Convert a raw TeX fragment to readable text.

    Math is kept as TeX. Figures become a one-line marker and, when `figures`
    is a list, are appended to it as records.

    With a `Numbering`, every equation, figure, table and heading is numbered
    and anchored so that the paper's own cross-references can be linked back to
    it later. Without one — a caption, a title, the abstract — nothing is
    numbered, since those fragments are converted out of document order.
    """
    found_figures: list[dict] = []
    text = strip_comments(raw)
    holder = Placeholder()

    # A `\label` at the head of a section body names the section: the title
    # was consumed with the `\section` that split_sections cut at.
    chapter_anchor = ""
    if numbering is not None:
        opening = LABEL_COMMAND.match(text.lstrip())
        if opening:
            chapter_anchor = numbering.register(
                opening.group(1), "section", str(numbering.chapter_index)
            )
        else:
            chapter_anchor = numbering.reserve(
                "sec-" + anchor_slug(numbering.chapter_title)
            )

    # --- verbatim-ish environments, kept as fenced blocks -----------------
    for name in VERBATIM_ENVIRONMENTS:
        while True:
            found = find_environment(text, name)
            if not found:
                break
            start, end, body = found
            block = "\n\n```\n%s\n```\n\n" % body.strip("\n")
            text = text[:start] + holder.stash(block) + text[end:]

    # --- figures ----------------------------------------------------------
    while True:
        found = find_first_environment(text, FIGURE_ENVIRONMENTS)
        if not found:
            break
        _, start, end, body = found
        records = parse_figure(body, chapter)
        found_figures.extend(records)
        if records:
            number = numbering.next_number("figure") if numbering else ""
            marker = ""
            for index, record in enumerate(records):
                panel = number
                if number and len(records) > 1:
                    panel += PANEL_LETTERS[index % len(PANEL_LETTERS)]
                record["number"] = panel
                anchor = (
                    numbering.register(record["label"], "figure", panel)
                    if numbering else ""
                )
                if numbering and index == 0:
                    # The prose cites the figure as a whole; its label sits on
                    # the environment, not on any one panel.
                    whole = LABEL_COMMAND.search(body)
                    if whole:
                        numbering.point_at(
                            whole.group(1), "figure", number, anchor
                        )
                marker += figure_block(
                    record["file_hint"], record["caption"], panel, anchor
                )
        else:
            marker = "\n\n[FIGURE: unresolved]\n\n"
        text = text[:start] + holder.stash(marker) + text[end:]

    # --- tables, kept verbatim -------------------------------------------
    while True:
        found = find_first_environment(text, TABLE_ENVIRONMENTS)
        if not found:
            break
        _, start, end, body = found
        caption = extract_caption(body)
        anchor = ""
        number = ""
        if numbering:
            number = numbering.next_number("table")
            label = LABEL_COMMAND.search(body)
            if label:
                anchor = numbering.register(label.group(1), "table", number)
        block = "%s\n\n```tex\n%s\n```\n" % (anchor_tag(anchor), body.strip("\n"))
        if caption:
            block += "\n**Table%s.** %s\n\n" % (
                " " + number if number else "", caption
            )
        text = text[:start] + holder.stash(block) + text[end:]

    # --- display math -----------------------------------------------------
    while True:
        found = find_first_environment(text, MATH_ENVIRONMENTS)
        if not found:
            break
        name, start, end, body = found
        body, anchors, tag = number_display_math(name, body, numbering)
        if name in BARE_MATH_ENVIRONMENTS:
            inner = body
        elif name in ALIGNED_MATH_ENVIRONMENTS:
            # KaTeX has no eqnarray, flalign or multline. aligned takes the
            # same '&'-separated rows and renders them acceptably.
            inner = "\\begin{aligned}%s\\end{aligned}" % body
        else:
            inner = "\\begin{%s}%s\\end{%s}" % (name, body, name)
        text = (
            text[:start]
            + holder.stash(anchors + display_math(inner + tag))
            + text[end:]
        )

    def bare_display(body: str) -> str:
        body, anchors, tag = number_display_math("", body, numbering)
        return holder.stash(anchors + display_math(body + tag))

    text = re.sub(
        r"\\\[(.+?)\\\]", lambda m: bare_display(m.group(1)), text, flags=re.DOTALL
    )
    text = re.sub(
        r"\$\$(.+?)\$\$", lambda m: bare_display(m.group(1)), text, flags=re.DOTALL
    )

    # --- inline math ------------------------------------------------------
    text = re.sub(
        r"(?<!\\)\$(.+?)(?<!\\)\$",
        lambda m: holder.stash("$%s$" % sanitize_math(m.group(1))),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\\\((.+?)\\\)",
        lambda m: holder.stash("$%s$" % sanitize_math(m.group(1)).strip()),
        text,
        flags=re.DOTALL,
    )

    # --- headings ---------------------------------------------------------
    # Numbered first, which also takes the \label naming each heading; what is
    # left over is a heading no cross-reference points at.
    text = number_headings(text, numbering)
    text = replace_command_arg(text, "subsubsection", lambda arg: "\n\n### %s\n\n" % clean_inline(arg))
    text = replace_command_arg(text, "subsection", lambda arg: "\n\n## %s\n\n" % clean_inline(arg))
    text = replace_command_arg(text, "paragraph", lambda arg: "\n\n**%s** " % clean_inline(arg))
    text = replace_command_arg(text, "section", lambda arg: "\n\n## %s\n\n" % clean_inline(arg))

    # --- colour, which carries no meaning here ----------------------------
    text = re.sub(r"\\textcolor\s*\{[^}]*\}\s*", "", text)

    # --- references -------------------------------------------------------
    text = re.sub(
        r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear|onlinecite)\s*(?:\[[^\]]*\])*\s*\{([^}]*)\}",
        lambda m: "[cite: %s]" % collapse_whitespace(m.group(1)),
        text,
    )
    text = re.sub(
        r"\\(?:ref|eqref|autoref|cref|Cref|pageref|figref|tabref)\s*\{([^}]*)\}",
        lambda m: "[ref: %s]" % collapse_whitespace(m.group(1)),
        text,
    )
    text = re.sub(
        r"\\(?:href|url)\s*(?:\{([^}]*)\})?\s*\{([^}]*)\}",
        lambda m: m.group(1) or m.group(2),
        text,
    )
    text = replace_command_arg(text, "footnote", lambda arg: " (footnote: %s)" % clean_inline(arg))

    # --- lists ------------------------------------------------------------
    text = re.sub(r"\\begin\{(itemize|enumerate|description)\}", "\n", text)
    text = re.sub(r"\\end\{(itemize|enumerate|description)\}", "\n", text)
    text = re.sub(r"\\item\s*(\[[^\]]*\])?\s*", "\n- ", text)

    # --- leftover commands -------------------------------------------------
    for name in DROP_WITH_ARGS:
        text = replace_command_arg(text, name, lambda arg: "")
    for _ in range(3):
        for name in UNWRAP:
            text = replace_command_arg(text, name, lambda arg: arg)
    text = re.sub(r"\\begin\{[^}]*\}(\s*\{[^}]*\})*(\s*\[[^\]]*\])*", "\n", text)
    text = re.sub(r"\\end\{[^}]*\}", "\n", text)
    for name in DROP_BARE:
        text = re.sub(r"\\%s\b\s?" % re.escape(name), "", text)
    # Any command still standing: keep its argument's text, drop the name.
    text = re.sub(r"\\[a-zA-Z]+\*?\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?\s*", "", text)

    # --- characters --------------------------------------------------------
    text = text.replace("~", " ")
    text = re.sub(r"\\([%&_#$])", r"\1", text)
    text = text.replace("``", '"').replace("''", '"')
    text = text.replace("\\\\", "\n").replace("&", " ")
    text = re.sub(r"[{}]", "", text)

    text = holder.restore(text)

    # --- whitespace --------------------------------------------------------
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Last, and after the blank lines have settled: a paragraph is one line,
    # and reflow needs the blank line that ends one to be a blank line.
    text = reflow(text)

    if chapter_anchor:
        text = anchor_tag(chapter_anchor).lstrip("\n") + "\n" + text.lstrip("\n")

    if figures is not None:
        figures.extend(found_figures)
    return text.strip() + "\n", found_figures


def replace_command_arg(text: str, name: str, build) -> str:
    """Replace every `\\name[opt]{arg}` using build(arg)."""
    pattern = re.compile(r"\\%s\*?\s*(?=[\[{])" % re.escape(name))
    out = []
    cursor = 0
    while True:
        match = pattern.search(text, cursor)
        if not match:
            out.append(text[cursor:])
            break
        index = read_optional(text, match.end())
        if index >= len(text) or text[index] != "{":
            out.append(text[cursor : match.end()])
            cursor = match.end()
            continue
        end = match_brace(text, index)
        argument = text[index + 1 : end - 1]
        out.append(text[cursor : match.start()])
        out.append(build(argument))
        cursor = end
    return "".join(out)


def extract_caption(body: str) -> str:
    match = re.search(r"\\caption\*?\s*(?=[\[{])", body)
    if not match:
        return ""
    index = read_optional(body, match.end())
    if index >= len(body) or body[index] != "{":
        return ""
    end = match_brace(body, index)
    return clean_inline(body[index + 1 : end - 1])


def parse_figure(body: str, chapter: str) -> list[dict]:
    """Pull one record per included graphic out of a figure environment."""
    records = []
    label = ""
    match = re.search(r"\\label\s*\{([^}]*)\}", body)
    if match:
        label = collapse_whitespace(match.group(1))
    caption = extract_caption(body)

    # Subfigures each carry their own graphic, label and caption.
    sub_bodies = []
    for name in ("subfigure", "subfloat", "minipage"):
        cursor = 0
        while True:
            found = find_environment(body, name, cursor)
            if not found:
                break
            sub_bodies.append(found[2])
            cursor = found[1]

    graphics = [
        collapse_whitespace(match.group(1))
        for match in re.finditer(GRAPHIC_COMMAND, body)
    ]
    # \psfig and \epsfig name the file in a key=value list instead.
    graphics.extend(
        collapse_whitespace(match.group(1))
        for match in re.finditer(GRAPHIC_KEYVALUE, body)
    )
    if not graphics:
        return []

    letters = "abcdefghijklmnopqrstuvwxyz"
    for index, graphic in enumerate(graphics):
        sub_caption = ""
        sub_label = ""
        if len(graphics) > 1 and index < len(sub_bodies):
            sub_caption = extract_caption(sub_bodies[index])
            sub_match = re.search(r"\\label\s*\{([^}]*)\}", sub_bodies[index])
            if sub_match:
                sub_label = collapse_whitespace(sub_match.group(1))
        records.append(
            {
                "source": graphic,
                "file_hint": Path(graphic).name,
                "label": sub_label or (
                    label + letters[index] if label and len(graphics) > 1 else label
                ),
                "caption": " ".join(part for part in (caption, sub_caption) if part),
                "chapter": chapter,
            }
        )
    return records


# ==========================================================================
# writing the paper directory
# ==========================================================================


def split_long_chapter(text: str, limit: int) -> list[tuple[str, str]]:
    """Cut a chapter at its '## ' headings when it is too long to read at once."""
    if len(text.encode("utf-8")) <= limit:
        return []
    parts = re.split(r"\n(?=## )", text)
    if len(parts) < 2:
        return []
    # A heading may be preceded by the anchor its own label owns. The cut falls
    # between the two, so the anchor moves to the piece it names.
    trailing_anchor = re.compile(r'\n\s*(<a id="[^"]*"></a>)\s*\Z')
    for index in range(len(parts) - 1):
        moved = trailing_anchor.search(parts[index])
        if moved:
            parts[index] = parts[index][: moved.start()]
            parts[index + 1] = moved.group(1) + "\n" + parts[index + 1]

    pieces = []
    for part in parts:
        part = part.strip()
        anchor = ""
        anchor_match = re.match(r'<a id="[^"]*"></a>\s*\n', part)
        if anchor_match:
            anchor = anchor_match.group(0).strip()
            part = part[anchor_match.end() :].lstrip("\n")
        heading = part.split("\n", 1)[0]
        if heading.startswith("## "):
            # The heading number belongs to the chapter it came from; the piece
            # is named after the words alone.
            title = re.sub(r"\A\d+(?:\.\d+)*\s+", "", heading[3:].strip())
            part = part[len(heading) :].lstrip("\n")
            if anchor:
                part = anchor + "\n\n" + part
        else:
            title = "opening"
            # Drop the chapter heading; the caller writes its own.
            part = re.sub(r"\A# [^\n]*\n*", "", part)
        part = part.strip()
        if not part:
            continue  # a heading with nothing under it
        pieces.append((title, part + "\n"))
    return pieces


def copy_figures(
    records: list[dict], source_dir: Path, figures_dir: Path, warnings: list[str]
) -> tuple[list[dict], dict[str, str]]:
    """Stage the originals, then convert each one to a cropped PNG.

    The paper's own files land in `figures_raw/` and the PNGs in `figures/`.
    Returns the records with their final file names, and the map from original
    name to PNG name so the chapter text can be pointed at the right file.
    """
    raw_dir = figures_dir.parent / convert_figures.RAW_DIR_NAME
    staged = []
    for record in records:
        path = resolve_figure(record["source"], source_dir)
        if path is None:
            warnings.append("figure source not found: %s" % record["source"])
            record = dict(record)
            record["file"] = ""
            staged.append(record)
            continue
        raw_dir.mkdir(parents=True, exist_ok=True)
        target = raw_dir / path.name
        if not target.exists():
            shutil.copyfile(path, target)
        record = dict(record)
        record["file"] = target.name
        staged.append(record)

    figures_dir.mkdir(parents=True, exist_ok=True)
    renames = convert_figures.convert_directory(figures_dir, warnings)

    resolved = []
    for record in staged:
        record = dict(record)
        if record["file"]:
            record["file"] = renames.get(record["file"], record["file"])
        resolved.append(record)
    return resolved, renames


def resolve_figure(reference: str, source_dir: Path) -> Path | None:
    reference = reference.strip().strip('"')
    direct = source_dir / reference
    if direct.is_file():
        return direct
    for extension in FIGURE_EXTENSIONS:
        candidate = source_dir / (reference + extension)
        if candidate.is_file():
            return candidate
    stem = Path(reference).name
    for candidate in source_dir.rglob("*"):
        if not candidate.is_file():
            continue
        if candidate.name == stem or candidate.stem == stem:
            if candidate.suffix.lower() in FIGURE_EXTENSIONS:
                return candidate
    return None


def write_figures_index(records: list[dict], figures_dir: Path) -> None:
    lines = [
        "# Figures",
        "",
        "One row per figure, with the caption as the paper gives it. Search this",
        "file to find the figure that shows a given thing, then read the image.",
        "",
        "| # | File | Label | Chapter | Caption |",
        "|---|---|---|---|---|",
    ]
    for record in records:
        caption = record["caption"].replace("|", "\\|").replace("\n", " ")
        chapter = record.get("chapter") or ""
        chapter_file = record.get("chapter_file") or ""
        if chapter_file:
            anchor = record.get("anchor") or ""
            chapter = "[%s](../chapters/%s%s)" % (
                chapter, chapter_file, "#" + anchor if anchor else ""
            )
        lines.append(
            "| %s | %s | %s | %s | %s |"
            % (
                record.get("number") or "",
                record.get("file") or "(missing: %s)" % record["source"],
                record.get("label") or "",
                chapter,
                caption,
            )
        )
    figures_dir.mkdir(parents=True, exist_ok=True)
    (figures_dir / "FIGURES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def arxiv_only_publication(metadata: dict) -> dict:
    """What arXiv alone knows about the publication, which is usually nothing."""
    journal_ref = collapse_whitespace(metadata.get("journal_ref", ""))
    return {
        "source": "arxiv" if journal_ref else "none",
        "journal": journal_ref,
        "published_year": None,
        "doi": collapse_whitespace(metadata.get("doi", "")),
        "errata": [],
        "inspire_url": "",
    }


def resolve_publication(arxiv_id: str, metadata: dict, warnings: list[str]) -> dict:
    """Ask INSPIRE where the paper was published, and fall back to arXiv.

    arXiv's own `journal_ref` is written by the authors and is usually empty,
    so INSPIRE decides when it holds the paper. A lookup that fails is a
    warning, never an error: the TeX source is what the ingest is for.
    """
    record = inspire_lookup.lookup_by_arxiv(arxiv_id)
    if not record["found"] and metadata.get("doi"):
        record = inspire_lookup.lookup_by_doi(metadata["doi"])

    if record["found"] and record["journal"]:
        source, journal = "inspire", record["journal"]
    else:
        fallback = arxiv_only_publication(metadata)
        source, journal = fallback["source"], fallback["journal"]

    if not record["found"]:
        warnings.append(
            "INSPIRE-HEP gave no record for this paper (%s), so the journal and "
            "the year of publication come from arXiv alone" % record.get("reason", "")
        )
    elif not record["journal"]:
        warnings.append(
            "INSPIRE-HEP holds this paper but reports no journal publication; "
            "treat it as a preprint unless you find otherwise"
        )

    return {
        "source": source,
        "journal": journal,
        "published_year": record["published_year"],
        "doi": record["doi"] or collapse_whitespace(metadata.get("doi", "")),
        "errata": record["errata"],
        "inspire_url": record.get("inspire_url", ""),
    }


def fetch_metadata_by_id(arxiv_id: str) -> dict:
    """The arXiv record of one paper: its title, its authors and its date.

    It raises rather than answering with an empty record. The title, the authors
    and the submission year are what the slug, the index and the collection row
    are built from. A lookup that failed and answered `{}` used to put a paper
    on disk under `anon_nd`, with no title and no author, and the ingest still
    reported success. A paper whose identity nothing established must not enter
    the collection quietly.

    `read_feed` sends the request, so it retries and it waits at the gate.
    """
    try:
        feed = read_feed({"id_list": arxiv_id, "max_results": 1})
    except (RuntimeError, urllib.error.URLError, TimeoutError) as error:
        raise MetadataUnavailable(
            "arXiv did not answer for %s (%s), so the title, the authors and "
            "the year of the paper are unknown" % (arxiv_id, error)
        )

    try:
        entries = parse_entries(feed)
    except ET.ParseError as error:
        raise MetadataUnavailable("arXiv sent no readable record for %s (%s)"
                                  % (arxiv_id, error))
    if not entries:
        raise NoSource("arXiv holds no record for %s; check the identifier"
                       % arxiv_id)
    return entries[0]


# ==========================================================================
# main
# ==========================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = cli.parser(__doc__)
    parser.add_argument("arxiv_id", help="arXiv identifier, for example 1706.03621")
    parser.add_argument("--slug", required=True, help="directory name under the literature root")
    cli.add_root_argument(parser)
    parser.add_argument("--max-chapter-bytes", type=int, default=DEFAULT_MAX_CHAPTER_BYTES)
    parser.add_argument("--force", action="store_true", help="overwrite an existing paper directory")
    parser.add_argument(
        "--no-inspire",
        action="store_true",
        help="skip the INSPIRE-HEP lookup; take the journal from arXiv alone",
    )
    parser.add_argument(
        "--no-references",
        action="store_true",
        help="skip the bibliography; citations keep the paper's own LaTeX keys",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the manifest, write nothing")
    parser.add_argument("--keep-source", type=Path, help="keep the extracted TeX source here")
    return parser


ANCHOR_TAG = re.compile(r'<a id="[^"]*"></a>')
HEADING_LINE = re.compile(r"^#+ .*$", re.MULTILINE)


def chapter_has_text(chapter: dict) -> bool:
    """Whether a chapter holds any of the paper under its headings.

    Headings and anchors do not count. A conversion that found the structure of
    a document and none of its words produces exactly those, and reporting that
    as a chapter would put an empty file into the collection.
    """
    body = HEADING_LINE.sub("", chapter.get("text", ""))
    return bool(ANCHOR_TAG.sub("", body).strip())


def convert(args) -> dict:
    """Fetch one paper and write its chapters. Returns the manifest.

    `args` is what `build_parser()` produces, or anything carrying the same
    attributes: `add_paper.py` calls this rather than the command line, so the
    manifest comes back as an object instead of as text on stdout.

    It raises `NoSource` when arXiv has no TeX for the paper, and
    `ParserFailure` when the source yields no chapter. Both are facts about the
    paper, and the driver reports each as its own exception code.
    """
    warnings: list[str] = []

    work_dir = Path(tempfile.mkdtemp(prefix="arxiv_fetch_"))
    try:
        metadata = fetch_metadata_by_id(args.arxiv_id)
        if args.no_inspire:
            publication = arxiv_only_publication(metadata)
        else:
            try:
                publication = resolve_publication(args.arxiv_id, metadata, warnings)
            except Exception as error:  # the TeX matters more than the journal
                publication = arxiv_only_publication(metadata)
                warnings.append("the INSPIRE-HEP lookup failed (%s)" % error)
        # No courtesy delay here: the gate paces every arXiv request, and this
        # one waits behind the metadata request above by itself.
        source_dir = download_source(args.arxiv_id, work_dir)

        main_tex = find_main_tex(source_dir)
        raw = inline_inputs(strip_comments(read_text(main_tex)), main_tex.parent, source_dir)
        begin_document = raw.find("\\begin{document}")
        macros = collect_macros(raw[: begin_document if begin_document > 0 else 0])
        body = expand_macros(extract_body(raw), macros)

        # The bibliography is read before the body is cut down to its sections,
        # since a paper that types its references out sits them after the last
        # \section and they would otherwise be split into that chapter.
        cited: list[dict] = []
        key_tags: dict[str, list[str]] = {}
        if not args.no_references:
            try:
                cited, key_tags = references.collect(
                    source_dir, body, args.arxiv_id, args.literature_root, warnings
                )
            except Exception as error:  # the paper matters more than its bibliography
                warnings.append(
                    "the bibliography could not be resolved (%s); citations keep "
                    "their original keys" % error
                )
        body = drop_bibliography(body)

        positions = section_positions_texsoup(body)
        parser_used = "texsoup"
        if positions is None:
            positions = section_positions_regex(body)
            parser_used = "fallback"
            warnings.append(
                "TexSoup could not parse this source; sections were found by regex, "
                "so the chapter split may be less exact"
            )
        elif not positions:
            positions = section_positions_regex(body)
            if positions:
                parser_used = "fallback"

        abstract = extract_abstract(expand_macros(raw, macros))
        sections = split_sections(body, positions)

        chapters = []
        figure_records: list[dict] = []
        numbering = Numbering()
        for index, (title, section_body) in enumerate(sections, start=1):
            numbering.start_chapter(index, title)
            text, section_figures = clean_text(
                section_body, figure_records, title, numbering
            )
            if not text.strip():
                continue
            heading = "# %d. %s\n\n" % (index, title)
            content = heading + text
            subsections = [
                re.sub(r"\A\d+(?:\.\d+)*\s+", "", found)
                for found in re.findall(r"^## (.+)$", content, flags=re.MULTILINE)
            ]
            pieces = split_long_chapter(content, args.max_chapter_bytes)
            if pieces:
                for piece_index, (piece_title, piece_text) in enumerate(pieces, start=1):
                    chapters.append(
                        {
                            "file": "%02d-%02d_%s.md"
                            % (index, piece_index,
                               slugify(piece_title, whole_words=True)),
                            "number": "%d.%d" % (index, piece_index),
                            "title": "%s — %s" % (title, piece_title),
                            "subsections": re.findall(
                                r"^### (.+)$", piece_text, flags=re.MULTILINE
                            ),
                            "text": "# %d.%d %s — %s\n\n%s"
                            % (index, piece_index, title, piece_title, piece_text),
                        }
                    )
            else:
                chapters.append(
                    {
                        "file": "%02d_%s.md" % (index, slugify(title, whole_words=True)),
                        "number": str(index),
                        "title": title,
                        "subsections": subsections,
                        "text": content,
                    }
                )
            for record in section_figures:
                record["chapter"] = title

        # A chapter that is only its own heading holds none of the paper. A
        # source that yields nothing else converted to nothing, whatever the
        # section split found.
        if not any(chapter_has_text(chapter) for chapter in chapters):
            raise ParserFailure(
                "the source of %s produced no chapter holding text; it needs a "
                "conversion by hand, or none" % args.arxiv_id,
                main_tex=str(main_tex.relative_to(source_dir)),
                sections_found=len(sections),
            )

        if key_tags:
            for chapter in chapters:
                chapter["text"] = apply_cite_tags(chapter["text"], key_tags)
            for record in figure_records:
                record["caption"] = apply_cite_tags(record.get("caption", ""), key_tags)

        # The chapters are settled, so a cross-reference now knows which file
        # its target ended up in.
        unresolved_refs = apply_ref_links(chapters, numbering)
        if unresolved_refs:
            warnings.append(
                "%d cross-reference label(s) had no target in the source and keep "
                "their [ref: ...] marker: %s"
                % (len(unresolved_refs), ", ".join(unresolved_refs[:10]))
            )
        residue = {
            chapter["file"]: len(RESIDUE.findall(chapter["text"]))
            for chapter in chapters
            if RESIDUE.search(chapter["text"])
        }
        if residue:
            warnings.append(
                "%d placeholder residue match(es) in %d chapter(s), where the "
                "text now reads PH<number> instead of what the paper wrote: %s"
                % (sum(residue.values()), len(residue),
                   ", ".join(sorted(residue)[:10]))
            )
        apply_figure_targets(figure_records, chapters, numbering)

        if args.dry_run:
            return build_manifest(
                args, metadata, publication, cited, abstract, parser_used, chapters,
                [dict(record, file=record["file_hint"]) for record in figure_records],
                warnings, main_tex, source_dir, numbering, unresolved_refs)

        paper_dir = args.literature_root / args.slug
        if paper_dir.exists():
            shutil.rmtree(paper_dir)
        chapters_dir = paper_dir / "chapters"
        chapters_dir.mkdir(parents=True)

        # Before the chapters are written: their [FIGURE: ...] markers name the
        # file as the TeX source did, and conversion renames it to .png.
        resolved, renames = copy_figures(
            figure_records, source_dir, paper_dir / "figures", warnings
        )
        changed = {old: new for old, new in renames.items() if old != new}
        # The marker names the figure as the TeX did, which may carry no
        # extension at all (\includegraphics{fig1} against fig1.eps on disk).
        for record in resolved:
            hint, final = record.get("file_hint"), record.get("file")
            if hint and final and hint != final:
                changed[hint] = final
        if changed:
            # The name reaches the chapter text in one place: the `src` of the
            # image tag. It also reads as a run of characters inside the anchor
            # id above that tag, and inside the link that points at the anchor.
            # A substitution that is not tied to the `src` rewrites those too,
            # and `FIGURES.md` carries the anchor as the numbering wrote it, so
            # its link then names an id the chapter does not hold.
            pattern = re.compile(
                r'(?<=src="\.\./figures/)(?:%s)(?=")'
                % "|".join(
                    re.escape(old) for old in sorted(changed, key=len, reverse=True)
                )
            )
            for chapter in chapters:
                chapter["text"] = pattern.sub(
                    lambda match: changed[match.group(0)], chapter["text"]
                )

        for chapter in chapters:
            # Last of all: the paragraph numbers count the paragraphs of the
            # file that holds them, and sanitise answers for what reaches disk.
            text = sanitise(paragraph_anchors(chapter["text"]))
            (chapters_dir / chapter["file"]).write_text(text, encoding="utf-8")
            chapter["bytes"] = len(text.encode("utf-8"))

        write_figures_index(resolved, paper_dir / "figures")

        if args.keep_source:
            shutil.copytree(source_dir, args.keep_source, dirs_exist_ok=True)

        for chapter in chapters:
            chapter.pop("text", None)

        return build_manifest(
            args, metadata, publication, cited, abstract, parser_used, chapters, resolved,
            warnings, main_tex, source_dir, numbering, unresolved_refs)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def main() -> int:
    args = cli.parse(build_parser())
    rate_gate.use_root(args.literature_root)

    paper_dir = args.literature_root / args.slug
    if paper_dir.exists() and not args.force and not args.dry_run:
        fail("%s already exists; pass --force to replace it" % paper_dir)
        return 1

    try:
        manifest = convert(args)
    except (NoSource, ParserFailure, MetadataUnavailable) as error:
        fail(str(error))
        return 1

    cli.emit(manifest)
    return 0


def build_manifest(
    args, metadata, publication, cited, abstract, parser_used, chapters, figures, warnings,
    main_tex, source_dir, numbering=None, unresolved_refs=None
) -> dict:
    for chapter in chapters:
        chapter.pop("text", None)
    return {
        "arxiv_id": args.arxiv_id,
        "slug": args.slug,
        "paper_dir": str(args.literature_root / args.slug),
        "title": metadata.get("title", ""),
        "authors": metadata.get("authors", []),
        "year": metadata.get("year"),
        # The arXiv submission year, which the slug and the index order use.
        # `publication.published_year` is the year the journal carried it.
        "submitted_year": metadata.get("year"),
        "abs_url": metadata.get("abs_url", "https://arxiv.org/abs/%s" % args.arxiv_id),
        "journal_ref": metadata.get("journal_ref", ""),
        "doi": metadata.get("doi", ""),
        "publication": publication,
        "abstract": abstract or metadata.get("summary", ""),
        "ingested": date.today().isoformat(),
        "parser": parser_used,
        "main_tex": str(main_tex.relative_to(source_dir)),
        "chapters": [
            {
                "file": chapter["file"],
                "number": chapter["number"],
                "title": chapter["title"],
                "bytes": chapter.get("bytes", 0),
                "subsections": chapter.get("subsections", []),
            }
            for chapter in chapters
        ],
        "figures": [
            {
                "file": record.get("file", ""),
                "label": record.get("label", ""),
                "number": record.get("number", ""),
                "chapter": record.get("chapter", ""),
            }
            for record in figures
        ],
        # What the paper's own \ref commands now point at: one entry per label,
        # naming the file and anchor a reader lands on.
        "labels": numbering.labels if numbering else {},
        # Labels the source never defined; their [ref: ...] markers stayed put.
        "unresolved_refs": unresolved_refs or [],
        # Every work this paper cites, tagged. update_references.py folds these
        # into the store; until it runs, the tags in the chapters name rows
        # that REFERENCES.md does not have yet.
        "references": cited,
        "warnings": warnings,
    }


def fail(message: str) -> None:
    cli.emit({"error": message})


if __name__ == "__main__":
    sys.exit(main())
