# literature-skills

Claude Code skills for building and reading a local database of scientific
papers, stored as plain text that both humans and agents can read.

The papers themselves are **never** version controlled — they are copyrighted.
This repository holds only the skills and their scripts. A project's
`literature/` directory stays out of git, and `init-literature` makes sure of
it.

| Skill | What it does |
|---|---|
| [init-literature](init-literature/SKILL.md) | Starts an empty collection in a project: creates `literature/` with its index, and makes git ignore it. |
| [add-paper](add-paper/SKILL.md) | Finds a paper on arXiv, downloads its TeX source, splits it into per-chapter Markdown, converts the figures to cropped PNGs, asks INSPIRE-HEP where it was published, resolves its bibliography, and indexes the result. |
| [use-literature](use-literature/SKILL.md) | How to find and read a paper already in the collection. |
| [find-papers](find-papers/SKILL.md) | Searches arXiv by the subject of a paper's abstract, ranks the hits against the question with a local cross-encoder, and marks the ones the collection already holds. |

## Installing

Install once per machine, at the user level, and every project sees the skills
with no per-project setup:

```bash
git clone <this repo> ~/work/software/literature-skills

for s in add-paper use-literature init-literature find-papers; do
    ln -s ~/work/software/literature-skills/$s ~/.claude/skills/$s
done
```

They are symlinks, so `git pull` in the clone updates every project at once, and
an edit in the clone takes effect immediately.

To install for one project only, symlink into that project's `.claude/skills/`
instead of `~/.claude/skills/`.

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
from the root of the project that holds `literature/`. The lines below use this
repository's own `.venv`, which is how they are run while the skills are
developed here.

```bash
.venv/bin/python -m pip install -r add-paper/requirements.txt
```

| Script | Does |
|---|---|
| `arxiv_search.py --title … --author … --year …` | finds the paper on arXiv and prints the candidates |
| `arxiv_discover.py --topic "…"` | searches arXiv abstracts for a subject, ranks the hits against it, and marks the ones the collection holds |
| `arxiv_fetch.py <arxiv-id> --slug <dir>` | ingests one paper: source, chapters, figures, bibliography |
| `convert_figures.py <paper-dir>` | converts the figures of a paper again |
| `check_references.py` | asserts that every `[cite: …]` and `[ref: …]` in the collection still resolves |
| `reference_lookup.py <tag>` | resolves one citation, or searches the reference store |
| `update_references.py` | renders `REFERENCES.md` from the store |
| `inspire_lookup.py <arxiv-id>` | asks INSPIRE-HEP where a paper was published |

Two options of `arxiv_fetch.py` matter while the conversion is worked on:
`--dry-run` prints the manifest and writes nothing, and `--keep-source <dir>`
keeps the extracted TeX to compare the output against. `--force` overwrites a
paper directory that exists.

## Developing

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/python -m pyright
```

The tests cover the three parts that fail quietly: the queries the scripts send
to arXiv, the ranking, and the answers the collection gives about a paper.

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

The conversion pipeline has no unit tests. To exercise it end to end, ingest a
real paper and then run `check_references.py`. `pyrightconfig.json` configures
the type checks.

## What a paper ends up as

```
literature/
├── README.md                 one row per paper held here
├── REFERENCES.md             one row per work those papers cite
├── .references.jsonl         the store REFERENCES.md is rendered from
└── <first-author>_<year>_<keywords>/
    ├── INDEX.md              identity, abstract, per-chapter summaries
    ├── chapters/NN_<title>.md    the text, one file per section
    ├── figures/<name>.png    cropped PNGs, embedded in the chapters
    └── figures_raw/          the arXiv originals, never deleted
```

Chapters are written to render in a Markdown preview: display maths as
`$$ … $$`, figures as centred `<img>` blocks with their captions beneath.

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

The numbers are recomputed rather than read off the published paper, so one that
renumbers by hand can end up a little out; the link still lands on the right
object. A label the source never defined keeps its `[ref: …]` marker, which is
how it stays visible. `check_references.py` reports both, alongside the
citations it checks.

## Citations that go somewhere

A citation is a dead end on its own: `[cite: Lipari:2002at]` is the author's
private label for an entry in a bibliography that the conversion does not carry
into the chapters. Left at that, nothing in the collection would say which paper
it means, and a claim a paper borrowed could not be traced back to whoever
established it.

So the bibliography is read from the TeX source, each entry is resolved against
[INSPIRE-HEP](https://inspirehep.net/) and [Crossref](https://www.crossref.org/),
and the citation names a row:

```
[cite: lipari_2002_neutrino_oscillation_neutrino_cross]
```

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

**Storage is separate from presentation.** `.references.jsonl` is the store —
one JSON object per line, written atomically, deduplicated on DOI, arXiv
identifier, INSPIRE record number, or journal-volume-page. Two views sit on top
of it, and neither is where the data lives:

| | For | Answers |
|---|---|---|
| `reference_lookup.py` | resolving one citation | a tag, a DOI, an arXiv id, a search, or everything one paper cites |
| `REFERENCES.md` | reading | one row per cited work, most-cited first, linked where the collection holds it |

The table carries no tags — they run to fifty characters and made that column
wider than the titles beside it, for a string that is looked up rather than
read. It is rendered from the store in full on every run, so editing it by hand
achieves nothing.

**A row marked ⚠ was not confirmed.** Only a DOI, an arXiv identifier, an
INSPIRE texkey, or a journal-volume-page triple with agreeing authors counts as
verified. A match on a title alone, or on a reference's position in the
bibliography, does not — those drift, and a confidently wrong publication
attached to a real claim is worse than no citation at all. Unresolvable entries
keep whatever their own bibliography said, marked, rather than disappearing.

`check_references.py` reads every `[cite: …]` in the collection and asserts each
one still resolves. It is the only guard against a tag quietly going stale, and
`add-paper` runs it after every ingest.

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
