# Ingesting without an agent

`lit add-paper --auto` does an ingest end to end. By default, this step is purely mechanical.
An agent may be called to resolve ambiguities in the paper's metadata if they arise.
The ingested paper is added to the common library in 
markdown format, broken down by chapters. Work cited by the ingested papers
is catalogued in the common reference store.

```bash
lit add-paper --auto 2307.09241 1706.03621
```

**The exit code says who acts.**

| Exit | Means | Then |
|---|---|---|
| 0 | the collection holds the paper | nobody has to do anything |
| 2 | a structured exception, with a code | an agent decides, and runs the script again |
| 1 | a usage error, or an unusable argument | fix the command |

Two artefacts come out, and they are different sizes. The **full manifest** goes
to `<paper-dir>/paper.json`. It holds every reference the paper
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
| `warnings` | `{code, detail, count}` for each |
| `exception` | `{code, detail, …}`, or `null` |
| `next_action` | `none` or `handle_exception` |

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

`lit add-paper --index-only <slug>` renders the paper again from `paper.json`
and the files, and refreshes the paper's row in the collection table. That is
what brings a preprint up to date once INSPIRE reports where it was published.

**One request at a time, enforced in code.** The request gate holds each host to
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

