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
| `TOPIC_STOPWORDS` | 81 words | The words that the script removes from a topic before the topic becomes a query. This set is not `reference_store.TAG_STOPWORDS`: that set drops `measurement` and `effect`, and a search needs those words. It is not `META_TERMS` either: that set holds the words that describe the wanted kind of paper. Add a word here when questions use it and it never separates one paper from another. |
| `META_TERMS` | 6 words | The words that the arXiv query drops and the cross-encoder keeps. Each one says what kind of paper the caller wants. No abstract carries them, and the strict rung fails on them. Add a word here when it describes a wanted paper. A word here that names a subject makes the search return the wrong papers. |
| `AUTHORS_SHOWN` | 3 | How many authors a result names. `authors_total` gives the count of the rest. |
| `ENRICH_CANDIDATES` | 40 | How many of the ranked candidates one INSPIRE request describes. A higher value describes more papers for `--kind` and `--sort` to work over. It costs one further request for each further 40. `references.BATCH_SIZE` is 40, thus this value costs one request. |
| `DEFAULT_SORT` | `relevance` | The order of the shortlist when the caller asks for none. `relevance` answers "which paper answers my question". `recent` and `cited` answer the other two questions. Each is one flag away. |
| `--kind` | `any` | Which kinds of paper the report holds. `review` answers a broad question. It drops a review that is a preprint, because a preprint has no venue. |
| `--max-results` | 15 | How many results the report holds, out of the `CANDIDATES` that the ranking ordered. |

`add-paper/scripts/paper_facts.py` describes a candidate: its length, its kind
and its citation count. None of these enters the score. A citation count and an
author count both point the wrong way for a research question, so they travel
beside the score as fields and the caller decides.

| Parameter | Now | What it does |
|---|---|---|
| `REVIEW_VENUES` | 6 names | The journals that `--kind review` reads as a review. A name added here admits every paper of that journal. A name missing here hides its reviews from the filter. |
| `REVIEW_DOCUMENT_TYPES` | `review` | The INSPIRE document types that `--kind review` reads as a review. INSPIRE gives the type of some records only. |
| `PAGE_COUNT_MAX` | 1000 | The largest page count that the parse of an arXiv comment accepts. A comment is free text, and a number in it can be a volume or a year. A lower value rejects a real long report. A higher value reports a wrong number as a length. |

`add-paper/scripts/rerank.py` orders what the search found.

| Parameter | Now | What it does |
|---|---|---|
| `MODEL_NAME` | `ms-marco-MiniLM-L-12-v2` | The cross-encoder. `ms-marco-TinyBERT-L-2-v2` is 4 MB. It is faster, and it gives a worse order. `rank-T5-flan` is larger, and it is better on a subject far from its training data. FlashRank names the other models. |
| `MAX_TOKENS` | 512 | How much of the question and the abstract the model reads. An abstract holds about 250 words. A lower value gives the model the first sentence only, and the model then ranks on that sentence. |
| `MIN_PREFIX` | 4 | How many first letters make two words the same term. arXiv applies stemming to its index, and this value must agree: `scatter` answers `scattering`. A lower value lets `ion` take `ionisation`. A higher value reports a true stem as a missing term. |
| `MIN_COVERAGE` | 0.34 | The share of the question a candidate must carry before the cross-encoder reads it. A candidate below it stays in the report and sorts after every paper the model read. This value sets the speed of a search: the model takes about 8 seconds for 100 papers, and the broad rung returns papers that carry one term. Measured across four questions, the lowest coverage among the 15 results the model chose was 0.56, so 0.34 leaves a wide margin. Above about 0.6 the model stops reading papers that it would have chosen. |
| `MODEL_CACHE` | `~/.cache/flashrank` | Where the model stays. This is not a quality parameter. FlashRank's own default is `/tmp`, which the system clears. |
| `DOWNLOAD_TIMEOUT_S` | 300.0 | How long the first run waits for the 21 MB model. A stalled download then reports a reason, and the search answers by coverage. |

## Following the citations of a paper

`add-paper/scripts/inspire_citations.py` finds the papers that cite one paper,
and the works that it draws on.

| Parameter | Now | What it does |
|---|---|---|
| `MAX_RESULTS` | 20 | How many papers one direction reports. A well-cited review has thousands of citers, and the report says how many it left behind. A higher value gives more to triage, from one request either way. |
| `CITED_FETCH_CAP` | 40 | How many of a paper's own references the script looks up. This is one batch. A review cites five hundred works, and a higher value costs one more request for each further forty. |
| `DEFAULT_SORT` | `mostcited` | The order of the citing papers when the caller asks for none. `mostcited` answers "what did the field build on this". `mostrecent` answers "what came after it", and is one flag away. |

## Researching a task

`research-report/SKILL.md` runs the loop that answers a task from the
literature. These limits stop the loop. They are not numbers in a script: the
skill states them, and the agent obeys them.

| Parameter | Now | What it does |
|---|---|---|
| `MAX_ITERATIONS` | 4 | How many times the loop can search, read and assess again. A higher value follows a subject further, and costs more time and more API calls. A report that stopped at this limit says so. |
| `MAX_NEW_PAPERS_PER_ITERATION` | 5 | How many papers one iteration ingests. Each ingest happens in a `paper-ingestor` agent, thus the cost is time at arXiv, and not context of the agent that researches. |
| `MAX_TOTAL_INGESTS` | 20 | How many papers the whole task ingests. It bounds a task that keeps finding one more paper worth reading. |
| `DRY_ITERATIONS` | 2 | How many iterations can find no new relevant paper before the loop stops. A lower value stops earlier on a subject that the collection covers already. |
| `MAX_PARALLEL_SCOUTS` | 4 | How many `paper-scout` agents read at one time. A scout calls no API, thus this value trades tokens against waiting. |

## Searching the text

`add-paper/scripts/search_literature.py` finds a phrase in the text of the
papers. Nobody measured these values. Each one is a judgement.

| Parameter | Now | What it does |
|---|---|---|
| `CONTEXT_CHARS` | 300 | How many characters of the matching sentence the answer prints. A higher value shows more of the paragraph and costs more context. A lower value can cut the words that decide whether the passage supports the claim. |
| `MAX_RESULTS` | 20 | How many matches one search reports. A common word matches hundreds of times. A higher value shows more of them, and `--max-results` raises it for one call. |
| `MIN_BACKOFF_WORDS` | 3 | The shortest phrase the backoff tries after the full phrase fails. A lower value finds a match for two words, which most papers carry, and that match says little. A higher value reports no partial match at all. |

## Choosing a model for an agent

The frontmatter of each agent in `.claude/agents/` names its model. A cheaper
model costs less and reads less well.

| Parameter | Now | What it does |
|---|---|---|
| `model` of `paper-ingestor` | `sonnet` | The model that handles an exception of the ingest script. The script does the mechanical work. Two judgements are left: the identity of a paper, and a name that two works want. Each one decides what the collection holds from then on. `haiku` is the cheaper value to try. A wrong paper, or a tag given to the wrong work, costs more than the saving. |
| `model` of `paper-scout` | `haiku` | The model that reads one paper against the sub-questions. This is targeted extraction, and not synthesis. `sonnet` is the value to try when scouts miss a passage that answers a question. |
| `model` of `literature-researcher` | `inherit` | The model that runs the loop and writes the report. It reads no full text, and it makes every judgement. |

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
| `ID_BATCH` | `arxiv_search.py` | 100 | How many identifiers one `id_list` request asks arXiv about. A bibliography holds fewer references than this, so one request answers a whole paper. A lower value sends more requests, and each one waits `COURTESY_DELAY_S`. The API accepts up to 2000. |
| `RENDER_DPI` | `convert_figures.py` | 300 | The resolution that the script renders a vector figure at. A higher value is easier to read and larger on disk. |
| `MAX_PIXELS` | `convert_figures.py` | 2000 | The longest edge of a converted figure. |
| `CROP_MARGIN` | `convert_figures.py` | 8 | How many pixels of whitespace stay around a cropped figure. |
| `PARAGRAPH_ANCHOR_MIN_CHARS` | `arxiv_fetch.py` | 80 | The length under which a block of text gets no paragraph anchor. A lower value addresses more of the chapter, and writes an anchor line above shorter blocks. A higher value leaves a short paragraph addressable only through the paragraph above it. The value is a judgement: one sentence of prose is longer than 80 characters. |
| `RESTORE_PASSES` | `arxiv_fetch.py` | 4 | How often the placeholder restore walks its items. Each pass answers one further level of nesting, such as the maths of a table inside that table. A lower value can leave a `PH<number>` in the text, which the manifest then reports as a warning. A higher value costs one more walk over a text that already holds no key. |
| `SLUG_MIN_CHARS` | `arxiv_search.py` | 24 | The length under which a chapter file name keeps a cut word rather than lose more of the title. A higher value returns more names that end in half a word. A lower value returns shorter and less exact names. |
| `MAX_CONCURRENT_FETCHES` | `add_paper.py` | 2 | How many papers run the fetch stage together. The gate still sends one request at a time. A higher value fills the wait of one request with the work of another paper. It never sends more requests, and each paper in the stage costs memory. |
| `INDEX_SUBSECTIONS_SHOWN` | `write_index.py` | 6 | How many subsection titles one chapter row lists. A higher value says more about a long chapter, and makes the table harder to read. |
| `SLUG_TITLE_WORDS` | `identity.py` | 2 | How many title words the derived slug carries. A higher value separates two papers of one author in one year more often, and gives a longer directory name. |
| `ROW_DESCRIPTION_CHARS` | `collection_index.py` | 160 | How much of the abstract the collection row carries before a summary pass replaces it. |
| `REPORT_WARNINGS_SHOWN` | `add_paper.py` | 10 | How many warnings the compact report prints. The full manifest holds them all. |
| `CANDIDATES_SHOWN` | `identity.py` | 5 | How many candidates an `AMBIGUOUS_TITLE` exception carries for an agent to choose between. A higher value describes more papers, and each one costs the agent context at the moment it has to decide. |
| `AUTHORS_SHOWN` | `write_index.py` and `add_paper.py` | 3 | How many authors the identity table and the report name before `et al.`. `authors_total` gives the count of the rest. |

## Not tunable

These numbers look like tunable parameters. They are not. Something outside this
repository sets each one. A lower value makes nothing faster.

| Parameter | Where | Why it is fixed |
|---|---|---|
| `COURTESY_DELAY_S` | `arxiv_search.py`, 3.0 | arXiv asks for three seconds between calls. A lower value causes a rate limit, and that costs more time than the change saves. |
| `RATE_LIMIT_WINDOW_S` | `inspire_lookup.py`, 5.0 | The rate-limit window of INSPIRE-HEP. The script answers a 429 and then waits out the whole window. |
| `MAX_RETRY_DELAY_S` | `inspire_lookup.py`, 60.0 | A ceiling on the delay that a `Retry-After` header can ask for. A wrong header cannot then stop a run. |
| `INSPIRE_PACE_S` | `inspire_lookup.py`, 0.5 | The pace the INSPIRE API accepts. It sits beside `fetch_record`, which is the one function every INSPIRE request in these scripts passes through. `references.py` reads the name from there. |
| `BATCH_SIZE` | `references.py`, 40 | The batch size the INSPIRE API accepts. `inspire_citations.py` sends its requests through the same functions. |
| `CROSSREF_PACE_S` | `references.py`, 0.5 | The pace Crossref asks of a client with no polite-pool token. |
| `HOST_INTERVALS` | `rate_gate.py` | The pace each API asks for, one entry per host. Each value is registered by the module that owns the constant, so a pace has one definition. |
| `DEFAULT_INTERVAL_S` | `rate_gate.py`, 1.0 | What a host nobody registered gets. It is slower than every pace registered, so an unknown host is paced conservatively rather than not at all. |
| `GATE_WAIT_TIMEOUT_S` | `rate_gate.py`, 120.0 | How long a caller waits for the lock. It bounds a wait, and it makes nothing faster. |
| `LOCK_POLL_S` | `rate_gate.py`, 0.05 | How often a waiting caller retries the lock. Short enough that a caller takes the gate promptly after the holder releases it. |
| `REQUEST_TIMEOUT_S` and `CROSSREF_TIMEOUT_S` | four scripts, 20 to 120 | How long a script waits for a server. `arxiv_fetch.py` waits the longest, at 120, because it downloads an archive of the source. |
| `MAX_RETRIES` | two scripts, 3 | How many times a script repeats a failed request. |
