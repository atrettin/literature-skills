# What a paper ends up as

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
The ingest measures all three. No agent then spends context to restate a number
that a command can count.

The word count says where the substance of the paper is. The anchor count counts
the `sec-`, `eq-`, `fig-` and `tab-` anchors. It leaves the `pN` paragraph
anchors out, because every long paragraph carries one and their count merely
repeats the word count beside it. A count of the named anchors says something
else: it separates a chapter that labels its equations from a chapter of plain
prose.

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
how it stays visible. the reference check reports both, alongside the
citations it checks.

An anchor is written `<a id="sec-pcac"></a>`, and never as the pandoc form
`{#sec-pcac}`. `lit search` is what turns a phrase into that address.
It exists because `grep` cannot: chapter text wraps, so a line break splits a
phrase and the search finds nothing, and a file that holds a NUL byte reads as
binary, so `grep` prints nothing for the whole file. Neither failure reports
itself, and both make text that is present look absent — a correct quotation
then looks invented. The script matches against a flattened copy of the text and
answers with the paper, the chapter, the anchor above the match, the line and
the sentence. When the phrase matches nothing, it drops words from the end until
something matches, and reports that shorter phrase under `partial_matches`.

