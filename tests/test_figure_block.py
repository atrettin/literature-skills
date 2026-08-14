"""What a figure block stores, and what a rendered image says in its alt text."""

from __future__ import annotations

import re

from lit import arxiv_fetch
from lit import blocks
from lit import reference_store
from lit import render


def stored(file_name: str, caption: str, number: str = "", anchor: str = "") -> dict:
    """The one figure block that `figure_block` produces."""
    found = blocks.parse(arxiv_fetch.figure_block(file_name, caption, number, anchor))
    assert len(found) == 1, found
    return found[0]


def context(flavor: str = "vscode") -> render.Context:
    return render.Context(flavor, {}, {}, {}, "../../references")


def alt_of(image: str) -> str:
    """The alt text of a rendered figure, whichever syntax the flavor used."""
    found = re.search(r'alt="([^"]*)"', image) or re.search(r"!\[([^\]]*)\|", image)
    assert found is not None, "the figure carries no alt text"
    return found.group(1)


def test_the_block_stores_the_caption_as_the_paper_wrote_it() -> None:
    """The markers stay: what a citation looks like is the renderer's business."""
    block = stored("fig1.png", "A cross section [cite: lipari_2002_neutrino].",
                   number="3", anchor="fig-xsec")

    assert block["kind"] == "figure"
    assert block["file"] == "fig1.png"
    assert block["number"] == "3"
    assert block["anchor"] == "fig-xsec"
    assert "[cite: lipari_2002_neutrino]" in block["caption"]


def test_the_alt_text_carries_no_citation_marker() -> None:
    """A marker cut in half invents a tag that no record can ever answer.

    The alt text is cut at ALT_MAX_CHARS. A `[cite: ...]` that straddles the cut
    loses its closing bracket, and `CITE_TAG` then matches on to the next `]`
    anywhere in the file — so a whole run of markup gets reported as an
    unresolved tag. The caption under the image is where the citation belongs.
    """
    caption = (
        "Coherent pion production data compared with the model of "
        "[cite: Alvarez-Ruso:2007ipn] and with the later calculation of "
        "[cite: Higuera:2014azj], over the whole energy range of the beam."
    )

    block = stored("fig23a.png", caption, number="23", anchor="fig-coh")
    image = render.render_figure(block, context())

    alt = alt_of(image)
    assert "cite:" not in alt
    assert "[" not in alt
    # The caption below the image keeps both markers, for the renderer to link.
    assert len(reference_store.CITE_TAG.findall(block["caption"])) == 2


def test_a_long_alt_text_is_still_cut() -> None:
    image = render.render_figure(stored("fig1.png", "word " * 100), context())

    alt = alt_of(image)
    assert alt.endswith("...")
    assert len(alt) <= render.ALT_MAX_CHARS


def test_a_caption_of_only_a_citation_still_gives_an_alt() -> None:
    image = render.render_figure(stored("fig1.png", "[cite: lipari_2002_neutrino]"),
                                 context())

    assert alt_of(image) == "figure"


def test_obsidian_sizes_the_image_with_its_own_syntax() -> None:
    """Markdown cannot set a width. Obsidian does it inside the alt text."""
    block = stored("fig1.png", "A cross section.", number="3")

    image = render.render_figure(block, context("obsidian"))

    assert image.startswith("![A cross section.|%d](../figures/fig1.png)"
                            % render.FIGURE_WIDTH_PX)
    assert "<img" not in image


def test_vscode_sizes_the_image_with_html() -> None:
    block = stored("fig1.png", "A cross section.", number="3")

    image = render.render_figure(block, context("vscode"))

    assert '<img src="../figures/fig1.png"' in image
    assert 'width="%d"' % render.FIGURE_WIDTH_PX in image
