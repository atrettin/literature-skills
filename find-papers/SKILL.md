---
name: find-papers
description: Finds papers on arXiv, locally or on the literature server — one paper you can name by its title (or part of it), author or year, or the papers on a subject — and says which of them the collection already holds. Use before add-paper whenever the arXiv identifier is not known, and when a research question needs a paper that the collection may not hold yet.
---

# Find papers on arXiv

This skill finds. It does not add a paper to the collection. When you have the
arXiv identifier of the paper you want, the `add-paper` skill adds it.

**Start here.** Which search do you need?

1. **One paper that someone named**: by its title, part of its title, an author
   or a year. Go to "Find one paper you can name". With a DOI and nothing
   else, go to "Find a paper by its DOI".
2. **Papers on a subject**: a question, not a paper. Use `use-literature` first,
   because the collection may answer it already. Then go to "Step 1. Turn the
   question into a topic".

Never search arXiv any other way: no `curl`, no web fetch, no script of your
own. `find` is the only way in.

Each result says whether the collection holds that paper. You thus see what is
new and what is on disk already.

## Before you start

**On the literature server** (which place to use: see `use-literature`), the
search is the `find` tool. Its parameters have the names of the options below:
`litdb find --title "..." --year 2019` is `find(title="...", year=2019)`.

**On the local collection**, run every command from the root of the project, so
that `literature/` resolves. The collection is at `$LITERATURE_ROOT` when that
variable is set. If it is not set, it is `literature/` in the project. `litdb`
reads the variable itself, thus you do not give `--literature-root`.

## Find one paper you can name

```bash
litdb find --title "PART OF THE TITLE" --author "SURNAME" --year YEAR
```

Give what you have, and leave out what you do not have. Part of a title is
enough. A surname narrows the search. Give `--year` only when you are sure of
it: the search covers that year and the year before.

`--category`, `--since`, `--kind` and `--sort` belong to the subject search.
With `--title` they are a usage error.

**Read the exit status first** (on the server: the `exit` field):

| Exit | What it means | What you do |
|---|---|---|
| 0 | An answer. | Read `match`, below. |
| 1 | arXiv did not answer. `error` says why. | Report it, and try again later. This is not `none`: never report that arXiv lacks the paper. |
| 2 | A usage error. `error` says which. | Fix the call, and run it again. |

The answer has a `match` for the whole search, and one for each result:

| `match` | What it means |
|---|---|
| `exact` | One result agrees with everything you gave. |
| `approximate` | Results resemble the search, but none agrees closely, or more than one does. This is the usual answer for part of a title. |
| `none` | Nothing resembles the search. `results` is empty. |

Each result carries `arxiv_id`, `title`, `authors` (first three),
`authors_total`, `year` (of the arXiv preprint),
`summary`, `doi`, `journal_ref`, `match`, `held_as`, `known_as` and
`cited_by`.

### Settle which paper it is

Do this for every answer, `exact` included. `match` compares titles, and a
title is the weakest evidence of identity.

**The DOI, the journal reference and the author list decide identity — not the
title, and not `match`.** Test each result in this order:

1. **The user gave a DOI.** The result's `doi` is the same: it fits, stop
   testing. It is another DOI: it does not fit, stop testing. It is empty: go on.
2. **The user gave a journal.** Compare it with `journal_ref`. An empty
   `journal_ref` says nothing: most preprints have none.
3. **The user gave an author.** A surname among `authors` agrees. A surname
   not among them, when `authors_total` is more than 3, does not disagree:
   only the first three are shown.
4. **The user gave a year.** It may be the result's `year` or a later one: the
   user usually quotes the journal year, and `year` is the preprint's.
5. **The title.** Words of the user's title in the result's `title` agree.
   Notation and small words may differ.

A result fits when nothing in steps 1–5 disagrees, and at least one step
agrees. Then:

   - **Exactly one result fits.** Its `arxiv_id` is the identifier.
     - Its `held_as` names a directory: the collection holds the paper
       already. Locally, report `held_as` and stop; do not run `add-paper`. On
       the server, `add` it: it is `listed` in your library at once.
     - Its `held_as` is `null`: follow `add-paper` with that identifier.
   - **Two or more fit equally well.** Ask the user. Show each one with its
     `arxiv_id`, title, first author and year. Do not choose for the user.
   - **None fits.** Go to "When the paper is not in the results".

### Find a paper by its DOI

- **Local:** `litdb inspire --doi DOI`. Its `arxiv_id` is the identifier.
- **Server:** `citations(doi="DOI", max_results=1)`. Its `paper.arxiv_id` is
  the identifier. (The server has no `inspire` tool.)

Then confirm it: `find --title` with the title the answer gives, and check that
the result's `doi` is the DOI. An empty `arxiv_id` means that INSPIRE knows no
arXiv version: see the end of the next section.

### When the paper is not in the results

Three known causes hide a paper that arXiv holds. Try them in this order, one
search at a time:

1. **The year is the journal year.** A preprint can come more than a year
   before its journal. Search again without `--year`.
2. **The notation differs.** `$C_5^A$` against `C(5)_A`, or `medium nuclei`
   against `medium-mass nuclei`. Search again with only the plainest,
   most distinctive words of the title.
3. **The preprint has another title.** Authors retitle papers between arXiv and
   the journal; Phys. Rev. C91 045501 is "Investigation of recent weak
   single-pion production data", and its preprint is "On Recent Weak Single
   Pion Production Data". Then:
   - With a DOI: "Find a paper by its DOI", above.
   - With an author: search with `--author` and `--year` and no title.
   - Otherwise: search the subject of the title with `--topic`.

Still nothing? Report that arXiv does not hold the paper, and say what you
searched. An INSPIRE record whose title agrees and whose `arxiv_id` is empty
means that nobody posted the paper to arXiv; many theses and older proceedings
are of that kind. **That is a real answer. Never add a similar paper instead.**

## Step 1. Turn the question into a topic

`litdb find` orders its results with a cross-encoder when one is installed. Step 2
tells you how to read which order you got.

```bash
litdb find --topic "how meson exchange currents change the quasielastic neutrino cross section"
```

**Write the question as a full phrase.** `litdb find` reads `--topic` two times,
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

### The options of a subject search

| Option | What it does |
|---|---|
| `--topic` | the subject, as a phrase. Required. |
| `--category` | an arXiv category, such as `hep-ph`. Repeat it for more. |
| `--since` | earliest year of submission. It is the currency check: `--since 2023` answers "what came out after the papers I hold". |
| `--max-results` | how many papers to report. The default is 15. |
| `--kind` | `any` or `review`. `review` keeps the papers a review venue or an INSPIRE document type names as a review. |
| `--sort` | `relevance`, `recent` or `cited`. It re-orders the papers the ranking chose. It never changes which papers those are. |
| `--literature-root` | where the collection is. The default is `literature`. |
| `--full` | report every field. Without it, the fields marked "`--full` only" in step 2 are left out. |

**Each `--sort` answers a different question.** `relevance` answers "which paper
answers my question". `recent` answers "what came out last". `cited` answers
"which paper does the field lean on". Every result keeps its `score` and its
`relevance_rank` in each of the three orders. You thus see how the model ranked
each paper, in every order.

**A search takes about 5 to 9 seconds.** It sends up to three requests to
arXiv: the strict one, and two that widen when the one before finds little. It
then reads the abstract of every candidate that carries at least a third of
the terms, with the cross-encoder. One INSPIRE request follows the arXiv
requests, and it describes the shortlist with its length and its citation
count. The first search of all also fetches the model, which adds a few seconds
and happens one time. It writes what it is doing to the error output while you
wait. Wait for it. Do not start a second search because the first looks slow.

**A category is exact.** `--category astro-ph` excludes `astro-ph.HE`, which is
a separate category and not a part of it. Give both when you want both.

## Step 2. Read the answer

It prints JSON. The answer is short by default. A field marked "`--full` only"
is there only when you gave `--full`. Ask for `--full` in three cases, and in no
other: to see why a paper ranked where it did (`query.term_weights`,
`coverage`), to get a paper's DOI or its length (`doi`, `pages`), or to see
whether INSPIRE answered at all when every `citation_count` is `null`
(`enrichment`).

Read these fields first:

| Field | What it holds |
|---|---|
| `ranking.backend` | which of the two orders you are reading. See below. |
| `ranking.sort` | the order the results are in. It differs from the order you asked for when no source could answer that order. `ranking.note` then says why. |
| `counts` | how many results are `held`, `cited`, and `new`. |
| `query.terms` | the words the search used. Read them: they show what the search asked arXiv for. |
| `query.meta_terms_dropped` | the words that describe the wanted kind of paper. The search dropped them, the ranking kept them. |
| `query.queries` | `--full` only. The query of each rung that ran. |
| `query.term_weights` | `--full` only. What each term was worth to the order. A term that nearly every candidate carries weighs almost nothing, because it separated none of them; a term that one candidate carries weighs everything. This is why a paper can rank first while carrying fewer of the words than the paper below it. |
| `enrichment` | `--full` only. How many papers of the shortlist INSPIRE described. A `matched` of 0 means that INSPIRE described none of them. Every `citation_count` below is then `null`. |
| `kind_filter` | what `--kind` kept and what it dropped. It is absent when `--kind` is `any` (`null` with `--full`). |

Then, for each result:

| Field | What it holds |
|---|---|
| `score` | the rank. Its meaning depends on `ranking.backend`. |
| `relevance_rank` | the position the ranking gave this paper, from 1. A re-sort never changes it. It is there when `--sort` is `recent` or `cited`, or with `--full`. |
| `citation_count` | how many papers INSPIRE knows that cite this one. `null` means that INSPIRE holds no record of it. |
| `pages` | `--full` only. The length of the paper. `pages_source` says which source gave it. `null` means that neither source did. |
| `kind` | `review`, `article`, or `unknown`. `unknown` means that no venue and no document type described the paper. Every preprint is of that kind. |
| `coverage` | `--full` only. The share of the terms this paper's title and abstract carry, weighed by `query.term_weights`. It is not the plain count: missing the one term that picks a paper out costs nearly all of it, and missing a term that every candidate carries costs almost none. |
| `missing_terms` | the terms it does not carry. This is the plain list, unweighed — check it against the abstract. |
| `found_by` | `strict` means the paper carries every term. `broad` means it carries some of the terms. |
| `held_as`, `known_as`, `cited_by` | what the collection knows. Step 3 uses these. |

**Read `ranking.backend` before you trust the order.**

| `ranking.backend` | What the order means |
|---|---|
| `flashrank:…` | A cross-encoder read the question and each abstract together. The top result answers the question. |
| `coverage` | No cross-encoder is installed. The order counts words only. A paper that repeats the words of the question ranks above one that answers it. |

Do two things when the backend is `coverage`. Tell the user that the order
counts words only, and give them the install command: `pip install flashrank`.

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
| `known_as` holds a tag, `held_as` is `null` | A paper in the collection cites this work. Run `litdb lookup <tag>` for the full record. The caller ingests it with `add-paper` when the question needs the work itself. |
| both are `null` | The collection does not know this paper. Report it with its arXiv identifier. Whether to ingest it is the caller's decision, and `add-paper` is the skill that adds it. |

On the server, `held_as` means that the collection holds the paper. Your
library may still not list it: `add` with its identifier lists it at once, with
no ingest.

## Step 4. Weigh a candidate against the papers of your question

A rank says how well a candidate's abstract answers your question. It does not
say whether the candidate builds on the same works as the papers you hold for
that question. `litdb overlap` answers that from the reference store, which already
holds every work that every held paper cites.

```bash
litdb overlap <arxiv-id> --scope <slug> --scope <slug>
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
an ingest your question needs. The flag is required, so a caller with no such
list yet does not run the check: there is no set to measure against. On the
server, `overlap` falls back to the default library when `scope` is missing,
and that library holds the papers of other tasks: always pass
`scope=[...]` with the slugs of your working set.

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

## When the subject search finds nothing

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
  not enough to know what the paper says. The caller ingests it with `add-paper`
  and reads it, or cites nothing.
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
