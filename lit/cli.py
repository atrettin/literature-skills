#!/usr/bin/env python3
"""What every command of `litdb` does the same way.

A command builds a parser here, parses through `parse` so the request gate
locks the collection the caller named, and prints one JSON object. The exit
status says who acts on it:

    0  the command answered
    1  what was asked for is absent or unreadable
    2  a bad argument, or a judgement the agent has to make

Nothing here decides anything about a paper. It is the shape of the answer,
and not the answer.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lit import paths, rate_gate

ABSENT = 1
JUDGEMENT = 2


# What the usage line calls this program. `lit/__main__.py` sets it to the
# subcommand it is about to run, so `litdb search --help` says `litdb search` and
# not the path of a module.
PROGRAM: str | None = None


def parser(doc: str | None) -> argparse.ArgumentParser:
    """A parser described by the first line of the module's own docstring."""
    return argparse.ArgumentParser(prog=PROGRAM, description=(doc or "").splitlines()[0])


def add_root_argument(target: argparse.ArgumentParser) -> None:
    """`--literature-root`, defaulting to `$LITERATURE_ROOT` or `literature`.

    The default is read when the parser is built, which is inside the command
    rather than at import, so the variable a caller exports still decides it.
    """
    target.add_argument(
        "--literature-root",
        type=Path,
        default=paths.default_root(),
        help="the collection directory; $LITERATURE_ROOT, else literature/",
    )


def parse(target: argparse.ArgumentParser, argv: list[str] | None = None):
    """Parse, and point the request gate at the collection the caller named.

    Without the second half, two processes on one collection started from two
    directories would take two different locks, and neither would hold the
    other back — which is the whole of what the gate promises.
    """
    args = target.parse_args(argv)
    root = getattr(args, "literature_root", None)
    if root is not None:
        rate_gate.use_root(root)
    return args


def emit(report: dict) -> None:
    """One report, indented, with the accents the papers actually carry."""
    print(json.dumps(report, indent=2, ensure_ascii=False))


def fail(message: str, code: int, **fields: Any) -> int:
    """An error, in the shape the command's caller parses.

    `fields` carries the empty form of whatever the command answers with — an
    empty list, a null band — so a caller reading the answer finds the key it
    expects rather than a KeyError on top of the error.
    """
    emit({"error": message, **fields})
    return code
