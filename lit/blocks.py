#!/usr/bin/env python3
"""The stored form of a paper's text: one JSON object per line, one per block.

A paper is stored, not presented. `<slug>/text/NN_title.jsonl` holds the words,
and `litdb render` writes the Markdown a person reads. The store carries markers
rather than links — `[cite: tag]` for a citation and `[ref: label]` for the
paper's reference to itself — because what a link looks like depends on the
flavor being rendered, and the words do not.

One line is one block, which is what makes the file readable as it stands: a
`Read` gives an agent a line number per block, and a `Grep` matches a block the
way it matched a paragraph when this was Markdown. A block never spans two
lines, since JSON escapes the newlines inside it.

    {"kind":"heading","level":1,"number":"6.5","title":"…","anchor":"sec-coherent-pi"}
    {"kind":"paragraph","anchor":"p2","text":"… Figure [ref: fig:coh] … [cite: vilain_1993]."}
    {"kind":"math","env":"eqnarray","tex":"…","numbers":["78","79"],"anchor":""}
    {"kind":"figure","file":"coherent_pi.png","number":"22","caption":"…","anchor":"fig-coh"}
    {"kind":"table","number":"13","tex":"\\begin{tabular}…","caption":"…","anchor":"tab-new"}
    {"kind":"code","text":"…","anchor":""}

`kind` and `anchor` are on every block; an empty `anchor` means the block has no
address of its own. Everything else belongs to the kind.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TEXT_DIR = "text"
SUFFIX = ".jsonl"

# What brackets a structured block inside the intermediate text the conversion
# builds. Private-use characters, for the same reason the placeholder sentinels
# are: one that escapes into a rendered file stays readable text rather than
# turning the file into something `grep` treats as binary. The payload is JSON
# on one line, so a block sentinel never spans two lines and every pass that
# splits the intermediate on blank lines leaves it whole.
BLOCK_OPEN = "\ue002"
BLOCK_CLOSE = "\ue003"

# Every C0 control character other than the tab. None of them belongs inside a
# stored string, and a NUL byte stops the line being JSON at all.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0a-\x1f]")

ANCHOR_LINE = re.compile(r'^<a id="([^"]*)"></a>$')
HEADING_LINE = re.compile(r"^(#{1,6})\s+(?:(\d+(?:\.\d+)*)\.?\s+)?(.*)$")

# A block that carries no address of its own and is not prose either. `[FIGURE:`
# names a figure the conversion could not resolve, which is a marker rather
# than a sentence.
MARKER_PREFIXES = ("[FIGURE:",)


def sentinel(payload: dict) -> str:
    """A structured block, as it travels through the text passes."""
    return "\n\n%s%s%s\n\n" % (
        BLOCK_OPEN,
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        BLOCK_CLOSE,
    )


# --------------------------------------------------------------------------
# the intermediate text, to blocks
# --------------------------------------------------------------------------


def parse(text: str) -> list[dict]:
    """Read the intermediate text of one chapter as a list of blocks.

    The intermediate is machine-written and regular: blocks separated by a blank
    line, an `<a id="…"></a>` on a line of its own above the block it names, and
    a sentinel for anything the conversion already knew the structure of. So
    this recognises four things and calls the rest prose.
    """
    blocks: list[dict] = []
    pending_anchor = ""

    for part in re.split(r"\n\s*\n", text):
        part = part.strip()
        if not part:
            continue

        anchor_match = ANCHOR_LINE.match(part)
        if anchor_match:
            anchor = anchor_match.group(1)
            # A chapter's own anchor is written under its heading, because the
            # heading names the chapter and the anchor names the section the
            # conversion cut at. Every other anchor is written above the thing
            # it names. So an anchor that lands directly under a heading with
            # none of its own belongs to that heading, and nothing else can
            # reach this branch: a subsection's anchor precedes its heading.
            if blocks and blocks[-1].get("kind") == "heading" and not blocks[-1]["anchor"]:
                blocks[-1]["anchor"] = anchor
            else:
                pending_anchor = anchor
            continue

        block = read_one(part)
        if block is None:
            continue
        if pending_anchor and not block.get("anchor"):
            block["anchor"] = pending_anchor
        pending_anchor = ""
        blocks.append(block)

    return blocks


def read_one(part: str) -> dict | None:
    """One block from one piece of the intermediate, or None for nothing."""
    if part.startswith(BLOCK_OPEN) and part.endswith(BLOCK_CLOSE):
        payload = json.loads(part[len(BLOCK_OPEN) : -len(BLOCK_CLOSE)])
        payload.setdefault("anchor", "")
        return payload

    if part.startswith("```"):
        lines = part.split("\n")
        language = lines[0][3:].strip()
        body = "\n".join(lines[1:])
        if body.endswith("```"):
            body = body[: -len("```")]
        return {
            "kind": "code",
            "language": language,
            "text": body.strip("\n"),
            "anchor": "",
        }

    heading = HEADING_LINE.match(part)
    if heading and "\n" not in part:
        return {
            "kind": "heading",
            "level": len(heading.group(1)),
            "number": heading.group(2) or "",
            "title": heading.group(3).strip(),
            "anchor": "",
        }

    if part.startswith(MARKER_PREFIXES):
        return {"kind": "marker", "text": part, "anchor": ""}

    return {"kind": "paragraph", "text": part, "anchor": ""}


# --------------------------------------------------------------------------
# reading and writing the file
# --------------------------------------------------------------------------


def dump(blocks: list[dict]) -> str:
    """The text of one `.jsonl`: one block per line, in order."""
    return "".join(
        json.dumps(block, ensure_ascii=False, sort_keys=True) + "\n" for block in blocks
    )


def write(path: Path, blocks: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(blocks), encoding="utf-8")
    return path


def read(path: Path) -> list[dict]:
    """The blocks of one file.

    A line that does not parse raises, naming its number. The store is the
    paper, and a paper that reads as one block short is worse than one that
    refuses to be read.

    The control characters go before the parse. A NUL byte inside a stored
    string is not JSON, so a chapter carrying one would refuse to be read at
    all — and a paper that cannot be read is a paper whose text silently looks
    absent, which is the failure the search exists to prevent, arriving by
    another route. The byte is a defect of the conversion and it stays visible:
    a caller that reports on the collection reads the file itself and says so.
    Nothing is written back, so the store keeps whatever it holds.
    """
    blocks = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            blocks.append(json.loads(CONTROL_CHARACTERS.sub("", line)))
        except json.JSONDecodeError as error:
            raise ValueError("%s line %d is not JSON: %s" % (path, number, error))
    return blocks


# --------------------------------------------------------------------------
# what a block says
# --------------------------------------------------------------------------


def words(block: dict) -> str:
    """The readable words of a block: what a search matches against.

    Maths and the raw TeX of a table are not words. A caption is.
    """
    kind = block.get("kind")
    if kind == "paragraph":
        return block.get("text", "")
    if kind == "heading":
        return block.get("title", "")
    if kind in ("figure", "table"):
        return block.get("caption", "")
    return ""


def display(block: dict) -> str:
    """Everything a block says, for a caller that is reading rather than matching.

    `words` answers what a search matches, and deliberately calls mathematics
    nothing. This answers what a reader has to see, so an equation is its TeX
    and a table is its caption above its TeX. The two must stay separate: an
    equation that entered `words` would put backslashes and braces into a
    ranking, and a chapter shown without its equations is missing the half of
    the argument that carries the result.
    """
    kind = block.get("kind")
    if kind == "paragraph":
        return block.get("text", "")
    if kind == "heading":
        number = block.get("number") or ""
        return ("%s %s" % (number, block.get("title", ""))).strip()
    if kind == "math":
        return block.get("tex", "")
    if kind == "code":
        return block.get("text", "")
    if kind == "figure":
        return block.get("caption", "")
    if kind == "table":
        caption = block.get("caption", "")
        return "\n".join(part for part in (caption, block.get("tex", "")) if part)
    return block.get("text", "")


def anchors(blocks: list[dict]) -> list[str]:
    return [block["anchor"] for block in blocks if block.get("anchor")]


def find_anchor(blocks: list[dict], anchor: str) -> dict | None:
    for block in blocks:
        if block.get("anchor") == anchor:
            return block
    return None


def neighbours(blocks: list[dict], index: int) -> dict:
    """The blocks a reader would step to from this one: back, forward, and up.

    An argument in a paper is not one block. Prose runs into an equation and out
    of it again, and each of those is addressed on its own, so a caller that has
    found the middle of an argument needs the way to its edges without searching
    again. `parent` is the heading the block sits under, which is the whole
    section when the two blocks either side are not enough.

    Each is an anchor, or None where the chapter ends or the block stands
    outside any heading. A block carrying no anchor is stepped over rather than
    returned: it cannot be addressed, so naming it would give a caller a place
    it cannot open.
    """
    def addressable(positions) -> str | None:
        for position in positions:
            anchor = blocks[position].get("anchor")
            if anchor:
                return anchor
        return None

    # A heading's parent is the heading above it, and a heading's equal is not
    # above it: two sections at the same level are siblings, so the search skips
    # them. Anything that is not a heading sits under the nearest heading of any
    # level.
    here = blocks[index]
    under = (here.get("level") or 0) if here.get("kind") == "heading" else None

    parent = None
    for position in range(index - 1, -1, -1):
        block = blocks[position]
        if block.get("kind") != "heading" or not block.get("anchor"):
            continue
        if under is not None and (block.get("level") or 0) >= under:
            continue
        parent = block["anchor"]
        break

    return {
        "prev": addressable(range(index - 1, -1, -1)),
        "next": addressable(range(index + 1, len(blocks))),
        "parent": parent,
    }
