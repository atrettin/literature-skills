"""The `litdb` command, and that every subcommand behind it is reachable.

Cheap, and it catches the failure that no other test does: a command whose
parser or whose module-level code is broken only shows it when somebody runs
it, and most of these commands call an API, so no other test runs them.
"""

from __future__ import annotations

import importlib

import pytest

from lit import __main__ as dispatcher
from lit import arxiv_search, cli


@pytest.mark.parametrize("name", sorted(dispatcher.COMMANDS))
def test_every_subcommand_imports_and_builds_its_parser(name: str) -> None:
    module = importlib.import_module(dispatcher.COMMANDS[name][0])

    assert callable(module.main)
    parser = module.build_parser() if hasattr(module, "build_parser") else None
    if parser is not None:
        assert parser.format_help()


@pytest.mark.parametrize("name", sorted(dispatcher.COMMANDS))
def test_every_subcommand_answers_help(name: str, capsys: pytest.CaptureFixture) -> None:
    """`--help` exits 0 and names the subcommand, not the module behind it."""
    with pytest.raises(SystemExit) as exit_status:
        dispatcher.main([name, "--help"])

    assert exit_status.value.code == 0
    assert capsys.readouterr().out.startswith("usage: litdb %s" % name)


def test_the_bare_command_lists_what_there_is(capsys: pytest.CaptureFixture) -> None:
    assert dispatcher.main([]) == 2
    listed = capsys.readouterr().out
    for name in dispatcher.COMMANDS:
        assert name in listed


def test_a_command_that_is_not_there_is_a_usage_error(
    capsys: pytest.CaptureFixture,
) -> None:
    assert dispatcher.main(["summarize"]) == cli.JUDGEMENT
    assert "no such command" in capsys.readouterr().err


def test_the_query_ladder_builds_its_queries() -> None:
    """Reached only through `identity` and the network tests, so guarded here."""
    assert arxiv_search.build_search_query("axial mass", "Bodek", 2008) == (
        'ti:"axial mass" AND au:"Bodek" '
        "AND submittedDate:[200701010000 TO 200812312359]"
    )
    assert arxiv_search.build_fallback_query("axial mass", "Bodek")
    assert arxiv_search.build_loose_query("axial mass", "Bodek")
