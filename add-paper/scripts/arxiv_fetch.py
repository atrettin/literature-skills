#!/usr/bin/env python3
"""Download an arXiv paper's TeX source and write it into the literature database.

Writes, under `<literature-root>/<slug>/`:

    chapters/NN_<title>.md        one file per \\section, long ones split further
    figures/<figure files>        every figure the paper includes
    figures/FIGURES.md            file name, label, chapter and caption per figure

It does **not** write INDEX.md. The calling agent writes that, from the JSON
manifest this script prints on stdout plus its own reading of the chapters.

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
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import convert_figures  # noqa: E402
from arxiv_search import (  # noqa: E402
    COURTESY_DELAY_S,
    USER_AGENT,
    collapse_whitespace,
    fetch_feed,
    parse_entries,
)

EPRINT_URL = "https://arxiv.org/e-print/%s"
REQUEST_TIMEOUT_S = 120.0
DEFAULT_MAX_CHAPTER_BYTES = 40000

FIGURE_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps", ".gif", ".svg")

# How a figure names its file. \includegraphics carries a star form, and older
# papers reach for the epsf and psfig interfaces instead — a paper using any of
# these would otherwise arrive with no figures at all.
GRAPHIC_COMMAND = re.compile(
    r"\\(?:includegraphics|epsfbox|epsffile|plotone|plottwo)\*?\s*"
    r"(?:\[[^\]]*\])?\s*\{([^}]*)\}"
)
GRAPHIC_KEYVALUE = re.compile(
    r"\\(?:psfig|epsfig)\s*\{[^}]*?\bfile\s*=\s*([^,}]+)[^}]*\}"
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


def slugify(text: str, limit: int = 48) -> str:
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    return (text[:limit].rstrip("_")) or "section"


# ==========================================================================
# download and extract
# ==========================================================================


def download_source(arxiv_id: str, work_dir: Path) -> Path:
    url = EPRINT_URL % arxiv_id
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            "arXiv returned HTTP %s for %s. The submission may be PDF-only, "
            "which carries no TeX source." % (error.code, url)
        )
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("download of %s failed: %s" % (url, error))

    if not payload:
        raise RuntimeError("arXiv served an empty source archive for %s" % arxiv_id)

    source_dir = work_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    if payload[:2] == b"\x1f\x8b":
        payload_plain = gzip.decompress(payload)
    else:
        payload_plain = payload

    if payload_plain[:5] == b"%PDF-":
        raise RuntimeError(
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
        raise RuntimeError("no .tex file in the downloaded source")

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
    """Holds verbatim chunks (math, tables) out of harm's way while cleaning."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}
        self.counter = 0

    def stash(self, payload: str) -> str:
        self.counter += 1
        key = "\x00PH%d\x00" % self.counter
        self.items[key] = payload
        return key

    def restore(self, text: str) -> str:
        for key, payload in self.items.items():
            text = text.replace(key, payload)
        return text


def clean_inline(text: str) -> str:
    """Clean a short fragment such as a section title or a caption."""
    return collapse_whitespace(clean_text(text, figures=None, chapter="")[0])


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
    return "\n\n$$\n%s\n$$\n\n" % sanitize_math(body).strip("\n").strip()


def figure_block(file_name: str, caption: str) -> str:
    """Embed a figure so it shows in the preview, with its caption beneath.

    The chapters sit in `chapters/`, so the image is one level up in
    `figures/`. HTML rather than Markdown image syntax, because Markdown has
    no way to set a width and the figures are far too large at full size.
    """
    # Maths reads as noise in an alt attribute, and its backslashes and quotes
    # would have to be escaped anyway. The caption below the image keeps it.
    alt = re.sub(r"\$[^$]*\$", "", caption)
    alt = collapse_whitespace(re.sub(r'["\\<>]', " ", alt))
    alt = re.sub(r"\s+([,.;:])", r"\1", alt).strip(" ,;:") or "figure"
    if len(alt) > 120:
        alt = alt[:117].rstrip() + "..."
    block = (
        '\n\n<p align="center">\n'
        '<img src="../figures/%s" alt="%s" width="%d"/>\n'
        "</p>\n" % (file_name, alt, FIGURE_WIDTH_PX)
    )
    if caption:
        block += "\n**Figure.** %s\n" % collapse_whitespace(caption)
    return block + "\n"


def clean_text(
    raw: str, figures: list | None, chapter: str
) -> tuple[str, list[dict]]:
    """Convert a raw TeX fragment to readable text.

    Math is kept as TeX. Figures become a one-line marker and, when `figures`
    is a list, are appended to it as records.
    """
    found_figures: list[dict] = []
    text = strip_comments(raw)
    holder = Placeholder()

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
    for name in FIGURE_ENVIRONMENTS:
        while True:
            found = find_environment(text, name)
            if not found:
                break
            start, end, body = found
            records = parse_figure(body, chapter)
            found_figures.extend(records)
            if records:
                marker = "".join(
                    figure_block(record["file_hint"], record["caption"])
                    for record in records
                )
            else:
                marker = "\n\n[FIGURE: unresolved]\n\n"
            text = text[:start] + holder.stash(marker) + text[end:]

    # --- tables, kept verbatim -------------------------------------------
    for name in TABLE_ENVIRONMENTS:
        while True:
            found = find_environment(text, name)
            if not found:
                break
            start, end, body = found
            caption = extract_caption(body)
            block = "\n\n```tex\n%s\n```\n" % body.strip("\n")
            if caption:
                block += "\n[TABLE: %s]\n\n" % caption
            text = text[:start] + holder.stash(block) + text[end:]

    # --- display math -----------------------------------------------------
    for name in MATH_ENVIRONMENTS:
        while True:
            found = find_environment(text, name)
            if not found:
                break
            start, end, body = found
            if name in BARE_MATH_ENVIRONMENTS:
                inner = body
            elif name in ALIGNED_MATH_ENVIRONMENTS:
                # KaTeX has no eqnarray, flalign or multline. aligned takes the
                # same '&'-separated rows and renders them acceptably.
                inner = "\\begin{aligned}%s\\end{aligned}" % body
            else:
                inner = "\\begin{%s}%s\\end{%s}" % (name, body, name)
            text = text[:start] + holder.stash(display_math(inner)) + text[end:]

    text = re.sub(
        r"\\\[(.+?)\\\]",
        lambda m: holder.stash(display_math(m.group(1))),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\$\$(.+?)\$\$",
        lambda m: holder.stash(display_math(m.group(1))),
        text,
        flags=re.DOTALL,
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
    pieces = []
    for part in parts:
        part = part.strip()
        heading = part.split("\n", 1)[0]
        if heading.startswith("## "):
            title = heading[3:].strip()
            part = part[len(heading) :].lstrip("\n")
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
        "| File | Label | Chapter | Caption |",
        "|---|---|---|---|",
    ]
    for record in records:
        caption = record["caption"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            "| %s | %s | %s | %s |"
            % (
                record.get("file") or "(missing: %s)" % record["source"],
                record.get("label") or "",
                record.get("chapter") or "",
                caption,
            )
        )
    figures_dir.mkdir(parents=True, exist_ok=True)
    (figures_dir / "FIGURES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fetch_metadata_by_id(arxiv_id: str) -> dict:
    """Query the arXiv API for a single paper's metadata."""
    import urllib.parse

    params = urllib.parse.urlencode({"id_list": arxiv_id, "max_results": 1})
    url = "http://export.arxiv.org/api/query?%s" % params
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            feed = response.read().decode("utf-8", errors="replace")
        entries = parse_entries(feed)
        return entries[0] if entries else {}
    except Exception:
        return {}


# ==========================================================================
# main
# ==========================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("arxiv_id", help="arXiv identifier, for example 1706.03621")
    parser.add_argument("--slug", required=True, help="directory name under the literature root")
    parser.add_argument("--literature-root", type=Path, default=Path("literature"))
    parser.add_argument("--max-chapter-bytes", type=int, default=DEFAULT_MAX_CHAPTER_BYTES)
    parser.add_argument("--force", action="store_true", help="overwrite an existing paper directory")
    parser.add_argument("--dry-run", action="store_true", help="print the manifest, write nothing")
    parser.add_argument("--keep-source", type=Path, help="keep the extracted TeX source here")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    warnings: list[str] = []

    paper_dir = args.literature_root / args.slug
    if paper_dir.exists() and not args.force and not args.dry_run:
        fail("%s already exists; pass --force to replace it" % paper_dir)
        return 1

    work_dir = Path(tempfile.mkdtemp(prefix="arxiv_fetch_"))
    try:
        metadata = fetch_metadata_by_id(args.arxiv_id)
        time.sleep(COURTESY_DELAY_S)
        try:
            source_dir = download_source(args.arxiv_id, work_dir)
        except RuntimeError as error:
            fail(str(error))
            return 1

        main_tex = find_main_tex(source_dir)
        raw = inline_inputs(strip_comments(read_text(main_tex)), main_tex.parent, source_dir)
        begin_document = raw.find("\\begin{document}")
        macros = collect_macros(raw[: begin_document if begin_document > 0 else 0])
        body = expand_macros(extract_body(raw), macros)

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
        for index, (title, section_body) in enumerate(sections, start=1):
            text, section_figures = clean_text(section_body, figure_records, title)
            if not text.strip():
                continue
            heading = "# %d. %s\n\n" % (index, title)
            content = heading + text
            subsections = re.findall(r"^## (.+)$", content, flags=re.MULTILINE)
            pieces = split_long_chapter(content, args.max_chapter_bytes)
            if pieces:
                for piece_index, (piece_title, piece_text) in enumerate(pieces, start=1):
                    chapters.append(
                        {
                            "file": "%02d-%02d_%s.md" % (index, piece_index, slugify(piece_title)),
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
                        "file": "%02d_%s.md" % (index, slugify(title)),
                        "number": str(index),
                        "title": title,
                        "subsections": subsections,
                        "text": content,
                    }
                )
            for record in section_figures:
                record["chapter"] = title

        if args.dry_run:
            print(json.dumps(build_manifest(
                args, metadata, abstract, parser_used, chapters,
                [dict(record, file=record["file_hint"]) for record in figure_records],
                warnings, main_tex, source_dir), indent=2))
            return 0

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
            pattern = re.compile(
                "|".join(re.escape(old) for old in sorted(changed, key=len, reverse=True))
            )
            for chapter in chapters:
                chapter["text"] = pattern.sub(
                    lambda match: changed[match.group(0)], chapter["text"]
                )

        for chapter in chapters:
            (chapters_dir / chapter["file"]).write_text(chapter["text"], encoding="utf-8")
            chapter["bytes"] = len(chapter["text"].encode("utf-8"))

        write_figures_index(resolved, paper_dir / "figures")

        if args.keep_source:
            shutil.copytree(source_dir, args.keep_source, dirs_exist_ok=True)

        for chapter in chapters:
            chapter.pop("text", None)

        print(json.dumps(build_manifest(
            args, metadata, abstract, parser_used, chapters, resolved,
            warnings, main_tex, source_dir), indent=2))
        return 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def build_manifest(
    args, metadata, abstract, parser_used, chapters, figures, warnings, main_tex, source_dir
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
        "abs_url": metadata.get("abs_url", "https://arxiv.org/abs/%s" % args.arxiv_id),
        "journal_ref": metadata.get("journal_ref", ""),
        "doi": metadata.get("doi", ""),
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
                "chapter": record.get("chapter", ""),
            }
            for record in figures
        ],
        "warnings": warnings,
    }


def fail(message: str) -> None:
    print(json.dumps({"error": message}, indent=2), file=sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
