"""The HTML a figure becomes, and what its alt attribute must not carry."""

from __future__ import annotations

import re

import arxiv_fetch
import reference_store


def alt_of(block: str) -> str:
    """The alt attribute of the block. A block without one fails the test here."""
    found = re.search(r'alt="([^"]*)"', block)
    assert found is not None, "the figure block carries no alt attribute"
    return found.group(1)


def test_the_alt_text_carries_no_citation_marker() -> None:
    """A marker cut in half invents a tag that no record can ever answer.

    The alt text is cut at 120 characters. A `[cite: …]` that straddles the cut
    loses its closing bracket, and `CITE_TAG` then matches on to the next `]`
    anywhere in the file — so a whole run of HTML gets reported as an unresolved
    tag. The caption under the image is where the citation belongs.
    """
    caption = (
        "Coherent pion production data compared with the model of "
        "[cite: Alvarez-Ruso:2007ipn] and with the later calculation of "
        "[cite: Higuera:2014azj], over the whole energy range of the beam."
    )

    block = arxiv_fetch.figure_block("fig23a.png", caption, number="23", anchor="fig-coh")

    alt = alt_of(block)
    assert "cite:" not in alt
    assert "[" not in alt
    # The caption below the image keeps both citations, where they resolve.
    assert len(reference_store.CITE_TAG.findall(block)) == 2


def test_a_long_alt_text_is_still_cut() -> None:
    block = arxiv_fetch.figure_block("fig1.png", "word " * 100)

    alt = alt_of(block)
    assert alt.endswith("...")
    assert len(alt) <= 120


def test_a_caption_of_only_a_citation_still_gives_an_alt() -> None:
    block = arxiv_fetch.figure_block("fig1.png", "[cite: lipari_2002_neutrino]")

    assert 'alt="figure"' in block
