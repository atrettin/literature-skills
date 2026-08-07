---
name: add-paper
description: Adds a paper from arXiv to the local literature database in literature/. Use when the user gives a paper title, an author or a year and asks to add, ingest or download the paper.
---

# Add a paper to the literature

The literature database holds papers as plain text, split into chapters. Agents
read it with the `use-literature` skill. This skill puts a new paper into it.

Two scripts do the mechanical work. You do the reading and the summaries.

## Before you start

This skill is installed once and used from any project, so nothing below can
assume a fixed path. Two shorthands are used throughout:

- **`$SKILL`** — this skill's own directory. The line *"Base directory for this
  skill"*, printed when the skill loads, gives it. The scripts live in
  `$SKILL/scripts/`.
- **`$PY`** — the project's Python. Use `.venv/bin/python` when the project has
  a virtual environment, otherwise `python3`.

Then:

1. Run `$PY -c "import TexSoup, PIL"`.
2. If that fails, run `$PY -m pip install -r $SKILL/requirements.txt`.
3. Run every command from the root of the project, so that `literature/`
   resolves.

## Step 1. Search arXiv

Run the search script with the information that the user gave you:

```bash
$PY $SKILL/scripts/arxiv_search.py \
    --title "<title>" --author "<author>" --year <year>
```

Give at least one of the three options. Give more options for a better result.
The script prints JSON. The top-level `match` field tells you what to do next.

**Search for one paper at a time.** arXiv rate-limits by client and answers
concurrent queries with `HTTP 429`. The script already waits 3 seconds between
its own requests, which is enough — but only while a single search runs. Never
run two searches at once, and never launch one sub-agent per paper in parallel
when the user asks for several papers.

## Step 2. Act on the match

| `match` | What you do |
|---|---|
| `exact` | Go to step 3. Use the `arxiv_id` of the first result. |
| `approximate` | Work through step 2a. Ask the user with `AskUserQuestion` only if that leaves the result still in doubt. |
| `none` | Work through step 2a before you believe it. |

Do not download a paper that the user did not confirm.

## Step 2a. Before you believe `approximate` or `none`

The `match` field is a title-similarity heuristic. It is wrong in three known
ways, each of which has produced a false negative on a paper that arXiv held all
along. The script now widens its query twice by itself — a quoted phrase, then
the title words joined with AND, then the author with the words merely OR-ed —
which recovers most of these. Rule the rest out before you report a paper as
missing.

1. **The year is the journal year.** `--year` filters on the arXiv submission
   date. The search covers the year you give and the one before it, which
   catches the usual case, but a preprint can precede its journal by more than
   a year — proceedings volumes are the worst offenders. If a search with
   `--year` finds nothing, **run it again with no `--year` at all**.
2. **Notation differs.** The title comparison is a character diff at a high
   threshold. `$C_5^A$` against `C(5)_A`, or `medium nuclei` against
   `medium-mass nuclei`, can drop a true match into `approximate`.
3. **The preprint carries a different title.** Authors retitle papers between
   arXiv and the journal, sometimes completely — Phys. Rev. C91 045501 is
   "Investigation of recent weak single-pion production data", while its
   preprint is "On Recent Weak Single Pion Production Data". Such a paper
   reports `approximate` with the right record at the top of the results. The
   title tells you nothing; check the DOI.

**The DOI, the journal reference and the author list decide identity — not the
title, and not the `match` field.** When those three agree, the paper is the
paper, whatever the heuristic said, and you may go to step 3 without asking the
user. When the DOI disagrees, no amount of title similarity makes it the right
paper.

Cross-check against [INSPIRE-HEP](https://inspirehep.net/api/literature?q=) or
[CrossRef](https://api.crossref.org/works/) when the arXiv record alone does not
settle it. Both take a DOI directly. An INSPIRE record with an empty
`arxiv_eprints` field is strong evidence that the paper was never posted to
arXiv — theses and older conference proceedings frequently were not. That is a
real answer: report it, and do not substitute a similar paper for it.

## Step 3. Make the directory name

Build the slug from the confirmed result:

```
<first-author-surname>_<year>_<one-or-two-keywords>
```

Write the slug in lower case. Replace each other character with `_`. Use the
year of the arXiv submission, not the year of the journal. Example:
`alvarez-ruso_2017_nustec_review`.

## Step 4. Fetch the paper

```bash
$PY $SKILL/scripts/arxiv_fetch.py <arxiv_id> \
    --slug <slug>
```

The script downloads the TeX source. It writes these files:

- `literature/<slug>/chapters/NN_<title>.md` — one file for each section
- `literature/<slug>/figures/<name>.png` — one PNG for each figure, cropped
- `literature/<slug>/figures/FIGURES.md` — the caption of each figure
- `literature/<slug>/figures_raw/<figure files>` — the originals, untouched

Every figure is converted to PNG so that it can be read directly, and the
surrounding whitespace is cropped. The paper's own files stay in
`figures_raw/`, so a conversion can be redone without downloading the paper
again. Conversion needs `gs` for EPS, PS and PDF, `rsvg-convert` for SVG, and
Pillow for raster formats and for the cropping step. A figure whose converter
is missing is copied over unconverted and reported as a warning — the paper
keeps the figure either way.

`convert_figures.py` does this work and also runs on its own, to convert a
paper that was ingested before this step existed:

```bash
$PY $SKILL/scripts/convert_figures.py \
    literature/<slug>
```

The script prints a JSON manifest. Keep the manifest. You need it in step 6.

The script writes no `INDEX.md`. You write that file.

The chapters are written to render in a Markdown preview, not only to be read
as text:

- Display maths is wrapped in `$$ ... $$`. Environments KaTeX does not know
  (`eqnarray`, `flalign`, `multline`) become `aligned`, and constructs it
  rejects (`\ensuremath`, `\mbox`, `\hfill`, the `isotope` package, plain-TeX
  `\pmatrix`) are rewritten. One unknown control sequence fails the whole
  equation with "Undefined control sequence", so a new paper is worth a glance
  in the preview.
- Figures are embedded as a centred `<img>` pointing at `../figures/<name>.png`,
  with the caption beneath. HTML rather than Markdown, because the images need
  a width.

Read the `warnings` field of the manifest. Tell the user about each warning.
A `parser` value of `fallback` means that TexSoup did not parse the source.
The text is then less exact. Tell the user when this happens.

Add `--force` only when the user wants to replace a paper that is already there.
`--force` empties the paper directory first, which **deletes `INDEX.md` along
with everything else**. Write it again from step 5 after any re-fetch.

## Step 5. Read the chapters and write INDEX.md

1. Read each file in `literature/<slug>/chapters/`.
2. Write a summary of 1 to 3 sentences for each chapter.
3. Say what the chapter contains. A later agent uses your summary to decide
   whether to open the file.
4. Write `literature/<slug>/INDEX.md` with this structure:

```markdown
# <Title>

| Field | Value |
|---|---|
| Authors | <first three authors, then "et al." for more> |
| Year | <year> |
| arXiv | [<arxiv_id>](https://arxiv.org/abs/<arxiv_id>) |
| Journal | <journal_ref, or "—"> |
| Ingested | <YYYY-MM-DD> |
| Parser | <texsoup or fallback> |

## Abstract

<the abstract from the manifest>

## Chapters

| # | File | What it covers |
|---|---|---|
| 1 | [chapters/01_introduction.md](chapters/01_introduction.md) | <your summary> |

## Figures

<count> figures. See [figures/FIGURES.md](figures/FIGURES.md) for the captions.
```

Never write a summary of a chapter that you did not read.

Do not change the text in the chapter files. The chapter files hold the words of
the paper.

## Step 6. Add the paper to the top-level index

Add one row to the table in `literature/README.md`:

```markdown
| [<Title>](<slug>/INDEX.md) | <first author> et al. | <year> | <what the paper is about, one sentence> |
```

Keep the rows in order of the year, newest last.

## Rules

- The papers are copyrighted. Never commit a file under `literature/`.
- Never copy a long passage from a chapter into `docs/` or another tracked file.
- Report each warning from the manifest to the user.
- Search for one paper at a time. Concurrent searches trip the arXiv rate limit
  and every one of them fails.
- Work through step 2a before you report a paper as missing or ask the user
  about an approximate match. Most such results are one of the three known
  false negatives.
- Never ingest a paper other than the one asked for. When only a similar paper
  exists, report the difference and add nothing.
- Never delete `figures_raw/`. It is the only copy of the paper's own figure
  files, and every conversion is redone from it.
