# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This repository develops Claude Code skills. The skills let an agent search
scientific literature, extract information from full text, and answer questions
with citations. A human reader must be able to audit every citation.

## Ethos

The skills render the literature into a format that both agents and humans can
browse well. The Markdown full text must render correctly in a KaTeX-based
previewer.

A citation must lead somewhere. A tag or a number that resolves to nothing is a
defect. A confident but wrong attribution is worse than no citation: mark what
you could not verify, and keep it visible.

## Rules

- **Never commit the literature.** Papers are copyrighted. Git ignores
  `literature/`, `*.pdf` and `*.eps`. Keep it that way.
- Download papers into `literature/` to test the skills. Git ignores the result.
- Use the Python environment in `.venv` to run code and to install packages.
- Do not use historical framing in documentation. State what is and why, not
  what was, what changed, or what a thing used to do.
- Review documentation against the `asd-ste100` skill when you write or update
  it.
- Review a plan against the `asd-ste100` skill after you write it.
- A planning agent must add an instruction to work in a worktree, unless the
  user says otherwise. Work large enough to need a plan is large enough to need
  a worktree.
- `README.md` documents the skills, their scripts and their commands. When you
  change something that `README.md` describes, update `README.md` in the same
  change.
- The arXiv API and the INSPIRE-HEP API both limit their rate. Call them from
  one agent at a time. Do not spawn sub-agents that call these APIs in parallel,
  and do not ingest several papers at the same time. A rate limit that you hit
  costs more time than the work that you tried to make parallel.
