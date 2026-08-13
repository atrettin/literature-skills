# Citations that go somewhere

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
for and what it passes to `lit lookup`:

```console
$ lit lookup lipari_2002_neutrino_oscillation_neutrino_cross
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
| `lit lookup` | an agent resolving a citation | a tag, a DOI, an arXiv id, a search, or everything one paper cites |
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

the reference check reads every citation in the collection and asserts each one
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
`lit inspire` also runs on its own, to refresh a paper that has been published
since it was ingested:

```bash
lit inspire 2307.09241
```
