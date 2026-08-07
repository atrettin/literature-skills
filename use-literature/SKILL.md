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

## The structure

```
literature/
  README.md                     one row for each paper
  <slug>/                       one directory for each paper
    INDEX.md                    metadata, abstract, and a summary of each chapter
    chapters/NN_<title>.md      the text of one section
    chapters/NN-MM_<title>.md   one part of a long section
    figures/FIGURES.md          the caption of each figure
    figures/<name>.png          the figures, cropped, one PNG each
    figures_raw/                the files as the paper shipped them
```

The slug is `<first-author-surname>_<year>_<keyword>`.

Chapter files hold the words of the paper. Citations become `[cite: key]` and
cross-references become `[ref: label]`. Inline maths stays as `$…$` and display
maths as `$$…$$`, so a Markdown preview renders it. A figure is embedded as a
centred `<img>` pointing at `../figures/<name>.png`, followed by a line starting
`**Figure.**` that carries its caption.

Read `figures/` for a figure. `figures_raw/` exists only so the conversion can
be redone; never read it, and never delete it.

## To answer a question

1. Read `literature/README.md`.
2. Select the papers that cover the subject.
3. Read `INDEX.md` of each selected paper.
4. Read only the chapter files whose summary matches the question.
5. Read one more chapter when a chapter points to it.

Do not read all chapters of a paper.

## To find a figure

1. Read or grep `literature/<slug>/figures/FIGURES.md`.
2. Find the caption that describes the thing that you want.
3. Read the PNG in `figures/` with the `Read` tool.

Do not read the chapters to find a figure.

## To find a paper that is not there

1. Tell the user that the database has no paper on the subject.
2. Offer the `add-paper` skill.

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
  paper as `(Author year, arXiv:ID, §section)`.
