---
name: research-report
description: Answers a task that needs a review of the scientific literature, and writes a report in which each claim links to the chapter that it came from. Use for "research X and write a report", "survey the literature on X", "check the claims in this file against the literature", or any task whose result is a report with citations.
---

# Research a task and report with citations

This skill answers a task from the published literature. It searches, it reads,
it judges what is still missing, and it searches again. It stops when the task
is answered, and then it writes a report.

The loop is the point. The first papers that a search finds are approximate
matches. You learn from them what you should have searched for. You also learn
which papers they cite, and which papers cite them.

Two things must both be true at the end:

1. The report answers the task, and it is honest about what the literature does
   not settle.
2. A reader can audit each claim. Each citation opens the chapter that the claim
   came from.

## What this skill produces

| File | What it holds |
|---|---|
| `reports/<task-slug>.md` | the report. |
| `reports/<task-slug>.research-log.md` | the record of the search that made it. |

Write both to `reports/` in the project, unless the task gives a different path.
Both are your own words and your own links. You can commit them. Never commit a
file below the literature root.

## Before you start

Four shorthands are used below. The `add-paper` skill prints its own base
directory when it loads; its `scripts/` directory holds each script.

- **`$PY`** — the project's Python. Use `.venv/bin/python` when the project has
  a virtual environment. If it does not, use `python3`.
- **`$LOOKUP`** — `<add-paper>/scripts/reference_lookup.py`
- **`$CITE`** — `<add-paper>/scripts/inspire_citations.py`
- **`$AUDIT`** — `<add-paper>/scripts/check_report.py`

**Find the collection first.** It is at `$LITERATURE_ROOT` when that variable is
set. If it is not set, it is `literature/` in the project. If neither is there,
run `init-literature` before you search. Write the path down: the header of the
report and each link in it depend on it.

**Delegate the heavy reading.** Your own context is the limit on this work, and
the full text of a paper is large. Two agents keep that text out of it:

| Agent | What it does |
|---|---|
| `paper-ingestor` | ingests one paper. Start one at a time. It reports the slug and the warnings, and no paper text. |
| `paper-scout` | reads one paper that is on disk against your sub-questions. It reports the locations that answer them. It uses no API, thus several can run at the same time. |

If the environment cannot start an agent, do the same work yourself: ingest with
`add-paper`, read with `use-literature`. The workflow does not change. It only
costs more of your context.

## Step 0. Frame the task, before you search

Open the research log and write these three things:

1. The task, in one sentence.
2. The task, divided into numbered sub-questions: **SQ1**, **SQ2**, and so on.
3. For each sub-question, what an answer to it would look like.

Each kind of task divides:

| The task | The sub-questions |
|---|---|
| A question | one for each part of the question that the literature must settle. |
| "Check the claims in this file" | one for each claim. Quote the claim in the log. |
| "List the models that X uses, by energy range" | one for each class of model, and one more for the completeness of the list. |

**This list is the contract.** Step 4 judges the work against it, and not
against your memory of the task. You can add a sub-question that the reading
uncovers. Never delete one without a line in the log that says why.

## The loop

These limits hold for the whole task:

| Limit | Value |
|---|---|
| `MAX_ITERATIONS` | 4 |
| `MAX_NEW_PAPERS_PER_ITERATION` | 5 |
| `MAX_TOTAL_INGESTS` | 20 |
| `DRY_ITERATIONS` | 2 |
| `MAX_PARALLEL_SCOUTS` | 4 |

### Step 1. Plan the iteration

Choose the open sub-questions to work on. Choose a search or a citation lookup
from the table in "How to refine". Write the choice and the reason in the log
**before** you act.

### Step 2. Search

Search the collection first with `use-literature`. That costs nothing. Then
search arXiv with `find-papers`. Run one search at a time.

Write in the log: the exact `--topic` phrase, `ranking.backend`, the counts, and
the best candidates with their `missing_terms`.

### Step 3. Ingest and read

**Ingest** at most `MAX_NEW_PAPERS_PER_ITERATION` new papers, and at most
`MAX_TOTAL_INGESTS` in the whole task. Start one `paper-ingestor` agent for each
paper, **one agent at a time**. Give it the arXiv identifier. Write one line in
the log for each: which sub-question needs this paper. A paper that the
collection holds already needs no ingest and counts against no limit.

**Read in two tiers.** The tier depends on how much you must read:

| What you have | What you do |
|---|---|
| One paper, and its `INDEX.md` names the chapter you need | Read that chapter yourself, as `use-literature` says. |
| Several papers, or an `INDEX.md` that does not settle it | Start one `paper-scout` agent for each paper. Give it the slug and the open sub-questions. Run at most `MAX_PARALLEL_SCOUTS` at one time. |

A chapter summary in `INDEX.md` says what the chapter covers. Nobody knew your
sub-questions when they wrote it, thus it can miss the paragraph that answers
one. That is what a scout is for: it reads the whole paper against the questions
that you have.

**Verify before you cite.** A scout report tells you where to look. It is not a
source. Open the chapter at the anchor that the scout names. Check that the text
there supports the claim. Then write the finding in the log:

```
SQ2: <the claim, in one sentence> — <slug>/chapters/03_results.md#sec-axialff
```

A finding with no chapter and no anchor is not a finding.

### Step 4. Assess

Read the sub-questions **from the log**, and not from memory. Mark each one:

| Mark | What it means |
|---|---|
| answered | a finding supports it, and you read the text at the link yourself. |
| partial | the literature answers a part of it. |
| open | you have no finding for it yet. |
| closed-negative | you searched for it in several ways, and the literature does not answer it, or the papers disagree. |

A closed-negative sub-question is an answer. It goes in the report.

Three things answer nothing. Say so each time:

- An abstract. You read 400 characters, and that is a choice of paper, not a source.
- A `verified: false` record. The citing paper made that attribution, and no
  lookup confirmed it.
- Your own memory of the field. Only the text at the link counts.

### Step 5. Decide

| The state | What you do |
|---|---|
| Each sub-question is answered or closed-negative | Stop. Write the report. |
| You used `MAX_ITERATIONS`, or `MAX_TOTAL_INGESTS` | Stop. Write the report. Put the limit in "Limitations". |
| The last `DRY_ITERATIONS` iterations found no new relevant paper | Stop. Write the report. Say that the search stopped finding papers. |
| Anything else | Write the refinement and the reason in the log. Go to step 1. |

**Never present a limit as an exhausted subject.** They are different, and the
reader must know which one stopped you.

## How to refine

| What the last iteration showed | The next move |
|---|---|
| The papers use a term that your query did not have | Search again with the words of the papers. Your first query used the words of the person who asked. |
| A paper you read cites the claim that a sub-question needs | Backward: `$PY $LOOKUP <tag>`. It costs nothing. Ingest the source only when the claim must be read at the source. |
| The best paper is old, or the sub-question asks for the state of the art | Forward: `$PY $CITE <arxiv-id> --direction citing --sort mostrecent` |
| The sub-question needs the accepted treatment | Forward: `$PY $CITE <arxiv-id> --direction citing --sort mostcited` |
| A sub-question is about a subject that no paper you read reaches | A new search, with a narrower phrase. This is the one case where a search beats the citation graph. |
| Each result is broad and shallow | Divide the sub-question in two. Work on the halves. |

## The research log

Write one entry for each iteration, in this shape:

```markdown
## Iteration <n> — <date>

### Plan
<the open sub-questions, the move, and why>

### Actions
- search: topic="…" backend=… counts={held:…, cited:…, new:…}
- cite:   <arxiv-id> direction=… sort=… returned=… of …
- ingest: <slug> — because <sub-question>
- scout:  <slug> for SQ2, SQ3
- read:   <slug>/chapters/03_results.md

### Findings
- SQ2: <the claim> — <slug>/chapters/03_results.md#sec-axialff

### Assessment
SQ1 answered · SQ2 partial · SQ3 open · SQ4 closed-negative (searched: "…", "…")

### Decision
<continue, with the refinement and the reason | stop, with the reason>
```

Two rules hold the log together:

- **Write it as the iteration runs.** A log that you write at the end is a
  memory of the work. Step 4 must not judge the work by memory.
- **Add to it. Do not edit it.** An assessment that a later iteration disproves
  gets a new entry. The old one stays.

## Write the report

Write it in the form of a scientific paper:

| Section | What goes in it |
|---|---|
| Title | the task, as a statement. |
| Header | `**Literature root:** <path>` and the date. |
| Summary | one paragraph. The findings, and not the process. |
| Body | one section for each sub-question or subject. Each claim carries a citation. |
| Limitations of this search | see below. It is not optional. |
| References | one entry for each work you cite. |

**"Limitations of this search" must hold each of these that is true:**

- the sub-questions that you closed as negative, and how you searched for them;
- a limit that stopped the loop, and which limit it was;
- the searches that you planned and did not run;
- the papers that you found and did not ingest;
- each claim that rests on a `verified: false` record.

**Give the reader a nuanced answer.** Where the papers disagree, say that they
disagree, and say which paper says what. Where one measurement carries the
weight, say so. A confident answer that the literature does not support is the
failure that this whole skill exists to prevent.

**Write your own words.** Quote a few sentences at most, and mark each quotation.

## How to cite

**Each link is relative to the report.** Compute the path from `reports/` to the
literature root, whether the root is in the project or outside it. A relative
path opens in each Markdown viewer and the auditor can check it. An absolute
path works on one machine only.

| What you cite | The form |
|---|---|
| A paper you read | `(Katori 2018, J.Phys.G 45 (2018) 013001, [§2.3](../literature/katori_2018_neutrino_nucleus/chapters/03_model.md#sec-form-factors))` |
| A work you traced but did not read in full | `([Bodek et al., 2008](../literature/references/bodek_2008_axial_mass_quasielastic.md))` |
| A work that no lookup confirmed | the same, and write "the citing paper attributes this to …", and keep the ⚠ in the entry for it. |

Put several works in one pair of brackets, separated by `;`.

**Never link a chapter that you did not open.** The link is a statement that
you read the text there.

The `## References` section holds one entry for each work. **Which page an entry
opens depends on whether the collection holds the paper:**

| The work | The entry opens |
|---|---|
| A paper the collection holds | its `INDEX.md`. |
| A work that a paper here cites, and the collection does not hold | its page under `references/`. |

A page under `references/` exists for a work that a paper of the collection
cites. A paper that the collection holds and that nothing here cites has no such
page, and an entry that links one is a dead link. Its `INDEX.md` is the page
that names it, and it is the better page: it carries the abstract and each
chapter.

```markdown
- **<slug>** — Authors (year). *Title*. Journal.
  [paper](../literature/<slug>/INDEX.md) ·
  [arXiv](https://arxiv.org/abs/<id>) ·
  read: [§2](../literature/<slug>/chapters/02_introduction.md#sec-introduction)
- **<tag>** — Authors (year). *Title*. Journal.
  [record](../literature/references/<tag>.md) ·
  [arXiv](https://arxiv.org/abs/<id>)
```

Each work that the body cites goes here. Each work that is here must be cited in
the body. Mark a work that no lookup confirmed with ⚠, and write one sentence
that says what that means.

## Step 6. Audit the report

```bash
$PY $AUDIT reports/<task-slug>.md
```

It checks five things:

1. Each link opens a file that exists.
2. Each anchor is in the file that the link names.
3. Each tag has a record in the store.
4. The body and the references name the same works.
5. Each unconfirmed work carries its mark.

**The report is not finished until `"ok": true`.** Correct what it reports and
run it again.

Then tell the user:

- the answer, in short;
- how many iterations and how many ingests it took, from the log;
- what "Limitations" says;
- the result of the audit.

## Rules

- **One agent talks to arXiv and INSPIRE.** Start one `paper-ingestor` at a
  time. Never run two searches at the same time. A scout uses no API, thus
  several scouts can run together.
- **Keep the full text out of your context.** Read `INDEX.md` files, the reports
  of the agents, the JSON of the scripts, and the chapters that you cite.
  Never read a paper from beginning to end yourself. That is what a scout does.
- **Cite only what you read.** Not an abstract. Not a summary. Not a quotation
  from a scout that you did not verify at the anchor.
- **Report the limit that stopped you.** A budget is not an answer.
- **Never commit a file below the literature root.** The papers are copyrighted.
