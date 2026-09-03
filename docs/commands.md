# The commands

`litdb` is one command in front of sixteen. Each takes `--help`, and each expects to
run from the root of the project that holds `literature/` — or with
`LITERATURE_ROOT` set, from anywhere. Each prints one JSON object, and its exit
status says who acts: `0` it answered, `1` what was asked for is absent or
unreadable, `2` a bad argument or a judgement for the caller to make.

| Command | Answers |
|---|---|
| `litdb init` | starts an empty collection: creates the directory with its index, makes git ignore it, and renders the reference index. Refuses if one already exists |
| `litdb add-paper --auto <arxiv-id> …` | **the entry point.** Ingests each paper end to end, and prints one report per paper |
| `litdb find --topic "…"` | searches arXiv abstracts for a subject, ranks the hits against it, describes each hit with its length and its citation count, and marks the ones the collection holds |
| `litdb overlap <arxiv-id> --scope <slug> …` | says how much of what a candidate paper cites the collection already knows |
| `litdb citations <arxiv-id>` | finds the papers that cite one paper, and the works it draws on |
| `litdb lookup <tag>` | resolves one citation, or searches the reference store |
| `litdb search "<phrase>"` | finds a phrase in the text of the papers, and gives the address of every block that matches |
| `litdb show <address>` | reads what stands at an address: one block, a span, a section or a chapter |
| `litdb toc <slug>` | what a paper is, and every chapter and section in it, with an address and a word count |
| `litdb remove <slug>` | takes a paper out of the collection |
| `litdb terminology --topic "…" --scope <slug> …` | weighs the multiword terms of the named papers and of the titles they cite, and reports the ones the topic does not hold, with the passages that state an alias |
| `litdb render` | writes the collection a person reads, from the store, in one flavor |
| `litdb render-report <report.source.md>` | turns the `lit:` markers of a report into the links of that flavor |
| `litdb check-report <report.source.md>` | asserts that every citation of a report names text the collection holds |
| `litdb inspire <arxiv-id>` | asks INSPIRE-HEP where a paper was published |
| `litdb references --render-only` | renders `REFERENCES.md` and the pages under `references/` from the store |


## The scope

Every command that reads the papers takes the same `--scope`. A scope token is
the citation contract without its `lit:` prefix, cut off at whichever level the
caller wants:

```
disk                            every paper the collection holds
<slug>                          one paper
<slug>/<stem>                   one chapter
<slug>/<stem>#<anchor>          one section, or one block
<slug>/<stem>#<from>..#<to>     a span of blocks, both ends included
<slug>#<anchor>                 the anchor, in whichever chapter carries it
```

The last form is a convenience with a guard: an anchor a paper writes once needs
no chapter, and one that repeats — `#p5` is in every file — is refused with the
list of chapters that carry it, so a caller chooses rather than guesses.

The grammar is closed on itself. `litdb search` reports a `location` in exactly
this form, so the address an answer gives is an address the next command
accepts, and no caller assembles a path.

`--scope` is multi-valued and repeatable, so `--scope a b c` and `--scope a
--scope b` say the same thing. Every answer reports the scope it resolved to: a
scope a reader cannot see is a scope a reader cannot check.

Whether a scope is required is each command's own judgement. `search`, `show`
and `toc` read the whole collection by default; `terminology` and `overlap`
refuse to run without one, because the collection keeps the papers of every task
it ever served and mixing them answers somebody else's question. `--scope disk`
is the explicit opt-out for a question about the collection itself.

`terminology` and `overlap` work a paper at a time, so they refuse a scope that
names a chapter or an anchor rather than widening it to the paper around it.

## Reading a paper

`litdb toc <slug>` is the first thing to run on a paper and often the last. It
says what the paper is — title, authors, year, where it appeared, its abstract —
and then every chapter and section with an address and a word count. The title
says whether a section bears on the question, the word count says whether to
read it whole or search inside it, and the address opens it.

`--depth N` bounds the listing, at two ranks of heading by default, and
`truncated_at_depth` says when there is more. It bounds rather than truncates
silently because a paper can be very large: a manual of sixty-six chapters would
otherwise put hundreds of rows in front of a caller. Deeper goes one chapter at
a time, with `litdb show <slug>/<stem> --anchors-only`. Depth counts ranks and
not raw heading levels, because a paper's levels are not contiguous — one writes
its chapters at level 1 and its sections at level 3.

`litdb show <address>` reads what is there. A heading addresses its section: the
heading and everything under it, down to the next heading of its own rank or
higher. Anything else addresses its own block. `--anchors-only` gives the
addresses inside the target and none of its words.

Two things make an argument readable rather than one block of it. `--context N`
widens by N blocks either side, and a span addresses a run whose ends the caller
has seen. Both matter because prose in a physics paper is interleaved with
mathematics, and **an equation never matches a search**: it is stored as the TeX
the paper wrote rather than as words, deliberately, since indexing raw TeX would
rank on backslashes and braces. So the blocks around a paragraph are the only
way an equation reaches a caller at all. `search` takes `--context` for the same
reason.

Both commands cap what they answer with. `--max-words` cuts at a block boundary
and reports `truncated` with the anchor to resume from: a command whose purpose
is to protect a context window must not be the thing that fills one.

`litdb search --approx` ranks the blocks in scope against the phrase instead of
matching it, for when the words the field uses are uncertain. It runs the same
two stages as `litdb find`: a term-coverage prefilter, then a cross-encoder over
what survives. It refuses `--scope disk` without `--force`, because scoring
every block of a collection is minutes of model time and a command that appears
to hang is worse than one that refuses.

`litdb find` climbs three rungs, and stops at the first that answers: every term
scoped to the abstract, then the topic quoted as the title of a paper, then any
term anywhere in the record. The title rung is what answers a caller who names
a paper rather than a subject; it runs only for a topic short enough to be a
title. Each result says in `found_by` which rung found it.

The order weighs each term of the topic by how rare it is among the candidates.
A term that nearly every candidate carries separated none of them, and counts
for almost nothing; a term that one candidate carries counts for nearly
everything. `query.term_weights` reports what each term was worth, so a reader
can account for the order. `missing_terms` stays the plain list of terms a
paper lacks.

`litdb find` sends one INSPIRE request for its shortlist, after its arXiv
requests. That request gives the citation count, the document type and the page
count of each candidate. A candidate INSPIRE does not hold keeps `null` in those
fields, and its length then comes from the arXiv comment. `--kind review` keeps
the papers whose venue or INSPIRE document type names them a review, and
`--sort {relevance,recent,cited}` re-orders the shortlist without changing which
papers are on it.

`litdb terminology` finds new search terms that are related to the topic in
one of two different corpora. `--corpus text` reads the
papers themselves: the title, the abstract, the headings, the figure captions
and the paragraphs. `--corpus cited` reads the titles of the works those
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
then report the other names of somebody else's question. `--scope disk` is the
explicit opt-out, for a question about the collection itself. The research loop
passes its working set and never `--scope disk`, and it gates the scan rather
than running it every time: the scan earns its cost when the question arrived in
lay terms and the field has its own name for the subject, and earns nothing when
the question already arrived in the field's own words.

The loop then reads the passages behind such a term itself, and records whether
it names the same object, a narrower one, a wider one, or a different one. When
the scan finds nothing usable and a sub-question is still open, the loop escalates to a
`terminology-prospector`, which reads a whole paper for the names it uses. That
gate is in `research-report/SKILL.md`, and it never opens in the first
iteration.

### Weighing a candidate against what you hold

`litdb overlap` compares the works a candidate paper cites with the works
the papers in scope cite. Both sides are sets of *works*, resolved by the store's
own rule of identity — a DOI, an arXiv identifier, an INSPIRE record number, or a
journal with a volume and a page — and never sets of tags or titles. The signal
is the Szymkiewicz-Simpson coefficient, `|C ∩ R| / min(|C|, |R|)`, whose `min`
denominator keeps a 30-reference letter comparable with a 500-reference review.

The scope is required, and it takes the same shape as the scope of
`litdb terminology`: `--scope <slug> <slug>` for the papers of one task, or
`--scope disk`. A held paper outside the scope is reported under `outside_scope`,
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

## Rendering

`litdb render` writes the collection a person reads, from the store, in one flavor
— `vscode` or `obsidian`. Without `--flavor` it renders again in the flavor
`literature/.collection.json` records; with one it renders in that flavor and
records it. `--out <dir>` writes elsewhere, recording nothing and deleting
nothing. It sweeps each paper of rendered files this render did not write, and
re-renders every report under `reports/`, so a flavor change never leaves a
report citing anchors that moved.

`litdb render-report <path>` turns the `lit:` markers of a report source into the
links of the recorded flavor, writing `<task>.md` beside `<task>.source.md`.
[rendering.md](rendering.md) has the three marker forms and what each resolves
to.

Two options of the conversion stage matter while the conversion is worked on:
`--dry-run` prints the manifest and writes nothing, and `--keep-source <dir>`
keeps the extracted TeX to compare the output against. `--force` overwrites a
paper directory that exists.

