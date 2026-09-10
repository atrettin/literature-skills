---
name: find-terms
description: Finds the other names the field uses for a subject, so the search runs on the papers' words instead of the asker's. Use inside a research-report task, after its first iteration, when the question arrived as a description of a phenomenon rather than the field's name for it. Its gate closes it when the question already arrived in the field's words.
---

# Find the other names of the subject

The query holds the words of the person who asked. The papers hold the words of
the field, and the two are often different words for one area. `missing_terms`
cannot tell you this. It names the terms of your query that a paper lacks. It
never names the terms of the papers that your query lacks.

This skill runs inside the loop of `research-report`, after its first
iteration. The loop holds what this skill takes: the topic phrase, the working
set, the sub-questions, and the log the results go into.

## The limits

These limits hold the step:

| Limit | Value |
|---|---|
| `MAX_TERMS_CHECKED` | 3 |
| `FIRST_PROSPECT_ITERATION` | 2 |
| `MAX_PROSPECTORS` | 2 |
| `MAX_PROPOSED_TERMS` | 6 |

## The gate: is there a vocabulary gap to find?

The scan earns its cost when the person who asked described the subject in lay
terms and the field has its own name for it. It earns nothing when the question
already arrived in the field's own words. Skip it when **all** of these hold,
and write in the log that you did and why:

1. The topic phrase is drawn from the seed paper's own terminology, rather than
   from a description you translated.
2. The user named the subject, the method or the instrument in the field's
   words.
3. Your searches so far are returning papers on the subject, rather than papers
   that merely repeat the words.

When any of them fails, run the scan. A question that arrived as a description
of a phenomenon rather than as its name is the case this exists for.

## Run the scan

**Scope it to the working set**, in one call:

```bash
litdb terminology --topic "<your topic phrase>" --scope <slug> <slug> <slug>
```

The scan reads two things, and it calls no API. `--corpus text` reads the
papers themselves: their titles, abstracts, headings, captions and paragraphs.
`--corpus cited` reads the titles of the works they cite. By default it reads
both; give one `--corpus` when you want one side alone. It reports the terms
that your topic does not hold, and a word your topic holds already lowers a
term rather than lifting it — the names worth finding are the ones your query
could not have reached.

The collection is persistent. It holds the papers of tasks that came before
yours, and their words carry the vocabulary of other subjects. A scan of the
whole store thus offers you the other names of somebody else's question. `litdb
terminology` refuses to run without a scope for that reason. Never use
`--scope disk` here: it answers a question about the collection, and not about
your task.

Check the `scope` block of the report. Its `papers` list must equal your working
set. When it does not, you passed the wrong slugs.

**Read `stated_aliases` first.** Those entries are the places where an author
writes your subject beside another name, with the cue that joins them and the
sentence that says it:

```
"…an acute coronary event, or myocardial infarction, in the first year"
```

Each one arrives with its chapter and anchor, so a term from that block is a
claim you can open. Take your candidates from there before you take them from
the ranked `terms` list.

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

## When the scan finds nothing, and a question is still open

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
with `litdb search` before any part of your report rests on it, exactly as you
do for a `paper-scout`. Discard a row whose line does not hold the words.

Write the table in the log under `### Terminology`, **and the reason the gate
opened**: which sub-question is still open, and what the last scan failed to
give you. A reader has to see why the tokens were spent.
