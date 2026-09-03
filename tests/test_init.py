"""`litdb init`: the mechanical half of starting a collection.

It creates the directory and its index, and — the part that used to live in a
skill — makes git ignore the collection so a copyrighted paper never reaches a
remote. These cases pin the two things a script must get right: refusing to
touch a collection that already exists, and settling the git ignore before a
single file is written.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from lit import collection_index, init_collection, paths


def run(collection: Path, capsys) -> tuple[int, dict]:
    status = init_collection.main(["--literature-root", str(collection)])
    return status, json.loads(capsys.readouterr().out)


def git(cwd: Path, *arguments: str) -> tuple[int, str]:
    process = subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, text=True)
    return process.returncode, process.stdout


def make_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    return repo


def test_a_fresh_collection_is_created_outside_any_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "literature"

    status, report = run(root, capsys)

    assert status == 0
    assert report["created"] is True
    assert report["already_exists"] is False
    assert report["papers"] == 0
    assert report["git"] == "no-repository"
    assert (root / "README.md").is_file()
    assert "## Papers" in (root / "README.md").read_text(encoding="utf-8")
    assert (root / "REFERENCES.md").is_file()
    assert (root / "references").is_dir()


def test_a_collection_that_exists_is_refused_and_never_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from conftest import write_paper

    root = tmp_path / "literature"
    root.mkdir()
    write_paper(root, "lovelace_2025_analytical_engine", {"01_intro": [
        {"type": "p", "anchor": "p1", "tex": "The engine is analytical."},
    ]})

    status, report = run(root, capsys)

    assert status == 2
    assert report["already_exists"] is True
    assert report["created"] is False
    assert report["papers"] == len(paths.papers_on_disk(root))


def test_a_git_repository_gets_an_ignore_rule_before_any_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = make_repo(tmp_path)
    root = repo / "literature"

    status, report = run(root, capsys)

    assert status == 0
    assert report["git"] == "ignored"
    assert "literature/" in (repo / ".gitignore").read_text(encoding="utf-8")
    code, _ = git(repo, "check-ignore", "-q", "literature")
    assert code == 0


def test_an_already_ignored_collection_adds_no_second_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = make_repo(tmp_path)
    (repo / ".gitignore").write_text("literature/\n", encoding="utf-8")
    root = repo / "literature"

    status, report = run(root, capsys)

    assert status == 0
    assert report["git"] == "already-ignored"
    # The rule is written once, not stacked.
    assert (repo / ".gitignore").read_text(encoding="utf-8").count("literature/") == 1


def test_a_repository_reached_through_a_symlink_is_still_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """git reports the real path; the root may be reached through a symlink."""
    real = tmp_path / "real"
    real.mkdir()
    git(real, "init", "-q")
    link = tmp_path / "link"
    link.symlink_to(real)

    root = link / "literature"

    status, report = run(root, capsys)

    assert status == 0
    assert report["git"] == "ignored"
    assert "literature/" in (real / ".gitignore").read_text(encoding="utf-8")
    code, _ = git(real, "check-ignore", "-q", "literature")
    assert code == 0


def test_the_index_it_writes_is_the_shared_empty_template(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "literature"

    run(root, capsys)

    assert (root / "README.md").read_text(encoding="utf-8") == collection_index.EMPTY_INDEX
