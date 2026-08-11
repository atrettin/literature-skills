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
- Review implementation plans and agent instructions against the `asd-ste100`
  skill after you write them.
- A planning agent must add an instruction to work in a worktree, unless the
  user says otherwise. Work large enough to need a plan is large enough to need
  a worktree.
- When an agent starts to implement a plan, it must update the `TODO.md`. If
  the task being worked on is not yet in `TODO.md`, add it and mark it as being
  in progress.
- `README.md` documents the skills, their scripts and their commands. When you
  change something that `README.md` describes, update `README.md` in the same
  change.
- `TUNING.md` lists the parameters that decide how good an answer is. Such a
  parameter does not decide whether the answer is correct. A threshold, a limit,
  a weight, a word list and a choice of model are all of this kind. When you add
  one, add its row to `TUNING.md` in the same change. Say what the parameter
  does. Say what changes when its value moves. You choose the value by
  judgement, so write that. Never report a number as measured when nobody
  measured it. Something outside this repository fixes some numbers, such as the
  rate limit of an API. Put those in the last section of that file.
- The arXiv API and the INSPIRE-HEP API both limit their rate. Call them from
  one agent at a time. Do not spawn sub-agents that call these APIs in parallel,
  and do not ingest several papers at the same time. A rate limit that you hit
  costs more time than the work that you tried to make parallel.

@./.claude/TODOS.md