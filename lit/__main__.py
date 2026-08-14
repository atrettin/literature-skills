#!/usr/bin/env python3
"""The `lit` command: one name in front of every command the skills run.

Each subcommand is a module with its own parser, and the module is imported
only when its name is given. `lit search` therefore starts without loading
TexSoup, which only the ingest needs.
"""

from __future__ import annotations

import importlib
import sys

# The subcommand, the module behind it, and what it does. The help below is
# built from this, so a command that is added here is documented by that.
COMMANDS: dict[str, tuple[str, str]] = {
    "add-paper": ("lit.add_paper", "ingest a paper from arXiv into the collection"),
    "find": ("lit.arxiv_discover", "find papers on arXiv by the subject of their abstracts"),
    "overlap": ("lit.collection_overlap", "weigh a candidate paper against what the collection holds"),
    "citations": ("lit.inspire_citations", "the papers that cite a paper, and the works it draws on"),
    "lookup": ("lit.reference_lookup", "what the collection knows about a cited work"),
    "search": ("lit.search_literature", "find a phrase in the text of the papers"),
    "render": ("lit.render", "write the collection a person reads, in one flavor"),
    "render-report": ("lit.render_report", "turn the lit: markers of a report into links"),
    "terminology": ("lit.terminology_scan", "the other names the literature uses for a subject"),
    "check-report": ("lit.check_report", "check that every citation of a report resolves"),
    "inspire": ("lit.inspire_lookup", "ask INSPIRE-HEP where a paper was published"),
    "references": ("lit.update_references", "merge and render the reference store"),
}


def usage() -> str:
    width = max(len(name) for name in COMMANDS)
    lines = ["usage: lit <command> [options]", "", "commands:"]
    lines += ["  %-*s  %s" % (width, name, what) for name, (_, what) in COMMANDS.items()]
    lines += ["", "Run `lit <command> --help` for the options of one command."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0 if argv else 2

    name = argv[0]
    if name not in COMMANDS:
        print("lit: no such command: %s\n" % name, file=sys.stderr)
        print(usage(), file=sys.stderr)
        return 2

    from lit import cli

    # Set before the command builds its parser, so its usage line names the
    # subcommand a reader would type rather than the module behind it.
    cli.PROGRAM = "lit %s" % name
    module = importlib.import_module(COMMANDS[name][0])
    return module.main(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
