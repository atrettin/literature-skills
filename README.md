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

## Installing

Install once per machine, at the user level, and every project sees the skills
with no per-project setup:

```bash
git clone <this repo> ~/work/software/literature-skills

for s in add-paper use-literature init-literature; do
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

## Citations that go somewhere

A citation in a chapter used to be a dead end: `[cite: Lipari:2002at]` is the
author's private label for an entry in a bibliography that the conversion threw
away. Nothing in the collection could say which paper it meant, so a claim a
paper borrowed could not be traced back to whoever established it.

Now the bibliography is read from the TeX source, each entry is resolved against
[INSPIRE-HEP](https://inspirehep.net/) and [Crossref](https://www.crossref.org/),
and the citation names a row instead:

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
