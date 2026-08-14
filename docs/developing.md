# Developing

```bash
git clone <this repo> && cd literature-skills
python3 -m venv .venv
.venv/bin/python -m pip install --editable ".[rerank,dev]"
.venv/bin/python -m pytest
.venv/bin/python -m pyright
```

`pytest.ini` puts the repository root on the path, so the suite tests the working
tree and not whichever copy happens to be installed.

## The layout

Everything is one package, `lit/`. A module is either a command, or work that
the commands share.

| Module | Holds |
|---|---|
| `__main__.py` | the `lit` command: the subcommand table, and a lazy import of the module behind the name given |
| `cli.py` | the parser, `--literature-root`, the JSON printer, the exit codes |
| `text.py` | normalising a title, a name on disk, a table cell, an author list, a sentence |
| `paths.py` | where things are in a collection, and which files a citation can be in |
| `http.py` | one gated GET, and the header that identifies us to an API |
| `rate_gate.py` | one request at a time to each host, across processes |
| `reference_store.py` | `.references.jsonl`: the records, their tags, and merging one into another |
| `add_paper.py` | the ingest driver, which calls the stages below and prints the report |
| `arxiv_fetch.py`, `convert_figures.py`, `references.py` | the conversion stages: source, chapters, figures, bibliography |
| `blocks.py` | the stored form of a chapter: one JSON block per line, and the parse that builds it |
| `render.py`, `render_report.py` | what a person reads: the collection in one flavor, and the `lit:` markers of a report resolved into links |
| `write_index.py`, `collection_index.py`, `update_references.py` | the rendered views: `INDEX.md`, the collection table, `REFERENCES.md` and the pages |
| `arxiv_search.py`, `arxiv_discover.py`, `rerank.py`, `paper_facts.py`, `identity.py` | finding a paper on arXiv, and deciding which paper it is |
| `inspire_lookup.py`, `inspire_citations.py`, `collection_overlap.py` | INSPIRE-HEP: where a paper was published, what cites it, what it shares with the collection |
| `check_references.py`, `check_report.py`, `search_literature.py`, `reference_lookup.py`, `terminology_scan.py` | reading and checking what the collection holds |

## The tests

They cover the parts that fail quietly: the queries the commands send to arXiv,
the ranking, the answers the collection gives about a paper, the citations
written into the chapters, the citations written into a report, the queries sent
to INSPIRE for the citation graph, the phrase search over the text of the papers
(`tests/test_search_literature.py`), and which collection a command reads.

They call no network. `tests/data/` holds the arXiv responses they run against.
`tests/data/collection_fixture/` holds the collection they check against. That
directory is not called `literature`, because git ignores every directory of
that name.

One group of tests does call arXiv. It is deselected by default:

```bash
.venv/bin/python -m pytest -m network
```

Those tests assert what the queries depend on at arXiv:

- A quoted phrase finds far fewer papers than the same words joined with `AND`.
- An unknown field returns no results and no error.
- A category excludes its subcategories.

Each of these can change at arXiv rather than here, and arXiv reports none of
them as a failure. Run this group when a search returns the wrong kind of
answer.

The LaTeX-to-Markdown conversion has no unit tests. To exercise it end to end,
ingest a real paper and then run the reference check. `pyrightconfig.json`
configures the type checks.

## Tuning

[TUNING.md](../TUNING.md) lists the numbers that decide how good an answer is.
They do not decide whether the answer is correct. Three examples:

- how far the search widens when it finds little,
- which cross-encoder puts the results in order,
- how much of a paper one chapter holds.

Nobody measured these numbers. Each one is a judgement. Read that file before
you change one. Add a row to it when you introduce another.
