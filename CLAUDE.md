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
- A planning agent must add an instruction to work in a worktree, unless the
  user says otherwise. Work large enough to need a plan is large enough to need
  a worktree.
- A sub-agent cannot make its own worktree. Its launch fixes its working
  directory, thus `EnterWorktree` fails in it. The agent that launches must give
  the worktree. Pass `isolation: "worktree"` to the `Agent` tool, or make the
  worktree first and give its absolute path in the prompt:

  ```bash
  git worktree add .claude/worktrees/<name> -b worktree-<name>
  ```

  Then tell the agent that the worktree is there, and that it starts work in
  it. An instruction to call `EnterWorktree` costs the agent a failure and a
  workaround.
- A worktree sits at `.claude/worktrees/<name>`, and its branch is
  `worktree-<name>`. One name for both makes the branch of a worktree, and the
  worktree of a branch, plain to read in `git worktree list`.
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
- The arXiv API and the INSPIRE-HEP API both limit their rate. `rate_gate.py`
  holds every script to one request at a time, at the pace each API asks for,
  and it does so across processes. One `add_paper.py --auto` command therefore
  ingests a whole queue of papers. Do not call these APIs beside a running
  ingest, and do not spawn sub-agents that call them in parallel. A rate limit
  that you hit costs more time than the work that you tried to make parallel.

@./.claude/TODOS.md