#!/usr/bin/env python3
"""Start an empty collection, and make git keep its papers out of the repository.

This is the mechanical half of starting a collection. It creates the directory
and its index, makes sure git ignores it, and renders the reference index from
the (empty) store. What is left to a person is choosing what the collection is
for, and what `add-paper` puts into it — neither of which this command guesses.

The one thing it must get right is git. The papers are copyrighted, and a
collection that is not ignored will be committed sooner or later. So the ignore
is settled **before** a file of the collection is written: the directory is
created empty, the rule is confirmed against it, and only then is the index
written.

It never touches a collection that already exists. Refusing is the safe answer;
overwriting the index of a collection would drop every paper it lists.

Writes files; sends no request.

Exit status is 0 when a collection was created, and 2 when one already exists
and the caller has to decide whether to keep it.

Usage:
    litdb init
    litdb init --literature-root ~/literature
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from lit import cli, collection_index, paths, update_references

# The reason git must keep the collection out. Stated as a fact the caller
# relays, not a warning to be dismissed.
COPYRIGHT_NOTE = (
    "The papers are under copyright. Pushing them to a remote distributes "
    "them, and the liability for that is the user's."
)


# --------------------------------------------------------------------------
# keeping the collection out of git
# --------------------------------------------------------------------------


def _git(cwd: Path, *arguments: str) -> tuple[int, str]:
    """Run git from one directory. (exit status, combined output)."""
    try:
        process = subprocess.run(
            ["git", *arguments], cwd=cwd, capture_output=True, text=True
        )
    except FileNotFoundError:
        return -1, ""
    return process.returncode, (process.stdout or "") + (process.stderr or "")


def _in_work_tree(parent: Path) -> bool:
    code, out = _git(parent, "rev-parse", "--is-inside-work-tree")
    return code == 0 and out.strip() == "true"


def _git_available() -> bool:
    code, _ = _git(Path.cwd(), "--version")
    return code == 0


def _ignored(repo: Path, root: Path) -> bool:
    code, _ = _git(repo, "check-ignore", "-q", str(root))
    return code == 0


def settle_git(root: Path) -> tuple[str, list[str]]:
    """Make git ignore the collection, and say what was done.

    Returns (the outcome, the note for the user). The outcome is one of:
    `ignored`, `already-ignored`, `outside-repo`, `no-repository`,
    `git-unavailable`. It writes nothing unless it must add a rule.

    `git rev-parse --show-toplevel` answers with the repository's real path,
    with symlinks resolved. A root reached through a symlink — `/tmp` on macOS
    is one — would otherwise compare unequal and be read as sitting outside the
    repository, so both sides are resolved to the same form before they meet.
    """
    root = root.resolve()
    if not _git_available():
        return "git-unavailable", [
            "git is not on PATH, so no ignore rule was written. %s Do not "
            "publish the collection by any other means." % COPYRIGHT_NOTE
        ]

    parent = root.parent
    if not _in_work_tree(parent):
        return "no-repository", [
            "No repository at %s can commit the collection where it sits. %s "
            "If one is made there later, ignore the collection first."
            % (parent, COPYRIGHT_NOTE)
        ]

    code, toplevel = _git(parent, "rev-parse", "--show-toplevel")
    toplevel = Path(toplevel.strip()).resolve()

    try:
        relative = root.relative_to(toplevel)
    except ValueError:
        return "outside-repo", [
            "%s sits outside the repository rooted at %s, which can therefore "
            "not commit it. %s" % (root, toplevel, COPYRIGHT_NOTE)
        ]

    if _ignored(toplevel, root):
        return "already-ignored", ["The collection is already git-ignored."]

    rule = relative.as_posix() + "/"
    gitignore = toplevel / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
    lines = []
    if existing and not existing.endswith("\n"):
        lines.append("")
    lines += [
        "# Literature. The papers are copyrighted and must never be committed "
        "or",
        "# pushed to a remote.",
        rule,
    ]
    gitignore.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")

    if not _ignored(toplevel, root):
        return "git-unavailable", [
            "Wrote %s to %s, but git still does not ignore %s. %s"
            % (rule, gitignore, root, COPYRIGHT_NOTE)
        ]
    return "ignored", ["git now ignores %s (rule in %s)." % (rule, gitignore)]


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = cli.parser(__doc__)
    cli.add_root_argument(parser)
    return parser


def _exists_report(root: Path) -> dict:
    return {
        "literature_root": str(root),
        "created": False,
        "already_exists": True,
        "papers": len(paths.papers_on_disk(root)),
    }


def run(argv: list[str] | None = None) -> tuple[int, dict]:
    """Create the collection. Returns (exit status, the report `main` prints)."""
    args = cli.parse(build_parser(), argv)
    root = args.literature_root

    if root.exists() and root.is_dir():
        # Refuse rather than guess: the index is the record of what is held,
        # and rewriting it would drop every paper it lists.
        return 2, _exists_report(root)

    # The empty directory first, and no file of the collection: git's
    # trailing-slash rule only matches once the directory exists, so the ignore
    # is confirmed against it, while nothing copyrighted is present yet.
    root.mkdir(parents=True, exist_ok=True)
    git_outcome, git_notes = settle_git(root)

    readme = root / collection_index.INDEX_NAME
    readme.write_text(collection_index.EMPTY_INDEX, encoding="utf-8")

    references_status, references = update_references.run(
        ["--render-only", "--literature-root", str(root)]
    )
    if references_status != 0:
        # The collection now exists; a reference render that failed still
        # leaves a usable, empty store, so report it and carry on.
        references = {"error": references}

    report = {
        "literature_root": str(root),
        "created": True,
        "already_exists": False,
        "papers": 0,
        "readme": str(readme),
        "git": git_outcome,
        "git_note": git_notes,
        "references": references,
        "next": "litdb add-paper --auto <arxiv-id>",
    }
    return 0, report


def main(argv: list[str] | None = None) -> int:
    status, report = run(argv)
    cli.emit(report)
    return status


if __name__ == "__main__":
    sys.exit(main())
