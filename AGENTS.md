# AGENTS.md

This file provides guidance to OpenCode agents working in this repository.

## Key Commands

- **Installation**: Run `./install.sh` to install the `litdb` command and symlink skills/agents. Use `PYTHON=~/.venvs/tools/bin/python ./install.sh` to specify a Python environment.
- **Testing**: Run `.venv/bin/python -m pytest` for unit tests. Use `.venv/bin/python -m pytest -m network` for network-dependent tests.
- **Type Checking**: Run `.venv/bin/python -m pyright` to verify type correctness.

## Repository Structure

- **`lit/`**: Core package containing all commands and shared utilities.
- **`tests/`**: Unit tests covering critical functionality (queries, ranking, citations, etc.).
- **`docs/`**: Detailed documentation for commands, research workflows, and development.
- **`skills/`**: OpenCode skills for literature management tasks.

## Development Workflow

1. **Environment Setup**: Use `.venv` for development. Install dependencies with:
   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install --editable ".[rerank,dev]"
   ```

2. **Testing**: Run tests with `pytest`. Network-dependent tests are opt-in via `-m network`.

3. **Type Checking**: Use `pyright` to ensure type safety. Configuration is in `pyrightconfig.json`.

## Critical Notes

- **Rate Limiting**: The arXiv and INSPIRE-HEP APIs enforce rate limits. `lit/rate_gate.py` ensures compliance across processes. Avoid parallel API calls.
- **Literature Directory**: Git ignores `literature/` and `*.pdf`/`*.eps` files. Papers are copyrighted and must not be committed.
- **Flavor Rendering**: The collection is rendered in a specific flavor (`vscode` or `obsidian`). Use `litdb render --flavor` to set it.
- **Scope Handling**: Commands use `--scope` to target specific papers or chapters. Defaults vary by command.

## Common Pitfalls

- **Exit Codes Through Pipes**: `litdb <cmd> | head` reports the exit status of `head`, not of `litdb`. When a command's exit status matters (0 answered, 1 absent, 2 judgement), capture it without a pipe, e.g. `litdb <cmd> > /dev/null; echo $?`.
- **Missing Converters**: Figures may require `ghostscript` or `librsvg`. Install them separately if needed.
- **API Dependencies**: Network tests require arXiv/INSPIRE-HEP access. Use mock data in `tests/data/` for offline testing.
- **Flavor Mismatch**: Reports cite anchors specific to the rendered flavor. Ensure consistency with `litdb render`.

## Documentation

- **`README.md`**: Overview of skills and installation.
- **`docs/commands.md`**: Detailed command reference.
- **`docs/developing.md`**: Development guidelines and module layout.
- **`TUNING.md`**: Parameters affecting answer quality.

## Testing Quirks

- **Network Tests**: Deselected by default. Use `-m network` to run them.
- **Collection Fixtures**: Tests use `tests/data/collection_fixture/` (not `literature/`).
- **No LaTeX Conversion Tests**: Verify end-to-end via ingestion and reference checks.
