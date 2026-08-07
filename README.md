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
| [add-paper](add-paper/SKILL.md) | Finds a paper on arXiv, downloads its TeX source, splits it into per-chapter Markdown, converts the figures to cropped PNGs, asks INSPIRE-HEP where it was published, and indexes the result. |
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
literature/<first-author>_<year>_<keywords>/
├── INDEX.md                  identity, abstract, per-chapter summaries
├── chapters/NN_<title>.md    the text, one file per section
├── figures/<name>.png        cropped PNGs, embedded in the chapters
└── figures_raw/              the arXiv originals, never deleted
```

Chapters are written to render in a Markdown preview: display maths as
`$$ … $$`, figures as centred `<img>` blocks with their captions beneath.

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
