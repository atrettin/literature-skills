# Measuring the research agent

The `research-report` skill answers a task from the literature and writes a
report. This file says how to find out whether it did that well.

**Nobody measured a number in this file.** This is the method, and not a
result. A run produces the numbers, and a run needs the live arXiv and INSPIRE
APIs.

## What can be measured, and what must be judged

Two kinds of question are asked of a report, and only one kind has an answer
that a script can give.

| Question | How it is answered |
|---|---|
| Does each citation open the text it names? | `litdb check-report`. Measured. |
| Does the report cite the papers that the task needs? | Compare against a set of papers that a person chose. Measured, against a judgement. |
| Does the cited text support the claim beside it? | A person or a model reads both. Judged. |
| Is the report honest about what the literature does not settle? | A person or a model reads it. Judged. |

Record each result with the date, the model, the commit of the skills, and a
mark that says whether it was measured or judged. A number with no run behind it
belongs nowhere.

## The tasks

A benchmark task is a file with these parts:

| Part | What it holds |
|---|---|
| Prompt | the task, word for word, as a user would give it. |
| Kind | `question`, `claim-check` or `survey`. |
| Must-cite | the papers that an acceptable report cites, by arXiv identifier or DOI. Never by tag: a tag names a record of one collection, and the identifier names the paper. |
| Why | one line for each must-cite paper, that says why a report without it is wrong. |
| Start | the state of the collection at the start: empty, or a named fixture. |

Five to ten tasks, and each kind is present. A benchmark of questions only
measures a skill that also has to check claims and build lists.

**Choose the must-cite papers by hand.** A person who knows the subject decides.
A set built from what an earlier run cited measures agreement with that run, and
nothing else.

**Write down the state of the collection.** A collection that already holds the
answer measures the reading. An empty collection measures the search as well.
The two runs answer different questions and their numbers do not compare.

## What one run gives

Run one task at a time. arXiv and INSPIRE limit their rate.

| Number | Where it comes from | Kind |
|---|---|---|
| Audit | `litdb check-report` on the report. Record whether it passed at the first try, and what failed if it did not. | measured |
| Must-cite recall | the share of the must-cite papers that the references of the report name. Match by DOI and arXiv identifier. | measured |
| Extra papers | how many papers the report cites that the must-cite set does not name. A high number is not a failure. Read them: they are either a wider answer or a wandering search. | measured |
| Iterations, ingests, API calls | the research log. This is why the log is written as the work runs, and never edited. | measured |
| Faithfulness | take five citations at random. Open each link. Grade: supports, supports in part, contradicts, or the text is not there. | judged |
| Coverage | compare the sub-questions in the log against the task. Grade 1 to 4. | judged |
| Honesty | read "Limitations of this search". Does it name the gaps that the log shows? Does any claim rest on a `verified: false` record with no mark? Grade 1 to 4. | judged |

**Faithfulness is the number that matters most.** A report can cite the right
papers for claims that those papers do not make. Such a report passes every
mechanical check, and it is worse than a report that cites nothing. Grade this
number by opening the anchor, and not by reading the report alone.

A model can grade faithfulness. Give it the claim and the text at the anchor,
and nothing else. Do not give it the report: a model that reads the whole report
grades the argument, and the question here is narrower.

## Comparing two versions of the skills

1. Use the same tasks, and the same starting collection.
2. Run one task at a time, on one version, then on the other.
3. Record both sets of numbers, side by side, with their dates.

**Report a result that got worse.** A mean over the tasks hides the one task
that broke, and that task is the finding.

A judged number moves when the model moves, and the model moves under you. Note
the model beside each judged number, and never compare a judged number against
one that a different model gave.

## What a run costs

Read the limits in [TUNING.md](../TUNING.md). With `MAX_TOTAL_INGESTS` at 20, one
task that starts from an empty collection can ingest twenty papers. Each ingest
downloads a source archive from arXiv and asks INSPIRE about the paper and its
bibliography. Each search is one or two requests to arXiv, three seconds apart.
Each citation lookup is two or three requests to INSPIRE.

Plan a benchmark of ten tasks as hours, and not as minutes.
