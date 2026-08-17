# What a paper is on disk

A paper is **stored** once and **rendered** for a person to read. The store is
the paper; a render is one reading of it, and it can be thrown away and written
again at any time.

```
literature/<slug>/
  paper.json                 what the paper is                        stored
  text/NN_<title>.jsonl      the words, one JSON block per line       stored
  text/NN-MM_<title>.jsonl   one part of a long section               stored
  figures/<name>.png         one cropped PNG per figure               stored
  figures_raw/               the files as the paper shipped them      stored
  INDEX.md                   metadata, abstract, one row per chapter  rendered
  chapters/NN_<title>.md     the same words, for a person to read     rendered
  figures/FIGURES.md         the caption of each figure               rendered
```

Storage and render sit in separate directories on purpose. A `*.md` glob then
cannot reach the store and a `*.jsonl` glob cannot reach a render, so no pass
over the collection has to know which of two files holding the same words it
found, and no agent told to read one opens the other by accident.

The **stem** — `06-05_coherent_pion_production` — is shared by the stored text
and every rendering of it. That is what lets one address, `<slug>/<stem>#<anchor>`,
name a place in the paper without naming a flavor.

## `paper.json`

The record of the paper, written when it is ingested and read by everything
afterwards. It carries the metadata (title, authors, the arXiv year, the
publication INSPIRE reports), the abstract, one entry per chapter, the label map
and every reference the conversion resolved.

A chapter entry carries what a reader deciding where to look needs, all of it
counted at ingest so that nothing has to open a chapter to restate it:

| Field | What it says |
|---|---|
| `stem` | the name shared by `text/<stem>.jsonl` and `chapters/<stem>.md` |
| `number`, `title` | as the paper prints them |
| `subsections` | the `##` headings inside the chapter |
| `words` | where the substance is. A chapter of 200 words is a page of definitions; one of 4000 is the argument. Maths and the raw TeX of a table are not words; a caption is. |
| `anchors` | every address the chapter offers |
| `blocks`, `bytes` | how big it is |

`labels` maps each LaTeX label of the paper to the object it names — its kind,
its number, its anchor and the chapter stem it landed in. A `[ref: label]`
marker is resolved through it. The stem cannot be decided when the collection is
rendered, because it depends on where a long chapter was cut, so it is settled
at ingest and stored.

## A block

`text/<stem>.jsonl` holds the words. **One line is one block.** That is what
makes the file readable as it stands: `Read` gives an agent a line number per
block, and `Grep` matches a block the way it would match a paragraph. A block
never spans two lines, since JSON escapes the newlines inside it.

```json
{"anchor":"sec-coherent-pi","kind":"heading","level":2,"number":"6.5","title":"Coherent Pion Production"}
{"anchor":"p2","kind":"paragraph","text":"Figure [ref: fig:coh] shows … [cite: vilain_1993_phys_lett_b313]."}
{"anchor":"","kind":"math","env":"eqnarray","tex":"\\nu_\\mu \\, A &\\rightarrow& …","numbers":["78","79"]}
{"anchor":"fig-coherent-pi","kind":"figure","file":"coherent_pi.png","number":"22","caption":"…"}
{"anchor":"tab-new-coherent-pion","kind":"table","number":"13","tex":"\\begin{tabular}…","caption":"…"}
{"anchor":"","kind":"code","language":"","text":"…"}
```

`kind` and `anchor` are on every block; everything else belongs to the kind. An
`anchor` of `""` means the block has no address of its own.

## Markers, not links

The store carries `[cite: <tag>]` for a citation and `[ref: <label>]` for a
reference the paper makes to itself. Neither is a link. What a link looks like
depends on the tool that opens it — Obsidian and a KaTeX preview disagree about
anchors, and an HTML page would disagree with both — and the words do not. So
the store keeps the marker and the renderer resolves it.

That is also why a marker is what a defect is reported against.
`litdb check-references` reads the store, so a tag no record answers is found
once, for the collection, rather than once per rendering of it.

Maths is stored as the paper wrote it. A `math` block keeps the environment the
paper used and the numbers LaTeX would have given its rows; which environment a
renderer can accept, and how it prints a number, is a fact about that renderer.

## Anchors

Every paragraph, every heading and every labelled equation, figure and table
carries an anchor, so a citation can name the place a claim comes from and not
the file alone.

- `#eq-ckmt`, `#fig-f2compare`, `#tab-fit` — an object the paper labelled, named
  after the label rather than the number. An author who adds an equation
  renumbers every equation after it, and a re-ingest must not move an anchor a
  report already cites.
- `#sec-nuclear-effects` — a heading the source never labelled, named after its
  title, for the same reason.
- `#p12` — the twelfth paragraph of prose in that one file, counted from `p1` in
  each file. A block shorter than `PARAGRAPH_ANCHOR_MIN_CHARS` gets no `pN`: it
  is a stub or a fragment the conversion left standing, and counting it among
  the paragraphs would move every number after it.
- `#b7` — whatever is left, counted the same way per file: an unnumbered display
  equation, a code listing, an unlabelled table, a short paragraph.

**Every block has an anchor.** A block with no address could not be cited, could
not be opened, and could not be reported by a search that landed on it — the
answer would name the chapter and leave the reader to find the block inside it.
An unnumbered display equation is often the most quotable thing in a section,
and it is exactly the kind of block that carries no label of its own.

A block that already carries a label keeps it, and `pN` is assigned before `bN`.
The paper's own name for a block addresses it better than a count does, and
fixing the order means a re-ingest never moves an anchor a report already
cites.

## Splitting a long section

A section longer than `DEFAULT_MAX_CHAPTER_BYTES` is cut at its `##` headings
into `NN-MM_<piece>.md`. The head of such a section, before its first
subsection, is the piece named `opening`. The paragraph numbers are assigned
after the cut, so `p1` is the first paragraph of the file that holds it.

## Finding a phrase

`litdb search` is what turns a phrase into an address. It exists because `grep`
cannot: a phrase copied out of a rendered chapter carries the line break the
reader's viewer put in it, and a file holding a NUL byte reads to `grep` as
binary, so it prints nothing for the whole file. Both make text that is present
look absent. `litdb search` matches the phrase and the stored block against each
other in the same flat form, and answers with the block's anchor, the file and
the line.
