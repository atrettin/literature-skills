---
name: add-paper
description: Adds a paper from arXiv to the local literature database in literature/. Use when the user gives a paper title, an author or a year and asks to add, ingest or download the paper.
---

# Add a paper to the literature

The literature database holds papers as plain text, split into chapters. Agents
read it with the `use-literature` skill. This skill puts a new paper into it.

`litdb add-paper` does the ingest. You handle its exceptions. Never read a
chapter: the command measures every number that `paper.json` holds.

The paper comes from arXiv, because arXiv is the only source that carries the
TeX. arXiv does not say where the paper was published — its `journal_ref` field
is written by the authors and is empty for most records. INSPIRE-HEP does say,
and `litdb add-paper` asks it.

## Before you start

Run every command from the root of the project, so that `literature/` resolves.

The collection is at `$LITERATURE_ROOT` when that variable is set. If it is not
set, it is `literature/` in the project. `litdb` reads the variable itself, thus
you do not give `--literature-root`.

## Step 1. Run the ingest

```bash
litdb add-paper --auto <arxiv-id> [<arxiv-id> …]
```

Give the identifiers of every paper the user asked for, in one command. Give a
title instead when the user has no identifier:

```bash
litdb add-paper --auto \
    --title "<title>" --author "<author>" --year <year>
```

It prints one JSON object per paper, one object per line. **The exit
code says who acts:**

| Exit | What it means | What you do |
|---|---|---|
| 0 | The collection holds the paper. | Report the fields below. Stop. Open no chapter. |
| 2 | A structured exception. | Read `exception.code`. Go to the section for it. |
| 1 | A usage error. | Report the error. Ingest no other paper. |

On exit 0, report these fields of the report, and nothing else:

`slug`, `index`, `title`, `publication.journal`, `arxiv_id`, how many chapters
and how many words, `parser`, every entry of `warnings`, the counts of
`references`, and the counts of `checks.elsewhere` in one line.

`checks.elsewhere` counts the defects of the other papers. Leave those alone.
They belong to papers this run did not touch.

## Step 2. Handle an exception

The report carries `exception`, with a `code` and a `detail`. Each code below
says what it means and what to do. **A code that is not in this table is one you
must report and never guess at.**

### `AMBIGUOUS_TITLE`

The search found no single exact match. `candidates` holds up to five results,
each with `arxiv_id`, `title`, `authors`, `year`, `doi`, `journal` and `match`.

The `match` field is a title-similarity heuristic. It is wrong in three known
ways, each of which has hidden a paper that arXiv held all along:

1. **The year is the journal year.** `--year` filters on the arXiv submission
   date. The search covers that year and the year before it. A preprint can come
   more than a year before its journal, and a proceedings volume often does. Run
   the search again with no `--year` at all.
2. **Notation differs.** `$C_5^A$` against `C(5)_A`, or `medium nuclei` against
   `medium-mass nuclei`, drops a true match below the threshold.
3. **The preprint carries a different title.** Authors retitle papers between
   arXiv and the journal. Phys. Rev. C91 045501 is "Investigation of recent weak
   single-pion production data"; its preprint is "On Recent Weak Single Pion
   Production Data". The title then tells you nothing. Check the DOI.

**The DOI, the journal reference and the author list decide identity — not the
title, and not the `match` field.** When those three agree, the paper is the
paper. When the DOI disagrees, no title similarity makes it the right paper.

Cross-check against INSPIRE-HEP when the arXiv record alone does not settle it:

```bash
litdb inspire <arxiv_id>
litdb inspire --doi <doi>
```

`"found": false` for a candidate you found on arXiv usually means a paper
outside high-energy physics, and not a wrong identifier. A record whose title
agrees and whose `arxiv_id` comes back empty is strong evidence that nobody
posted the paper to arXiv. Many theses and older conference proceedings are of
that kind. **That is a real answer. Report it, and substitute no other paper.**
[Crossref](https://api.crossref.org/works/) takes a DOI directly, and it reaches
outside high-energy physics.

When you have settled the identity, run the ingest again with the identifier.
Ask the user with `AskUserQuestion` only when the checks above leave the answer
still in doubt.

### `NO_ARXIV_SOURCE`

arXiv served a PDF, an empty archive or an HTTP error. `http_status` and
`reason` say which. A PDF-only submission carries no TeX, so this paper cannot
be ingested. Report it as not ingestable. **Substitute no other paper.**

### `TAG_COLLISION`

The name this paper wants belongs to a different work. `slug` is the name,
`held_by` says what holds it, `held_arxiv_id` names the work that has it, and
`suggested_slug` carries one more title word.

Nothing reassigns a tag once a work has it. The tag sits in the chapter files of
every paper that cites that work. Decide which work owns the name. Then run the
ingest again with `--slug <name>` for the other work.

### `PARSER_FAILURE`

TexSoup failed and the regex fallback found no section, or the conversion
produced no chapter holding text. `main_tex` names the file it tried, and
`sections_found` says how many sections it found. Report the failure. The paper
needs a conversion by hand, or none.

### `SLUG_EXISTS`

The paper directory is already there, and the caller gave no `--force`.
`existing_arxiv_id` says which paper it holds. Ask the user whether to replace
it. Re-run with `--force` when the answer is yes.

`--force` empties the paper directory first, which deletes `paper.json` with
everything else. Every value in it is derived, so the ingest writes it again.

### `REFERENCE_CHECK_FAILED`

The paper is on disk and the collection lists it. Its citations are what failed.
The exception carries `unresolved`, `duplicates`, `missing_pages` and `residue`,
each already scoped to this paper, and `elsewhere` for the rest of the
collection.

- `unresolved` — a chapter cites a tag no record answers. Say so. The claim that
  citation supports cannot be traced until it resolves.
- `missing_pages` — the record is there and the page its citation opens is not.
  Run `litdb references --render-only`, which writes them.
- `duplicates` — one work holds two records, so its citations are split.
- `residue` — a chapter holds a `PH<number>` where the paper wrote something
  else, or a control character. Nothing repairs the text in place. Re-run the
  ingest with `--force`.

### `COLLECTION_INDEX_UNREADABLE`

`literature/README.md` holds no table with a Title column and a Year column
under a separator row. `path` and `reason` say what was read. Repair the table
by hand, then re-run with `--index-only <slug>`.

### `NETWORK_UNAVAILABLE`

An API did not answer after its retries. `host` and `reason` say which. Report
it and try again later. This is not a fault of the paper.

## What the ingest writes

### `literature/<slug>/`

| Path | What it holds | |
|---|---|---|
| `paper.json` | what the paper is: metadata, one entry per chapter, every label and every reference the conversion found | stored |
| `text/NN_<title>.jsonl` | the words, one JSON block per line, long sections split | stored |
| `figures/<name>.png` | one cropped PNG per figure | stored |
| `figures_raw/` | the paper's own figure files, never deleted | stored |
| `INDEX.md` | the identity table, the abstract, and one row per chapter | rendered |
| `chapters/NN_<title>.md` | the same words, for a person to read | rendered |
| `figures/FIGURES.md` | the caption of each figure | rendered |

The ingest stores the paper and then renders it, in whichever flavor
`literature/.collection.json` records. The rendered files can be thrown away and
written again with `litdb render`; the stored ones cannot.

The identity table of `INDEX.md` holds `Authors`, `Submitted`, `Published`,
`Journal`, `DOI`, `arXiv`, `Ingested` and `Parser`, and an `Erratum` row under
`Journal` when the paper has one. `Submitted` is the arXiv year and always has a
value. A paper INSPIRE reports no publication for says `preprint` in `Published`
and `—` in the other two. The slug keeps the submission year, whatever
`Published` says.

The chapter table has five columns:

```markdown
| # | File | Words | Named anchors | Subsections |
|---|---|---|---|---|
| 7 | [07_form_factors.md](chapters/07_form_factors.md) | 1435 | 15 | 7.1 Generic Dipole Form |
```

`Words` says where the substance of the paper is. `Named anchors` counts the
`sec-`, `eq-`, `fig-` and `tab-` anchors. It leaves the `pN` paragraph anchors
out, because every long paragraph carries one and their count merely repeats
`Words`. The named anchors say something else. A report can cite a chapter that
labels its equations more finely than a chapter of plain prose, and that is the
difference this column shows.

### `literature/README.md`

One row per paper, in order of the arXiv submission year, newest last:

```markdown
| [<Title>](<slug>/INDEX.md) | <first author> et al. | <year> | <journal> | <one sentence> |
```

The last cell holds the first sentence of the abstract. A second run on one
slug writes the Journal cell and changes nothing else. That is what brings a
published preprint up to date.

### The reference store

The ingest folds every work the paper cites into `.references.jsonl`, rewrites
`REFERENCES.md` and `references/` from it, and turns each `[cite: …]` marker in
the chapters into the link a reader follows:
`([Lipari, 2002](../../references/lipari_2002_neutrino_oscillation_neutrino_cross.md))`.

The `references` block of the report counts what happened:

| Field | What it means |
|---|---|
| `cited` | works this paper cites |
| `added` | works this paper is the first here to cite |
| `updated` | works already known, which now list this paper too |
| `unchanged` | works already known and already listing it — a re-run |
| `unverified` | rows of the whole store whose identity nothing confirmed |
| `retagged` | citations repointed, because the store knew a work by another tag |
| `relinked` | files whose `[cite: …]` markers became links |
| `held` | works of the store this collection also holds in full |

Tell the user the count of unverified references. Those rows are marked ⚠: their
fields come from a citing paper's own bibliography, and may be wrong.

Resolve a tag with `litdb lookup`, and never by reading `REFERENCES.md`:

```bash
litdb lookup <tag>
```

## Refresh a paper that is already there

A preprint gets published later. Look it up again:

```bash
litdb inspire <arxiv_id>
```

Then edit the `publication` block of the paper's `paper.json`, and re-run
`litdb add-paper --index-only <slug>`. That renders the paper again — `INDEX.md`,
the chapters and `FIGURES.md` — and writes the Journal cell of its row in
`literature/README.md`. Nothing else changes: do not re-fetch, do not pass
`--force`, and never edit a rendered file. The text of the paper did not change.
Only what is known about it did.

## Rules

- The papers are copyrighted. Never commit a file under `literature/`.
- Never copy a long passage from a chapter into `docs/` or another tracked file.
- Report each warning of the report to the user.
- **`litdb` sends one request at a time.** Its request gate holds every command
  to the pace each API asks for, and it does so across processes. One command
  therefore ingests a whole queue of papers. Pass every identifier to that one
  command. Do not call these APIs from two agents at once.
- Never read a chapter during an ingest. The ingest measures every number that
  `paper.json` holds. A paper that you read to restate those numbers costs the
  context that the task itself needs.
- Work through `AMBIGUOUS_TITLE` before you report a paper as missing. Most such
  results are one of the three known false negatives.
- Never ingest a paper other than the one asked for. When only a similar paper
  exists, report the difference and add nothing.
- Never delete `figures_raw/`. It is the only copy of the paper's own figure
  files, and every conversion is redone from it.
- Never write a journal reference that no lookup returned. A paper INSPIRE does
  not hold, or holds without a publication, is recorded as a preprint. Guessing
  the journal puts a wrong citation into every document that later cites it.
- Never edit `literature/REFERENCES.md` or `literature/references/` by hand.
  Both are rendered in full from `.references.jsonl` on every run, so an edit is
  discarded at the next one. Fix the store, or fix what put the wrong value there.
- Never fill in a ⚠ row from memory. A reference nothing could confirm stays
  unconfirmed until a lookup confirms it. That mark is what tells a later reader
  the row may be wrong.
