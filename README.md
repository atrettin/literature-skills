# literature-skills

Claude Code skills for building and reading a local database of scientific
papers, stored as plain text that both humans and agents can read.

The papers themselves are **never** version controlled — they are copyrighted.
This repository holds only the skills and their scripts. A project's
`literature/` directory stays out of git, and `init-literature` makes sure of
it.

| Skill | What it does |
|---|---|
| [init-literature](init-literature/SKILL.md) | Starts an empty collection: creates the directory with its index, and makes git ignore it. |
| [add-paper](add-paper/SKILL.md) | Runs the ingest script, which finds a paper on arXiv, downloads its TeX source, splits it into per-chapter Markdown, converts the figures to cropped PNGs, asks INSPIRE-HEP where it was published, resolves its bibliography and indexes the result. The skill handles the script's exceptions, and writes the chapter summaries when somebody asks for them. |
| [use-literature](use-literature/SKILL.md) | How to find and read a paper already in the collection. |
| [find-papers](find-papers/SKILL.md) | Searches arXiv by the subject of a paper's abstract, ranks the hits against the question with a local cross-encoder, describes each hit with its length and its citation count, and marks the ones the collection already holds. |
| [follow-citations](follow-citations/SKILL.md) | Finds the papers that cite a given paper, with INSPIRE-HEP, and the works it draws on, from the reference store. |
| [research-report](research-report/SKILL.md) | Answers a task that needs a literature review, in a bounded loop of search, read and assess, and writes a report whose every claim links to the chapter it came from. |

## Installing

Install once per machine, at the user level, and every project sees the skills
with no per-project setup:

```bash
git clone <this repo> ~/work/software/literature-skills

for s in add-paper use-literature init-literature find-papers \
         follow-citations research-report; do
    ln -s ~/work/software/literature-skills/$s ~/.claude/skills/$s
done

for a in literature-researcher paper-ingestor paper-scout terminology-scout; do
    ln -s ~/work/software/literature-skills/.claude/agents/$a.md ~/.claude/agents/$a.md
done
```

They are symlinks, so `git pull` in the clone updates every project at once, and
an edit in the clone takes effect immediately.

To install for one project only, symlink into that project's `.claude/skills/`
and `.claude/agents/` instead.

## Researching a task

`research-report` answers a task whose result is a report with citations. A
question is one such task. So is "check the claims in this file against the
literature", and so is "list the cross-section models this generator uses, by
the energy range where each applies".

It runs a loop, because the first papers a search finds are approximate matches.
Reading them teaches what the search should have asked for, and which papers to
follow through the citation graph. The loop stops when each sub-question is
answered, or when a limit in [TUNING.md](TUNING.md) stops it — and the report
says which of the two happened.

A sub-question counts as answered only after the loop asks INSPIRE which papers
cite the paper that supplies the answer. The research log holds that search,
under `Currency checks`, so a reader can see it.

Four agents divide the work, and the division is about context rather than
speed:

| Agent | Reads | Why it is separate |
|---|---|---|
| `literature-researcher` | `INDEX.md` files, the reports of the other two, and the chapters it cites | it runs the loop and writes the report. |
| `paper-ingestor` | one report, and no chapter | it handles an exception of the ingest script — an ambiguous title, a name two works want. The script does the rest, and it reads no paper into any context. |
| `paper-scout` | the whole paper, against the open sub-questions | most papers carry no chapter summary, because that pass is opt-in, and one that exists was written before anybody had these questions. Either way the index cannot say which chapter answers one. |
| `terminology-scout` | the chapters that use one term | a term the query lacks is a question about the words of the field. The answer must differentiate the two names, and it must never equate them: "heavy neutral lepton" names the heavy mass eigenstates, and "sterile neutrino" also covers a light state. |

`rate_gate.py` holds every script to one request at a time, at the pace each API
asks for, across processes. So one `add_paper.py --auto` command ingests a whole
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

`check_report.py` then checks the report the way `check_references.py` checks the
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

[EVALUATION.md](EVALUATION.md) says how to measure whether the agent does this
well.

## A collection shared between projects

A collection can serve more than one project. Set `LITERATURE_ROOT`:

```bash
export LITERATURE_ROOT=~/literature
```

Every script reads it as the default of `--literature-root`, and every skill
reads the collection there. Without it, the collection is `literature/` in the
project, and nothing changes for a project that has one.

A paper costs a download and a conversion. Paying that again in the next project
buys nothing, and the second copy is a second thing to keep in step.

A shared collection usually sits outside any repository. `init-literature` then
has no `.gitignore` to write, says so, and states that the copyright still
holds.

## Requirements

The skills run their scripts with the Python of whichever project they are used
from. Install the dependencies there:

```bash
<project>/.venv/bin/python -m pip install -r ~/work/software/literature-skills/add-paper/requirements.txt
```

External tools, needed only for the figure conversion. A figure whose converter
is missing keeps its original format and is reported as a warning, so a partial
install degrades rather than fails:

| Tool | Handles | Install (macOS) |
|---|---|---|
| `gs` (Ghostscript) | EPS, PS, PDF | `brew install ghostscript` |
| `rsvg-convert` (librsvg) | SVG | `brew install librsvg` |
| Pillow | raster formats, and the cropping step for everything | in `requirements.txt` |

`find-papers` has one dependency of its own, and it is optional:

```bash
<project>/.venv/bin/python -m pip install -r ~/work/software/literature-skills/find-papers/requirements.txt
```

It installs [FlashRank](https://github.com/PrithivirajDamodaran/FlashRank). That
package runs a cross-encoder on ONNX Runtime and not on torch, so it costs about
60 MB. It downloads a 21 MB model on first use and keeps it in
`~/.cache/flashrank`.

The search answers without it. The results are then ordered by how many of the
question's words each abstract carries. Every report names the order that
produced it, so a reader always knows which of the two they have.

## The scripts

Every script is a standalone command line tool, and `--help` gives its full
options. All of them live in `add-paper/scripts/`, and all of them expect to run
from the root of the project that holds `literature/` — or with
`LITERATURE_ROOT` set, from anywhere. The lines below use this repository's own
`.venv`, which is how they are run while the skills are developed here.

```bash
.venv/bin/python -m pip install -r add-paper/requirements.txt
```

| Script | Does |
|---|---|
| `add_paper.py --auto <arxiv-id> …` | **the entry point.** Ingests each paper end to end, and prints one report per paper |
| `arxiv_search.py --title … --author … --year …` | finds the paper on arXiv and prints the candidates |
| `arxiv_discover.py --topic "…"` | searches arXiv abstracts for a subject, ranks the hits against it, describes each hit with its length and its citation count, and marks the ones the collection holds |
| `arxiv_fetch.py <arxiv-id> --slug <dir>` | the conversion stage the driver calls: source, chapters, figures, bibliography |
| `write_index.py <paper-dir>` | writes `INDEX.md` again from the manifest and the files, keeping the summaries |
| `convert_figures.py <paper-dir>` | converts the figures of a paper again |
| `collection_index.py --report <report.json>` | puts one paper into the table of `literature/README.md`; `--description` gives its row a sentence |
| `check_references.py` | asserts that every citation and `[ref: …]` in the collection still resolves, and reports placeholder residue; `--paper <slug>` scopes the verdict to one paper |
| `reference_lookup.py <tag>` | resolves one citation, or searches the reference store |
| `search_literature.py "<phrase>"` | finds a phrase in the text of the papers, and gives the chapter, the anchor and the line |
| `terminology_scan.py --topic "…" --cited-by <slug>` | counts the multiword terms in the titles that the named papers cite, and reports the frequent ones the topic does not hold |
| `update_references.py` | renders `REFERENCES.md` from the store |
| `inspire_lookup.py <arxiv-id>` | asks INSPIRE-HEP where a paper was published |
| `inspire_citations.py <arxiv-id>` | finds the papers that cite one paper, and the works it draws on |
| `check_report.py <report.md>` | asserts that every citation of a report opens the text it names |

`arxiv_discover.py` sends one INSPIRE request for its shortlist, after its arXiv
requests. That request gives the citation count, the document type and the page
count of each candidate. A candidate INSPIRE does not hold keeps `null` in those
fields, and its length then comes from the arXiv comment. `--kind review` keeps
the papers whose venue or INSPIRE document type names them a review, and
`--sort {relevance,recent,cited}` re-orders the shortlist without changing which
papers are on it.

`terminology_scan.py` takes its scope, and it has no default: `--cited-by
<slug>` for each paper of one task, or `--all-papers` for the whole collection.
A collection serves more than one task, and it keeps the papers of each. A scan
with no scope would mix their subjects. It would then report the other names of
somebody else's question. It reads the titles of the reference store, drops each term the
topic already holds, and reports the frequent rest with the number of titles
that use each one. The research loop passes its working set and never
`--all-papers`. A `terminology-scout` agent then says how one such term relates
to the subject: the same object, a narrower one, a wider one, or a different
one.

Two options of `arxiv_fetch.py` matter while the conversion is worked on:
`--dry-run` prints the manifest and writes nothing, and `--keep-source <dir>`
keeps the extracted TeX to compare the output against. `--force` overwrites a
paper directory that exists.

## Ingesting without an agent

`add_paper.py --auto` does an ingest end to end. Each step of one was already a
script: the search, the conversion, the reference merge, the citation check. An
agent that drives those scripts pays about 42,000 tokens of fixed context for
one paper, and the paper passes through that context about two and a half times.
Almost none of that cost buys judgement.

```bash
.venv/bin/python add-paper/scripts/add_paper.py --auto 2307.09241 1706.03621
```

**The exit code says who acts.**

| Exit | Means | Then |
|---|---|---|
| 0 | the collection holds the paper | nobody has to do anything |
| 2 | a structured exception, with a code | an agent decides, and runs the script again |
| 1 | a usage error, or an unusable argument | fix the command |

Two artefacts come out, and they are different sizes. The **full manifest** goes
to `<paper-dir>/.ingest-manifest.json`. It holds every reference the paper
cites, every label it defines, and everything else the conversion learned. The
**compact report** goes to stdout, as one JSON object on one line per paper. It
holds the identity, the chapter table, the counts and the warnings. It holds no
field that grows with the size of a bibliography, thus a paper that cites five
hundred works costs the same to report as one that cites five.

Every field of the report is always present. `null` and `[]` are answers, so a
reader never has to tell a missing value from an unknown one:

| Field | Holds |
|---|---|
| `schema` | `add-paper/report/1`. Check this before anything else. |
| `status` | `ingested`, `exception` or `error` |
| `slug`, `paper_dir`, `index`, `manifest` | where the paper and its files went |
| `title`, `authors`, `authors_total`, `submitted_year`, `publication`, `abs_url` | what the paper is |
| `parser` | `texsoup` or `fallback` |
| `chapters` | one entry per file: `file`, `number`, `title`, `words`, `named_anchors`, `bytes`, `subsections` |
| `figures`, `figures_missing` | how many, and how many have no file on disk |
| `references` | the counts of the merge |
| `checks` | the citation verdict, scoped to this paper, with `elsewhere` for the rest |
| `collection_row` | `added` or `present` |
| `summary_state` | `pending` while the chapter summaries are `—` |
| `warnings` | `{code, detail, count}` for each |
| `exception` | `{code, detail, …}`, or `null` |
| `next_action` | `none`, `handle_exception` or `summarize` |

The exception codes are `AMBIGUOUS_TITLE`, `NO_ARXIV_SOURCE`, `TAG_COLLISION`,
`PARSER_FAILURE`, `SLUG_EXISTS`, `REFERENCE_CHECK_FAILED`,
`COLLECTION_INDEX_UNREADABLE` and `NETWORK_UNAVAILABLE`. Each one names a
question with no mechanical answer, and carries the fields the answer needs —
`AMBIGUOUS_TITLE` carries the candidates, `TAG_COLLISION` carries the work that
holds the name. `add-paper/SKILL.md` has a section for each code.

A warning names something the ingest went on past. The collection holds the
paper, and the report says what is imperfect about it:

| Warning | Means |
|---|---|
| `PARSER_FALLBACK` | TexSoup could not read the source, thus the chapters come from the fallback parser |
| `INSPIRE_NO_RECORD` | INSPIRE-HEP knows no record for this paper |
| `INSPIRE_NO_JOURNAL` | INSPIRE-HEP holds the paper, and names no journal for it |
| `INSPIRE_LOOKUP_FAILED` | the INSPIRE-HEP request itself failed |
| `BIBLIOGRAPHY_FAILED` | the bibliography could not be resolved, thus the citations of this paper stay unlinked |
| `UNRESOLVED_REFS` | a cross-reference label has no target in the source, and keeps its `[ref: …]` marker |
| `FIGURE_SOURCE_MISSING` | the archive holds no file for a figure the text names |
| `FIGURE_CONVERTER_MISSING` | the converter for that figure format is not installed |
| `UNVERIFIED_REFERENCES` | neither INSPIRE-HEP nor Crossref confirmed a reference, thus its row is marked |
| `PLACEHOLDER_RESIDUE` | a chapter still holds a `PH<digits>` marker or a control character |
| `RATE_GATE_LOCAL` | nothing can write the collection root, thus the lock holds inside this process alone |

`PLACEHOLDER_RESIDUE` comes from the `residue` field of the citation check, which
names the files. The check is the one thing that scans for residue, so the driver
scans no chapter itself: two scans are two definitions of residue, and they
drift apart.

The chapter summaries are the one part an agent writes, and they are opt-in:
`--summarize <slug>` names the chapters that have none. `--index-only <slug>`
writes `INDEX.md` again from the manifest and the files, keeping every summary
already in it.

**One request at a time, enforced in code.** `rate_gate.py` holds each host to
the pace its API asks for: three seconds for arXiv, half a second for INSPIRE-HEP
and for Crossref. It takes an exclusive lock on
`<literature-root>/.api-gate.json` for the length of each request. The lock is a
file, thus a second shell, or an agent beside a running ingest, cannot double
the rate between them.

The collection that lock belongs to is the one the caller named. Every script
that takes `--literature-root` passes it to the gate, so a run started from
another directory locks the same collection and waits its turn. The gate locks a
collection and never makes one: a gate that made one would leave an empty
`literature/` behind in whatever directory a script ran from, and would take its
lock there instead.

The limit counts requests, and not agents. One command can therefore resolve the
references of one paper while it downloads the next. A collection root that
nothing can write gives a lock inside one process, and the report says so with
`RATE_GATE_LOCAL`.

## Developing

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/python -m pyright
```

The tests cover the parts that fail quietly: the queries the scripts send to
arXiv, the ranking, the answers the collection gives about a paper, the
citations written into the chapters, the citations written into a report, the
queries sent to INSPIRE for the citation graph, the phrase search over the text
of the papers (`tests/test_search_literature.py`), and which collection a script
reads.

They call no network. `tests/data/` holds the arXiv responses they run against.
`tests/data/collection_fixture/` holds the collection they check against. That
directory is not called `literature`, because git ignores every directory of
that name.

One group of tests does call arXiv. It is deselected by default:

```bash
.venv/bin/python -m pytest -m network
```

Those tests assert what the queries depend on at arXiv:

- A quoted phrase finds far fewer papers than the same words joined with `AND`.
- An unknown field returns no results and no error.
- A category excludes its subcategories.

Each of these can change at arXiv rather than here, and arXiv reports none of
them as a failure. Run this group when a search returns the wrong kind of
answer.

The LaTeX-to-Markdown conversion has no unit tests. To exercise it end to end,
ingest a real paper and then run `check_references.py`. `pyrightconfig.json`
configures the type checks.

[TUNING.md](TUNING.md) lists the numbers that decide how good an answer is. They
do not decide whether the answer is correct. Three examples:

- how far the search widens when it finds little,
- which cross-encoder puts the results in order,
- how much of a paper one chapter holds.

Nobody measured these numbers. Each one is a judgement. Read that file before
you change one. Add a row to it when you introduce another.

## What a paper ends up as

```
literature/
├── README.md                 one row per paper held here
├── REFERENCES.md             one row per work those papers cite
├── .references.jsonl         the store the two views are rendered from
├── references/<tag>.md       one page per cited work, what a citation opens
└── <first-author>_<year>_<keywords>/
    ├── INDEX.md              identity, abstract, one row per chapter
    ├── .ingest-manifest.json every reference and every label of the paper
    ├── chapters/NN_<title>.md    the text, one file per section
    ├── figures/<name>.png    cropped PNGs, embedded in the chapters
    └── figures_raw/          the arXiv originals, never deleted
```

`INDEX.md` holds the identity table, the abstract, and one row per chapter. Each
row gives the word count, the count of named anchors and the subsection titles.
A script measures all three. No agent then spends context to restate a number
that a script can count.

The word count says where the substance of the paper is. The anchor count counts
the `sec-`, `eq-`, `fig-` and `tab-` anchors. It leaves the `pN` paragraph
anchors out, because every long paragraph carries one and their count merely
repeats the word count beside it. A count of the named anchors says something
else: it separates a chapter that labels its equations from a chapter of plain
prose. The last column says what the chapter covers. It stays `—` until a
summary pass fills it in.

Chapters are written to render in a Markdown preview: display maths as
`$$ … $$`, figures as centred `<img>` blocks with their captions beneath.

The conversion writes one line for one paragraph. TeX wraps its prose at about
70 characters. A phrase that crosses such a break answers no search for that
phrase. The preview wraps the long line again, so the page reads the same.

Every paragraph, every heading and every labelled equation, figure and table
carries an anchor. A citation can then name the place a claim comes from, and
not the file alone.

## Cross-references that go somewhere

A paper refers to itself constantly — "as shown in eq. (5)", "see Fig. 3", "in
Section IV". LaTeX writes those as a `\ref` against a `\label`, and the label is
the author's private name for a place in the source, not a number and not an
address. Left at that, the reader meets `eq. ([ref: eq:ckmt])` with nothing
anywhere to match it against.

So every equation, figure, table and section is numbered and anchored as it is
met, and a reference is a link to the thing it names, carrying the chapter file
when that is a different one:

```markdown
eq. ([6](#eq-ckmt))
Section [4](04_partially_conserved_axial_vector_current.md#sec-pcac)
```

A heading the source never labelled carries an anchor named after its title, as
`#sec-nuclear-effects`. Every paragraph carries a number of its own, as
`04_partially_conserved_axial_vector_current.md#p12`. The title and the count of
paragraphs are the stable names. A new section renumbers every section after it,
and an anchor that a report cites must not move.

The numbers are recomputed rather than read off the published paper, so one that
renumbers by hand can end up a little out; the link still lands on the right
object. A label the source never defined keeps its `[ref: …]` marker, which is
how it stays visible. `check_references.py` reports both, alongside the
citations it checks.

An anchor is written `<a id="sec-pcac"></a>`, and never as the pandoc form
`{#sec-pcac}`. `search_literature.py` is what turns a phrase into that address.
It exists because `grep` cannot: chapter text wraps, so a line break splits a
phrase and the search finds nothing, and a file that holds a NUL byte reads as
binary, so `grep` prints nothing for the whole file. Neither failure reports
itself, and both make text that is present look absent — a correct quotation
then looks invented. The script matches against a flattened copy of the text and
answers with the paper, the chapter, the anchor above the match, the line and
the sentence. When the phrase matches nothing, it drops words from the end until
something matches, and reports that shorter phrase under `partial_matches`.

## Citations that go somewhere

A citation is a dead end on its own: `[cite: Lipari:2002at]` is the author's
private label for an entry in a bibliography that the conversion does not carry
into the chapters. Left at that, nothing in the collection would say which paper
it means, and a claim a paper borrowed could not be traced back to whoever
established it.

So the bibliography is read from the TeX source, each entry is resolved against
[INSPIRE-HEP](https://inspirehep.net/), [Crossref](https://www.crossref.org/)
and [arXiv](https://arxiv.org/), and the citation becomes a link on to that
work's own page:

```markdown
… and for searches for physics beyond the standard model
([Lipari, 2002](../../references/lipari_2002_neutrino_oscillation_neutrino_cross.md);
[Katori et al., 2018](../../references/katori_2018_neutrino_nucleus_cross_sections.md)).
```

A reader sees `(Lipari, 2002)` and one click opens that work — its title,
authors, journal, DOI, arXiv link, and the papers here that cite it. Several
works at one point share one pair of brackets, separated by semicolons, the way
a journal sets them.

**A citation names a file rather than a row of a table.** The obvious thing is
to link to `REFERENCES.md#<tag>`, and it does not work: the VS Code Markdown
preview resolves a cross-file `#fragment` through the target's heading table of
contents, so an anchor in a table cell is unreachable and the file merely opens
at the top. A heading it could reach would have to be linked to by its slug
rather than by the tag, and the tag in the link is the whole point of the next
paragraph. A link to a file lands where it says, in every renderer, with nothing
to resolve.

The tag has not gone anywhere — it names the file, which is what an agent greps
for and what it passes to `reference_lookup.py`:

```console
$ reference_lookup.py lipari_2002_neutrino_oscillation_neutrino_cross
{
  "found": 1,
  "references": [
    {
      "tag": "lipari_2002_neutrino_oscillation_neutrino_cross",
      "title": "Neutrino oscillation studies and the neutrino cross-section",
      "authors": ["Lipari, Paolo"],
      "authors_total": 1,
      "year": 2002,
      "journal": "Nucl.Phys.B Proc.Suppl. 112 (2002) 274-287",
      "doi_url": "https://doi.org/10.1016/S0920-5632(02)01783-8",
      "arxiv_url": "https://arxiv.org/abs/hep-ph/0207172",
      "citation_count": 53,
      "verified": true,
      "held_as": null,
      "cited_by": ["jeong_2023_shallow_deep_inelastic"]
    }
  ]
}
```

The tag is a slug of the same shape as a paper's directory name, so a cited work
that is later ingested keeps one identifier throughout — `held_as` then names
the directory holding it in full. Author lists collapse to three by default,
with `authors_total` beside them: a high-energy physics paper can carry several
thousand authors, and a citation never turns on the four hundredth of them.

The answer is one object with three fields:

| Field | Type | Holds |
|---|---|---|
| `found` | integer | how many records the answer holds |
| `missing` | list of strings | each tag that no record answers, each DOI as `doi:<doi>`, each arXiv identifier as `arxiv:<id>` |
| `references` | list of objects | one object per record, most cited first; a record with no count sorts after every record that has one |

One record holds these fields. Every field but `tag` can be absent: the store
holds only what a lookup confirmed.

| Field | Type | Holds |
|---|---|---|
| `tag` | string | the name the chapters cite the work by |
| `title` | string | the title of the work |
| `title_source` | string | present only when no lookup confirmed the work: the title is then the bibliography line of the citing paper |
| `authors` | list of strings | at most `--authors N` names (3 by default), then `et al. (N more)`; `--all-authors` gives every name |
| `authors_total` | integer | how many authors the work has |
| `year` | integer | the year of publication |
| `journal` | string | the journal, volume, year and pages, as one line |
| `doi` | string | the DOI |
| `doi_url` | string | present only with a DOI: the resolver link |
| `arxiv_id` | string | the arXiv identifier |
| `arxiv_url` | string | present only with an arXiv identifier: the abstract page |
| `inspire_id` | string | the INSPIRE-HEP record number |
| `citation_count` | integer | how many papers INSPIRE-HEP counts as citing the work |
| `source` | string | which service answered |
| `match` | string | which identifier matched |
| `verified` | boolean | true when a lookup confirmed the work |
| `held_as` | string or null | the directory that holds the work in full, or null when the collection holds it only as a reference |
| `cited_by` | list of strings | the slug of each paper of the collection that cites the work, sorted |

The answer holds no bookkeeping field of the store: `journal_key`, `raw`,
`about` and `first_seen` stay out. The exit status is 1 when `missing` holds one
entry or more. The script prints `{"error": "…"}` and exits 1 when it cannot
read the store.

**Storage is separate from presentation.** `.references.jsonl` is the store —
one JSON object per line, written atomically, deduplicated on DOI, arXiv
identifier, INSPIRE record number, or journal-volume-page. Three views sit on
top of it, and none is where the data lives:

| | For | Answers |
|---|---|---|
| `reference_lookup.py` | an agent resolving a citation | a tag, a DOI, an arXiv id, a search, or everything one paper cites |
| `REFERENCES.md` | a person browsing | one row per cited work, most-cited first, linked where the collection holds it |
| `references/<tag>.md` | a person following a citation | that one work, on a page of its own |

The two files are rendered from the store in full on every run, so editing
either by hand achieves nothing; a page whose work has left the store is
deleted. The table has no tag column — a tag runs to fifty characters and made
that column wider than the titles beside it, for a string that is looked up
rather than read. Its titles link to the paper for the works this collection
holds in full, which is how a reader spots those at a glance.

**A row marked ⚠ was not confirmed.** Only a DOI, an arXiv identifier, an
INSPIRE texkey, or a journal-volume-page triple with agreeing authors counts as
verified. A match on a title alone, or on a reference's position in the
bibliography, does not — those drift, and a confidently wrong publication
attached to a real claim is worse than no citation at all. Unresolvable entries
keep whatever their own bibliography said, marked, rather than disappearing.

**A number that identifies a work says nothing about its date.** An entry that
INSPIRE and Crossref do not answer often prints an arXiv number, and the script
asks arXiv about that number: arXiv reports the date it received the paper, the
title and the authors, and the entry counts as verified on the identifier its own
bibliography printed. The digits of the number are never read as a date —
`2004.06601` is from 2020, and `hep-ph/0207172` is from 2002. An entry that
states no date and that no lookup answers keeps no year, and its tag says `nd`.

`check_references.py` reads every citation in the collection and asserts each one
still resolves — against the store, and against the anchors of the table it links
to. It is the only guard against a tag quietly going stale, and `add-paper` runs
it after every ingest.

`--paper <slug>` scopes the verdict to one paper. The read stays
collection-wide: one store answers the citations of every paper, so the check
cannot ask a smaller question of the files. The answer is the smaller question.
Each list then holds only that paper's defects, `elsewhere` counts the defects
of the rest of the collection, and `ok` and the exit status speak for that paper
alone. An agent that has just ingested a paper wants that answer. Without the
flag, the report answers for the whole collection, which is what a person
auditing the collection wants.

`INDEX.md` records both the year the preprint went to arXiv and the journal it
was published in. arXiv cannot answer the second question — its `journal_ref`
field is filled in by the authors and is empty for most records — so it comes
from [INSPIRE-HEP](https://inspirehep.net/), keyed on the arXiv identifier.
`add-paper/scripts/inspire_lookup.py` also runs on its own, to refresh a paper
that has been published since it was ingested:

```bash
<project>/.venv/bin/python \
    ~/work/software/literature-skills/add-paper/scripts/inspire_lookup.py 2307.09241
```
