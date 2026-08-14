# Rendering the collection

The store is the paper. What a person opens is a render of it, and `litdb render`
writes that. Rendering is not optional — a report has to link to something a
reader can open — but the flavor is a decision that one command changes.

## The flavors

| | `vscode` | `obsidian` |
|---|---|---|
| paragraph and object anchor | `<a id="p2"></a>` on its own line above the block | `^p2` at the end of the block |
| link fragment | `#p2` | `#^p2` |
| a section's fragment | `#sec-pcac` | the heading's own words, which is all Obsidian resolves |
| figure | `<p align="center"><img src=… width="500"/></p>` | `![alt\|500](../figures/x.png)` |
| display maths | KaTeX: `eqnarray` and friends re-wrapped as `aligned`, and `\qquad (78)` per row | MathJax: the environment the paper wrote, and `\tag{78}` |
| tables, citation links, cross-file paths | identical | identical |

Everything else is the same in both, and most of what a renderer does is the
same work: resolving `[cite: …]` and `[ref: …]`, and rewriting the commands that
neither KaTeX nor MathJax knows — `\alt`, `\isotope`, plain-TeX `\pmatrix`.

Obsidian cannot navigate to an HTML anchor at all. It resolves a fragment to a
heading or to a `^block-id`, which is why the anchors move to the end of the
block there, and why a section is addressed by its heading text. A block ID is
not allowed on a heading, so a heading has no other address.

## The recorded flavor

`literature/.collection.json` says which flavor the collection currently holds:

```json
{"flavor": "obsidian", "rendered": "2026-08-14"}
```

It is a property of the files on disk, not of the shell that reads them. The
anchors a render wrote are the anchors that are there, so a report written
against a different flavor names anchors that are not. `litdb render --flavor
<name>` records the answer; `$LITERATURE_FLAVOR` answers only for a collection
that has never been rendered.

`litdb add-paper` renders each paper it ingests in the recorded flavor, so a
collection is never half one thing and half another.

## The commands

```bash
litdb render                          # again, in the recorded flavor
litdb render --flavor obsidian        # change the flavor, and record it
litdb render --flavor obsidian --out ~/vault/lit   # elsewhere; records nothing
litdb render-report reports/x.source.md
```

`litdb render` writes every paper's `INDEX.md`, chapters and `FIGURES.md`, the
reference views, and the collection index. It then **sweeps**: a rendered file
under a paper's directory that this render did not write is deleted, so a
chapter the store no longer holds cannot outlive it. Only rendered files are
ever deleted — `paper.json`, `text/` and the figures are never touched.

It also re-renders every report under `reports/`. A flavor change that left the
reports alone would leave every one of them citing anchors that had moved.

`--out` writes below another directory instead of in place. It records nothing
and deletes nothing, which is what a one-off export wants.

## A report

A report is written twice.

```
reports/<task>.source.md   the agent writes this, with lit: markers
reports/<task>.md          litdb render-report writes this, with real links
```

The source is the master. The agent that writes it never learns the flavor, and
a flavor change re-renders it rather than editing it.

| Marker | Resolves to |
|---|---|
| `lit:<slug>` | the paper's `INDEX.md` |
| `lit:<slug>/<stem>#<anchor>` | a place in a chapter |
| `lit:ref/<tag>` | `references/<tag>.md` |

A `lit:` target cannot be mistaken for a path, which is the point: an agent that
writes a relative path instead has written something the checker can see is
wrong. A marker that names nothing the collection holds is left standing rather
than turned into a link — a dead citation that looks live is worse than one that
looks dead — and `litdb check-report` reports it.

`litdb check-report` reads the **source**, and checks it against the store: the
paper, the chapter, the anchor, the tag. The rendered report is written from a
checked source, so its links resolve by construction, and one check answers for
every flavor the collection is ever rendered in.
