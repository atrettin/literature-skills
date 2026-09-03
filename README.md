# literature-skills

Claude Code skills for building and reading a local database of scientific
papers, stored as plain text that both humans and agents can read.

The papers themselves are **never** version controlled — they are copyrighted.
This repository holds only the skills and the code behind them. A project's
`literature/` directory stays out of git, and `litdb init` makes sure of
it.

| Skill | What it does |
|---|---|
| [add-paper](add-paper/SKILL.md) | Finds a paper on arXiv, downloads its TeX source, splits it into per-chapter Markdown, converts the figures to cropped PNGs, asks INSPIRE-HEP where it was published, resolves its bibliography and indexes the result. The skill handles the exceptions the ingest raises. |
| [use-literature](use-literature/SKILL.md) | How to find and read a paper already in the collection. |
| [find-papers](find-papers/SKILL.md) | Searches arXiv by the subject of a paper's abstract, ranks the hits against the question with a local cross-encoder, describes each hit with its length and its citation count, and marks the ones the collection already holds. It then weighs a candidate you mean to ingest against the papers you hold for the question, from the works the two have in common. |
| [follow-citations](follow-citations/SKILL.md) | Finds the papers that cite a given paper, with INSPIRE-HEP, and the works it draws on, from the reference store. |
| [research-report](research-report/SKILL.md) | Answers a task that needs a literature review, in a bounded loop of search, read and assess, and writes a report whose every claim links to the chapter it came from. |

## Installing

```bash
git clone <this repo> ~/work/software/literature-skills
cd ~/work/software/literature-skills
./install.sh
```

That installs the `litdb` command and symlinks the five skills into
`~/.claude/skills/` and the four agents into `~/.claude/agents/`. Because they
are symlinks, `git pull` in the clone updates every project at once.

It installs into whichever Python runs it. To choose one:

```bash
PYTHON=~/.venvs/tools/bin/python ./install.sh
```

The installer says where `litdb` landed, and what to add to `PATH` if that
directory is not on it.

Two external programs convert some figures, and pip does not install them. A
figure whose converter is missing keeps its original format and is reported as a
warning, so a partial install degrades rather than fails:

| Program | Handles | Install (macOS) |
|---|---|---|
| `gs` (Ghostscript) | EPS, PS, PDF | `brew install ghostscript` |
| `rsvg-convert` (librsvg) | SVG | `brew install librsvg` |

## Using it

Ask Claude Code for what you want, in a project. The skills load themselves:

> Start a literature collection for this project.
> Add the NuSTEC white paper.
> What does the literature say about the axial mass, and where does 1.03 GeV
> come from?

The same work by hand:

```bash
litdb --help                          # the commands
litdb init                            # start an empty collection
litdb add-paper --auto 2307.09241     # ingest a paper
litdb toc <slug>                      # what a paper is, and what is in it
litdb search "axial mass"             # find a phrase in what you hold
litdb show <slug>/<stem>#<anchor>     # read what stands at an address
litdb lookup bodek_2008_axial_mass_quasielastic   # resolve a citation
```

Run `litdb` from the root of a project, so that `literature/` resolves.

## A collection shared between projects

A collection can serve more than one project. Set `LITERATURE_ROOT`:

```bash
export LITERATURE_ROOT=~/literature
```

Every command reads it as the default of `--literature-root`, and every skill
reads the collection there. Without it, the collection is `literature/` in the
project, and nothing changes for a project that has one.

A paper costs a download and a conversion. Paying that again in the next project
buys nothing, and the second copy is a second thing to keep in step.

A shared collection usually sits outside any repository. `litdb init` then
has no `.gitignore` to write, says so, and states that the copyright still
holds.

## Ranking the search results

`find-papers` orders its results with a cross-encoder when
[FlashRank](https://github.com/PrithivirajDamodaran/FlashRank) is installed,
which `install.sh` does. That package runs on ONNX Runtime and not on torch, so
it costs about 60 MB, and it downloads a 21 MB model on first use into
`~/.cache/flashrank`.

The search answers without it. The results are then ordered by how many of the
question's words each abstract carries. Every report names the order that
produced it, so a reader always knows which of the two they have.

## Documentation

| Document | What is in it |
|---|---|
| [docs/commands.md](docs/commands.md) | Every `litdb` command, and what each one answers |
| [docs/research.md](docs/research.md) | The research loop: the agents, the report, and how a citation is checked |
| [docs/ingest.md](docs/ingest.md) | Ingesting without an agent: the exit codes, the report fields, the warnings |
| [docs/papers.md](docs/papers.md) | What a paper is stored as, and the anchors a citation reaches |
| [docs/rendering.md](docs/rendering.md) | The flavors, `litdb render`, and the `lit:` markers a report cites with |
| [docs/references.md](docs/references.md) | Citations, the reference store, and what makes one verifiable |
| [docs/developing.md](docs/developing.md) | The layout of `lit/`, the tests, and the type checker |
| [docs/evaluation.md](docs/evaluation.md) | Measuring whether a change to the skills made the answers better |
| [TUNING.md](TUNING.md) | Every parameter that decides how good an answer is, and what moving it does |
