# Researching a task

`research-report` answers a task whose result is a report with citations. A
question is one such task. So is "check the claims in this file against the
literature", and so is "list the cross-section models this generator uses, by
the energy range where each applies".

It runs a loop, because the first papers a search finds are approximate matches.
Reading them teaches what the search should have asked for, and which papers to
follow through the citation graph. The loop stops when each sub-question is
answered, or when a limit in [TUNING.md](../TUNING.md) stops it — and the report
says which of the two happened.

A sub-question counts as answered only after the loop asks INSPIRE which papers
cite the paper that supplies the answer. The research log holds that search,
under `Currency checks`, so a reader can see it.

The skill runs in the agent that was given the task. That agent reads
`paper.json` files, the reports of the agents below, and the chapters it cites,
and it never reads a full text. Four agents take the reading off it, and the
division is about context rather than speed:

| Agent | Reads | Why it is separate |
|---|---|---|
| `paper-ingestor` | one report, and no chapter | it handles an exception of the ingest — an ambiguous title, a name two works want. `lit add-paper` does the rest, and it reads no paper into any context. |
| `paper-scout` | the whole paper, against the open sub-questions | `paper.json` says how long each chapter is and what it is called, and neither was written against these questions, so the record cannot say which chapter answers one. |
| `terminology-scout` | the chapters that use one term | a term the query lacks is a question about the words of the field. The answer must differentiate the two names, and it must never equate them: "myocardial infarction" names the tissue death, and "heart attack" is also said of the event that causes it. |
| `terminology-prospector` | the whole paper, for the names it gives the subject | a name can carry no string that a scan can match — an acronym a paper defines once, a symbol, or a name that no sentence joins to the subject. Only a reader of the whole paper finds those. It reads the paper for its vocabulary, which is a different question from the one a `paper-scout` reads it for, and a gate in the research loop decides when that second read is worth its tokens. |

The request gate holds every command to one request at a time, at the pace each
API asks for, across processes. So one `lit add-paper --auto` command ingests a whole
queue of papers, and no agent has to serialise them. A scout reads local files,
so several run together. They read the papers of the last command while the next
command runs. The constraint is one request at a time, not one agent at a
time.

A scout reports a location as `text/03_results.jsonl:181`, with the anchor of
the text and the words of the paper. The researcher opens the chapter at that
line and compares. It discards a quotation that carries no line number. The line
addresses the file on disk. The report cites the anchor, which a new ingest keeps.

The report goes to `reports/<task-slug>.source.md` in the project, beside
`reports/<task-slug>.research-log.source.md`, which records each iteration: what
was searched, what was read, what was found, and what stayed open. Both are the
agent's own words and can be committed. `lit render-report` writes the two a
person reads, `reports/<task-slug>.md` and its log, with every `lit:` marker
resolved into a link for the collection's flavor — see
[rendering.md](rendering.md).

Each citation in a report is a relative link into the collection, down to the
anchor of the section the claim came from:

```markdown
(Jeong 2023, Phys.Rev.D 108 (2023) 113010,
[§2](lit:jeong_2023_shallow_deep_inelastic/02_introduction#sec-introduction))
```

`lit check-report` then checks the report source the way the reference check
checks the collection: every marker names a paper the collection holds, every
chapter and anchor is one that paper has, every tag has a record, the body and
the references name the same works (`cited_but_not_listed` names a work the body
cites and the references omit, `listed_but_not_cited` a work the references list
and the body cites nowhere), and every unconfirmed work carries its ⚠.

It reads the source and checks it against the store, never against a rendered
file. The rendered report is written from a checked source, so its links resolve
by construction, and one check answers for every flavor the collection is ever
rendered in. `broken_markers` gives one of four answers:

| `why` | What it means | The repair |
|---|---|---|
| `no such paper` | the collection holds no paper of that slug | get the paper, or correct the slug |
| `no such chapter` | the paper holds no chapter of that stem | cite a chapter the paper has |
| `no such anchor` | the chapter is there and the block is not | cite the anchor the chapter now carries |
| `no such record` | no record in the store answers the tag | correct the tag, or add the work |

`citations` counts the works the body cites, whether or not the collection holds
them. A report that names twelve papers cites twelve papers.
`works_not_in_collection` names the cited works this collection does not hold.
That list describes the collection, thus it alone does not fail the check.

[evaluation.md](evaluation.md) says how to measure whether the agent does this
well.

