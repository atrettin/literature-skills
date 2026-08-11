"""How a figure names its file, across the interfaces papers actually use.

A pattern that misses one of these drops the figure silently. The paper's own
`\\ref` commands then point at a figure that is not in the chapter, and nothing
says why — the count of figures is simply lower than the paper has.
"""

from __future__ import annotations

import pytest

import arxiv_fetch


@pytest.mark.parametrize("source,wanted", [
    (r"\includegraphics{fig1.pdf}", "fig1.pdf"),
    (r"\includegraphics*{fig1.pdf}", "fig1.pdf"),
    (r"\includegraphics[width=0.6\columnwidth]{fig1.pdf}", "fig1.pdf"),
    (r"\epsfbox{fig1.eps}", "fig1.eps"),
    (r"\epsffile{fig1.eps}", "fig1.eps"),
    (r"\plotone{fig1.eps}", "fig1.eps"),
])
def test_the_command_forms_name_their_file(source: str, wanted: str) -> None:
    assert arxiv_fetch.GRAPHIC_COMMAND.findall(source) == [wanted]


@pytest.mark.parametrize("source,wanted", [
    # `file=` is the epsfig spelling.
    (r"\psfig{file=flux.BW.eps,width=0.6\columnwidth}", "flux.BW.eps"),
    (r"\epsfig{file=fig1.eps,width=3in}", "fig1.eps"),
    # `figure=` is the older psfig spelling, and the commoner one in a paper of
    # the 1990s or 2000s. NuTeV's hep-ex/0509010 writes 11 of its 13 figures
    # this way, and every one of them used to vanish.
    (r"\psfig{figure=muon_sme_paper.eps,width=0.6\columnwidth}",
     "muon_sme_paper.eps"),
    (r"\psfig{figure=xsec_final_65gev.ps,width=0.6\columnwidth}",
     "xsec_final_65gev.ps"),
    (r"\epsfig{figure=fig1.eps,height=2in}", "fig1.eps"),
    # The key can sit after another one.
    (r"\psfig{width=0.6\columnwidth,figure=fig1.eps}", "fig1.eps"),
])
def test_the_key_value_forms_name_their_file(source: str, wanted: str) -> None:
    assert arxiv_fetch.GRAPHIC_KEYVALUE.findall(source) == [wanted]


def test_a_whole_figure_environment_keeps_its_file_and_its_label() -> None:
    body = (
        "\\begin{figure}\n"
        "\\centerline{\n"
        "\\psfig{figure=xsec_final_65gev.ps,width=0.6\\columnwidth}}\n"
        "\\caption{The differential cross section at 65 GeV.}\n"
        "\\label{fig:xsec65}\n"
        "\\end{figure}\n"
    )

    records = arxiv_fetch.parse_figure(body, "Cross section measurement")

    assert len(records) == 1
    assert records[0]["source"] == "xsec_final_65gev.ps"
    assert records[0]["label"] == "fig:xsec65"
    assert "differential cross section" in records[0]["caption"]
