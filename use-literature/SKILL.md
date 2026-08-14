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

## Before you start

Run every command from the root of the project, so that `literature/` resolves.

The collection is at `$LITERATURE_ROOT` when that variable is set. If it is not
set, it is `literature/` in the project. `lit` reads the variable itself, thus
you do not give `--literature-root`. Read and write the collection's files at
that path.

## The structure

```
literature/
  .collection.json              which flavor the collection is rendered in
  .references.jsonl             every work the papers cite            STORED
  <slug>/paper.json             what a paper is: metadata, chapters   STORED
  <slug>/text/NN_<title>.jsonl  the words of one section              STORED
  <slug>/text/NN-MM_<title>.jsonl   one part of a long section        STORED
  <slug>/figures/<name>.png     the figures, cropped, one PNG each
  <slug>/figures_raw/           the files as the paper shipped them

  README.md                     one row for each paper                rendered
  REFERENCES.md                 one row for each work the papers cite rendered
  references/<tag>.md           one page for each cited work          rendered
  <slug>/INDEX.md               metadata, abstract, one row per chapter  rendered
  <slug>/chapters/NN_<title>.md the same words, for a person to read  rendered
  <slug>/figures/FIGURES.md     the caption of each figure            rendered
```

**Read what is stored.** The rendered files are written from the store for a
person, in whichever flavor `lit render` last wrote — one of `vscode` or
`obsidian`, and the links and anchors in them differ accordingly. The store says
the same thing in one form, and it is the form every `lit` command answers in.

The slug is `<first-author-surname>_<year>_<keyword>`. The year in it is the
year the preprint went to arXiv, which is not always the year of publication.
The chapter **stem** — `06-05_coherent_pion_production` — names the stored text
and every rendering of it at once, which is why a citation uses it.

`paper.json` carries both years, the journal reference, and one entry per
chapter with its title, subsections, word count and anchors. A question about
where or when a paper appeared is answered from `paper.json` alone — never open
a chapter for it. A `publication.journal` of `""` and no `published_year` mean
the paper had not been published when it was last looked up; `add-paper` can
refresh that.

### A block

`text/NN_<title>.jsonl` holds the words. **One line is one block**, so `Read`
gives you a line number for every block and `Grep` matches a block the way it
would match a paragraph. Every block carries `kind` and `anchor`:

```json
{"anchor":"sec-coherent-pi","kind":"heading","level":2,"number":"6.5","title":"Coherent Pion Production"}
{"anchor":"p2","kind":"paragraph","text":"Figure [ref: fig:coh] shows … [cite: vilain_1993_phys_lett_b313]."}
{"anchor":"","kind":"math","env":"eqnarray","tex":"…","numbers":["78","79"]}
{"anchor":"fig-coherent-pi","kind":"figure","file":"coherent_pi.png","number":"22","caption":"…"}
{"anchor":"tab-new-coherent-pion","kind":"table","number":"13","tex":"…","caption":"…"}
```

An `anchor` of `""` means the block has no address of its own; cite the chapter
alone for it. `#eq-ckmt`, `#fig-f2compare` and `#tab-fit` name an object the
paper labelled. `#sec-nuclear-effects` names a heading, after its title. `#p12`
names the twelfth paragraph of prose in that one file, counted from `p1` in each
file. **Cite the anchor**, never the line: the line addresses the file as it is
now, and a re-ingest moves it.

A citation is stored as `[cite: <tag>]` and a reference the paper makes to
itself as `[ref: <label>]`. Both are markers and neither is a link: what a link
looks like belongs to the flavor the collection is rendered in. `lit lookup`
turns a tag into the publication it names — see below. A `[ref: label]` is the
paper saying "see elsewhere in this paper"; `paper.json` has a `labels` entry
saying which chapter and anchor it resolves to.

Maths is stored as the paper wrote it, and never as a rendered `$$…$$`. A block
of `kind` `math` is one display equation, with the environment the paper used
and the numbers it carries; `$…$` inside a paragraph is inline maths.

You do not have to find an anchor yourself: `lit search` gives the anchor of
every block it matches, and `location` in its answer is the citation form.

Read `figures/` for a figure. `figures_raw/` exists only so the conversion can
be redone; never read it, and never delete it.

## To answer a question

1. Read `literature/README.md`.
2. Select the papers that cover the subject.
3. Read `paper.json` of each selected paper.
4. Choose the chapters that the question needs. Read the chapter title, the
   subsection titles beside it and the word count. A title names the subject,
   and the word count says which chapter carries the argument rather than a
   page of definitions.
5. Run `lit search` for a phrase of the question when the titles leave the choice
   open. It answers with the chapter, the anchor and the line, so it selects the
   chapter and finds the passage in one step.
6. Read `text/<stem>.jsonl` for the chapters that steps 4 and 5 name, and one
   more when a chapter points to it.

Do not read all chapters of a paper.

## To trace a claim a paper borrowed

A paper states plenty it did not establish itself. Where it says so, it cites:

> The axial mass extracted from deuterium data is $1.03$ GeV
> [cite: bodek_2008_axial_mass_quasielastic].

The marker carries the tag, here `bodek_2008_axial_mass_quasielastic`.
**Do not open `references/<tag>.md`.** That page and `REFERENCES.md` are both
rendered for a person to read; `lit lookup` is the one way you resolve a
citation, and it answers with more, from the store the two are rendered from.
Look the tag up before you repeat the claim as though the paper you are reading
had shown it:

```bash
lit lookup bodek_2008_axial_mass_quasielastic
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
  `literature/<that slug>/paper.json` — it is an ordinary paper of the collection.
- **`held_as` is null, with a `doi` or `arxiv_id`.** The work is identified but
  not here. Cite it from the answer; fetch it only if the question turns on
  reading it, as below.
- **`verified` is false.** Nothing could confirm this record. Its fields come
  from the citing paper's own bibliography, or from a match on the title alone,
  and may be wrong or incomplete. Never present it as an established source: say
  what the citing paper claimed, and that its source could not be confirmed.

The same tool searches, when you have no tag in hand:

```bash
lit lookup --search "quasielastic neutrino"   # title, author, journal
lit lookup --doi 10.1103/physrevc.48.1246
lit lookup --arxiv 1611.07770
lit lookup --cited-by <slug>                  # everything a paper draws on
```

`literature/REFERENCES.md` is a view of the same data, sorted most-cited first,
for a person browsing what the field is built on, and `literature/references/`
is the same data again, one page per work, for a person following a citation.
Do not read either to resolve a tag: the table holds one row per work across
every paper here and grows without limit, and a page tells you less than the
lookup does at the same cost.

## To verify a quotation

Before you write a quotation into a report, find it in the paper it is said to
come from:

```bash
lit search "<the words>" --paper <slug>
```

**Do not use `grep` for this.** A phrase copied out of a rendered chapter
carries the line break the reader's viewer put in it, and `grep` then gives no
match. Some files hold a NUL byte, and `grep` prints nothing for the whole file
— no error, and no "binary file matches". Both failures make text that is
present look absent. `lit search` matches the phrase and the stored block
against each other in the same flat form, so neither can hide the other.

The answer gives `location`, which is what a report cites, and `line_location`,
which is the stored file and the line to open. `Read` that file at that line and
check the words around the quotation. A paper can write a sentence as a
condition, or give it to somebody else. Such a sentence does not support the
claim that you were about to make with it.

**When a search returns nothing, suspect the search before you conclude
absence.** Read `partial_matches`: it names the longest shorter phrase the
papers do carry, which tells you the word the paper never wrote. Try fewer
words. Try the term the field uses for the same thing.

A hit in a paper you did not expect is a paper of another task. The collection
serves more than one question, and it keeps the papers of each. Such a hit is
evidence about that paper. It is not evidence about yours. Read it, and decide.

```bash
lit search "axial mass" --paper <slug> --paper <slug>   # your working set
lit search "axial mass"                                 # the whole collection
lit search "M_A\s*=\s*1.03" --regex
```

## To find a figure

1. Read the `figures` list of `literature/<slug>/paper.json`, or grep the
   `"kind": "figure"` blocks of `text/`. Both carry the caption.
2. Find the caption that describes the thing that you want.
3. Read the PNG in `figures/` with the `Read` tool.

Do not read the chapters to find a figure.

Each entry carries the figure's number, its anchor and the chapter stem where
the paper discusses it, so a figure a cross-reference names — `[ref: fig:xsec]`
— is the entry whose `label` is `fig:xsec`, numbered 3, or 3a and 3b when the
paper drew it as panels.

## To find a paper that is not there

1. Search the references first: `lit lookup --search "<author or title word>"`.
   A paper the collection does not hold may still be cited by one that it does,
   and the answer gives you the arXiv identifier to fetch it by.
2. Search arXiv with the `find-papers` skill. It searches abstracts rather than
   titles, so it finds a paper on the subject of the question, and it marks the
   results the collection already holds. Use it when the question names a
   subject; `lit lookup` above answers when you have a name or a title.
3. Otherwise tell the user that the database has no paper on the subject.
4. Offer the `add-paper` skill.

You may add a cited work yourself, without asking, when answering the question
needs the source rather than the citing paper's summary of it — a number you
must check, a derivation the citing paper only names. Take the `arxiv_id` from
the lookup and follow `add-paper` from its step 3, using the record's `tag` as
the slug. Say that you did it and why.

## Rules

- Quote a few sentences at most. Give the source as `<slug>/<stem>#<anchor>`,
  which names the paper and not one rendering of it.
- The papers are copyrighted. Never copy a long passage into a tracked file —
  documentation, a comment, a commit message. Write the fact in your own words.
- Never commit a file under `literature/`.
- A paper describes the science. A paper does not describe this codebase. Read
  the code and its output for what the software does.
- When you write a fact from the literature into the project's documentation,
  follow that project's own documentation rules if it has any, and cite the
  paper by its publication when `paper.json` gives one —
  `(Author year, Phys.Rev.D 108 (2023) 113010, §section)` — and as
  `(Author year, arXiv:ID, §section)` when the paper is still a preprint. The
  year in a citation is `publication.published_year` for a published paper and
  `submitted_year` for a preprint.
- Attribute a claim to the work that made it. When a paper you read cites
  someone else for a fact, resolve the tag with `lit lookup` and cite that work.
  Citing the paper you happened to read for a result it borrowed puts a wrong
  attribution into the project's documentation.
- Never edit a rendered file — `README.md`, `REFERENCES.md`, `references/`,
  `INDEX.md` or anything under `chapters/`. Every one of them is written again
  from the store whenever a paper is added or `lit render` runs, so an edit
  there is lost. Never edit `.references.jsonl` or `text/` either; both belong
  to `add-paper`.
- A claim that a paper does not hold something needs a search method that you
  can state. A `grep` that found nothing is not such a method: it fails silently
  on wrapped text and on a file with a NUL byte. Search with `lit search`, and say
  which phrases you searched for.
- Give `lit search` a scope. The collection serves more than one task and keeps the
  papers of each, so name the papers with `--paper` when the question is about
  your task. Leave `--paper` out when the question is about the collection
  itself. Read the `scope` block of the answer, and check that it holds the
  papers that you meant.
- Never answer from a citation alone. Its text and its tag both carry an author
  and a year, which is enough to look convincing and not enough to be right —
  they are identifiers, not citations. Resolve the tag with `lit lookup`.
