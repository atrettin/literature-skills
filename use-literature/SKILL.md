---
name: use-literature
description: How to find and read physics knowledge in the local literature database in literature/. Use when a question is about neutrino-nucleus physics, generator models or experimental results that the code and docs/ do not answer.
---

# Read the literature database

`literature/` holds published papers as plain text. The text is split into
chapters. Read only the chapters that you need. A full paper fills your context
and gives you no more answers.

`literature/` is not tracked by git. A new clone has an empty directory.

## The structure

```
literature/
  README.md                     one row for each paper
  <slug>/                       one directory for each paper
    INDEX.md                    metadata, abstract, and a summary of each chapter
    chapters/NN_<title>.md      the text of one section
    chapters/NN-MM_<title>.md   one part of a long section
    figures/FIGURES.md          the caption of each figure
    figures/<figure files>      the images
```

The slug is `<first-author-surname>_<year>_<keyword>`.

Chapter files hold the words of the paper. Math stays as TeX. Citations become
`[cite: key]`. Cross-references become `[ref: label]`. A figure becomes one line
`[FIGURE: figures/<file> — <caption>]`.

## To answer a physics question

1. Read `literature/README.md`.
2. Select the papers that cover the subject.
3. Read `INDEX.md` of each selected paper.
4. Read only the chapter files whose summary matches the question.
5. Read one more chapter when a chapter points to it.

Do not read all chapters of a paper.

## To find a figure

1. Read or grep `literature/<slug>/figures/FIGURES.md`.
2. Find the caption that describes the thing that you want.
3. Read the image file with the `Read` tool.

Do not read the chapters to find a figure.

## To find a paper that is not there

1. Tell the user that the database has no paper on the subject.
2. Offer the `add-paper` skill.

## Rules

- Quote a few sentences at most. Give the source as
  `literature/<slug>/chapters/<file>.md`.
- The papers are copyrighted. Never copy a long passage into `docs/`, into a
  comment or into another tracked file. Write the fact in your own words.
- Never commit a file under `literature/`.
- A paper describes physics. A paper does not describe this codebase. Read the
  code, the cards or the generator output for what the framework does.
- Write a fact from the literature into `docs/` under the rules of the
  `docs-maintenance` skill. Cite the paper as `(Author year, arXiv:ID, §section)`.
