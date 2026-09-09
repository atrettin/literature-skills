---
name: research-report
description: Answers a task that needs a review of the scientific literature, and writes a report in which each claim links to the chapter that it came from. Use for "research X and write a report", "survey the literature on X", "check the claims in this file against the literature", or any task whose result is a report with citations.
---

# Research a task and report with citations

This skill answers a task from the published literature. It searches, it reads,
it judges what is still missing, and it searches again. It stops when the task
is answered, and then it writes a report.

The loop is the point. The first papers you find are only the entry point to
understanding the topic. From there you will learn how to refine the search
terms, refine the list of sub-questions, and enter the chain of citations you 
may want to follow.

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

The papers being ingested are stored in a persistent collection on disk.

**Find the collection first.** It is at `$LITERATURE_ROOT` when that variable is
set. If it is not set, it is `literature/` in the project. `litdb` reads the
variable itself, thus you do not give `--literature-root`. If neither is there,
run `litdb init` before you search: it creates the directory with its index and
makes git ignore it, and refuses if one already exists. Write the path down: the
header of the report and each link in it depend on it.

**Delegate the heavy reading.** Your own context is the limit on this work, and
the full text of a paper is large. Three agents keep that text out of it:

| Agent | What it does |
|---|---|
| `paper-ingestor` | resolves the exception of one failed ingest. When the resolution needs the user it brings the question back; when it completes it reports the slug and the warnings, and no paper text. |
| `paper-scout` | reads one paper that is on disk against your sub-questions. It reports the locations that answer them. It uses no API, thus several can run at the same time. |
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

Every one of them takes the same `--scope`, and it takes the whole set in one
call:

```bash
litdb search "<phrase>"    --scope <slug> <slug> <slug>
litdb terminology --topic "…" --scope <slug> <slug> <slug>
litdb overlap <arxiv-id>      --scope <slug> <slug> <slug>
```

A scope is the citation form cut off wherever you like — `disk`, `<slug>`,
`<slug>/<stem>`, `<slug>/<stem>#<anchor>`, a span
`<slug>/<stem>#<from>..#<to>`, or a bare anchor `<slug>#<anchor>`, which names
the chapter that carries it — so the `location` an answer reports is a scope
you hand straight back to narrow the next call.

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
| `MAX_SECTION_WORDS` | 1200 |
| `MIN_SCOUT_WORDS` | 2000 |
| `CURRENCY_GRACE_MONTHS` | 12 |
| `MAX_TERMS_CHECKED` | 3 |
| `FIRST_PROSPECT_ITERATION` | 2 |
| `MAX_PROSPECTORS` | 2 |
| `MAX_PROPOSED_TERMS` | 6 |

### Step 1. Plan the iteration

Choose the open sub-questions to work on. Choose a search or a citation lookup
from the table in "How to refine". Write the choice and the reason in the log
**before** you act.

### Step 2. Search

Search the collection first with `use-literature`. That costs nothing. Then
search arXiv, one search at a time:

```bash
litdb find --topic "<the question, as a full phrase>" --max-results 15
```

That is the command the `find-papers` skill documents. Read that skill for how
to write the topic and how to read the ranking.

Write in the log: the exact `--topic` phrase, `ranking.backend`, the counts, and
the best candidates with their `missing_terms`.

### Step 3. Ingest and read

**Ingest** at most `MAX_NEW_PAPERS_PER_ITERATION` new papers, and at most
`MAX_TOTAL_INGESTS` in the whole task. A paper that the collection holds already
needs no ingest, and it counts against no limit. Pass a queue of identifiers to
one command:

```bash
litdb add-paper --auto <arxiv-id> [<arxiv-id> …]
```

It sends one request at a time by itself, thus one command ingests the
whole queue. It prints one JSON report per paper, as one object per line. It
exits 2 when any paper raised an exception.

**Start a `paper-ingestor` agent only for a paper whose report carries an
`exception`.** Give that agent the identifier of that paper and the fields of
its exception. The exception is the one part of an ingest that needs
judgement, and a judgement it cannot make it brings back to you.

**When more candidates look worth an ingest than the iteration budget allows,
weigh them against what you already hold.** A rank says how well an abstract
answers the question. It does not say whether the candidate builds on the same
works as the papers of your working set, and the reference store does say that.

1. Run `litdb overlap <arxiv-id> --scope <slug> <slug> …` on each candidate. Run
   one check at a time: it asks INSPIRE, and INSPIRE limits its rate. Give the
   whole working set out of the `## Working set` table of the log. Never
   `--scope disk`: the collection serves other questions, and their papers would
   decide your band.

   It answers in this shape:

    ```json
    {"band": "low", "overlap": 0.12,
     "scope": {"mode": "working_set", "papers": ["…"]},
     "closest": [{"slug": "…", "references": 41, "shared": 3,
                  "overlap": 0.31}],
     "outside_scope": [{"slug": "…", "references": 38, "shared": 8,
                        "overlap": 0.44}]}
    ```

    `band` is `null` when nothing bands the candidate — an empty working set, or
    a reference list too short to compare. That is an answer, and
    `candidate_references` and `in_scope` still hold.
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
| `litdb lookup <tag>`, which reads the local store | yes |
| `litdb search "<phrase>"`, which reads the chapters on disk | yes |
| a second `litdb add-paper --auto` command, or a `paper-ingestor` | **no** |
| a `find-papers` search | **no** |
| `litdb citations …`, which asks INSPIRE | **no** |
| `litdb overlap …`, which asks INSPIRE | **no** |

**Read a paper only after the command that ingests it reports.** The chapters
are incomplete until then, and a scout that starts early reads a part of the
paper.

**Read on a ladder. Stop at the rung that answers.** Every rung is cheaper than
the one below it, and a rung skipped is context spent for nothing.

#### Rung 1. The table of contents

```bash
litdb toc <slug>
```

The same rung as in the `use-literature` skill: one call says what the paper is
and what is in it, with a word count and an address on every section, and a
review organised by the axis your question asks about is often answered by its
section titles alone. Where a section's title bears on a sub-question, read it
straight away with `litdb show <slug>/<stem>#<anchor>`.

**Where the section runs past `MAX_SECTION_WORDS`, do not read it whole** — go
to rung 2 scoped to that section, and read the block that answers.

Never read `paper.json` by hand. On a long paper its chapter list alone fills a
context window, and this says the same thing bounded.

#### Rung 2. Search

```bash
litdb search "<phrase>" --scope <slug>/<stem>#<anchor>
litdb search "<phrase>" --scope <slug> --approx
```

The same rung as in the `use-literature` skill, and its rules hold: exact
first, `--approx` when you are unsure of the words the field uses, scope it as
narrowly as the question allows and widen only when it answers nothing. An
argument in a paper is not one block, and mathematics never matches a search;
the `use-literature` skill gives the ways out of a block, and each costs no
second search.

#### Rung 3. A `paper-scout`

Start one **only** when rungs 1 and 2 left a sub-question open and you have good
reason this paper holds the answer. Give it the slug and the open sub-questions.
Run at most `MAX_PARALLEL_SCOUTS` at one time.

Two gates:

- **Never scout a paper under `MIN_SCOUT_WORDS`.** Read it. Below that a scout's
  report costs more than the paper it summarises.
- **Never scout before rung 1.** The table of contents sometimes answers the
  sub-question outright, and it always tells you whether a scout is worth it.

**A scout is also how you establish absence.** It is the only reader that goes
through a paper end to end, so "this paper does not treat SQ4" is a claim only a
scout can support. That is a finding, not a failure, and it goes in the report.

A paper that the collection held enters the working set here, and not at the
search: it enters when you read text in it that bears on a sub-question.

**Verify before you cite.** A scout report tells you where to look. It is not a
source. Each location it gives is an anchor, as `<slug>/03_results#p9`. Verify
it the way the `use-literature` skill gives under "To verify a quotation": find
the words in the paper they come from, open the `location` with
`litdb show <location> --context 1`, and read what stands around them, because a
found sentence is not a finding until its context says so — the paper may be
asserting it, writing it as the assumption its argument starts from, or
reporting a result that belongs to another work.

**When the words are not there, do not conclude that the scout invented them.**
Find them:

```bash
litdb search "<the words the scout quoted>" --scope <slug>
```

This is the reliable path and it returns the anchor that holds the words, so it
verifies and re-addresses in one call. A quotation the search cannot place is
not verified, whatever the scout wrote.

Then write the finding in the log:

```
SQ2: <the claim, in one sentence> — <slug>/03_results#p9
```

A finding with no anchor is not a finding. **Discard a quotation that carries no
anchor.** Every block of every paper has one, so a scout that gave none did not
read the block it quoted. Ask the scout again for that sub-question, or drop the
location.

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

Name the paper that supplies the answer, and show that it does: remove that
paper's full text, and the answer must go with it. An answer that stands
without the paper's text was supplied by something else — the paper's
abstract, another paper, or what you knew before the task — and the citation
is then an address you did not open. Ask INSPIRE which papers cite that
paper, newest first:

```bash
litdb citations <arxiv-id> --direction citing --sort mostrecent
```

It answers in this shape. The results are **nested under the direction you
asked for**, and not at the top level:

```json
{"paper": {...}, "query": {...},
 "citing": {"total": 41, "returned": 20,
            "counts": {"held": 0, "cited": 3, "new": 17},
            "results": [{"title": "…", "arxiv_id": "…",
                         "year": 2024, "held_as": null}]}}
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

**Run this after iteration 1, unless the gate below closes.** Your query holds
the words of the person who asked. The papers hold the words of the field, and
the two are often different words for one area. `missing_terms` cannot tell you
this. It names the terms of your query that a paper lacks. It never names the
terms of the papers that your query lacks.

**The gate: is there a vocabulary gap to find?** The scan earns its cost when
the person who asked described the subject in lay terms and the field has its
own name for it. It earns nothing when the question already arrived in the
field's own words. Skip it when **all** of these hold, and write in the log that
you did and why:

1. The topic phrase is drawn from the seed paper's own terminology, rather than
   from a description you translated.
2. The user named the subject, the method or the instrument in the field's
   words.
3. Your searches so far are returning papers on the subject, rather than papers
   that merely repeat the words.

When any of them fails, run the scan. A question that arrived as a description
of a phenomenon rather than as its name is the case this exists for.

**Scope it to the working set**, in one call:

```bash
litdb terminology --topic "<your topic phrase>" --scope <slug> <slug> <slug>
```

It reads both corpora by default: the papers' own words, and the titles of the
works they cite. `--corpus text` or `--corpus cited` narrows that when you want
one side alone.

The collection is persistent. It holds the papers of tasks that came before
yours, and their words carry the vocabulary of other subjects. A scan of the
whole store thus offers you the other names of somebody else's question. `litdb
terminology` refuses to run without a scope for that reason. Never use
`--scope disk` here: it answers a question about the collection, and not about
your task.

Check the `scope` block of the report. Its `papers` list must equal your working
set. When it does not, you passed the wrong slugs.

The scan reads two things, and it calls no API. `--corpus text` reads the papers
themselves: their titles, abstracts, headings, captions and paragraphs.
`--corpus cited` reads the titles of the works they cite, and the default reads
both. It reports the terms that
your topic does not hold, and a word your topic holds already lowers a term
rather than lifting it — the names worth finding are the ones your query could
not have reached.

**Read `stated_aliases` first.** Those entries are the places where an author
writes your subject beside another name, with the cue that joins them and the
sentence that says it:

```
"…an acute coronary event, or myocardial infarction, in the first year"
```

Each one arrives with its chapter and anchor, so a term from that block is a
claim you can open. Take your scouts from there before you take them from the
ranked `terms` list.

Then read `terms`. Each one is in one of three states:

| The term | What you do |
|---|---|
| You know it, and it names your subject | Add it to the topic phrase of the next search. |
| You know it, and it names something else | Ignore it. Write one line in the log that says so. |
| You do not know how it relates to your subject | Read the passage yourself. |

Check at most `MAX_TERMS_CHECKED` such terms. Each one arrives with its address,
so `litdb show <slug>/<stem>#<anchor> --context 1` puts the passage in front of
you, and `litdb search "<term>" --scope <your working set>` finds where else the
papers use it. Read the passage that defines the term, and the passage that
names it beside your subject. Five passages settle a term; when they do not, the
answer is `unclear` and you write that.

Answer each one in a row of this table, and write it in the log under
`### Terminology`:

```markdown
| Term | Where used | Same referent? | How it differs |
|---|---|---|---|
| <the term, as the papers write it> | <slug>/<stem>#<anchor> | <yes, narrower, wider, related or unclear> | <one or two sentences> |
```

| The answer | What it means |
|---|---|
| `yes` | a paper states that the two names denote one object. |
| `narrower` | the term names a part of what the subject names. |
| `wider` | the subject names a part of what the term names. |
| `related` | the term names a different object of the same area. |
| `unclear` | no passage that you read settles it. |

**Never treat a term as a synonym.** Begin from the assumption that two names
differ: a field coins a second name because the first one does not fit. Answer
`yes` only where a paper states the identity, and never because two terms share
a sentence or look interchangeable to you. `narrower`, `wider` and `related` are
the common answers, and that distinction is the finding — a search for a
narrower term finds papers about a part of your subject, and the report must say
which part.

A later iteration can run the scan again. When the gate opened at
iteration 1, run it there.

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
   topic phrase — either it reported none, or every term you checked was
   `related` or `unclear`.
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
with `litdb search` before any part of your report rests on it, exactly as you do for
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
| A paper you read cites the claim that a sub-question needs | Backward: `litdb lookup <tag>`. It costs nothing. Ingest the source only when the claim must be read at the source. |
| The best paper is old, or the sub-question asks for the state of the art | Forward: `litdb citations <arxiv-id> --direction citing --sort mostrecent` |
| The sub-question needs the accepted treatment | Forward: `litdb citations <arxiv-id> --direction citing --sort mostcited` |
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
- read:   <slug>/03_results
- lookup: <tag>, <tag> — verified: <n> of <n>

### Findings
- SQ2: <the claim> — <slug>/03_results#sec-axialff

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

**You write a marker, never a path.** A citation names the paper with a `lit:`
marker, and `litdb render-report` turns every marker into the link that opens the
collection in whatever flavor it is rendered in. You therefore never compute a
relative path, and never learn the flavor.

| What you cite | The form |
|---|---|
| A paper you read | `(Katori 2018, J.Phys.G 45 (2018) 013001, [§2.3](lit:katori_2018_neutrino_nucleus/03_model#sec-form-factors))` |
| A work you traced but did not read in full | `([Bodek et al., 2008](lit:ref/bodek_2008_axial_mass_quasielastic))` |
| A work that no lookup confirmed | the same, and write "the citing paper attributes this to …", and keep the ⚠ in the entry for it. |

The three forms are `lit:<slug>` for a paper, `lit:<slug>/<stem>#<anchor>` for a
place in one, and `lit:ref/<tag>` for a work the collection knows and does not
hold. The chapter **stem** carries no `.md`: it names the paper's chapter and
not one rendering of it.

Put several works in one pair of brackets, separated by `;`.

**Never cite a chapter that you did not open.** The marker is a statement that
you read the text there.

The `## References` section holds one entry for each work. **Which page an entry
opens depends on whether the collection holds the paper:**

| The work | The entry opens |
|---|---|
| A paper the collection holds | the paper, as `lit:<slug>`. |
| A work that a paper here cites, and the collection does not hold | its record, as `lit:ref/<tag>`. |

A record exists for a work that a paper of the collection cites. A paper the
collection holds and that nothing here cites has no record, and an entry naming
one is a dead citation. `lit:<slug>` names it, and it is the better page: it
carries the abstract and each chapter.

```markdown
- **<slug>** — Authors (year). *Title*. Journal.
  [paper](lit:<slug>) ·
  [arXiv](https://arxiv.org/abs/<id>) ·
  read: [§2](lit:<slug>/02_introduction#sec-introduction)
- **<tag>** — Authors (year). *Title*. Journal.
  [record](lit:ref/<tag>) ·
  [arXiv](https://arxiv.org/abs/<id>)
```

Each work that the body cites goes here. Each work that is here must be cited in
the body. Mark a work that no lookup confirmed with ⚠, and write one sentence
that says what that means.

## Step 6. Audit the report, then render it

```bash
litdb check-report reports/<task-slug>.source.md
```

It checks the report against the store, and not against any rendered file:

1. Each marker resolves. A work the collection does not hold is reported in
   `works_not_in_collection` without failing the check: a report may name a
   work it does not hold, and the reader can go and get it.
2. Each chapter and each anchor is one the paper has.
3. Each tag has a record in the store.
4. The body holds no `[cite: …]` marker: those belong to the chapters of the
   collection, and one in the report means chapter text was copied where a
   `lit:ref/<tag>` reference was wanted.
5. The body and the references name the same works. `cited_but_not_listed`
   names a work the body cites and the references omit: add the work to the
   references. `listed_but_not_cited` names a work the references list and the
   body cites nowhere: cite the work in the body, or remove the entry.
6. Each unconfirmed work carries its mark.
7. The report cites at least one work. A report that attributes nothing to
   anything has nothing to audit.

Any of them false is `"ok": false`.

**The report is not finished until `"ok": true`.** Correct what it reports and
run it again. Then write the report a person reads:

```bash
litdb render-report reports/<task-slug>.source.md
```

That writes `reports/<task-slug>.md`, with every marker resolved into a link
for the collection's current flavor. The source is the master: a flavor change
re-renders it and never edits it. The research log needs no rendering: it holds
plain addresses and no `lit:` marker, so it is written under its final name,
`reports/<task-slug>.research-log.md`, from the start.

Then tell the user:

- the answer, in short;
- how many iterations and how many ingests it took, from the log;
- what "Limitations" says;
- the result of the audit.

## Rules

- **One request at a time reaches arXiv and INSPIRE.** The request gate holds
  every command to that, across processes, so one `litdb add-paper --auto` command
  ingests a whole queue. Do not start a search, a `litdb citations` lookup or a second
  ingest beside a running ingest. A scout and your own reading call no API, thus
  they run beside an ingest.
- **Check for later work before you call a sub-question answered.** Step 4 says
  how, and the log says that you did it.
- **Keep the full text out of your context.** Read `litdb toc` for what a paper
  holds, the reports of the agents, the JSON of the commands, and the sections
  that you cite. Never read a paper from beginning to end yourself. That is what
  a `paper-scout` does for your sub-questions, and a `terminology-prospector`
  for its words.
- **Cite only what you read.** Not an abstract. Not a summary. Not a quotation
  from a scout that you did not open at the anchor the scout gave. Discard a
  quotation that carries no anchor.
- **Report the limit that stopped you.** A budget is not an answer.
- **Never commit a file below the literature root.** The papers are copyrighted.
