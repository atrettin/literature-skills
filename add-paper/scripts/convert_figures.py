#!/usr/bin/env python3
"""Convert paper figures to PNG, keeping the originals.

A paper directory ends up with two figure folders:

    figures/       one PNG per figure, whitespace cropped
    figures_raw/   the files exactly as the arXiv source shipped them

The originals are kept so a conversion can be redone — with a different
resolution, or a better tool — without downloading the paper again.

Used by arxiv_fetch.py during ingestion, and runnable on its own to convert a
paper whose figures/ holds anything other than cropped PNGs:

    convert_figures.py literature/<slug> [...]
    convert_figures.py --all literature

External tools, all optional until a paper actually needs one:

    gs             EPS, PS and PDF   (brew install ghostscript)
    rsvg-convert   SVG               (brew install librsvg)
    Pillow         raster formats, and the cropping step for every format
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"}
GHOSTSCRIPT_SUFFIXES = {".eps", ".ps", ".pdf"}
SVG_SUFFIXES = {".svg"}

RAW_DIR_NAME = "figures_raw"
FIGURES_DIR_NAME = "figures"

RENDER_DPI = 300
# Ghostscript at 300 dpi turns a full-page plot into several thousand pixels.
# Nothing reads these figures at that size, and the files get large, so the
# long edge is capped and the image resampled down.
MAX_PIXELS = 2000
# Left around the cropped content, so a plot's outermost ink is not flush
# against the image border.
CROP_MARGIN = 8


class ConversionError(RuntimeError):
    """A figure could not be turned into a PNG."""


def run_tool(command: list[str]) -> None:
    # CPython only takes its posix_spawn path when the executable is given as a
    # path, not a bare name looked up on PATH. See the close_fds note below.
    resolved = shutil.which(command[0])
    if resolved is None:
        raise ConversionError("%s is not installed" % command[0])
    command = [resolved] + command[1:]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=120,
            check=False,
            stdin=subprocess.DEVNULL,
            # macOS aborts a fork() from a process that has threads running,
            # in Network.framework's atfork handler — the child dies with
            # SIGSEGV before it can exec, and every figure fails with an empty
            # error. arxiv_fetch downloads the paper before converting it, so
            # its process is in exactly that state. close_fds=False lets
            # CPython use posix_spawn, which never forks.
            close_fds=False,
        )
    except FileNotFoundError as error:
        raise ConversionError("%s is not installed" % command[0]) from error
    except subprocess.TimeoutExpired as error:
        raise ConversionError("%s timed out" % command[0]) from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ConversionError(
            "%s failed: %s" % (command[0], detail[-1] if detail else "no output")
        )


def render_with_ghostscript(source: Path, target: Path) -> None:
    command = [
        "gs",
        "-dSAFER",
        "-dBATCH",
        "-dNOPAUSE",
        "-dQUIET",
        "-sDEVICE=png16m",
        "-r%d" % RENDER_DPI,
        "-dFirstPage=1",
        "-dLastPage=1",
        "-dTextAlphaBits=4",
        "-dGraphicsAlphaBits=4",
    ]
    if source.suffix.lower() == ".eps":
        # Render the BoundingBox rather than a full page of mostly white.
        command.append("-dEPSCrop")
    command.extend(["-sOutputFile=%s" % target, str(source)])
    run_tool(command)
    if not target.exists():
        raise ConversionError("ghostscript wrote no output")


def render_with_rsvg(source: Path, target: Path) -> None:
    run_tool(
        [
            "rsvg-convert",
            "-f",
            "png",
            "-d",
            str(RENDER_DPI),
            "-p",
            str(RENDER_DPI),
            "-o",
            str(target),
            str(source),
        ]
    )
    if not target.exists():
        raise ConversionError("rsvg-convert wrote no output")


def render_raster(source: Path, target: Path) -> None:
    try:
        from PIL import Image
    except ImportError as error:
        raise ConversionError("Pillow is not installed") from error
    with Image.open(source) as image:
        image.load()
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            flattened = Image.new("RGB", image.size, (255, 255, 255))
            flattened.paste(image, mask=image.split()[-1])
            image = flattened
        else:
            image = image.convert("RGB")
        image.save(target, format="PNG")


def crop_and_shrink(target: Path) -> None:
    """Trim the white border and cap the resolution. Best effort."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return  # the PNG is still valid, merely untrimmed
    try:
        with Image.open(target) as image:
            image.load()
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                flattened = Image.new("RGB", image.size, (255, 255, 255))
                flattened.paste(image, mask=image.split()[-1])
                image = flattened
            else:
                image = image.convert("RGB")

            background = Image.new("RGB", image.size, (255, 255, 255))
            difference = ImageChops.difference(image, background)
            box = difference.getbbox()
            if box:
                left = max(box[0] - CROP_MARGIN, 0)
                top = max(box[1] - CROP_MARGIN, 0)
                right = min(box[2] + CROP_MARGIN, image.width)
                bottom = min(box[3] + CROP_MARGIN, image.height)
                if right > left and bottom > top:
                    image = image.crop((left, top, right, bottom))

            longest = max(image.width, image.height)
            if longest > MAX_PIXELS:
                scale = MAX_PIXELS / longest
                image = image.resize(
                    (max(int(image.width * scale), 1), max(int(image.height * scale), 1)),
                    Image.Resampling.LANCZOS,
                )
            image.save(target, format="PNG")
    except Exception:
        return  # a figure that will not crop is still a usable figure


def convert_one(source: Path, target: Path) -> None:
    """Write `source` to `target` as a cropped PNG. Raises ConversionError."""
    suffix = source.suffix.lower()
    target.parent.mkdir(parents=True, exist_ok=True)
    if suffix in GHOSTSCRIPT_SUFFIXES:
        render_with_ghostscript(source, target)
    elif suffix in SVG_SUFFIXES:
        render_with_rsvg(source, target)
    elif suffix in RASTER_SUFFIXES:
        render_raster(source, target)
    else:
        raise ConversionError("no converter for %s files" % (suffix or "extension-less"))
    crop_and_shrink(target)


def unique_target(figures_dir: Path, stem: str, taken: set[str]) -> Path:
    """A free `<stem>.png`, since a.eps and a.pdf would collide."""
    candidate = "%s.png" % stem
    counter = 2
    while candidate in taken:
        candidate = "%s_%d.png" % (stem, counter)
        counter += 1
    taken.add(candidate)
    return figures_dir / candidate


def convert_directory(
    figures_dir: Path, warnings: list[str] | None = None
) -> dict[str, str]:
    """Convert every original in `figures_raw/` into a PNG in `figures/`.

    Returns a map of original file name to PNG file name, for rewriting the
    references that the chapters and FIGURES.md carry. A figure that cannot be
    converted is copied over unchanged and reported in `warnings`, so the paper
    keeps the figure rather than losing it.
    """
    warnings = warnings if warnings is not None else []
    raw_dir = figures_dir.parent / RAW_DIR_NAME
    if not raw_dir.is_dir():
        return {}

    renames: dict[str, str] = {}
    taken: set[str] = set()
    for source in sorted(raw_dir.iterdir()):
        if not source.is_file() or source.name.endswith(".md"):
            continue
        target = unique_target(figures_dir, source.stem, taken)
        try:
            convert_one(source, target)
        except ConversionError as error:
            warnings.append("figure not converted (%s): %s" % (error, source.name))
            target.unlink(missing_ok=True)
            taken.discard(target.name)
            fallback = figures_dir / source.name
            figures_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, fallback)
            renames[source.name] = fallback.name
            continue
        renames[source.name] = target.name
    return renames


def stage_originals(figures_dir: Path) -> None:
    """Move whatever is in `figures/` into `figures_raw/`, keeping FIGURES.md."""
    raw_dir = figures_dir.parent / RAW_DIR_NAME
    raw_dir.mkdir(parents=True, exist_ok=True)
    for item in sorted(figures_dir.iterdir()):
        if not item.is_file() or item.name.endswith(".md"):
            continue
        destination = raw_dir / item.name
        if destination.exists():
            item.unlink()
            continue
        shutil.move(str(item), str(destination))


def rewrite_references(paper_dir: Path, renames: dict[str, str]) -> None:
    """Point the chapters and FIGURES.md at the converted file names."""
    changed = {old: new for old, new in renames.items() if old != new}
    if not changed:
        return
    targets = [paper_dir / FIGURES_DIR_NAME / "FIGURES.md"]
    chapters_dir = paper_dir / "chapters"
    if chapters_dir.is_dir():
        targets.extend(sorted(chapters_dir.glob("*.md")))
    targets.append(paper_dir / "INDEX.md")

    pattern = re.compile(
        "|".join(re.escape(old) for old in sorted(changed, key=len, reverse=True))
    )
    for path in targets:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        replaced = pattern.sub(lambda match: changed[match.group(0)], text)
        if replaced != text:
            path.write_text(replaced, encoding="utf-8")


def has_originals(raw_dir: Path) -> bool:
    if not raw_dir.is_dir():
        return False
    return any(
        item.is_file() and not item.name.endswith(".md") for item in raw_dir.iterdir()
    )


def clear_generated(figures_dir: Path) -> None:
    """Empty `figures/` of images, keeping FIGURES.md."""
    if not figures_dir.is_dir():
        return
    for item in sorted(figures_dir.iterdir()):
        if item.is_file() and not item.name.endswith(".md"):
            item.unlink()


def convert_paper(paper_dir: Path, warnings: list[str] | None = None) -> dict[str, str]:
    """Convert one paper's figures. Running it again is a no-op.

    Only the first run stages `figures/` into `figures_raw/`. Afterwards the
    originals are already there, and `figures/` holds nothing but generated
    PNGs — staging those again would file conversion output as source material
    and convert it a second time under a new name.
    """
    figures_dir = paper_dir / FIGURES_DIR_NAME
    raw_dir = paper_dir / RAW_DIR_NAME
    if not figures_dir.is_dir() and not raw_dir.is_dir():
        return {}
    if has_originals(raw_dir):
        clear_generated(figures_dir)
    else:
        stage_originals(figures_dir)
    renames = convert_directory(figures_dir, warnings)
    rewrite_references(paper_dir, renames)
    return renames


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="paper directories")
    args = parser.parse_args()

    paper_dirs: list[Path] = list(args.paths)

    failures = 0
    for paper_dir in paper_dirs:
        if not (paper_dir / FIGURES_DIR_NAME).is_dir():
            print("%-46s no figures directory" % paper_dir.name)
            continue
        warnings: list[str] = []
        renames = convert_paper(paper_dir, warnings)
        print("%-46s %2d figures" % (paper_dir.name, len(renames)))
        for warning in warnings:
            failures += 1
            print("    ! %s" % warning)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
