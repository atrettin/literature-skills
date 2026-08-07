# Tunable parameters

Every number here changes the quality of an answer. None of them changes whether
the answer is correct.

The scripts run with any of these values. Some values give better answers than
others. No test can say which value is best. The best value depends on the
collection, and on the questions that people ask of it.

This file lists the numbers so that a person who wants a better answer knows
which ones to change. It does not say what the values must be. **Nobody measured
them.** Each one is a judgement.

**Add a new parameter of this kind to this file, in the change that adds it to
the code.** A number that stays in the code with no row here is a number that
the next person cannot find.

The last section lists numbers that look tunable. They are not. Read that
section before you change a delay.

## How to change one

1. Change the value in the script. Each parameter is a module constant, and a
   comment above it gives its reason. Update that comment.
2. Update the row in this file.
3. Run `.venv/bin/python -m pytest`. Some tests name a parameter. Those tests
   assert a relationship and not a value: one test asserts that a prefix of four
   letters matches and a prefix of three letters does not. A test that fails
   names the relationship that you changed. Decide whether the relationship was
   wrong, or the value.
4. Run one real search. Read the result. The offline tests cannot tell you
   whether an answer is better.

## Finding papers

`add-paper/scripts/arxiv_discover.py` searches arXiv for a subject.

| Parameter | Now | What it does |
|---|---|---|
| `CANDIDATES` | 100 | How many papers arXiv returns for the ranking to choose from. A higher value finds a good paper that arXiv put far down. It costs one larger response, and more work for the cross-encoder. |
| `MIN_RESULTS` | 5 | The strict rung gives too little below this number of hits, and the broad rung then runs. A higher value widens the search more often. The search then finds more papers, and a larger part of what it finds is noise. **Change this one first.** |
| `MAX_TERMS` | 12 | How many words of the topic reach the query. A longer question sends its first twelve terms only. |
| `MIN_TERM_CHARS` | 3 | The query drops a shorter word. A higher value drops `pion`. A lower value keeps `of`, and `TOPIC_STOPWORDS` must then remove it. |
| `TOPIC_STOPWORDS` | 81 words | The words that the script removes from a topic before the topic becomes a query. This set is not `reference_store.TAG_STOPWORDS`: that set drops `measurement` and `effect`, and a search needs those words. Add a word here when questions use it and it never separates one paper from another. |
| `AUTHORS_SHOWN` | 3 | How many authors a result names. `authors_total` gives the count of the rest. |
| `--max-results` | 15 | How many results the report holds, out of the `CANDIDATES` that the ranking ordered. |

`add-paper/scripts/rerank.py` orders what the search found.

| Parameter | Now | What it does |
|---|---|---|
| `MODEL_NAME` | `ms-marco-MiniLM-L-12-v2` | The cross-encoder. `ms-marco-TinyBERT-L-2-v2` is 4 MB. It is faster, and it gives a worse order. `rank-T5-flan` is larger, and it is better on a subject far from its training data. FlashRank names the other models. |
| `MAX_TOKENS` | 512 | How much of the question and the abstract the model reads. An abstract holds about 250 words. A lower value gives the model the first sentence only, and the model then ranks on that sentence. |
| `MIN_PREFIX` | 4 | How many first letters make two words the same term. arXiv applies stemming to its index, and this value must agree: `scatter` answers `scattering`. A lower value lets `ion` take `ionisation`. A higher value reports a true stem as a missing term. |
| `MODEL_CACHE` | `~/.cache/flashrank` | Where the model stays. This is not a quality parameter. FlashRank's own default is `/tmp`, which the system clears. |

## Matching a paper you can name

`add-paper/scripts/arxiv_search.py` finds one paper that you can name.

| Parameter | Now | What it does |
|---|---|---|
| `EXACT_TITLE_RATIO` | 0.95 | The similarity above which two titles are the same title. The caller then stops and asks nothing. A lower value ingests a wrong paper without a question. A higher value asks the user about papers that agree plainly. |
| `APPROX_TITLE_RATIO` | 0.60 | The similarity below which the report drops a result. |
| `SUMMARY_CHARS` | 400 | How much of an abstract a result carries. `arxiv_discover.py` uses this value too. It is enough to choose a paper. It is never enough to cite one. |
| word length `> 2` and `> 3` | in `build_fallback_query` and `build_loose_query` | Which title words go into a looser query. A title renders its short words differently, so the query drops those first. |
| author and year bonus | 0.02 each, in `score_entry` | How much an author or a year that agrees lifts the score of a title. |

## The collection

| Parameter | Where | Now | What it does |
|---|---|---|---|
| `TAG_STOPWORDS` | `reference_store.py` | 38 words | The words that a citation tag leaves out. A tag must stay short enough to read inside a sentence. |
| `TAG_TITLE_WORDS` | `reference_store.py` | 4 | How many title words a tag carries. A higher value makes a tag more exact and harder to read. |
| `DEFAULT_AUTHORS` | `reference_lookup.py` | 3 | How many authors a resolved citation names. |
| `MAX_AUTHORS` | `update_references.py` | 3 | The same, for the rendered `REFERENCES.md` table. |
| `MAX_CITED_BY` | `update_references.py` | 8 | How many citing papers one row of that table lists. |

## Ingesting a paper

| Parameter | Where | Now | What it does |
|---|---|---|---|
| `DEFAULT_MAX_CHAPTER_BYTES` | `arxiv_fetch.py` | 40000 | The script divides a section larger than this across more than one file. The value sets how much context one chapter costs an agent that reads it. |
| `FIGURE_WIDTH_PX` | `arxiv_fetch.py` | 500 | The display width of a figure in a chapter. |
| `RENDER_DPI` | `convert_figures.py` | 300 | The resolution that the script renders a vector figure at. A higher value is easier to read and larger on disk. |
| `MAX_PIXELS` | `convert_figures.py` | 2000 | The longest edge of a converted figure. |
| `CROP_MARGIN` | `convert_figures.py` | 8 | How many pixels of whitespace stay around a cropped figure. |

## Not tunable

These numbers look like tunable parameters. They are not. Something outside this
repository sets each one. A lower value makes nothing faster.

| Parameter | Where | Why it is fixed |
|---|---|---|
| `COURTESY_DELAY_S` | `arxiv_search.py`, 3.0 | arXiv asks for three seconds between calls. A lower value causes a rate limit, and that costs more time than the change saves. |
| `RATE_LIMIT_WINDOW_S` | `inspire_lookup.py`, 5.0 | The rate-limit window of INSPIRE-HEP. The script answers a 429 and then waits out the whole window. |
| `MAX_RETRY_DELAY_S` | `inspire_lookup.py`, 60.0 | A ceiling on the delay that a `Retry-After` header can ask for. A wrong header cannot then stop a run. |
| `INSPIRE_PACE_S` and `BATCH_SIZE` | `references.py`, 0.5 and 40 | The pace and the batch size that the INSPIRE API accepts. |
| `REQUEST_TIMEOUT_S` and `CROSSREF_TIMEOUT_S` | four scripts, 20 to 120 | How long a script waits for a server. `arxiv_fetch.py` waits the longest, at 120, because it downloads an archive of the source. |
| `MAX_RETRIES` | two scripts, 3 | How many times a script repeats a failed request. |
