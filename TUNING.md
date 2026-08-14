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

`lit/arxiv_discover.py` searches arXiv for a subject.

| Parameter | Now | What it does |
|---|---|---|
| `CANDIDATES` | 100 | How many papers arXiv returns for the ranking to choose from. A higher value finds a good paper that arXiv put far down. It costs one larger response, and more work for the cross-encoder. |
| `MIN_RESULTS` | 5 | A rung gives too little below this number of hits, and the next rung then runs. A higher value widens the search more often. The search then finds more papers, and a larger part of what it finds is noise. **Change this one first.** |
| `PHRASE_MAX_WORDS` | 6 | The longest topic that the title rung asks arXiv for as a quoted title. A caller who names a paper fails the strict rung, because an abstract rarely carries every word of a title. A higher value spends a request on a topic that no title reads like, and the rung then returns nothing. A lower value drops a caller who names a paper by its full title. |
| `MAX_TERMS` | 12 | How many words of the topic reach the query. A longer question sends its first twelve terms only. |
| `MIN_TERM_CHARS` | 3 | The query drops a shorter word. A higher value drops `pion`. A lower value keeps `of`, and `TOPIC_STOPWORDS` must then remove it. |
| `TOPIC_STOPWORDS` | 81 words | The words that the script removes from a topic before the topic becomes a query. This set is not `reference_store.TAG_STOPWORDS`: that set drops `measurement` and `effect`, and a search needs those words. It is not `META_TERMS` either: that set holds the words that describe the wanted kind of paper. Add a word here when questions use it and it never separates one paper from another. |
| `META_TERMS` | 6 words | The words that the arXiv query drops and the cross-encoder keeps. Each one says what kind of paper the caller wants. No abstract carries them, and the strict rung fails on them. Add a word here when it describes a wanted paper. A word here that names a subject makes the search return the wrong papers. |
| `AUTHORS_SHOWN` | 3 | How many authors a result names. `authors_total` gives the count of the rest. |
| `ENRICH_CANDIDATES` | 40 | How many of the ranked candidates one INSPIRE request describes. A higher value describes more papers for `--kind` and `--sort` to work over. It costs one further request for each further 40. `references.BATCH_SIZE` is 40, thus this value costs one request. |
| `DEFAULT_SORT` | `relevance` | The order of the shortlist when the caller asks for none. `relevance` answers "which paper answers my question". `recent` and `cited` answer the other two questions. Each is one flag away. |
| `--kind` | `any` | Which kinds of paper the report holds. `review` answers a broad question. It drops a review that is a preprint, because a preprint has no venue. |
| `--max-results` | 15 | How many results the report holds, out of the `CANDIDATES` that the ranking ordered. |

`lit/paper_facts.py` describes a candidate: its length, its kind
and its citation count. None of these enters the score. A citation count and an
author count both point the wrong way for a research question, so they travel
beside the score as fields and the caller decides.

| Parameter | Now | What it does |
|---|---|---|
| `REVIEW_VENUES` | 6 names | The journals that `--kind review` reads as a review. A name added here admits every paper of that journal. A name missing here hides its reviews from the filter. |
| `REVIEW_DOCUMENT_TYPES` | `review` | The INSPIRE document types that `--kind review` reads as a review. INSPIRE gives the type of some records only. |
| `PAGE_COUNT_MAX` | 1000 | The largest page count that the parse of an arXiv comment accepts. A comment is free text, and a number in it can be a volume or a year. A lower value rejects a real long report. A higher value reports a wrong number as a length. |

`lit/rerank.py` orders what the search found.

| Parameter | Now | What it does |
|---|---|---|
| `MODEL_NAME` | `ms-marco-MiniLM-L-12-v2` | The cross-encoder. `ms-marco-TinyBERT-L-2-v2` is 4 MB. It is faster, and it gives a worse order. `rank-T5-flan` is larger, and it is better on a subject far from its training data. FlashRank names the other models. |
| `MAX_TOKENS` | 512 | How much of the question and the abstract the model reads. An abstract holds about 250 words. A lower value gives the model the first sentence only, and the model then ranks on that sentence. |
| `MIN_PREFIX` | 4 | How many first letters make two words the same term. arXiv applies stemming to its index, and this value must agree: `scatter` answers `scattering`. A lower value lets `ion` take `ionisation`. A higher value reports a true stem as a missing term. |
| `term_weights` smoothing | `log(1 + N/df)` | What one term of the question is worth, against `N` candidates of which `df` carry it. A term that nearly every candidate carries chose none of them, and weighs almost nothing; a term that one carries weighs everything. The `1 +` is what keeps a common term worth a little rather than nothing: without it, a question whose every term the whole set carries would weigh zero and every candidate would score zero. A steeper function separates a rare term further, and makes the order turn on one word. The separation grows with `N`, so a search that returns few candidates weighs its terms more evenly. |
| `MIN_COVERAGE` | 0.34 | The share of the question a candidate must carry before the cross-encoder reads it, weighed by `term_weights` — so a candidate that misses the one word which picks the paper out falls below this even when it carries every other word. Where the terms of a question are of similar rarity the weights are near-equal, and this share is then the plain count of terms. A candidate below it stays in the report and sorts after every paper the model read. This value sets the speed of a search: the model takes about 8 seconds for 100 papers, and the broad rung returns papers that carry one term. Measured across four questions, the lowest coverage among the 15 results the model chose was 0.56, so 0.34 leaves a wide margin. Above about 0.6 the model stops reading papers that it would have chosen. |
| `MODEL_CACHE` | `~/.cache/flashrank` | Where the model stays. This is not a quality parameter. FlashRank's own default is `/tmp`, which the system clears. |
| `DOWNLOAD_TIMEOUT_S` | 300.0 | How long the first run waits for the 21 MB model. A stalled download then reports a reason, and the search answers by coverage. |

## Following the citations of a paper

`lit/inspire_citations.py` finds the papers that cite one paper,
and the works that it draws on.

| Parameter | Now | What it does |
|---|---|---|
| `MAX_RESULTS` | 20 | How many papers one direction reports. A well-cited review has thousands of citers, and the report says how many it left behind. A higher value gives more to triage, from one request either way. |
| `CITED_FETCH_CAP` | 40 | How many of a paper's own references the script looks up. This is one batch. A review cites five hundred works, and a higher value costs one more request for each further forty. |
| `DEFAULT_SORT` | `mostcited` | The order of the citing papers when the caller asks for none. `mostcited` answers "what did the field build on this". `mostrecent` answers "what came after it", and is one flag away. |

## Discovering the other names of a subject

`lit/terminology_scan.py` weighs the multiword terms of the papers
in scope and of the titles they cite.

| Parameter | Now | What it does |
|---|---|---|
| `NGRAM_SIZES` | `(2, 3)` | The lengths of a term. Adding 4 finds a longer name, and most 4-grams are one title each. Adding 1 reports single words, which are what the query's term list already holds. |
| `STRUCTURE_WEIGHTS` | heading 6, abstract 4, caption 2, body 1, title 1 | What one occurrence of a term is worth, by the kind of text that holds it. A heading is the author naming what a section is about, and a paragraph is the author using the name in passing. Flatten these towards 1 and the report becomes a frequency count of the prose, where the words of the argument outweigh the names of the objects. Raise `heading` further and a paper with few headings offers few terms at all. |
| `MIN_WEIGHT` | 4 | How much weight a term must carry before it is reported. A cited title weighs 1, so a title-only scan needs this many titles. A lower value finds a name that few papers use, and it reports more phrases that name nothing. |
| `MAX_TERMS` | 20 | How many terms the report holds. Each one costs the agent a judgement, and some of them cost a scout. |
| `EXAMPLES_PER_TERM` | 3 | How many places a term names as evidence. This is what an agent reads to see what the term is about, before it starts a scout. |
| `SUBSUME_RATIO` | 0.8 | A shorter term goes when a longer term that holds it reaches this share of its weight. A lower value keeps both "myocardial infarction" and "acute myocardial infarction". A higher value reports the shorter term more often. |
| `SHARED_WORD_PENALTY` | 1.0 | How much a word shared with the topic lowers the score of a term. The scan exists to find the names the query could not reach, and a term built from the query's own words is no discovery: it sends the next search where the last one went. At 1.0 a term counts only the share of its words that are new. At 0 the order is the weight alone, and the report then leads with restatements of the query — "acute heart attack", "heart attack risk" — because those are the phrases a corpus about the subject repeats most. |
| `TITLE_FURNITURE` | 27 words | The words that describe a kind of paper and not a subject. A term never begins or ends with one, so "search for heavy" does not reach the report. A word inside a term stays. Add a word here when it leads many titles of your field, and when it separates no subject from another. |
| `PROSE_FURNITURE` | 16 words | The apparatus of running prose: the words that point at a citation, an equation or a figure. A term never begins or ends with one, so "et al" does not lead the report of every paper. A title holds none of them, and this list is why the text source is readable at all. Add a word only when it names nothing in any field the collection covers — "section" belongs to "cross section", and "right" to "right-handed", so neither is here. |
| `ALIAS_CUES`, `ALIAS_CUE_PHRASES` | `or`, `also called`, `sometimes referred to as`, a bracket, and 8 more | The constructions with which an author joins two names for one thing. Adding a cue finds an alias written another way, and a cue that is also ordinary prose ("and", "with") turns the block into a list of everything near the subject. |
| `ALIAS_WINDOW` | 6 | How far from the topic word a cue and a name may stand, in words. Wider finds a name that a long clause separates from the subject, and it reports the words of a neighbouring clause as a name. |
| `MAX_BRACKET_WORDS` | 3 | How long a bracketed span can be and still count as a name. Above this the brackets hold a clause, and the sentence is doing something other than naming twice. |
| `MAX_PIVOT_BRACKET_WORDS` | 2 | How long a bracketed span can be and still count as the subject written beside its other name — "an acute coronary (heart attack) event". A citation carries an author and a year, so it does not fit, and that is what keeps the block from reporting the words beside every citation a paper makes. Raise it and the block fills with the neighbours of citations. |
| `MAX_ALIASES` | 10 | How many alias claims the report holds. The block exists to be read in full, and each entry costs the reader a sentence. |

`MIN_PREFIX` needs no row of its own. `lit/terminology_scan.py` imports it from
`lit/rerank.py`, through `term_matches`, and the row there covers it.

Two things here are not tunable, and both are decided by the text.

The word that anchors the alias search is the topic word that the fewest units
hold. "Attack" separates the subject; "heart" fires on every sentence of a
cardiology paper and would report its whole vocabulary. A parameter would only
let somebody choose the wrong one.

Whether two spellings are one name is settled by what the corpus attests.
"Infarctions" gives "infarction" because the papers write "infarction" too;
"stress" keeps its `s` because nothing writes "stres". No rule of English is
applied, and no threshold decides it.

Every value here is a judgement. Nobody measured any of them.

## Weighing a candidate against the collection

`lit/collection_overlap.py` says how much of what a candidate paper
cites the papers in scope know already. It reports a coefficient, and it turns
that coefficient into a band and a fixed sentence.

| Parameter | Now | What it does |
|---|---|---|
| `MIN_COMPARABLE_REFS` | 10 | How many identified references a candidate needs before the script gives a band. One reference moves the coefficient by `1/N`, so a short list gives a ratio that swings. A higher value gives a band to fewer candidates, and each band it does give holds better. The counts hold at every size and are always reported. |
| `HIGH_OVERLAP` | 0.15 | At this coefficient and above, the reading says the candidate covers ground the papers of the question hold already. A lower value warns about more candidates, and it thus holds back a paper that brings something new. A higher value lets more duplicates through. |
| `LOW_OVERLAP` | 0.05 | Below this coefficient the reading says the candidate brings new ground. A higher value calls more candidates new, and new also means off the subject. |
| `RESOLVE_CAP` | 120 | How many unmatched references `--resolve` looks up. This is three batches of `references.BATCH_SIZE`, and thus three requests. A higher value matches more of the long bibliography of a review, at one further request per further batch. |
| `MAX_PAPERS` | 10 | How many held papers the `closest` and `outside_scope` lists report. The `overlap` comes from the first row of `closest`; the rows under it show whether one held paper is close or many are. |

Every value here is a judgement. Nobody measured any of them.

The scope is not tunable, and it has no default. `--scope <slug>` and
`--all-papers` are a required pair, the way `--in-text`, `--cited-by` and
`--all-papers` are for `lit/terminology_scan.py`. A collection is persistent and serves every task that
came before yours, so a band measured over all of it answers for those tasks and
not for your question.

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
| `MAX_TERMINOLOGY_SCOUTS` | 3 | How many terms of one scan go to a `terminology-scout`. A scout calls no API, thus this value trades tokens against the number of terms that stay unclear. |
| `FIRST_PROSPECT_ITERATION` | 2 | The earliest iteration in which a `terminology-prospector` may run. The scan is free and the prospector reads a whole paper, so the free method goes first and gets a whole iteration to work. A value of 1 spends tokens before anybody knows whether they were needed. A higher value delays the only method that finds a name carrying no string to match, and `MAX_ITERATIONS` is 4. |
| `MAX_PROSPECTORS` | 2 | How many papers one iteration reads for their vocabulary. Each one costs about as much as a `paper-scout`. A higher value covers a working set whose papers use different words; the terms of two papers already overlap heavily, because they are the words of one field. |
| `MAX_PROPOSED_TERMS` | 6 | How many names one prospector reports. Each one may then cost a scout or a search. A higher value returns the paper's whole vocabulary, and most of a paper's vocabulary names something other than the subject. |
| `CURRENCY_GRACE_MONTHS` | 12 | How young a paper must be for the loop to mark a sub-question answered without a forward-citation search on it. A higher value skips the search more often, and a conclusion can then rest on work that a later paper overtook. A lower value spends one INSPIRE request on a paper that few works can yet cite. This value is a judgement: a preprint of the last year has few citers, and a paper of two years can already carry a correction. Nobody measured it. |

## Searching the text

`lit/search_literature.py` finds a phrase in the text of the
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
| `model` of `terminology-scout` | `sonnet` | The model that says how one term relates to the subject. This is judgement about a referent, and not extraction. `haiku` is the cheaper value to try, and a smaller model tends to answer `yes` where the true answer is `narrower` — which is the failure this agent exists to prevent. |
| `model` of `terminology-prospector` | `sonnet` | The model that reads a whole paper for the names it gives the subject. It must separate a name for the subject from a topic the paper discusses beside it, and then judge the referent as a scout does. `haiku` is the cheaper value to try, and a smaller model returns the paper's subject headings as names. |
| `model` of `paper-scout` | `haiku` | The model that reads one paper against the sub-questions. This is targeted extraction, and not synthesis. `sonnet` is the value to try when scouts miss a passage that answers a question. |
| `model` of `literature-researcher` | `inherit` | The model that runs the loop and writes the report. It reads no full text, and it makes every judgement. |

## Matching a paper you can name

`lit/arxiv_search.py` finds one paper that you can name.

| Parameter | Now | What it does |
|---|---|---|
| `EXACT_TITLE_RATIO` | 0.95 | The similarity above which two titles are the same title. The caller then stops and asks nothing. A lower value ingests a wrong paper without a question. A higher value asks the user about papers that agree plainly. |
| `APPROX_TITLE_RATIO` | 0.60 | The similarity below which the report drops a result. |
| `SUMMARY_CHARS` | 400 | How much of an abstract a result carries. `lit/arxiv_discover.py` uses this value too. It is enough to choose a paper. It is never enough to cite one. |
| word length `> 2` and `> 3` | in `build_fallback_query` and `build_loose_query` | Which title words go into a looser query. A title renders its short words differently, so the query drops those first. |
| author and year bonus | 0.02 each, in `score_entry` | How much an author or a year that agrees lifts the score of a title. |

## The collection

| Parameter | Where | Now | What it does |
|---|---|---|---|
| `TAG_STOPWORDS` | `lit/reference_store.py` | 38 words | The words that a citation tag leaves out. A tag must stay short enough to read inside a sentence. |
| `TAG_TITLE_WORDS` | `lit/reference_store.py` | 4 | How many title words a tag carries. A higher value makes a tag more exact and harder to read. |
| `DEFAULT_AUTHORS` | `lit/reference_lookup.py` | 3 | How many authors a resolved citation names. |
| `MAX_AUTHORS` | `lit/update_references.py` | 3 | The same, for the rendered `REFERENCES.md` table. |
| `MAX_CITED_BY` | `lit/update_references.py` | 8 | How many citing papers one row of that table lists. |
| `DEFAULT_FLAVOR` | `lit/render.py` | `vscode` | Which flavor a collection is rendered in when nothing has recorded one and `$LITERATURE_FLAVOR` is unset. It decides what the anchors of a fresh collection look like, and so which viewer opens a citation without further work. `vscode` because a KaTeX preview needs no other program installed; a reader who keeps the collection in Obsidian sets the flavor once with `lit render --flavor obsidian`. Nobody measured it. |
| `ALT_MAX_CHARS` | `lit/render.py` | 120 | How long the alt text of a rendered figure runs before it is cut. It repeats the caption, which sits under the image in full, so it exists for a reader who cannot see the image and not as a second copy of the text. A higher value describes a complicated figure better and makes the markup harder to read past. Nobody measured it. |

## Ingesting a paper

| Parameter | Where | Now | What it does |
|---|---|---|---|
| `DEFAULT_MAX_CHAPTER_BYTES` | `lit/arxiv_fetch.py` | 40000 | The script divides a section larger than this across more than one file. The value sets how much context one chapter costs an agent that reads it. |
| `FIGURE_WIDTH_PX` | `lit/arxiv_fetch.py` | 500 | The display width of a figure in a chapter. |
| `ID_BATCH` | `lit/arxiv_search.py` | 100 | How many identifiers one `id_list` request asks arXiv about. A bibliography holds fewer references than this, so one request answers a whole paper. A lower value sends more requests, and each one waits `COURTESY_DELAY_S`. The API accepts up to 2000. |
| `RENDER_DPI` | `lit/convert_figures.py` | 300 | The resolution that the script renders a vector figure at. A higher value is easier to read and larger on disk. |
| `MAX_PIXELS` | `lit/convert_figures.py` | 2000 | The longest edge of a converted figure. |
| `CROP_MARGIN` | `lit/convert_figures.py` | 8 | How many pixels of whitespace stay around a cropped figure. |
| `PARAGRAPH_ANCHOR_MIN_CHARS` | `lit/arxiv_fetch.py` | 80 | The length under which a block of text gets no paragraph anchor. A lower value addresses more of the chapter, and writes an anchor line above shorter blocks. A higher value leaves a short paragraph addressable only through the paragraph above it. The value is a judgement: one sentence of prose is longer than 80 characters. |
| `RESTORE_PASSES` | `lit/arxiv_fetch.py` | 4 | How often the placeholder restore walks its items. Each pass answers one further level of nesting, such as the maths of a table inside that table. A lower value can leave a `PH<number>` in the text, which the manifest then reports as a warning. A higher value costs one more walk over a text that already holds no key. |
| `SLUG_MIN_CHARS` | `lit/text.py` | 24 | The length under which a chapter file name keeps a cut word rather than lose more of the title. A higher value returns more names that end in half a word. A lower value returns shorter and less exact names. |
| `MAX_CONCURRENT_FETCHES` | `lit/add_paper.py` | 2 | How many papers run the fetch stage together. The gate still sends one request at a time. A higher value fills the wait of one request with the work of another paper. It never sends more requests, and each paper in the stage costs memory. |
| `INDEX_SUBSECTIONS_SHOWN` | `lit/write_index.py` | 6 | How many subsection titles one chapter row lists. A higher value says more about a long chapter, and makes the table harder to read. |
| `SLUG_TITLE_WORDS` | `lit/identity.py` | 2 | How many title words the derived slug carries. A higher value separates two papers of one author in one year more often, and gives a longer directory name. |
| `ROW_DESCRIPTION_CHARS` | `lit/collection_index.py` | 160 | How much of the abstract the collection row carries. |
| `ROW_AUTHORS_SHOWN` | `lit/collection_index.py` | 1 | How many authors a collection row names before `et al.`. The column is narrow, and the row is a pointer to the paper rather than a citation. A higher value makes the table wider and says little a reader could not get by opening the paper. |
| `ABBREVIATIONS` | `lit/text.py` | 40 words | The words that end in a full stop without ending a sentence, so that `Phys. Rev. D 108` is one reference and not three sentences. A word missing from this set splits a sentence that no author ended, which cuts a quotation short and divides a clause a terminology scan reads. A word wrongly in it joins two sentences into one long quotation. Nobody measured the set; it is the journal names and the citation shorthands that these papers write. |
| `REPORT_WARNINGS_SHOWN` | `lit/add_paper.py` | 10 | How many warnings the compact report prints. The full manifest holds them all. |
| `CANDIDATES_SHOWN` | `lit/identity.py` | 5 | How many candidates an `AMBIGUOUS_TITLE` exception carries for an agent to choose between. A higher value describes more papers, and each one costs the agent context at the moment it has to decide. |
| `AUTHORS_SHOWN` | `lit/write_index.py` and `lit/add_paper.py` | 3 | How many authors the identity table and the report name before `et al.`. `authors_total` gives the count of the rest. |

## Not tunable

These numbers look like tunable parameters. They are not. Something outside this
repository sets each one. A lower value makes nothing faster.

| Parameter | Where | Why it is fixed |
|---|---|---|
| `COURTESY_DELAY_S` | `lit/arxiv_search.py`, 3.0 | arXiv asks for three seconds between calls. A lower value causes a rate limit, and that costs more time than the change saves. |
| `RATE_LIMIT_WINDOW_S` | `lit/inspire_lookup.py`, 5.0 | The rate-limit window of INSPIRE-HEP. The script answers a 429 and then waits out the whole window. |
| `MAX_RETRY_DELAY_S` | `lit/inspire_lookup.py`, 60.0 | A ceiling on the delay that a `Retry-After` header can ask for. A wrong header cannot then stop a run. |
| `INSPIRE_PACE_S` | `lit/inspire_lookup.py`, 0.5 | The pace the INSPIRE API accepts. It sits beside `fetch_record`, which is the one function every INSPIRE request in these scripts passes through. `lit/references.py` reads the name from there. |
| `BATCH_SIZE` | `lit/references.py`, 40 | The batch size the INSPIRE API accepts. `lit/inspire_citations.py` sends its requests through the same functions. |
| `CROSSREF_PACE_S` | `lit/references.py`, 0.5 | The pace Crossref asks of a client with no polite-pool token. |
| `HOST_INTERVALS` | `lit/rate_gate.py` | The pace each API asks for, one entry per host. Each value is registered by the module that owns the constant, so a pace has one definition. |
| `DEFAULT_INTERVAL_S` | `lit/rate_gate.py`, 1.0 | What a host nobody registered gets. It is slower than every pace registered, so an unknown host is paced conservatively rather than not at all. |
| `GATE_WAIT_TIMEOUT_S` | `lit/rate_gate.py`, 120.0 | How long a caller waits for the lock. It bounds a wait, and it makes nothing faster. |
| `LOCK_POLL_S` | `lit/rate_gate.py`, 0.05 | How often a waiting caller retries the lock. Short enough that a caller takes the gate promptly after the holder releases it. |
| `REQUEST_TIMEOUT_S` and `CROSSREF_TIMEOUT_S` | four scripts, 20 to 120 | How long a script waits for a server. `lit/arxiv_fetch.py` waits the longest, at 120, because it downloads an archive of the source. |
| `MAX_RETRIES` | two scripts, 3 | How many times a script repeats a failed request. |
