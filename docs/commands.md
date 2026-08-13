# The commands

`lit` is one command in front of ten. Each takes `--help`, and each expects to
run from the root of the project that holds `literature/` — or with
`LITERATURE_ROOT` set, from anywhere. Each prints one JSON object, and its exit
status says who acts: `0` it answered, `1` what was asked for is absent or
unreadable, `2` a bad argument or a judgement for the caller to make.

| Command | Answers |
|---|---|
| `lit add-paper --auto <arxiv-id> …` | **the entry point.** Ingests each paper end to end, and prints one report per paper |
| `lit find --topic "…"` | searches arXiv abstracts for a subject, ranks the hits against it, describes each hit with its length and its citation count, and marks the ones the collection holds |
| `lit overlap <arxiv-id> --scope <slug>` | says how much of what a candidate paper cites the collection already knows |
| `lit citations <arxiv-id>` | finds the papers that cite one paper, and the works it draws on |
| `lit lookup <tag>` | resolves one citation, or searches the reference store |
| `lit search "<phrase>"` | finds a phrase in the text of the papers, and gives the chapter, the anchor and the line |
| `lit terminology --topic "…" --in-text <slug> --cited-by <slug>` | weighs the multiword terms of the named papers and of the titles they cite, and reports the ones the topic does not hold, with the passages that state an alias |
| `lit check-report <report.md>` | asserts that every citation of a report opens the text it names |
| `lit inspire <arxiv-id>` | asks INSPIRE-HEP where a paper was published |
| `lit references --render-only` | renders `REFERENCES.md` and the pages under `references/` from the store |


`lit find` sends one INSPIRE request for its shortlist, after its arXiv
requests. That request gives the citation count, the document type and the page
count of each candidate. A candidate INSPIRE does not hold keeps `null` in those
fields, and its length then comes from the arXiv comment. `--kind review` keeps
the papers whose venue or INSPIRE document type names them a review, and
`--sort {relevance,recent,cited}` re-orders the shortlist without changing which
papers are on it.

`lit terminology` finds new search terms that are related to the topic in
one of two different corpora. Calling it with `--in-text <slug>` reads the
papers themselves: the title, the abstract, the headings, the figure captions
and the paragraphs. `--cited-by <slug>` reads the titles of the works those
papers cite.

The papers' own text is where alternative terms for the input topic can usually
be found. They are detected where an author writes the equation between them —
"an acute coronary event, **or** myocardial infarction".

An occurrence is weighed by the kind of text that holds it: a heading is the
author naming what a section is about, and a paragraph is the author using the
name in passing. Two spellings of one name count together, when the corpus
attests both. A word the topic already holds *lowers* a term rather than lifting
it: the names worth finding are the ones the query could not have reached, so a
term built from the query's own words is no discovery.

The report holds a second block, `stated_aliases`. Each entry is one place where
a paper writes the subject beside another name, with the cue that joins them —
`or`, `also called`, `sometimes referred to as`, a bracket — the chapter, the
anchor and the sentence. A term that reaches that block already carries the
location that justifies it, so an agent reads it before it reads the ranking.
The search is anchored on the rarest word of the topic, which the text decides
and no parameter does: `attack` separates the subject, and `heart` fires on
every sentence of a cardiology paper.

The scope has no default. A collection serves more than one task, and it keeps
the papers of each. A scan with no scope would mix their subjects, and it would
then report the other names of somebody else's question. `--all-papers` is the
explicit opt-out, for a question about the collection itself, and it combines
with neither of the others. The research loop passes its working set and never
`--all-papers`.

A `terminology-scout` agent then says how one such term relates to the subject:
the same object, a narrower one, a wider one, or a different one. When the scan
finds nothing usable and a sub-question is still open, the loop escalates to a
`terminology-prospector`, which reads a whole paper for the names it uses. That
gate is in `research-report/SKILL.md`, and it never opens in the first
iteration.

### Weighing a candidate against what you hold

`lit overlap` compares the works a candidate paper cites with the works
the papers in scope cite. Both sides are sets of *works*, resolved by the store's
own rule of identity — a DOI, an arXiv identifier, an INSPIRE record number, or a
journal with a volume and a page — and never sets of tags or titles. The signal
is the Szymkiewicz-Simpson coefficient, `|C ∩ R| / min(|C|, |R|)`, whose `min`
denominator keeps a 30-reference letter comparable with a 500-reference review.

The scope is required, and it takes the same shape as the scope of
`lit terminology`: `--scope <slug>` for each paper of one task, or
`--all-papers`. A held paper outside the scope is reported under `outside_scope`,
with its coefficient and no band. It is on disk already, so reading it costs no
ingest — and because an earlier task chose it for another subject, it must not
decide the band of yours.

A candidate the collection does not hold costs two requests to INSPIRE: one
resolves the identifier, one reads the reference list. A candidate the collection
holds costs no request, because the ingest wrote its whole bibliography to the
store. `--resolve` spends one further request per batch of references that
matched nothing, and it is off by default.

The number orders candidates when the ingest budget is tighter than the list of
papers worth reading. It never rejects a candidate on its own: it counts shared
references, so it reads no argument and no result, and the paper that answers a
question best is often the one that works on the same material.

Two options of the conversion stage matter while the conversion is worked on:
`--dry-run` prints the manifest and writes nothing, and `--keep-source <dir>`
keeps the extracted TeX to compare the output against. `--force` overwrites a
paper directory that exists.

