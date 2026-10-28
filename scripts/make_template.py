"""Tool 1 — Grid template generator.

Produces a printable A4 PDF grid the user fills in by hand (one labelled block
of N cells per character), plus a sidecar template_layout.json that records the
exact pixel geometry of every cell and the corner registration markers. Tool 2
(import_handwriting.py) reads that JSON to split a scan reliably — the grid is
never re-guessed.

Coordinate system: template pixels at `dpi` (A4). Every cell rect and marker
center in the JSON is in these template pixels. Marker order per page is
[top-left, top-right, bottom-right, bottom-left], by their centers.

Each writing cell carries four faint horizontal writing-guide lines (ascender,
x-height, baseline, descender) so the user keeps letter proportions inside the
cell. Their y-positions are recorded per cell in the layout JSON ("guides"), and
the shared fractions are recorded once at the top level ("guide_fractions"), so
Tool 2 reads the exact baseline per cell instead of estimating it from ink, and
strips the guides the same way it strips the border/label.

The character set is data, not code: it is read from a charset file (default
template/charset_default.txt, one entry per line, `#` comments and blank lines
allowed). The generator is charset-agnostic — swap the file to make a template
for any set (e.g. Greek + math) with no code change. Every cell in the layout
JSON records the exact character it maps to, so Tool 2 stays correct for ANY
charset, never assuming the default 87-char set.

Run: .venv/bin/python scripts/make_template.py [--charset PATH] [--cell-w N] [--cell-h N] [--n-cells K]
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
OUT_DIR = Path(__file__).resolve().parents[1] / "template"
DEFAULT_CHARSET = OUT_DIR / "charset_default.txt"

# Layout constants (template pixels at DPI). All tunable via CLI where useful.
DPI = 150
A4_PX = (1240, 1754)          # A4 at 150 dpi
MARGIN = 90                   # page margin; markers sit at its corners
MARKER_SIZE = 36              # solid black fiducial square side
REGION_PAD = 34               # gap between markers and the cell area
LABEL_H = 30                  # height reserved above each block for its label
CELL_GAP = 8                  # gap between a character's cells
BLOCK_HGAP = 44               # horizontal gap between blocks
# Vertical gap between block rows. Kept large (and much bigger than the ~4px gap
# between a label and its OWN cells right below it) so every label reads as
# belonging to the block beneath it, never the block above.
BLOCK_VGAP = 46

# Printed elements are gray so real (dark) pen ink is trivially separable by a
# lightness threshold in Tool 2, and labels sit OUTSIDE the writing cells (at
# known positions) so they're never scanned as ink. Labels are a medium gray:
# dark enough to read reliably on print (even small punctuation), still clearly
# lighter than pen ink.
CELL_BORDER = (176, 176, 176)
LABEL_COLOR = (120, 120, 120)
MARKER_COLOR = (0, 0, 0)

# Writing-guide lines inside each cell. Tool 2 reads the baseline y from the
# layout JSON (not from the printed line), so EVERY guide — the baseline
# included — is printed light enough that Tool 2's brightness threshold
# (gray < INK_THRESH=190 = ink) strips it cleanly, while dark pen ink survives.
# The baseline was previously darker (170, kept by that threshold → leftover
# residue that fought glyph strokes); it is now light like the others and only
# stands out by being THICKER, so the user still finds it at a glance.
GUIDE_COLOR = (210, 210, 210)           # ascender / x-height / descender
GUIDE_BASELINE_COLOR = (205, 205, 205)  # baseline: same lightness, removable
GUIDE_WIDTH = 1
GUIDE_BASELINE_WIDTH = 3                 # thicker = findable despite being light

# Guide y-positions as fractions of the cell's full height, measured DOWN from
# the cell top. Tunable here (or via generate(guide_fracs=...)); not hardcoded at
# the draw site. Same frame for every cell, so all captured glyphs share one
# consistent baseline/x-height. Cells are portrait (taller than wide), so these
# leave every zone roomy: visible top/bottom padding off the border, a generous
# ascender→baseline body, a comfortable x-body band (x-height→baseline), and a
# real descender zone (baseline→descender) for tails.
#   top padding    0.14        ascender→baseline body  0.56
#   x-body band    0.24        descender zone          0.19
#   bottom padding 0.11
GUIDE_FRACTIONS = {
    "ascender": 0.14,
    "x_height": 0.46,
    "baseline": 0.70,
    "descender": 0.89,
}


def load_charset(path) -> list:
    """Read a charset file into an ordered list of cell-block entries.

    One entry per line, in file order. Blank lines are skipped. A line whose
    first non-space character is `#` is a comment and skipped, EXCEPT a line
    that is exactly `#` (which captures the hash character itself). Entries are
    taken verbatim minus the trailing newline, so multi-codepoint or
    whitespace-bearing entries survive intact.
    """
    entries = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#") and stripped != "#":
            continue
        entries.append(raw.rstrip())
    if not entries:
        raise ValueError(f"charset file has no entries: {path}")
    return entries


def _blocks_per_page(cell_w: int, cell_h: int, n_cells: int):
    """Compute block grid geometry for one page. Returns (cols, rows, positions).

    positions: list of (x, y) top-left of each block's cell strip, in template px.
    """
    block_w = n_cells * cell_w + (n_cells - 1) * CELL_GAP
    block_h = LABEL_H + cell_h
    x0 = MARGIN + MARKER_SIZE // 2 + REGION_PAD
    y0 = MARGIN + MARKER_SIZE // 2 + REGION_PAD
    x1 = A4_PX[0] - (MARGIN + MARKER_SIZE // 2 + REGION_PAD)
    y1 = A4_PX[1] - (MARGIN + MARKER_SIZE // 2 + REGION_PAD)
    cols = max(1, (x1 - x0 + BLOCK_HGAP) // (block_w + BLOCK_HGAP))
    rows = max(1, (y1 - y0 + BLOCK_VGAP) // (block_h + BLOCK_VGAP))
    positions = []
    for r in range(rows):
        for c in range(cols):
            bx = x0 + c * (block_w + BLOCK_HGAP)
            by = y0 + r * (block_h + BLOCK_VGAP)
            positions.append((bx, by))
    return int(cols), int(rows), positions, block_w, block_h


def _guide_ys(cell_top: int, cell_h: int, fracs: dict) -> dict:
    """Absolute template-px y for each guide line of a cell at `cell_top`.

    Same fractions (of cell_h, from the cell top) for every cell, so all cells
    share one baseline/x-height frame. Keys: ascender, x_height, baseline,
    descender. Rounded to whole pixels.
    """
    return {name: cell_top + round(fracs[name] * cell_h)
            for name in ("ascender", "x_height", "baseline", "descender")}


def _marker_centers():
    m = MARGIN + MARKER_SIZE // 2
    return [
        [m, m],                              # top-left
        [A4_PX[0] - m, m],                   # top-right
        [A4_PX[0] - m, A4_PX[1] - m],        # bottom-right
        [m, A4_PX[1] - m],                   # bottom-left
    ]


def generate(out_dir=OUT_DIR, cell_w: int = 84, cell_h: int = 132, n_cells: int = 5,
             charset=None, guide_fracs=None, lossless_pdf: bool = False):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if charset is None:
        charset = load_charset(DEFAULT_CHARSET)
    if guide_fracs is None:
        guide_fracs = GUIDE_FRACTIONS
    label_font = ImageFont.truetype(FONT_PATH, 24)

    cols, rows, positions, block_w, _ = _blocks_per_page(cell_w, cell_h, n_cells)
    per_page = len(positions)
    markers = _marker_centers()

    pages_img = []
    pages_json = []
    page_cells: list = []
    page_index = 0

    def flush_page():
        nonlocal page_cells, page_index
        img = Image.new("RGB", A4_PX, (255, 255, 255))
        d = ImageDraw.Draw(img)
        for cx, cy in markers:  # solid fiducial squares centered on corners
            h = MARKER_SIZE // 2
            d.rectangle([cx - h, cy - h, cx + h, cy + h], fill=MARKER_COLOR)
        for cell in page_cells:
            x0, y0, x1, y1 = cell["rect"]
            d.rectangle([x0, y0, x1, y1], outline=CELL_BORDER, width=2)
            # faint writing guides inside the cell (baseline heavier)
            g = cell["guides"]
            for name in ("ascender", "x_height", "descender"):
                d.line([x0, g[name], x1, g[name]], fill=GUIDE_COLOR, width=GUIDE_WIDTH)
            d.line([x0, g["baseline"], x1, g["baseline"]],
                   fill=GUIDE_BASELINE_COLOR, width=GUIDE_BASELINE_WIDTH)
        # labels: one per block, sitting in the reserved strip DIRECTLY above
        # that block's own cells (bottom of text ~4px above the cell tops), so
        # the label unmistakably attaches to the block below it, not above.
        for blk in _page_blocks:
            char, bx, by = blk
            cell_top = by + LABEL_H
            d.text((bx + block_w / 2, cell_top - 4), f"write:  {char}",
                   font=label_font, fill=LABEL_COLOR, anchor="ms")
        pages_img.append(img)
        pages_json.append({"index": page_index, "markers": markers, "cells": page_cells})
        page_cells = []
        page_index += 1

    _page_blocks: list = []
    slot = 0
    for char in charset:
        if slot == per_page:
            flush_page()
            _page_blocks = []
            slot = 0
        bx, by = positions[slot]
        _page_blocks.append((char, bx, by))
        cell_top = by + LABEL_H
        for i in range(n_cells):
            cx0 = bx + i * (cell_w + CELL_GAP)
            page_cells.append({
                "char": char, "index": i,
                "rect": [cx0, cell_top, cx0 + cell_w, cell_top + cell_h],
                "guides": _guide_ys(cell_top, cell_h, guide_fracs),
            })
        slot += 1
    if page_cells:
        flush_page()

    layout = {
        "version": 1,
        "dpi": DPI,
        "page_px": list(A4_PX),
        "native_size_px": cell_h,
        "cell_w": cell_w,
        "cell_h": cell_h,
        "n_cells": n_cells,
        "marker_size_px": MARKER_SIZE,
        # Shared guide frame: fractions of cell height (from cell top) used for
        # every cell. Per-cell absolute y's are under each cell's "guides".
        "guide_fractions": dict(guide_fracs),
        "pages": pages_json,
    }
    pdf_path = out_dir / "template.pdf"
    json_path = out_dir / "template_layout.json"
    if lossless_pdf:
        # palette pages embed with Flate (lossless): PIL's default JPEG path
        # chroma-subsamples 1px colored lines into gray, which would defeat a
        # color-keyed template (iPad pilot)
        pages_img = [im.convert("P", palette=Image.ADAPTIVE,
                                dither=Image.Dither.NONE) for im in pages_img]
    pages_img[0].save(pdf_path, save_all=True, append_images=pages_img[1:])
    json_path.write_text(json.dumps(layout, indent=2, ensure_ascii=False), encoding="utf-8")

    total_cells = sum(len(p["cells"]) for p in pages_json)
    print(f"template: {len(charset)} chars x {n_cells} cells = {total_cells} cells "
          f"across {len(pages_img)} page(s), {cols}x{rows} blocks/page, "
          f"cell {cell_w}x{cell_h}px")
    print(f"wrote {pdf_path} and {json_path}")
    return pdf_path, json_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate the handwriting grid template PDF.")
    ap.add_argument("--charset", type=Path, default=DEFAULT_CHARSET,
                    help="charset file, one entry per line (default template/charset_default.txt)")
    ap.add_argument("--cell-w", type=int, default=84, help="cell width in template px (default 84)")
    ap.add_argument("--cell-h", type=int, default=132,
                    help="cell height in template px; portrait, taller than wide (default 132)")
    ap.add_argument("--n-cells", type=int, default=5, help="samples per character (default 5)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    generate(args.out_dir, cell_w=args.cell_w, cell_h=args.cell_h, n_cells=args.n_cells,
             charset=load_charset(args.charset))


if __name__ == "__main__":
    main()
