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
set, it is `literature/` in the project. `litdb` reads the variable itself, thus
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
person, in whichever flavor `litdb render` last wrote — one of `vscode` or
`obsidian`, and the links and anchors in them differ accordingly. The store says
the same thing in one form, and it is the form every `litdb` command answers in.

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
{"anchor":"b3","kind":"math","env":"eqnarray","tex":"…","numbers":["78","79"]}
{"anchor":"fig-coherent-pi","kind":"figure","file":"coherent_pi.png","number":"22","caption":"…"}
{"anchor":"tab-new-coherent-pion","kind":"table","number":"13","tex":"…","caption":"…"}
```

**Every block has an anchor**, so everything in a paper can be cited and
opened. `#eq-ckmt`, `#fig-f2compare` and `#tab-fit` name an object the paper
labelled. `#sec-nuclear-effects` names a heading, after its title. `#p12` names
the twelfth paragraph of prose in that one file, counted from `p1` in each file.
`#b7` is a block the paper gave no label of its own — an unnumbered equation, a
code listing, a short paragraph — counted the same way.

**The anchor is the address, and there is no other.** A line number describes
the file that holds the paper rather than the paper: a re-ingest rewrites the
chapter and moves it. No command reports one, and no citation carries one.

A citation is stored as `[cite: <tag>]` and a reference the paper makes to
itself as `[ref: <label>]`. Both are markers and neither is a link: what a link
looks like belongs to the flavor the collection is rendered in. `litdb lookup`
turns a tag into the publication it names — see below. A `[ref: label]` is the
paper saying "see elsewhere in this paper"; `paper.json` has a `labels` entry
saying which chapter and anchor it resolves to.

Maths is stored as the paper wrote it, and never as a rendered `$$…$$`. A block
of `kind` `math` is one display equation, with the environment the paper used
and the numbers it carries; `$…$` inside a paragraph is inline maths.

You do not have to find an anchor yourself: `litdb search` gives the anchor of
every block it matches, and `location` in its answer is the citation form. That
same string is a scope and a `litdb show` argument, so the address you just read
is the address you hand to the next command.

Read `figures/` for a figure. `figures_raw/` exists only so the conversion can
be redone; never read it, and never delete it.

## To answer a question

1. Read `literature/README.md`.
2. Select the papers that cover the subject.
3. Climb the ladder below on each paper, and stop at the rung that answers.

Do not read all chapters of a paper, and never read `paper.json` by hand: on a
long paper its chapter list alone fills a context window, and `litdb toc` says
the same thing bounded.

### Rung 1. Read the table of contents

```bash
litdb toc <slug>
```

It says what the paper is — title, authors, year, where it appeared, its
abstract — and then every chapter and section with an address and a word count.
Often that is the whole answer: a review organised by the axis you are asking
about is answered by its section titles, for the cost of one call.

Where a title bears on the question, open it:

```bash
litdb show <slug>/<stem>#<anchor>
```

**Where that section runs past about 1200 words, do not read it whole.** Search
inside it instead, with rung 2 scoped to it, and read the block that answers.

`--depth` bounds the listing on a long paper and `truncated_at_depth` says when
there is more. Go deeper one chapter at a time with
`litdb show <slug>/<stem> --anchors-only`.

### Rung 2. Search

```bash
litdb search "<a phrase of the question>" --scope <slug>/<stem>#<anchor>
litdb search "<a phrase of the question>" --scope <slug>
```

Scope it as narrowly as the question allows, and widen only when it answers
nothing. Exact first; `--approx` when you are unsure of the words the field
uses, which ranks the blocks in scope against your phrase rather than matching
it.

**An argument in a paper is not one block.** Prose runs into an equation and out
of it again, and each of those is addressed separately. Every result carries
`prev`, `next` and `parent`, so the way out of a block costs no second search:

| What you need | What you run |
|---|---|
| the blocks around a hit, when it reads as the middle of an argument | `litdb search "…" --context 2` |
| a run you can already see the ends of, from an `--anchors-only` listing | `litdb show <slug>/<stem>#p5..#p8` |
| the whole argument, when you cannot see its ends | `litdb show` on the `parent` anchor |

**Mathematics never matches a search.** An equation is stored as the TeX the
paper wrote, not as words, so a claim that rests on one is reached through
`--context` or a span and is never found directly.

### Rung 3. Read the chapter

When rungs 1 and 2 leave the question open and you have good reason the paper
holds the answer, read the chapter that the table of contents points at. That is
the last rung because it is the most expensive one.

## To trace a claim a paper borrowed

A paper states plenty it did not establish itself. Where it says so, it cites:

> The axial mass extracted from deuterium data is $1.03$ GeV
> [cite: bodek_2008_axial_mass_quasielastic].

The marker carries the tag, here `bodek_2008_axial_mass_quasielastic`.
**Do not open `references/<tag>.md`.** That page and `REFERENCES.md` are both
rendered for a person to read; `litdb lookup` is the one way you resolve a
citation, and it answers with more, from the store the two are rendered from.
Look the tag up before you repeat the claim as though the paper you are reading
had shown it:

```bash
litdb lookup bodek_2008_axial_mass_quasielastic
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
litdb lookup --search "quasielastic neutrino"   # title, author, journal
litdb lookup --doi 10.1103/physrevc.48.1246
litdb lookup --arxiv 1611.07770
litdb lookup --cited-by <slug>                  # everything a paper draws on
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
litdb search "<the words>" --scope <slug>
```

**Do not use `grep` for this.** A phrase copied out of a rendered chapter
carries the line break the reader's viewer put in it, and `grep` then gives no
match. Some files hold a NUL byte, and `grep` prints nothing for the whole file
— no error, and no "binary file matches". Both failures make text that is
present look absent. `litdb search` matches the phrase and the stored block
against each other in the same flat form, so neither can hide the other.

The answer gives `location`: the one address, which is what a report cites and
what opens the passage. Open it and read what stands around the quotation:

```bash
litdb show <location> --context 1
```

A paper can write a sentence as a condition, or give it to somebody else. Such a
sentence does not support the claim that you were about to make with it, and the
block either side is what tells you which it is.

**When a search returns nothing, suspect the search before you conclude
absence.** Read `partial_matches`: it names the longest shorter phrase the
papers do carry, which tells you the word the paper never wrote. Try fewer
words. Try the term the field uses for the same thing.

A hit in a paper you did not expect is a paper of another task. The collection
serves more than one question, and it keeps the papers of each. Such a hit is
evidence about that paper. It is not evidence about yours. Read it, and decide.

```bash
litdb search "axial mass" --scope <slug> <slug>   # your working set, in one call
litdb search "axial mass" --scope disk            # the whole collection
litdb search "M_A\s*=\s*1.03" --regex
```

Every command that reads the papers takes the same `--scope`, and a scope is the
citation form cut off wherever you like:

```
disk                            every paper the collection holds
<slug>                          one paper
<slug>/<stem>                   one chapter
<slug>/<stem>#<anchor>          one section, or one block
<slug>/<stem>#<from>..#<to>     a span of blocks
```

## To find a figure

```bash
litdb toc <slug> --all-anchors      # every figure, with its caption and anchor
litdb show <slug>#<fig-anchor>      # the caption, and the path to the image
```

Then `Read` the `path` the answer gives. Never build that path yourself.

Do not read the chapters to find a figure.

Each entry carries the figure's number, its anchor and the chapter stem where
the paper discusses it, so a figure a cross-reference names — `[ref: fig:xsec]`
— is the entry whose `label` is `fig:xsec`, numbered 3, or 3a and 3b when the
paper drew it as panels.

## To find a paper that is not there

1. Search the references first: `litdb lookup --search "<author or title word>"`.
   A paper the collection does not hold may still be cited by one that it does,
   and the answer gives you the arXiv identifier to fetch it by.
2. Search arXiv with the `find-papers` skill. It searches abstracts rather than
   titles, so it finds a paper on the subject of the question, and it marks the
   results the collection already holds. Use it when the question names a
   subject; `litdb lookup` above answers when you have a name or a title.
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
  someone else for a fact, resolve the tag with `litdb lookup` and cite that work.
  Citing the paper you happened to read for a result it borrowed puts a wrong
  attribution into the project's documentation.
- Never edit a rendered file — `README.md`, `REFERENCES.md`, `references/`,
  `INDEX.md` or anything under `chapters/`. Every one of them is written again
  from the store whenever a paper is added or `litdb render` runs, so an edit
  there is lost. Never edit `.references.jsonl` or `text/` either; both belong
  to `add-paper`.
- A claim that a paper does not hold something needs a search method that you
  can state. A `grep` that found nothing is not such a method: it fails silently
  on wrapped text and on a file with a NUL byte, and it never matches an
  equation. Search with `litdb search`, and say which phrases you searched for.
  Read `partial_matches`: it names the longest shorter phrase the papers do
  carry, which is the evidence for the word they never wrote.
- Give `litdb search` a scope. The collection serves more than one task and keeps
  the papers of each, so name the papers with `--scope <slug> <slug>` when the
  question is about your task, and `--scope disk` when it is about the
  collection itself. Read the `scope` block of the answer, and check that it
  holds the papers that you meant.
- Never answer from a citation alone. Its text and its tag both carry an author
  and a year, which is enough to look convincing and not enough to be right —
  they are identifiers, not citations. Resolve the tag with `litdb lookup`.
