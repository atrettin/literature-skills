---
name: add-paper
description: Adds a paper from arXiv to the local literature database in literature/. Use when the user gives a paper title, an author or a year and asks to add, ingest or download the paper.
---

# Add a paper to the literature

The literature database holds papers as plain text, split into chapters. Agents
read it with the `use-literature` skill. This skill puts a new paper into it.

The scripts do the mechanical work. You do the reading and the summaries.

The paper comes from arXiv, because arXiv is the only source that carries the
TeX. arXiv does not say where the paper was published — its `journal_ref` field
is written by the authors and is empty for most records. INSPIRE-HEP does say,
and the fetch script asks it.

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

This search finds a paper that you can name. The `find-papers` skill searches by
subject instead, and answers with the papers whose abstracts are about a
question. Use that one when the user asks for papers on a topic rather than for
one paper.

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

Cross-check against INSPIRE-HEP when the arXiv record alone does not settle it:

```bash
$PY $SKILL/scripts/inspire_lookup.py <arxiv_id>
$PY $SKILL/scripts/inspire_lookup.py --doi <doi>
```

The script prints the paper's title, journal and DOI as INSPIRE holds them.
`"found": false` means INSPIRE has no record under that identifier — for a
candidate you found on arXiv, that is usually a paper outside high-energy
physics rather than a wrong identifier. When you have a journal reference but
no arXiv candidate at all, look it up with `--doi`: a record whose title matches
and whose `arxiv_id` comes back empty is strong evidence that the paper
was never posted to arXiv — theses and older conference proceedings frequently
were not. That is a real answer: report it, and do not substitute a similar
paper for it. [CrossRef](https://api.crossref.org/works/) also takes a DOI
directly and reaches outside high-energy physics.

## Step 3. Make the directory name

Build the slug from the confirmed result:

```
<first-author-surname>_<year>_<one-or-two-keywords>
```

Write the slug in lower case. Replace each other character with `_`. Use the
year of the arXiv submission, not the year of the journal. Example:
`alvarez-ruso_2017_nustec_review`.

**First check whether the collection already has a tag for this paper.** Another
paper here may already cite it, in which case it has a record under a tag of
exactly this shape. Ask by identifier, not by name:

```bash
$PY $SKILL/scripts/reference_lookup.py --arxiv <arxiv_id>
$PY $SKILL/scripts/reference_lookup.py --doi <doi>
```

If that finds a record, **use its `tag` as the slug**. The tag is already
written into the chapters of every paper that cites this one, and reusing it
makes those citations resolve to the paper itself once it is here.

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

It also reads the paper's bibliography and resolves it, which is what makes the
citations in the chapters mean anything. `[cite: Lipari:2002at]` — the author's
private label — comes out as `[cite: lipari_2002_neutrino_oscillation_neutrino_cross]`,
a tag that step 6 gives a row in `literature/REFERENCES.md`. Step 6 also turns
that marker into the link a reader follows,
`([Lipari, 2002](../../references/lipari_2002_neutrino_oscillation_neutrino_cross.md))`,
so a chapter still holding a `[cite: ...]` marker after step 6 is one whose tag
the store could not answer. The references themselves are in the manifest's
`references` field; step 6 files them. Pass `--no-references` to skip this, and
the citations keep the paper's own keys.

Every figure is converted to PNG so that it can be read directly, and the
surrounding whitespace is cropped. The paper's own files stay in
`figures_raw/`, so a conversion can be redone without downloading the paper
again. Conversion needs `gs` for EPS, PS and PDF, `rsvg-convert` for SVG, and
Pillow for raster formats and for the cropping step. A figure whose converter
is missing is copied over unconverted and reported as a warning — the paper
keeps the figure either way.

`convert_figures.py` does this work and also runs on its own, to convert a
paper whose `figures/` holds anything other than cropped PNGs:

```bash
$PY $SKILL/scripts/convert_figures.py \
    literature/<slug>
```

The script prints a JSON manifest. **Write it to a file** — step 6 reads it, and
it is large enough that keeping it only in the conversation is wasteful:

```bash
$PY $SKILL/scripts/arxiv_fetch.py <arxiv_id> --slug <slug> > /tmp/<slug>.json
```

The script writes no `INDEX.md`. You write that file.

The manifest's `publication` block says where the paper was published. The
fetch script asks INSPIRE-HEP for it, keyed on the arXiv identifier:

| Field | What it holds |
|---|---|
| `source` | `inspire`, `arxiv` (INSPIRE had nothing, arXiv's `journal_ref` was used) or `none` |
| `journal` | `Phys.Rev.D 108 (2023) 113010`, or empty for a preprint |
| `published_year` | the year the journal carried it, or `null` |
| `doi` | the published DOI, or empty |
| `errata` | one entry per erratum or addendum, usually empty |

`submitted_year` sits beside it and holds the year of the arXiv submission.
The two differ often, and by more than a year for proceedings volumes.

A `journal` that comes back empty means the paper is still a preprint. That is
an answer, not a failure — write it as one in step 5. Pass `--no-inspire` to
skip the lookup; the journal then comes from arXiv alone and is usually empty.

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
- Equations, figures, tables and sections are numbered as the conversion meets
  them, and each one that the paper labelled gets an `<a id="...">` anchor named
  after that label. The paper's own `\ref` commands become links to those
  anchors: `eq. ([6](#eq-ckmt))` in the same chapter,
  `Section [4](04_partially_conserved_axial_vector_current.md#sec-pcac)` across
  chapters. An equation carries its number in the maths itself, as `\tag{6}` or,
  in a multi-row `align`, as `\qquad (6)` on each numbered row.

The numbers are counted afresh, not read off the published paper, so a paper
that renumbers by hand can come out a little different. The link still reaches
the right object. Section numbers are the collection's chapter numbers, which
count `Front matter` as chapter 1 when there is one, so they can sit one above
the numbers printed in the paper.

The manifest's `labels` block says what each label resolved to.
`unresolved_refs` names the labels that resolved to nothing — those keep their
`[ref: label]` marker in the text, and a warning says how many there were.

Read the `warnings` field of the manifest. Tell the user about each warning.
A `parser` value of `fallback` means that TexSoup did not parse the source.
The text is then less exact. Tell the user when this happens.

Add `--force` only when the user wants to replace a paper that is already there.
`--force` empties the paper directory first, which **deletes `INDEX.md` along
with everything else**. Write it again from step 5 after any re-fetch, and run
step 6 again so the reference store learns the paper's citations afresh.

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
| Submitted | <submitted_year> |
| Published | <publication.published_year, or "preprint"> |
| Journal | <publication.journal, or "—"> |
| DOI | [<publication.doi>](https://doi.org/<publication.doi>), or "—" |
| arXiv | [<arxiv_id>](https://arxiv.org/abs/<arxiv_id>) |
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

The two year rows answer different questions, so write both even when they
agree. `Submitted` is the arXiv date and always has a value. `Published` and
`Journal` and `DOI` come from the `publication` block; when the paper is still
a preprint, write `preprint` in `Published` and `—` in the other two. Add an
`Erratum` row, directly beneath `Journal`, only when `publication.errata` is
not empty, and put one erratum per line in it.

The slug from step 3 keeps the **submission** year, whatever `Published` says.
Do not rename a directory to match a journal year.

Never write a summary of a chapter that you did not read.

Do not change the text in the chapter files. The chapter files hold the words of
the paper.

## Step 6. File the paper's references

```bash
$PY $SKILL/scripts/update_references.py --manifest <manifest file>
$PY $SKILL/scripts/check_references.py
```

Write the manifest from step 4 to a file if you have not already, and pass it
here. The first script folds every work the paper cites into the reference
store, rewrites `literature/REFERENCES.md` and `literature/references/` from it,
and writes the citations into the chapters — `relinked` in its output counts the
files it touched. The second checks that every citation in the collection still
names a work and still has a page to open; it prints `"ok": true` and exits 0
when all is well.

Run this **after** `INDEX.md` exists, not before. The merge reads each paper's
`INDEX.md` to work out which cited works this collection also holds in full, and
links their rows to them.

What comes back from the merge:

| Field | What it means |
|---|---|
| `added` | works this paper is the first to cite |
| `updated` | works already known, which now list this paper too |
| `unchanged` | works already known and already listing it — a re-run |
| `unverified` | rows across the whole store whose identity is not confirmed |
| `retagged` | citations repointed because the store already knew a work under another tag |
| `relinked` | files whose `[cite: ...]` markers became links a reader can follow |
| `pages_written` | pages under `references/` written or brought up to date |
| `pages_removed` | pages whose work is no longer in the store |

One work has one row however many papers cite it, and re-running the merge on
the same manifest changes nothing, so it is safe to repeat.

Tell the user the count of unverified references, as you do for warnings. Those
rows are marked ⚠ in the table: they come from the paper's own bibliography or
from a title match, and their fields may be wrong. Every other row was confirmed
against INSPIRE-HEP or Crossref by DOI, arXiv identifier, or journal, volume and
page.

If `check_references.py` reports anything under `unresolved`, say so — a
citation in a chapter is naming a record that does not exist, and the claim it
supports cannot be traced until it does. `missing_pages` means the record is
there but the page its citation opens is not; re-run `update_references.py
--render-only`, which writes them.

`dangling_refs` is the same check for the papers' internal cross-references: a
link to an equation, figure or section anchor that is not there, or a
`[ref: label]` the conversion could not resolve. It does not fail the run. A
paper ingested before cross-references were linked reports one entry per
reference it holds; re-fetching it is what fixes that.

`reference_lookup.py` reads the store the merge just wrote, and is how anything
downstream resolves a tag. `REFERENCES.md` is the view beside it, for a person
browsing and for a citation to land on; take the tag from the fragment of the
link that cites it, and do not grep the table for one:

```bash
$PY $SKILL/scripts/reference_lookup.py <tag>
```

## Step 7. Add the paper to the top-level index

Add one row to the table in `literature/README.md`:

```markdown
| [<Title>](<slug>/INDEX.md) | <first author> et al. | <submitted_year> | <publication.journal, or "—"> | <what the paper is about, one sentence> |
```

Keep the rows in order of the year, newest last. The year here is the arXiv
submission year, the same one the slug uses, so that the order and the directory
names agree. The journal is the publication, or `—` while the paper is a
preprint.

A collection started before this skill had a Journal column has a four-column
table. Add the column to the header, the separator row and every existing row —
`—` for a row you have not looked up — before you add yours.

## Step 8. Refresh a paper that is already there

A preprint gets published later. To bring an ingested paper up to date, look it
up again:

```bash
$PY $SKILL/scripts/inspire_lookup.py <arxiv_id>
```

Then edit the `Published`, `Journal` and `DOI` rows of the paper's `INDEX.md`
and the Journal cell of its row in `literature/README.md`. Nothing else changes:
do not re-fetch, do not pass `--force`, and do not touch the chapters or the
figures. The paper's text did not change — only what is known about it did.

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
- Never write a journal reference that no lookup returned. A paper INSPIRE does
  not hold, or holds without a publication, is recorded as a preprint. Guessing
  the journal from the paper's own front matter puts a wrong citation into every
  document that later cites it.
- Never edit `literature/REFERENCES.md` or `literature/references/` by hand.
  Both are rendered in full from `.references.jsonl` every time a paper is
  added, so an edit is discarded at the next run. Fix the store, or fix what put
  the wrong value there.
- Never fill in a ⚠ row from memory. A reference nothing could confirm stays
  unconfirmed until a lookup confirms it; that mark is what tells a later reader
  the row may be wrong.
