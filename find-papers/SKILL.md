---
name: find-papers
description: Finds papers on arXiv by the subject of their abstracts, and says which of them the local literature/ collection already holds. Use when a research question needs a paper that the collection may not hold yet.
---

# Find papers on a subject

This skill searches arXiv for papers about a question. It reads abstracts and
not titles. It therefore finds a paper on the subject when the title of that
paper never gives the words.

Use `use-literature` first. It reads the papers the project holds already, and
that costs nothing. Use this skill when the collection cannot answer the
question.

Each result says whether the collection holds that paper. You thus see what is
new and what is on disk already.

## Before you start

This skill is installed once and used from any project, so nothing below can
assume a fixed path. Two shorthands are used throughout:

- **`$DISCOVER`** — `<the add-paper skill's directory>/scripts/arxiv_discover.py`.
  The `add-paper` skill prints its own base directory when it loads. If it is
  not installed beside this one, `find ~/.claude/skills -name arxiv_discover.py`
  finds it.
- **`$PY`** — the project's Python. Use `.venv/bin/python` when the project has
  a virtual environment, otherwise `python3`.

Run every command from the root of the project, so that `literature/` resolves.

The search runs with no package installed. One optional package gives a better
order of the results:

```bash
$PY -m pip install -r <this skill's directory>/requirements.txt
```

Step 2 tells you how to read which order you got.

## Step 1. Turn the question into a topic

```bash
$PY $DISCOVER --topic "how meson exchange currents change the quasielastic neutrino cross section"
```

**Write the question as a full phrase.** The script reads `--topic` two times,
and each read uses a different part of it:

1. It removes the common words. It searches arXiv for the terms that remain.
2. It gives the whole phrase to the cross-encoder. The cross-encoder ranks the
   papers against it.

Step 2 reads the words that step 1 removes. Write `how meson exchange currents
change the cross section` and not `meson exchange cross section`. Both send the
same terms to arXiv, but only the first tells the cross-encoder what to rank.

| Option | What it does |
|---|---|
| `--topic` | the subject, as a phrase. Required. |
| `--category` | an arXiv category, such as `hep-ph`. Repeat it for more. |
| `--since` | earliest year of submission. |
| `--max-results` | how many papers to report. The default is 15. |
| `--literature-root` | where the collection is. The default is `literature`. |

**A category is exact.** `--category astro-ph` excludes `astro-ph.HE`, which is
a separate category and not a part of it. Give both when you want both.

## Step 2. Read the answer

The script prints JSON. Read these fields first:

| Field | What it holds |
|---|---|
| `ranking.backend` | which of the two orders you are reading. See below. |
| `counts` | how many results are `held`, `cited`, and `new`. |
| `query.terms` | the words the search used. Read them: they show what the script asked arXiv for. |
| `query.queries` | the query of each rung that ran. |

Then, for each result:

| Field | What it holds |
|---|---|
| `score` | the rank. Its meaning depends on `ranking.backend`. |
| `coverage` | the share of the terms this paper's title and abstract carry. |
| `missing_terms` | the terms it does not carry. |
| `found_by` | `strict` means the paper carries every term. `broad` means it carries some of them. |
| `held_as`, `known_as`, `cited_by` | what the collection knows. Step 3 uses these. |

**Read `ranking.backend` before you trust the order.**

| `ranking.backend` | What the order means |
|---|---|
| `flashrank:…` | A cross-encoder read the question and each abstract together. The top result answers the question. |
| `coverage` | No cross-encoder is installed. The order counts words only. A paper that repeats the words of the question ranks above one that answers it. |

Do two things when the backend is `coverage`. Tell the user that the order
counts words only. Give the install command from "Before you start".

**A `broad` result is a weak result.** No paper carried every term, so the
search asked for any of them. Read `missing_terms` before you use that paper.

`missing_terms` also shows what a good paper leaves alone. A paper that answers
most of a question and misses one term is still the best answer. The missing
term then tells you what to search for next.

The abstract in `summary` stops at 400 characters. Use it to decide whether the
paper is worth the reading. It is not a source. Do not quote it. Do not cite a
paper from it.

## Step 3. Decide what to do

| The result | What you do |
|---|---|
| `held_as` holds a directory name | The collection holds this paper in full. Read it with `use-literature`. Do not ingest it again. |
| `known_as` holds a tag, `held_as` is `null` | A paper in the collection cites this work. Run `reference_lookup.py <tag>` for the full record. Ingest it with `add-paper` when the question needs the work itself. |
| both are `null` | The collection does not know this paper. Report it, and offer the `add-paper` skill with the arXiv identifier. |

## When the search finds nothing

Try these, in order, one search at a time:

1. Remove the least important word from `--topic`.
2. Remove `--category`.
3. Make `--since` earlier, or remove it.

Then tell the user that arXiv has no paper on the subject. Report that as the
answer. A weak result is worse than no result. Never give one as an answer.

## Rules

- **Run one search at a time.** arXiv limits its rate. Never start a sub-agent
  for each query, and never run several searches at once. A rate limit costs
  more time than the parallel work saves.
- **An abstract is not a paper.** Never cite a paper that you found here. You
  read 400 characters of its abstract. That is enough to choose the paper. It is
  not enough to know what the paper says. Ingest it with `add-paper` and read
  it, or cite nothing.
- **Ask before you ingest.** A paper that the user did not name costs a
  download, a conversion, and space on disk. Report what you found. Let the user
  choose.
- **A rank is not a judgement of relevance.** Report the backend that produced
  the order, and report `missing_terms`. Never present position 1 as the answer
  without them.
- **Report the counts.** The user wants to know what is new. `counts.held` and
  `counts.cited` say how much of the answer was already on disk.
