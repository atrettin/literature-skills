---
name: use-literature
description: How to find and read published scientific papers in the local literature database in literature/. Use when a question is about the science behind the project — physical models, methods, experimental results — that the code and the project's own documentation do not answer.
---

# Read the literature database

`literature/` holds published papers as plain text. The text is split into
chapters. Read only the chapters that you need. A full paper fills your context
and gives you no more answers.

`literature/` is not tracked by git. A new clone has an empty directory. A
project with no `literature/` at all has no database yet — the `init-literature`
skill starts one.

## Two shorthands

Resolving a citation runs one script, which ships with the `add-paper` skill.
Neither path is fixed, so:

- **`$LOOKUP`** — `<the add-paper skill's directory>/scripts/reference_lookup.py`.
  The `add-paper` skill prints its own base directory when it loads; if it is
  not installed alongside this one, `find ~/.claude/skills -name reference_lookup.py`
  finds it.
- **`$PY`** — the project's Python: `.venv/bin/python` when the project has a
  virtual environment, otherwise `python3`.

Run every command from the root of the project, so that `literature/` resolves.

The collection is at `$LITERATURE_ROOT` when that variable is set. If it is not
set, it is `literature/` in the project. The scripts read the variable
themselves, thus you do not give `--literature-root`. Read and write the
collection's files at that path.

## The structure

```
literature/
  README.md                     one row for each paper
  REFERENCES.md                 one row for each work the papers cite
  .references.jsonl             the store the two views are rendered from
  references/<tag>.md           one page for each cited work — for a person
  <slug>/                       one directory for each paper
    INDEX.md                    metadata, abstract, and a summary of each chapter
    chapters/NN_<title>.md      the text of one section
    chapters/NN-MM_<title>.md   one part of a long section
    figures/FIGURES.md          the caption of each figure
    figures/<name>.png          the figures, cropped, one PNG each
    figures_raw/                the files as the paper shipped them
```

The slug is `<first-author-surname>_<year>_<keyword>`. The year in it is the
year the preprint went to arXiv, which is not always the year of publication.

`INDEX.md` carries both years and the journal reference. A question about where
or when a paper appeared is answered from `INDEX.md` alone — never open a
chapter for it. A `Journal` row of `—` and a `Published` row of `preprint` mean
the paper had not been published when it was last looked up; `add-paper` can
refresh that.

Chapter files hold the words of the paper. A citation becomes a link that reads
`(Lipari, 2002)` and names a file whose stem is the tag; `$LOOKUP` turns that
tag into the publication it names — see below.

A reference the paper makes to itself becomes a link to the thing it names:
`eq. ([6](#eq-ckmt))` for an equation in the same chapter, and
`Section [4](04_partially_conserved_axial_vector_current.md#sec-pcac)` for one in
another. The number in the link is the number the object carries in this
collection, and the file named before the `#` is the chapter to read for it. A `[ref: label]` with no link is a reference
whose target the paper's own source never defined; treat it as the paper saying
"see elsewhere in this paper".

Inline maths stays as `$…$` and display maths as `$$…$$`, so a Markdown preview
renders it. A numbered equation carries its number as `\tag{6}`. A figure is
embedded as a centred `<img>` pointing at `../figures/<name>.png`, followed by a
line starting `**Figure 6.**` that carries its caption; a table is the paper's
own LaTeX in a ```` ```tex ```` block, with `**Table 2.**` and its caption
beneath.

Read `figures/` for a figure. `figures_raw/` exists only so the conversion can
be redone; never read it, and never delete it.

## To answer a question

1. Read `literature/README.md`.
2. Select the papers that cover the subject.
3. Read `INDEX.md` of each selected paper.
4. Read only the chapter files whose summary matches the question.
5. Read one more chapter when a chapter points to it.

Do not read all chapters of a paper.

## To trace a claim a paper borrowed

A paper states plenty it did not establish itself. Where it says so, it cites:

> The axial mass extracted from deuterium data is $1.03$ GeV
> ([Bodek et al., 2008](../../references/bodek_2008_axial_mass_quasielastic.md)).

The tag is the name of the file the link opens, without `.md` — here
`bodek_2008_axial_mass_quasielastic`. **Do not follow the link.** `references/`
and `REFERENCES.md` are both rendered for a person to read; `$LOOKUP` is the one
way you resolve a citation, and it answers with more, from the store the two are
rendered from. Look the tag up before you repeat the claim as though the paper
you are reading had shown it:

```bash
$PY $LOOKUP bodek_2008_axial_mass_quasielastic
```

It answers in JSON with the title, authors, year, journal, DOI and arXiv
identifier of the work the claim actually comes from. Cite **that** work, not
the paper you found it in. Several tags at once is fine — pass them all.

Author lists come back collapsed to three names with `authors_total` beside
them, because a high-energy physics paper can carry several thousand authors and
listing them answers nothing. Pass `--all-authors` on the rare occasion you need
the rest.

What the answer can tell you:

- **`held_as` names a directory.** The work is here in full. Read
  `literature/<that slug>/INDEX.md` — it is an ordinary paper of the collection.
- **`held_as` is null, with a `doi` or `arxiv_id`.** The work is identified but
  not here. Cite it from the answer; fetch it only if the question turns on
  reading it, as below.
- **`verified` is false.** Nothing could confirm this record. Its fields come
  from the citing paper's own bibliography, or from a match on the title alone,
  and may be wrong or incomplete. Never present it as an established source: say
  what the citing paper claimed, and that its source could not be confirmed.

The same tool searches, when you have no tag in hand:

```bash
$PY $LOOKUP --search "quasielastic neutrino"   # title, author, journal
$PY $LOOKUP --doi 10.1103/physrevc.48.1246
$PY $LOOKUP --arxiv 1611.07770
$PY $LOOKUP --cited-by <slug>                  # everything a paper draws on
```

`literature/REFERENCES.md` is a view of the same data, sorted most-cited first,
for a person browsing what the field is built on, and `literature/references/`
is the same data again, one page per work, for a person following a citation.
Do not read either to resolve a tag: the table holds one row per work across
every paper here and grows without limit, and a page tells you less than the
lookup does at the same cost.

## To find a figure

1. Read or grep `literature/<slug>/figures/FIGURES.md`.
2. Find the caption that describes the thing that you want.
3. Read the PNG in `figures/` with the `Read` tool.

Do not read the chapters to find a figure.

Each row carries the figure's number and links to the place in the chapter where
the paper discusses it, so a figure a cross-reference names — `Fig. [3](…)` —
is the row numbered 3, or 3a and 3b when the paper drew it as panels.

## To find a paper that is not there

1. Search the references first: `$PY $LOOKUP --search "<author or title word>"`.
   A paper the collection does not hold may still be cited by one that it does,
   and the answer gives you the arXiv identifier to fetch it by.
2. Search arXiv with the `find-papers` skill. It searches abstracts rather than
   titles, so it finds a paper on the subject of the question, and it marks the
   results the collection already holds. Use it when the question names a
   subject; `$LOOKUP` above answers when you have a name or a title.
3. Otherwise tell the user that the database has no paper on the subject.
4. Offer the `add-paper` skill.

You may add a cited work yourself, without asking, when answering the question
needs the source rather than the citing paper's summary of it — a number you
must check, a derivation the citing paper only names. Take the `arxiv_id` from
the lookup and follow `add-paper` from its step 3, using the record's `tag` as
the slug. Say that you did it and why.

## Rules

- Quote a few sentences at most. Give the source as
  `literature/<slug>/chapters/<file>.md`.
- The papers are copyrighted. Never copy a long passage into a tracked file —
  documentation, a comment, a commit message. Write the fact in your own words.
- Never commit a file under `literature/`.
- A paper describes the science. A paper does not describe this codebase. Read
  the code and its output for what the software does.
- When you write a fact from the literature into the project's documentation,
  follow that project's own documentation rules if it has any, and cite the
  paper by its publication when `INDEX.md` gives one —
  `(Author year, Phys.Rev.D 108 (2023) 113010, §section)` — and as
  `(Author year, arXiv:ID, §section)` when the paper is still a preprint. The
  year in a citation is the `Published` year of a published paper and the
  `Submitted` year of a preprint.
- Attribute a claim to the work that made it. When a paper you read cites
  someone else for a fact, resolve the tag with `$LOOKUP` and cite that work.
  Citing the paper you happened to read for a result it borrowed puts a wrong
  attribution into the project's documentation.
- Never edit `literature/REFERENCES.md`, `literature/references/` or
  `.references.jsonl`. The first two are rendered from the store and rewritten
  in full whenever a paper is added; all three belong to `add-paper`.
- Never answer from a citation alone. Its text and its tag both carry an author
  and a year, which is enough to look convincing and not enough to be right —
  they are identifiers, not citations. Resolve the tag with `$LOOKUP`.
