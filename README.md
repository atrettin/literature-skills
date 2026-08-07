# claude-skills

Claude Code skills for building and reading a local literature database of
physics papers.

The database itself is **not** version controlled anywhere — the papers are
copyrighted. This repository holds only the skills and their scripts.

| Skill | What it does |
|---|---|
| [add-paper](add-paper/SKILL.md) | Finds a paper on arXiv, downloads its TeX source, splits it into per-chapter Markdown, converts the figures to cropped PNGs, and indexes the result. |
| [use-literature](use-literature/SKILL.md) | How to find and read a paper already in the database. |

## Installing into a project

The skills are picked up from a project's `.claude/skills/` directory. Symlink
them in rather than copying, so every project runs the same version:

```bash
git clone <this repo> ~/work/software/claude-skills

cd <your project>
mkdir -p .claude/skills
ln -s ~/work/software/claude-skills/add-paper      .claude/skills/add-paper
ln -s ~/work/software/claude-skills/use-literature .claude/skills/use-literature
```

Project-specific skills stay as ordinary directories alongside the symlinks.

The project needs a `literature/` directory for the papers to land in, and
should ignore it in its own `.gitignore`.

## Requirements

Python packages, into the project's virtual environment:

```bash
pip install -r add-paper/requirements.txt
```

External tools, needed only for the figure conversion. A figure whose converter
is missing is kept in its original format and reported as a warning, so a
partial install degrades rather than fails:

| Tool | Handles | Install (macOS) |
|---|---|---|
| `gs` (Ghostscript) | EPS, PS, PDF | `brew install ghostscript` |
| `rsvg-convert` (librsvg) | SVG | `brew install librsvg` |
| Pillow | raster formats, and the cropping step for everything | in `requirements.txt` |

## Layout a paper ends up with

```
literature/<first-author>_<year>_<keywords>/
├── INDEX.md                  identity, abstract, per-chapter summaries
├── chapters/NN_<title>.md    the text, one file per section
├── figures/<name>.png        cropped PNGs, embedded in the chapters
└── figures_raw/              the arXiv originals, never deleted
```
