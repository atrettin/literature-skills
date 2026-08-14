---
name: follow-citations
description: Finds the papers that cite a given paper, and the works that the paper draws on, with INSPIRE-HEP and the local reference store. Use when a paper is old and the question needs the work that came after it, or when a claim must be traced to the paper that first made it.
---

# Follow the citations of a paper

A search of abstracts finds the papers that describe themselves in the words of
the question. This skill finds the papers that the citation graph connects to a
paper you have. A paper cites the work that it builds on. The papers that cite
it are its corrections, its applications, and the state of the art after it.

Use this skill when a search gives you a good paper but not a full answer. The
answer is frequently one step along the graph.

## Before you start

Run every command from the root of the project, so that `literature/` resolves.

The collection is at `$LITERATURE_ROOT` when that variable is set. If it is not
set, it is `literature/` in the project. `litdb` reads the variable itself, thus
you do not give `--literature-root`.

## Step 1. Choose the direction

| What you need | The direction |
|---|---|
| The source of a claim that a paper you read borrowed | `--direction cited`. Try `litdb lookup <tag>` first: for a paper the collection holds, that is the same answer and it costs no request. |
| The work that came after an old paper | `--direction citing --sort mostrecent` |
| The accepted treatment of the subject of a key paper | `--direction citing --sort mostcited` |
| Both lists at one time | `--direction both` |

## Step 2. Run it

```bash
litdb citations 1706.03621 --direction citing --sort mostcited
```

| Option | What it does |
|---|---|
| `<arxiv-id>` | the paper, by its arXiv identifier. |
| `--doi` | the paper, by its DOI. |
| `--recid` | the paper, by its INSPIRE record number. |
| `--direction` | `citing`, `cited` or `both`. The default is `citing`. |
| `--sort` | `mostcited` or `mostrecent`. It orders the citing papers. The default is `mostcited`. |
| `--max-results` | how many papers to report. The default is 20. |
| `--literature-root` | where the collection is. It defaults to `$LITERATURE_ROOT`, or to `literature`. |

**One run costs two requests, or three.** A paper that the collection holds
answers the `cited` direction from the reference store, and that costs no
request at all.

## Step 3. Read the answer

It prints JSON with these parts:

| Field | What it holds |
|---|---|
| `paper` | the paper you asked about, and `held_as` if the collection holds it. |
| `citing.total` | how many papers cite it. `returned` says how many of those you are reading. |
| `citing.counts` | how many results are `held`, `cited` and `new`. |
| `cited.source` | `store` when the answer came from disk, `inspire` when it came from a request. |

Then, for each result:

| Field | What it holds |
|---|---|
| `held_as` | the directory that holds this paper in full. |
| `known_as` | the tag of a work that a paper here cites, but does not hold. |
| `citation_count` | how many papers cite this result. |
| `verified` | `false` marks a work that no lookup confirmed. |
| `summary` | 400 characters of the abstract. |

**A `total` much larger than `returned` is a message.** The paper has more
citers than you can read. Make the question narrower, or accept the order that
you asked for.

## Step 4. Decide what to do

| The result | What you do |
|---|---|
| `held_as` holds a directory name | The collection holds the paper. Read it with `use-literature`. |
| `known_as` holds a tag, `held_as` is `null` | A paper here cites this work. Run `litdb lookup <tag>` for the record. Ingest it with `add-paper` when the question needs the work itself. |
| both are `null` | The collection does not know this paper. Report it, and offer `add-paper` with the arXiv identifier. |

## Rules

- **Run one lookup at a time.** INSPIRE limits its rate. Never start a sub-agent
  for each paper, and never run several lookups at the same time.
- **A citation count measures attention, not correctness.** A wrong paper that
  started an argument gets more citations than a correct paper that ended it.
  Report the count. Do not present it as a judgement of quality.
- **A summary is not a paper.** 400 characters of an abstract are enough to
  choose a paper. They are never enough to cite one. Ingest the paper with
  `add-paper` and read it, or cite nothing.
- **A `verified: false` result is an attribution, not a fact.** The citing paper
  made it, and no lookup confirmed it. Say so each time you use it.
