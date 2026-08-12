---
name: find-papers
description: Finds papers on arXiv by the subject of their abstracts, and says which of them the local literature/ collection already holds. Use when a research question needs a paper that the collection may not hold yet.
---

# Find papers on a subject

This skill searches arXiv for papers about a question. It reads abstracts and
not titles. It therefore finds a paper on the subject when the title of that
paper never gives the words.

Use `use-literature` first. It reads the papers the project holds already, and
that costs nothing. Use this skill when the collection cannot answer the
question.

Each result says whether the collection holds that paper. You thus see what is
new and what is on disk already.

## Before you start

This skill is installed once and used from any project, so nothing below can
assume a fixed path. Three shorthands are used throughout:

- **`$DISCOVER`** — `<the add-paper skill's directory>/scripts/arxiv_discover.py`.
  The `add-paper` skill prints its own base directory when it loads. If it is
  not installed beside this one, `find ~/.claude/skills -name arxiv_discover.py`
  finds it.
- **`$OVERLAP`** — `<the add-paper skill's directory>/scripts/collection_overlap.py`,
  beside `$DISCOVER`. Step 4 uses it.
- **`$PY`** — the project's Python. Use `.venv/bin/python` when the project has
  a virtual environment, otherwise `python3`.

Run every command from the root of the project, so that `literature/` resolves.

The collection is at `$LITERATURE_ROOT` when that variable is set. If it is not
set, it is `literature/` in the project. The scripts read the variable
themselves, thus you do not give `--literature-root`. Read and write the
collection's files at that path.

The search runs with no package installed. One optional package gives a better
order of the results:

```bash
$PY -m pip install -r <this skill's directory>/requirements.txt
```

Step 2 tells you how to read which order you got.

## Step 1. Turn the question into a topic

```bash
$PY $DISCOVER --topic "how meson exchange currents change the quasielastic neutrino cross section"
```

**Write the question as a full phrase.** The script reads `--topic` two times,
and each read uses a different part of it:

1. It removes the common words. It searches arXiv for the terms that remain.
2. It gives the whole phrase to the cross-encoder. The cross-encoder ranks the
   papers against it.

Step 2 reads the words that step 1 removes. Write `how meson exchange currents
change the cross section` and not `meson exchange cross section`. Both send the
same terms to arXiv, but only the first tells the cross-encoder what to rank.

### Phrase a broad question the way a review abstract reads

A broad question needs a review. Write the topic as a review writes its own
abstract. These two forms find different papers:

| Form | What it finds |
|---|---|
| `review of type II superconductors: why they are theoretically motivated` | narrow papers. It reads as a request, and no abstract is written as a request. |
| `we review the present status of high-temperature superconductivity, summarising the theoretical framework, materials and transport measurements` | reviews. It reads as the first sentence of one. |

The reason is the cross-encoder. It compares the topic against an abstract. A
topic that reads like a review abstract therefore scores a review highest.

Six words name the wanted *kind* of paper: `review`, `status`, `present`,
`summarising`, `theoretically` and `motivated`. They never reach arXiv. No
abstract carries them as search terms. A query that asks for them makes every
paper fail the strict rung. The report names them in
`query.meta_terms_dropped`. They stay in the phrase the cross-encoder reads,
and there they do their work.

| Option | What it does |
|---|---|
| `--topic` | the subject, as a phrase. Required. |
| `--category` | an arXiv category, such as `hep-ph`. Repeat it for more. |
| `--since` | earliest year of submission. It is the currency check: `--since 2023` answers "what came out after the papers I hold". |
| `--max-results` | how many papers to report. The default is 15. |
| `--kind` | `any` or `review`. `review` keeps the papers a review venue or an INSPIRE document type names as a review. |
| `--sort` | `relevance`, `recent` or `cited`. It re-orders the papers the ranking chose. It never changes which papers those are. |
| `--literature-root` | where the collection is. The default is `literature`. |

**Each `--sort` answers a different question.** `relevance` answers "which paper
answers my question". `recent` answers "what came out last". `cited` answers
"which paper does the field lean on". Every result keeps its `score` and its
`relevance_rank` in each of the three orders. You thus see how the model ranked
each paper, in every order.

**A search takes about 5 to 9 seconds.** It sends one request to arXiv, and a
second one three seconds later when the first finds little. It then reads up to
a hundred abstracts with the cross-encoder. One INSPIRE request follows the
arXiv requests, and it describes the shortlist with its length and its citation
count. The first search of all also fetches the model, which adds a few seconds
and happens one time. The script writes what it is doing to the error output
while you wait. Wait for it. Do not start a second search because the first
looks slow.

**A category is exact.** `--category astro-ph` excludes `astro-ph.HE`, which is
a separate category and not a part of it. Give both when you want both.

## Step 2. Read the answer

The script prints JSON. Read these fields first:

| Field | What it holds |
|---|---|
| `ranking.backend` | which of the two orders you are reading. See below. |
| `ranking.sort` | the order the results are in. It differs from the order you asked for when no source could answer that order. `ranking.note` then says why. |
| `counts` | how many results are `held`, `cited`, and `new`. |
| `query.terms` | the words the search used. Read them: they show what the script asked arXiv for. |
| `query.meta_terms_dropped` | the words that describe the wanted kind of paper. The search dropped them, the ranking kept them. |
| `query.queries` | the query of each rung that ran. |
| `enrichment` | how many papers of the shortlist INSPIRE described. A `matched` of 0 means that INSPIRE described none of them. Every `citation_count` below is then `null`. |
| `kind_filter` | what `--kind` kept and what it dropped. It is `null` when `--kind` is `any`. |

Then, for each result:

| Field | What it holds |
|---|---|
| `score` | the rank. Its meaning depends on `ranking.backend`. |
| `relevance_rank` | the position the ranking gave this paper, from 1. A re-sort never changes it. |
| `citation_count` | how many papers INSPIRE knows that cite this one. `null` means that INSPIRE holds no record of it. |
| `pages` | the length of the paper. `pages_source` says which source gave it. `null` means that neither source did. |
| `kind` | `review`, `article`, or `unknown`. `unknown` means that no venue and no document type described the paper. Every preprint is of that kind. |
| `coverage` | the share of the terms this paper's title and abstract carry. |
| `missing_terms` | the terms it does not carry. |
| `found_by` | `strict` means the paper carries every term. `broad` means it carries some of them. |
| `held_as`, `known_as`, `cited_by` | what the collection knows. Step 3 uses these. |

**Read `ranking.backend` before you trust the order.**

| `ranking.backend` | What the order means |
|---|---|
| `flashrank:…` | A cross-encoder read the question and each abstract together. The top result answers the question. |
| `coverage` | No cross-encoder is installed. The order counts words only. A paper that repeats the words of the question ranks above one that answers it. |

Do two things when the backend is `coverage`. Tell the user that the order
counts words only. Give the install command from "Before you start".

**A `broad` result is a weak result.** No paper carried every term, so the
search asked for any of them. Read `missing_terms` before you use that paper.

`missing_terms` also shows what a good paper leaves alone. A paper that answers
most of a question and misses one term is still the best answer. The missing
term then tells you what to search for next.

The abstract in `summary` stops at 400 characters. Use it to decide whether the
paper is worth the reading. It is not a source. Do not quote it. Do not cite a
paper from it.

## Step 3. Decide what to do

| The result | What you do |
|---|---|
| `held_as` holds a directory name | The collection holds this paper in full. Read it with `use-literature`. Do not ingest it again. |
| `held_as` holds a directory name, and your task did not put it there | Read the paper. Add it to the working set of your task when its text bears on a sub-question. `research-report/SKILL.md` defines the working set. |
| `known_as` holds a tag, `held_as` is `null` | A paper in the collection cites this work. Run `reference_lookup.py <tag>` for the full record. Ingest it with `add-paper` when the question needs the work itself. |
| both are `null` | The collection does not know this paper. Report it, and offer the `add-paper` skill with the arXiv identifier. |

## Step 4. Weigh a candidate against the papers of your question

A rank says how well a candidate's abstract answers your question. It does not
say whether the candidate builds on the same works as the papers you hold for
that question. `$OVERLAP` answers that from the reference store, which already
holds every work that every held paper cites.

```bash
$PY $OVERLAP <arxiv-id> --scope <slug> --scope <slug>
```

That command is an example. Replace each `<slug>` with a paper of your own
working set, and `<arxiv-id>` with the candidate.

**Run the check on one candidate at a time, and only on a candidate you want to
ingest.** Do not run it over 15 results. INSPIRE limits its rate, and the check
sends its requests one at a time.

**Name the scope.** Give `--scope <slug>` for each paper you hold *for this
question*. The collection is persistent and serves other questions, and their
papers must not decide your band: a candidate that shares nothing with your
subject still shares references with whatever an earlier task ingested, and
measured against all of it that candidate reads `high`. You would then decline
an ingest your question needs. A caller with no such list yet gives no `--scope`,
and the script says so instead of guessing.

**State the cost.** A candidate the collection does not hold costs two requests
to INSPIRE: one resolves the identifier to a record, one reads the reference
list. A paper the collection holds costs no request, because the store answers.
`--resolve` costs one further request for each 40 references that matched
nothing, and it is off by default.

**Read `outside_scope` before you ingest.** A paper there is on disk already, and
it shares references with the candidate. Reading it costs no ingest. Add it to
your working set when its text bears on a sub-question.

A candidate the collection already holds is never compared with itself.
`paper.held_as` names the directory that holds it, and the two lists then say how
it relates to the *other* papers on disk.

**Read `candidate_references.unidentified` before you read any ratio.** It counts
the references that carry no identifier at all. Those leave every set, so a ratio
over a small `identified` base says little.

Then read the `band` and give the user its `reading`:

| `band` | `reading` |
|---|---|
| `high` | "This paper draws on the works you read for this question already. It probably covers ground you hold now. Spend an ingest on it only when the question needs this paper's own words." |
| `partial` | "This paper shares part of its ground with the papers of this question. The number decides nothing on its own. Read the abstract again." |
| `low` | "This paper draws on works the papers of this question do not cite. It brings new ground, and it may also be off the subject. Read the abstract again before you spend an ingest." |
| none | "Too few references carry an identifier. The counts hold. The ratio does not." |

Four rules hold beside that table:

- **Overlap is not relevance.** A candidate with a high overlap can be the paper
  that answers your question best, because it works on the same material.
  Never reject a candidate on this number alone.
- **Overlap is not quality.** It counts shared references. It reads no argument
  and no result.
- **Use the number to put candidates in order** when the budget is tight. Give
  the number in the report when it decided which paper you read.
- **The band answers for your working set alone.** A paper of another task never
  lifts or lowers it. Such a paper appears under `outside_scope`, as something to
  read.

## When the search finds nothing

Try these, in order, one search at a time:

1. Remove the least important word from `--topic`.
2. Remove `--category`.
3. Make `--since` earlier, or remove it.

Then tell the user that arXiv has no paper on the subject. Report that as the
answer. A weak result is worse than no result. Never give one as an answer.

## Rules

- **Run one search at a time.** arXiv limits its rate. Never start a sub-agent
  for each query, and never run several searches at once. A rate limit costs
  more time than the parallel work saves.
- **Run one overlap check at a time.** It asks INSPIRE, and INSPIRE limits its
  rate the same way arXiv does. Never start a sub-agent for each candidate, and
  never run an overlap check beside a search or an ingest.
- **An abstract is not a paper.** Never cite a paper that you found here. You
  read 400 characters of its abstract. That is enough to choose the paper. It is
  not enough to know what the paper says. Ingest it with `add-paper` and read
  it, or cite nothing.
- **Ask before you ingest.** A paper that the user did not name costs a
  download, a conversion, and space on disk. Report what you found. Let the user
  choose.
- **A rank is not a judgement of relevance.** Report the backend that produced
  the order, and report `missing_terms`. Never present position 1 as the answer
  without them.
- **A citation count measures attention, not correctness.** A recent paper that
  settles a question holds few citations. A much-cited paper can be the one the
  field has moved past. Never drop a paper for a low count, and never choose a
  paper for a high one.
- **`--kind review` finds a published review only.** A review that is still a
  preprint has no venue and no document type. Its kind is `unknown`, and the
  filter drops it. Read `kind_filter.dropped_unknown`. Run the search again with
  `--kind any` before you report that the field holds no review.
- **The collection answers for every task, and not for yours.** The collection
  is persistent, and one collection serves many research tasks. A paper is
  `held` because some task ingested it. `cited_by` names the papers of the
  collection that cite the work, and an earlier question chose those papers.
  Read the slugs in `cited_by`. A slug your task did not put there belongs to
  other work. Such a paper is worth reading, because it is on disk already. It
  is not evidence that your question is covered.
- **Report the counts.** The user wants to know what is new. `counts.held` and
  `counts.cited` say how much of the answer was already on disk.
