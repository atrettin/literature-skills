---
name: init-literature
description: Starts an empty literature database in the current project, creating literature/ with its index and making sure git ignores it. Use when a project has no literature/ directory yet and the user wants to begin collecting papers.
---

# Start a literature collection

This skill creates an empty `literature/` for a project that has none. Papers go
in afterwards with the `add-paper` skill.

## Step 1. Refuse if one already exists

If `literature/` is present, stop. Tell the user that the project already has a
collection and how many papers are in it. Do not overwrite `README.md` — it is
the index of papers already collected, and rewriting it destroys their
summaries.

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

1. Check for a repository:

   ```bash
   git rev-parse --is-inside-work-tree
   ```

2. **If it is a repository**, find the root and test whether the path is covered
   already — this respects patterns that are there and the user's global ignore
   file, so a project that is already safe gets no duplicate rule:

   ```bash
   git rev-parse --show-toplevel
   git check-ignore -q literature/ && echo ignored || echo "NOT ignored"
   ```

   When it is not ignored, append to the `.gitignore` at the repository root:

   ```
   # Literature. The papers are copyrighted and must never be committed or
   # pushed to a remote.
   literature/
   ```

   Then confirm with `git check-ignore -q literature/`.

3. **If it is not a repository**, carry on, but tell the user plainly that
   nothing protects the directory yet and that they must ignore `literature/`
   before they run `git init` and commit.

Tell the user what you did either way, and why: the papers are under copyright,
pushing them to a remote distributes them, and the liability is theirs. One or
two sentences — state it as a fact they need, not as a warning to be dismissed.

## Step 4. Write the directory and its index

Create `literature/` and write `literature/README.md`:

~~~markdown
# Literature

<One sentence on what this collection covers, from step 2.> Papers are stored as
plain text for humans and agents to read. Each paper has its own directory:

```
<first-author-surname>_<year>_<keyword>/
  INDEX.md            metadata, abstract, and a summary of each chapter
  chapters/           the text of the paper, one file for each section
  figures/            the figures, cropped, one PNG each
  figures/FIGURES.md  the caption of each figure
  figures_raw/        the files as the paper shipped them
```

Start at `INDEX.md` of a paper. Read only the chapters that you need.

Agents: use the `use-literature` skill to read a paper, and the `add-paper`
skill to add one.

This directory is **not tracked by git**. The papers are copyrighted, so their
text must not go to a remote. Never commit a file under `literature/`.

## Papers

| Title | Authors | Year | What it is about |
|---|---|---|---|
~~~

Leave the table empty, with only its header. `add-paper` adds a row per paper,
in order of the year, newest last.

## Step 5. Say what comes next

Tell the user the collection is ready and that `add-paper` fills it, given a
title, an author or an arXiv ID. Mention that `add-paper` needs `TexSoup` and
`Pillow` in the project's Python environment, and `gs` and `rsvg-convert` on
`PATH` for the figures — but do not install anything now.

## Rules

- Never create `literature/` without settling step 3 first.
- Never write a paper into the collection here. That is `add-paper`'s work.
- Never add the collection to version control, and never suggest a way to
  distribute its contents.
