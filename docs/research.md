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

Five agents divide the work, and the division is about context rather than
speed:

| Agent | Reads | Why it is separate |
|---|---|---|
| `literature-researcher` | `INDEX.md` files, the reports of the other two, and the chapters it cites | it runs the loop and writes the report. |
| `paper-ingestor` | one report, and no chapter | it handles an exception of the ingest — an ambiguous title, a name two works want. `lit add-paper` does the rest, and it reads no paper into any context. |
| `paper-scout` | the whole paper, against the open sub-questions | `INDEX.md` says how long each chapter is and what it is called, and neither was written against these questions, so the index cannot say which chapter answers one. |
| `terminology-scout` | the chapters that use one term | a term the query lacks is a question about the words of the field. The answer must differentiate the two names, and it must never equate them: "myocardial infarction" names the tissue death, and "heart attack" is also said of the event that causes it. |
| `terminology-prospector` | the whole paper, for the names it gives the subject | a name can carry no string that a scan can match — an acronym a paper defines once, a symbol, or a name that no sentence joins to the subject. Only a reader of the whole paper finds those. It reads the paper for its vocabulary, which is a different question from the one a `paper-scout` reads it for, and a gate in the research loop decides when that second read is worth its tokens. |

The request gate holds every command to one request at a time, at the pace each
API asks for, across processes. So one `lit add-paper --auto` command ingests a whole
queue of papers, and no agent has to serialise them. A scout reads local files,
so several run together. They read the papers of the last command while the next
command runs. The constraint is one request at a time, not one agent at a
time.

A scout reports a location as `chapters/03_results.md:181`, with the anchor above
the text and the words of the paper. The researcher opens the chapter at that
line and compares. It discards a quotation that carries no line number. The line
addresses the file on disk. The report cites the anchor, which a new ingest keeps.

The report goes to `reports/<task-slug>.md` in the project, beside
`reports/<task-slug>.research-log.md`, which records each iteration: what was
searched, what was read, what was found, and what stayed open. Both are the
agent's own words and can be committed.

Each citation in a report is a relative link into the collection, down to the
anchor of the section the claim came from:

```markdown
(Jeong 2023, Phys.Rev.D 108 (2023) 113010,
[§2](../literature/jeong_2023_shallow_deep_inelastic/chapters/02_introduction.md#sec-introduction))
```

`lit check-report` then checks the report the way the reference check checks the
collection: every link opens a file that exists, every anchor is in that file,
every tag has a record, the body and the references name the same works
(`cited_but_not_listed` names a work the body cites and the references omit,
`listed_but_not_cited` a work the references list and the body cites nowhere),
and every unconfirmed work carries its ⚠.

It reads each link from the report, the way a reader reads it. A link that
opens nothing there is broken, however `--literature-root` is set. The root
tells the reader which repair the link needs. `broken_links` gives one of three
answers:

| `why` | What it means | The repair |
|---|---|---|
| `no such file` | the link opens nothing, and the root holds no such path either | get the paper, or correct the name of the chapter |
| `the collection holds this file, the link does not reach it` | `in_collection` gives the path under the root, and `anchor_in_collection` says whether the anchor is there | write the link for the collection this reader opens |
| `no such anchor` | the file opens and the section is not in it | cite the anchor the chapter now carries |

`citations` counts the works the body cites, whether or not their links open.
A report that names twelve papers cites twelve papers. A count that fell with
the reader's `LITERATURE_ROOT` would describe the collection and call itself a
description of the report. `works_not_in_collection` names the cited works this
collection does not hold. That list describes the collection, thus it alone
does not fail the check.

[evaluation.md](evaluation.md) says how to measure whether the agent does this
well.

