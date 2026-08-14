---
name: init-literature
description: Starts an empty literature database, creating the collection directory with its index and making sure git ignores it. Use when a project has no literature/ directory yet and the user wants to begin collecting papers.
---

# Start a literature collection

This skill creates an empty collection for a project that has none. Papers go in
afterwards with the `add-paper` skill.

## Step 0. Find where the collection goes

The collection is at `$LITERATURE_ROOT` when that variable is set. If it is not
set, it is `literature/` in the project.

One collection can serve many projects, and that is what the variable is for: a
paper costs a download and a conversion, and paying that a second time in the
next project buys nothing. Every path below means the collection's directory,
wherever it is.

## Step 1. Refuse if one already exists

If the directory is present, stop. Tell the user that the collection exists and
how many papers are in it. Do not overwrite its `README.md` — it is the index of
papers already collected, and rewriting it loses every row.

## Step 2. Ask what the collection covers

The index opens with one sentence saying what subject the collection is for.
Infer it from the project — its README, its `CLAUDE.md`, the code — and ask the
user if that leaves it unclear. A collection for a neutrino event generator says
something different from one for a protein-folding pipeline.

## Step 3. Make git ignore the directory

**Do this before writing any files, and do not skip it.** The papers are
copyrighted. If they reach a remote, the user has published someone else's work
under their own account — that is their personal legal exposure, not an abstract
policy. A collection that is not ignored will be committed sooner or later.

1. Check for a repository. Ask about the collection's own directory, and not
   about the project: a shared collection outside the project can sit in a
   repository of its own, or in none.

   ```bash
   git -C <the collection's parent directory> rev-parse --is-inside-work-tree
   ```

2. **If it is a repository**, find the root and test whether the path is covered
   already — this respects patterns that are there and the user's global ignore
   file, so a project that is already safe gets no duplicate rule:

   ```bash
   git -C <the collection's parent directory> rev-parse --show-toplevel
   git check-ignore -q <the collection's path> && echo ignored || echo "NOT ignored"
   ```

   When it is not ignored, append to the `.gitignore` at that repository's root
   the collection's path, relative to that root, with a `/` at the end:

   ```
   # Literature. The papers are copyrighted and must never be committed or
   # pushed to a remote.
   literature/
   ```

   Then confirm with `git check-ignore -q <the collection's path>`.

3. **If it is not a repository**, carry on. Tell the user plainly that no
   repository can commit the collection where it is, and that the copyright
   still holds: they must not publish the papers by any other means either. If
   they run `git init` there later, they must ignore the collection first.

Tell the user what you did either way, and why: the papers are under copyright,
pushing them to a remote distributes them, and the liability is theirs. One or
two sentences — state it as a fact they need, not as a warning to be dismissed.

## Step 4. Write the directory and its index

Create the collection's directory and write its `README.md`:

~~~markdown
# Literature

<One sentence on what this collection covers, from step 2.> A paper is **stored**
once and **rendered** for a person to read. Each paper has its own directory:

```
<first-author-surname>_<year>_<keyword>/
  paper.json          what the paper is: metadata, and one entry per chapter
  text/               the words, one JSON block per line, one file per section
  figures/            the figures, cropped, one PNG each
  figures_raw/        the files as the paper shipped them
  INDEX.md            rendered: metadata, abstract, one row for each chapter
  chapters/           rendered: the same words, for a person to read
  figures/FIGURES.md  rendered: the caption of each figure
```

Start at `INDEX.md` of a paper. Read only the chapters that you need.

Everything rendered is written from what is stored, in one flavor at a time —
`vscode` or `obsidian` — recorded in `.collection.json`. `lit render --flavor
<name>` writes the collection again in the other one. Nothing is lost: the store
is untouched. Never edit a rendered file; the next render overwrites it.

A citation is stored as `[cite: <tag>]` and rendered as `(Lipari, 2002)`, which
opens that work's page under `references/`, named after the work's tag. Agents
resolve that tag with `lit lookup`, which reads `.references.jsonl` and answers
with the title, authors, journal, DOI and arXiv identifier. That is how a claim
a paper borrowed gets traced back to whoever established it.

[REFERENCES.md](REFERENCES.md) is the same data as one table, most-cited first:
what these papers are built on, and which of it is already held here. It and
`references/` are both for reading, and both are rendered from
`.references.jsonl` — never edit either by hand.

Agents: use the `use-literature` skill to read a paper, and the `add-paper`
skill to add one.

This directory is **not tracked by git**. The papers are copyrighted, so their
text must not go to a remote. Never commit a file of this collection.

## Papers

| Title | Authors | Year | Journal | What it is about |
|---|---|---|---|---|
~~~

Leave the table empty, with only its header. `add-paper` adds a row per paper,
in order of the year, newest last. Year is the year of the arXiv submission, the
same one the directory name uses. Journal is where the paper was published, and
`—` while the paper is still a preprint.

Then write the empty reference index, so the collection has one from the start:

```bash
lit references --render-only
```

That creates `REFERENCES.md` and an empty `references/` in the collection from
an empty store. Give `--literature-root` when `$LITERATURE_ROOT` is not set and
the collection is not `literature/` in the project. Skip this step when `lit` is not
installed: `lit add-paper` writes both itself the first time it files a
paper's references.

## Step 5. Say what comes next

Tell the user the collection is ready and that `add-paper` fills it, given a
title, an author or an arXiv ID. Mention that `add-paper` needs `TexSoup` and
`Pillow` in the project's Python environment, and `gs` and `rsvg-convert` on
`PATH` for the figures — but do not install anything now.

## Rules

- Never create the collection without settling step 3 first.
- Never write a paper into the collection here. That is `add-paper`'s work.
- Never add the collection to version control, and never suggest a way to
  distribute its contents.
