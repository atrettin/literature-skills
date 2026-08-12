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

Seven shorthands are used below. The `add-paper` skill prints its own base
directory when it loads; its `scripts/` directory holds each script.

- **`$PY`** — the project's Python. Use `.venv/bin/python` when the project has
  a virtual environment. If it does not, use `python3`.
- **`$LOOKUP`** — `<add-paper>/scripts/reference_lookup.py`
- **`$CITE`** — `<add-paper>/scripts/inspire_citations.py`
- **`$SEARCH`** — `<add-paper>/scripts/search_literature.py`
- **`$SCAN`** — `<add-paper>/scripts/terminology_scan.py`
- **`$OVERLAP`** — `<add-paper>/scripts/collection_overlap.py`
- **`$AUDIT`** — `<add-paper>/scripts/check_report.py`

**Find the collection first.** It is at `$LITERATURE_ROOT` when that variable is
set. If it is not set, it is `literature/` in the project. If neither is there,
run `init-literature` before you search. Write the path down: the header of the
report and each link in it depend on it.

**Delegate the heavy reading.** Your own context is the limit on this work, and
the full text of a paper is large. Three agents keep that text out of it:

| Agent | What it does |
|---|---|
| `paper-ingestor` | handles an exception of the ingest script for one paper. It reports the slug and the warnings, and no paper text. |
| `paper-scout` | reads one paper that is on disk against your sub-questions. It reports the locations that answer them. It uses no API, thus several can run at the same time. |
| `terminology-scout` | says how one term of the literature relates to your subject. It uses no API, thus several can run at the same time. |
| `terminology-prospector` | reads one paper in full for the names it uses for your subject. It uses no API, thus several can run at the same time. A gate decides when it runs, because it reads a whole paper. |

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

**Open the working set.** The working set is the list of papers of the
collection that bear on this question. It starts empty. Write it in the log
under `## Working set`, and add to it as the task runs.

A paper enters the working set in one of two ways:

| How | When |
|---|---|
| You ingested it for this task | at the ingest, with the sub-question that needed it |
| The collection held it, and you read text in it that bears on a sub-question | at the read, and never at the search |

A paper that a search reports as held does **not** enter the set. A held paper
enters when you read it and the text bears on a sub-question. The collection
holds papers from other tasks, thus "held" says nothing about this question.

**Give the working set to every tool that reads more than one paper.** A tool of
that kind takes its scope as a flag that you repeat for each paper. The working
set is that scope:

| Tool | How you pass the set |
|---|---|
| `$SEARCH` | `--paper <slug>` for each paper of the set, when you verify a claim of this task |
| `$SCAN` | `--in-text <slug>` and `--cited-by <slug>` for each paper of the set, when you look for the other names of your subject |
| `$OVERLAP` | `--scope <slug>` for each paper of the set, when you weigh a candidate against what you hold |

A tool that you run over the whole collection answers a question about the
collection. It does not answer a question about your task.

## The loop

These limits hold for the whole task:

| Limit | Value |
|---|---|
| `MAX_ITERATIONS` | 4 |
| `MAX_NEW_PAPERS_PER_ITERATION` | 5 |
| `MAX_TOTAL_INGESTS` | 20 |
| `DRY_ITERATIONS` | 2 |
| `MAX_PARALLEL_SCOUTS` | 4 |
| `CURRENCY_GRACE_MONTHS` | 12 |
| `MAX_TERMINOLOGY_SCOUTS` | 3 |
| `FIRST_PROSPECT_ITERATION` | 2 |
| `MAX_PROSPECTORS` | 2 |
| `MAX_PROPOSED_TERMS` | 6 |

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
`MAX_TOTAL_INGESTS` in the whole task. A paper that the collection holds already
needs no ingest, and it counts against no limit. Pass a queue of identifiers to
one command:

```bash
$PY <add-paper>/scripts/add_paper.py --auto <arxiv-id> [<arxiv-id> …]
```

The script sends one request at a time by itself, thus one command ingests the
whole queue. It prints one JSON report per paper, as one object per line. It
exits 2 when any paper raised an exception.

**Start a `paper-ingestor` agent only for a paper whose report carries an
`exception`.** Give that agent the identifier of that paper. The exception is
the one part of an ingest that needs judgement.

**When more candidates look worth an ingest than the iteration budget allows,
weigh them against what you already hold.** A rank says how well an abstract
answers the question. It does not say whether the candidate builds on the same
works as the papers of your working set, and the reference store does say that.

1. Run `$PY $OVERLAP <arxiv-id> --scope <slug> …` on each candidate. Run one
   check at a time: it asks INSPIRE, and INSPIRE limits its rate. Give
   `--scope <slug>` for each paper of your working set, out of the `## Working
   set` table of the log. Never `--all-papers`: the collection serves other
   questions, and their papers would decide your band.
2. Read `outside_scope` first. A paper there is on disk, and it costs no ingest.
   Read it, and add it to the working set when its text bears on a sub-question.
3. Ingest the candidate with the lowest overlap first. It brings the most ground
   you do not hold.
4. Ignore point 3 when the question needs the words of one specific paper. A
   high overlap can also mean that the candidate is the best answer there is.

Write the number in the log beside the choice it decided, and write the scope you
gave beside it. A band with no scope beside it cannot be checked later.

**Order the queue by value, and read while it runs.** Put the paper that answers
the most open sub-questions first. Then run the queue in two commands:

1. Ingest the first paper alone, and wait for its report.
2. Start the command for the rest of the queue in the background.
3. While it runs, read the paper of point 1: open its chapters yourself, or
   start `paper-scout` agents on it.
4. When that command reports, read the papers it ingested the same way.

Write one line in the log for each paper: which sub-question needs it. Each
paper that you ingest enters the working set, with that sub-question.

**One request at a time is the rule. One agent at a time is not the rule.** The
limit belongs to arXiv and to INSPIRE. A scout reads files on disk, and your own
reading opens files on disk. Neither one sends a request.

| Beside a running ingest | Permitted |
|---|---|
| a `paper-scout`, or a `terminology-prospector`, on a paper that is on disk | yes |
| your own read of a chapter | yes |
| `$PY $LOOKUP <tag>`, which reads the local store | yes |
| `$PY $SEARCH "<phrase>"`, which reads the chapters on disk | yes |
| a second `add_paper.py --auto` command, or a `paper-ingestor` | **no** |
| a `find-papers` search | **no** |
| `$PY $CITE …`, which asks INSPIRE | **no** |
| `$PY $OVERLAP …`, which asks INSPIRE | **no** |

**Read a paper only after the command that ingests it reports.** The chapters
are incomplete until then, and a scout that starts early reads a part of the
paper.

**Read in two tiers.** The tier depends on how much you must read:

| What you have | What you do |
|---|---|
| One paper, and its `INDEX.md` names the chapter you need | Read that chapter yourself, as `use-literature` says. |
| Several papers, or an `INDEX.md` that does not settle it | Start one `paper-scout` agent for each paper. Give it the slug and the open sub-questions. Run at most `MAX_PARALLEL_SCOUTS` at one time. |

A paper that the collection held enters the working set here, and not at the
search: it enters when you read text in it that bears on a sub-question.

Expect `INDEX.md` to settle it rarely. Its `What it covers` column holds `—`
until somebody runs the summary pass, so what usually names a chapter for you is
its title, the subsection titles and the word count. A summary that somebody did
write was written before anybody had your sub-questions, thus it too can miss
the paragraph that answers one. That is what a scout is for: it reads the whole
paper against the questions that you have.

**Verify before you cite.** A scout report tells you where to look. It is not a
source. Each location it gives carries a line number, as
`chapters/03_results.md:181`. Read the chapter at that line with the `offset`
option of `Read`, and compare the words there with the quotation.

When the words are not at that line, do not conclude that the scout invented
them. Find them instead:

```bash
$PY $SEARCH "<the words the scout quoted>" --paper <slug>
```

**Never search for a quotation with `grep`.** The text wraps, thus `grep` misses
a phrase that a line break splits. `grep` also prints nothing for a file that
holds a NUL byte. A quotation that neither the line nor the search can place is
not verified, whatever the scout wrote. Then write the finding in the log:

```
SQ2: <the claim, in one sentence> — <slug>/chapters/03_results.md#sec-axialff
```

A finding with no chapter and no anchor is not a finding. The finding and the
report both carry the anchor, and not the line. The line addresses the file on
disk. The anchor addresses the section.

**Discard a quotation that carries no line number.** Do not read the chapter to
rescue it. Do not cite it. Ask the scout again for that sub-question, or drop the
location. The scout has the file open, thus a missing line number means that the
scout did not read the text that it quoted.

When the text at the line does not hold the quotation, do not conclude that the
scout invented it. Read 20 lines around the number first. Plain `grep` gives a
false negative on these files. The text wraps across lines, and some chapters
hold a NUL byte.

### Step 4. Assess

Read the sub-questions **from the log**, and not from memory. Mark each one:

| Mark | What it means |
|---|---|
| answered | a finding supports it, and you read the text at the link yourself. |
| partial | the literature answers a part of it. |
| open | you have no finding for it yet. |
| closed-negative | you searched for it in several ways, and the literature does not answer it, or the papers disagree. |

A closed-negative sub-question is an answer. It goes in the report.

**A sub-question is not answered until you look for later work.** This holds for
the mark `answered`, and for that mark alone. A `partial` sub-question stays in
the loop, and a `closed-negative` one leans on no paper.

Name the paper that supplies the answer. Remove that paper's text, and the
answer goes with it. Ask INSPIRE which papers cite that paper, newest first:

```bash
$PY $CITE <arxiv-id> --direction citing --sort mostrecent
```

Read the titles and the summaries, and act:

| What the result shows | What you do |
|---|---|
| no later paper that bears on the sub-question | Mark it answered. |
| a later paper that supports the answer | Mark it answered. Ingest that paper when the report needs its text. |
| a later paper that can change the answer | The sub-question stays open. Ingest that paper in the next iteration, and read it before you mark the sub-question again. |

One search covers each sub-question that leans on that paper. A sub-question
that leans on two papers needs a search on each of the two.

**One exemption.** A paper whose preprint is younger than
`CURRENCY_GRACE_MONTHS` needs no search. A paper of that age has few citers, and
the request answers nothing. Log the exemption in the same place as a search
that ran.

**Write each search in the log, under `### Currency checks`.** A mark of
`answered` beside no entry there is a defect, and the reader can see it.

Three things answer nothing. Say so each time:

- An abstract. You read 400 characters, and that is a choice of paper, not a source.
- A `verified: false` record. The citing paper made that attribution, and no
  lookup confirmed it.
- Your own memory of the field. Only the text at the link counts.

### Step 4b. Find the other names of the subject

**Run this after iteration 1. It is required.** Your query holds the words of
the person who asked. The papers hold the words of the field, and the two are
often different words for one area. `missing_terms` cannot tell you this. It
names the terms of your query that a paper lacks. It never names the terms of
the papers that your query lacks.

**Scope it to the working set.** Give one `--in-text` and one `--cited-by` for
each paper in your working set, and no more:

```bash
$PY $SCAN --topic "<your topic phrase>" \
          --in-text <slug> --cited-by <slug> \
          --in-text <slug> --cited-by <slug>
```

The collection is persistent. It holds the papers of tasks that came before
yours, and their words carry the vocabulary of other subjects. A scan of the
whole store thus offers you the other names of somebody else's question. The
script refuses to run without a scope for that reason. Never use `--all-papers`
here: it answers a question about the collection, and not about your task.

Check the `scope` block of the report. Its `papers` list must equal your working
set. When it does not, you passed the wrong slugs.

The scan reads two things, and it calls no API. `--in-text` reads the papers
themselves: their titles, abstracts, headings, captions and paragraphs.
`--cited-by` reads the titles of the works they cite. It reports the terms that
your topic does not hold, and a word your topic holds already lowers a term
rather than lifting it — the names worth finding are the ones your query could
not have reached.

**Read `stated_aliases` first.** Those entries are the places where an author
writes your subject beside another name, with the cue that joins them and the
sentence that says it:

```
"…the existence of right-handed (sterile) neutrinos or heavy neutral leptons"
```

Each one arrives with its chapter and anchor, so a term from that block is a
claim you can open. Take your scouts from there before you take them from the
ranked `terms` list.

Then read `terms`. Each one is in one of three states:

| The term | What you do |
|---|---|
| You know it, and it names your subject | Add it to the topic phrase of the next search. |
| You know it, and it names something else | Ignore it. Write one line in the log that says so. |
| You do not know how it relates to your subject | Give it to a `terminology-scout` agent. |

Start at most `MAX_TERMINOLOGY_SCOUTS` `terminology-scout` agents. Give each one
the subject and one term. A scout calls no API, thus several run at the same
time. Each one answers with a table: the term, where the papers use it, whether
it names the same object, and how it differs.

**Never treat a term as a synonym.** A scout answers `narrower`, `wider` or
`related` more often than `yes`. That distinction is the finding. A search for a
narrower term finds papers about a part of your subject, and the report must say
which part. Write the table in the log, under `### Terminology`.

A later iteration can run the scan again. Iteration 1 must run it.

#### When the scan finds nothing, and a question is still open

The scan matches strings. A name can carry none that it can match: an acronym a
paper defines once, a symbol that stands for the object, or a name a paper uses
throughout one section and never joins to your subject in one sentence. A
`terminology-prospector` reads a whole paper and reports the names it uses. That
costs about 25k tokens per paper, which is what a `paper-scout` costs, so a gate
decides when you spend it.

| The iteration | What runs |
|---|---|
| 1 | the scan alone. No prospector, whatever the scan found. |
| `FIRST_PROSPECT_ITERATION` and later | the scan again, and a prospector **only** when both conditions below hold. |

Both must hold:

1. **The scan gave you nothing usable.** No term of the last scan entered your
   topic phrase — either it reported none, or every `terminology-scout` you fed
   answered `related` or `unclear`.
2. **A sub-question is still open**, and no paper of your working set answers it.

When either fails, run the scan and stop there.

When both hold, start at most `MAX_PROSPECTORS` `terminology-prospector` agents.
Choose the papers for their vocabulary and not for the sub-question: prefer the
longest paper of the working set, and a review or a pedagogical introduction
over a letter. Never prospect one paper twice in a task. Give each agent the
subject, one slug, `MAX_PROPOSED_TERMS`, and the terms the scan already
reported, so that it does not hand you those back.

A prospector calls no API, thus several run at the same time.

**A term it proposes is a lead, and not a citation.** Open the line it gave you
with `$SEARCH` before any part of your report rests on it, exactly as you do for
a `paper-scout`. Discard a row whose line does not hold the words.

Write the table in the log under `### Terminology`, **and the reason the gate
opened**: which sub-question is still open, and what the last scan failed to
give you. A reader has to see why the tokens were spent.

### Step 5. Decide

| The state | What you do |
|---|---|
| Each sub-question is answered or closed-negative | Stop. Write the report. |
| You used `MAX_ITERATIONS`, or `MAX_TOTAL_INGESTS` | Stop. Write the report. Put the limit in "Limitations". |
| The last `DRY_ITERATIONS` iterations found no new relevant paper | Stop. Write the report. Say that the search stopped finding papers. |
| A limit stops you, and a sub-question has no currency check | Stop. Write the report. Name that sub-question in "Limitations", with the paper that supplies its answer. |
| Anything else | Write the refinement and the reason in the log. Go to step 1. |

**Never present a limit as an exhausted subject.** They are different, and the
reader must know which one stopped you.

## How to refine

| What the last iteration showed | The next move |
|---|---|
| The papers use a term that your query did not have | Search again with the words of the papers. Your first query used the words of the person who asked. |
| The scan found a term that names your subject, and your query did not have it | Search again with that term in the topic phrase. |
| A paper you read cites the claim that a sub-question needs | Backward: `$PY $LOOKUP <tag>`. It costs nothing. Ingest the source only when the claim must be read at the source. |
| The best paper is old, or the sub-question asks for the state of the art | Forward: `$PY $CITE <arxiv-id> --direction citing --sort mostrecent` |
| The sub-question needs the accepted treatment | Forward: `$PY $CITE <arxiv-id> --direction citing --sort mostcited` |
| A sub-question is about a subject that no paper you read reaches | A new search, with a narrower phrase. This is the one case where a search beats the citation graph. |
| Each result is broad and shallow | Divide the sub-question in two. Work on the halves. |

The forward search of Step 4 is required. It is not one of these moves. These
rows are the moves that you choose in Step 1. A currency check can give you the
reason to choose the forward search.

## The research log

Write one entry for each iteration, in this shape:

```markdown
## Working set

| Slug | How it entered | Sub-questions |
|---|---|---|
| <slug> | ingested, iteration 1 | SQ2, SQ3 |
| <slug> | held, read at iteration 2 | SQ5 |

## Iteration <n> — <date>

### Plan
<the open sub-questions, the move, and why>

### Actions
- search: topic="…" backend=… counts={held:…, cited:…, new:…}
- cite:   <arxiv-id> direction=… sort=… returned=… of …
- cite:   <arxiv-id> direction=citing sort=mostrecent returned=… of … — currency for SQ2
- ingest: <slug> — because <sub-question>
- skip:   <arxiv-id> — found, not ingested, because <reason>
- scope:  working set = <slug>, <slug>, <slug>
- scout:  <slug> for SQ2, SQ3
- read:   <slug>/chapters/03_results.md
- lookup: <tag>, <tag> — verified: <n> of <n>

### Findings
- SQ2: <the claim> — <slug>/chapters/03_results.md#sec-axialff

### Currency checks
- SQ2, SQ7: <slug> (<arxiv-id>) — searched <date>, newest citer <year>, nothing that changes the answer
- SQ4: <slug> — skipped, preprint <date>, younger than CURRENCY_GRACE_MONTHS

### Terminology
<the terms the scan reported, and what you did with each; the scout tables.
 When a prospector ran: the reason the gate opened, and its table>

### Assessment
SQ1 answered (currency: <slug>) · SQ2 partial · SQ3 open · SQ4 closed-negative (searched: "…", "…")

### Decision
<continue, with the refinement and the reason | stop, with the reason>
```

The `## Working set` table stands once, above the first iteration entry. Write
the `scope:` line each time the set grows. A reader can then see which papers a
tool covered at that point of the task.

Three rules hold the log together:

- **Write it as the iteration runs.** A log that you write at the end is a
  memory of the work. Step 4 must not judge the work by memory.
- **Add to it. Do not edit it.** An assessment that a later iteration disproves
  gets a new entry. The old one stays.
- **The working set table is the one exception to that rule.** A row enters the
  table, and no row leaves it. The iteration entries stay append-only.

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
- each sub-question that you marked answered with no currency check, and the
  paper that supplies its answer;
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
4. The body and the references name the same works. `cited_but_not_listed`
   names a work the body cites and the references omit: add the work to the
   references. `listed_but_not_cited` names a work the references list and the
   body cites nowhere: cite the work in the body, or remove the entry.
5. Each unconfirmed work carries its mark.

**The report is not finished until `"ok": true`.** Correct what it reports and
run it again.

Then tell the user:

- the answer, in short;
- how many iterations and how many ingests it took, from the log;
- what "Limitations" says;
- the result of the audit.

## Rules

- **One request at a time reaches arXiv and INSPIRE.** `rate_gate.py` holds
  every script to that, across processes, so one `add_paper.py --auto` command
  ingests a whole queue. Do not start a search, a `$CITE` lookup or a second
  ingest beside a running ingest. A scout and your own reading call no API, thus
  they run beside an ingest.
- **Check for later work before you call a sub-question answered.** Step 4 says
  how, and the log says that you did it.
- **Keep the full text out of your context.** Read `INDEX.md` files, the reports
  of the agents, the JSON of the scripts, and the chapters that you cite.
  Never read a paper from beginning to end yourself. That is what a `paper-scout`
  does for your sub-questions, and a `terminology-prospector` for its words.
- **Cite only what you read.** Not an abstract. Not a summary. Not a quotation
  from a scout that you did not check at the line that the scout gave. Discard a
  quotation that carries no line number. Never check such a quotation by hand.
- **Report the limit that stopped you.** A budget is not an answer.
- **Never commit a file below the literature root.** The papers are copyrighted.
