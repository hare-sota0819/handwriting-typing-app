"""Generate the FULL handwriting collection template for GoodNotes (iPad).

Same cyan colour-keyed sheet as the pilot (nothing black anywhere, so Tool 2b
strips furniture by hue and dark Apple-Pencil ink can never be collateral
damage) and the same guide frame, so every captured glyph shares one baseline
and one native_size_px. Two things the pilot template could not express are
added here, and they are why this generator exists instead of a --charset swap:

  * OVERSIZED DELIMITERS — ( ) [ ] { } | written to fill the whole cell
    height, for stretchy \\left(...\\right) assemblies. They share a codepoint
    with the normal-size versions, so each gets its own store key ("big:(")
    and the two sizes can never be picked for one another.
  * PEN STROKES in WIDE cells — MathJax emits the fraction bar and the radical
    overbar as RULES (rectangles), not glyphs. Without a real stroke to
    substitute, every fraction would carry a ruler-perfect line through
    otherwise handwritten output. Three lengths are captured and the nearest
    one is stretched at substitution time.

Cell HEIGHT is identical for every cell (including the wide ones), so the
guide fractions, the baseline and native_size_px stay shared store-wide; only
the WIDTH varies.

Scope: the ENGLISH set is collected here too, not just maths. Both output
looks (tablet-like and paper-like) have to come from ONE clean source,
because paper-scan artefacts are baked into a glyph and cannot be removed
afterwards, while paper character CAN be added at render time. So the whole
store is re-collected on the iPad and the paper store stays only as a restore
point.

Run: .venv/bin/python scripts/make_template_collection.py
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_template as mt
from handwriting import metrics  # noqa: E402  (shared geometry constants + helpers)

REPO = Path(__file__).resolve().parents[1]
# English first (warm-up, and it is the bulk of ordinary writing), then maths.
# Kept as two files so charset_default.txt stays the single source of truth for
# the English set — the print template reads the very same file.
CHARSETS = [REPO / "template" / "charset_default.txt",
            REPO / "template" / "charset_math.txt"]
OUT_DIR = REPO / "template" / "collection"

DEFAULT_VARIANTS = 10
CELL_W = 84
CELL_H = 132

# Cyan palette — same hue family as the pilot template (colour-key removal),
# lightened twice at the user's request ("지금도 두꺼워"): thinner AND paler
# furniture reads as thinner on the iPad.
MARKER_COLOR = (0, 165, 175)
CELL_BORDER = (170, 220, 226)
GUIDE_COLOR = (195, 232, 237)
# The size-guide character is a much lighter cyan than the guide lines: the
# user found the solid guide-coloured glyph visually heavy ("가이드가 너무
# 굵고 크게 보임"). Still clearly cyan-hued, so the colour key strips it,
# and light enough that stripping residue would die at the ink threshold.
GUIDE_GLYPH_COLOR = (213, 240, 244)
TALLEST_XH = 1.45                     # `f` is 1.39 x-heights; the rest is headroom
GUIDE_BASELINE_COLOR = (160, 214, 220)
LABEL_COLOR = (90, 180, 190)
# Line weights, thinned for the same reason (were: border 2 / baseline 3).
CELL_BORDER_WIDTH = 1
BASELINE_WIDTH = 1
# Uniform shrink of the guide frame (and therefore of the size-guide glyphs,
# which are sized off the ascender-baseline distance) about the band centre.
# 1.0 reproduces the historical frame; the user picks the value from an A/B.
GUIDE_SCALE = 1.0
# The size-guide glyph alone renders at this fraction of its guide-true size
# (still seated on the baseline). User choice: the full-size filled sample
# felt dominant, but they wanted the lines kept at 100% — so the sample is a
# half-size hint of shape/position, and the LINES carry the size standard.
GUIDE_GLYPH_SCALE = 0.5


def _scaled_fracs(scale: float) -> dict:
    base = mt.GUIDE_FRACTIONS
    center = (base["ascender"] + base["descender"]) / 2.0
    return {k: center + (v - center) * scale for k, v in base.items()}

BIG_DELIMITERS = "()[]{}|"

# (key, label, cell width, samples). Wide cells hold fewer samples so a block
# still fits the page width; a straight pen stroke has little shape variety.
STROKE_SPECS = [
    ("rule:short", "straight line — SHORT", 120, 7),
    ("rule:med", "straight line — MEDIUM", 300, 3),
    ("rule:long", "straight line — LONG", 460, 2),
]

_DELIM_NAMES = {"(": "lparen", ")": "rparen", "[": "lbracket", "]": "rbracket",
                "{": "lbrace", "}": "rbrace", "|": "bar", "√": "sqrt"}


def folder_for_key(key: str) -> str:
    """Store folder name for a collection key (mirrors split_ipad's fallback)."""
    if key.startswith("big:"):
        return f"big_{_DELIM_NAMES[key[4:]]}"
    if key.startswith("rule:"):
        return f"rule_{key[5:]}"
    if key.startswith("math:"):
        # a letter whose shape in an equation differs from its prose shape;
        # kept under its own key so the two can never substitute for each other
        return f"math_u{ord(key[5:]):04x}"
    if len(key) == 1:
        return f"sym_u{ord(key):04x}"
    raise ValueError(f"no folder rule for key {key!r}")


def load_charsets(paths):
    """Concatenate several charset files, refusing duplicate entries."""
    entries = []
    for path in paths:
        entries += mt.load_charset(path)
    dupes = {e for e in entries if entries.count(e) > 1}
    if dupes:
        raise ValueError(f"entry appears in more than one charset file: {sorted(dupes)}")
    return entries


def build_specs(charset, n_variants: int):
    """Ordered [(key, label, cell_w, n_cells)] for the whole collection."""
    specs = [(ch,
              f"{ch[5:]}   MATH — as written in equations" if ch.startswith("math:")
              else ch,
              CELL_W, n_variants) for ch in charset]
    specs += [(f"big:{ch}", f"{ch}   TALL — fill the cell", CELL_W, n_variants)
              for ch in BIG_DELIMITERS]
    specs += [(key, label, w, n) for key, label, w, n in STROKE_SPECS]
    return specs


def build_specs_explicit(entries, n_variants: int):
    """[(key, label, cell_w, n_cells)] for a hand-picked list of entries."""
    return [(key, label, CELL_W, n_variants) for key, label in entries]




def _draw_size_guide(draw, key, rect, guides):
    """Put the character faintly in its cell, at the size the renderer expects.

    Not decoration and not a tracing exercise — it is the one instrument that
    makes a hand produce consistent METRICS. The user writes their own letterform
    over it; what the guide fixes is how big the character is relative to the
    others and where it sits on the line, which is exactly what a typeface fixes
    by design and what no one can judge by eye. Their words: "그냥 내 글꼴을
    만드는 과정이라고 생각하면 되잖아?"

    Heights and depths come from handwriting/metrics.py — the same numbers the
    renderer seats glyphs by, so the sheet and the renderer cannot drift apart.
    """
    if key.startswith("math:"):
        key = key[5:]  # size/seat guide from the prose letter; shape is theirs
    if len(key) != 1 or not key.strip():
        return
    height = metrics.height_in_x_heights(key)
    depth = metrics.depth_in_x_heights(key)
    if height is None or depth is None:
        return

    x0, y0, x1, y1 = rect
    # Derive the x-height from the ASCENDER zone, not from the printed x-height
    # line: sized off that line the tallest letter still only reaches halfway up
    # the cell and most of the box goes unused, which is both wasteful and harder
    # to write into. TALLEST_XH is the tallest character in the charset (`f`, 1.39
    # x-heights) plus a little headroom, so the biggest letters just fill the
    # ascender-to-baseline frame and everything else follows in proportion.
    x_height_px = (guides["baseline"] - guides["ascender"]) / TALLEST_XH
    x_height_px *= GUIDE_GLYPH_SCALE  # half-size hint; lines keep the standard
    want_h = height * x_height_px
    if want_h <= 1:
        return
    # size a font instance so the character's ink is exactly want_h tall
    probe = ImageFont.truetype(mt.FONT_PATH, 200)
    box = probe.getbbox(key)
    ink_h = max(1, box[3] - box[1])
    font = ImageFont.truetype(mt.FONT_PATH, max(6, round(200 * want_h / ink_h)))
    box = font.getbbox(key)
    ink_w = box[2] - box[0]
    cx = (x0 + x1) / 2
    ink_bottom = guides["baseline"] + depth * x_height_px
    # Stamp it as a hard 1-bit mask rather than drawing text directly: antialiased
    # edges quantise to near-neutral greys when the page is written as a palette
    # PDF, and the colour key then cannot strip them — the template's own check
    # refuses that. A flat mask keeps every printed pixel exactly one cyan.
    ox = round(cx - ink_w / 2 - box[0])
    oy = round(ink_bottom - box[3])
    mask = Image.new("L", (x1 - x0 + 2 * CELL_W, CELL_H * 3), 0)
    ImageDraw.Draw(mask).text((ox - x0 + CELL_W, oy - y0 + CELL_H), key,
                              font=font, fill=255)
    mask = mask.point(lambda v: 255 if v >= 128 else 0)
    draw._image.paste(GUIDE_GLYPH_COLOR, (x0 - CELL_W, y0 - CELL_H), mask)


def _pack(specs):
    """Lay blocks out left-to-right, wrapping rows and pages.

    Returns [[(spec, bx, by), ...], ...] — one list per page.
    """
    x0 = mt.MARGIN + mt.MARKER_SIZE // 2 + mt.REGION_PAD
    y0 = x0
    x1 = mt.A4_PX[0] - x0
    y1 = mt.A4_PX[1] - y0
    block_h = mt.LABEL_H + CELL_H

    pages, page, x, y = [], [], x0, y0
    for spec in specs:
        _, _, cell_w, n = spec
        block_w = n * cell_w + (n - 1) * mt.CELL_GAP
        if block_w > x1 - x0:
            raise ValueError(f"block for {spec[0]!r} is {block_w}px wide, "
                             f"page fits {x1 - x0}px")
        if x + block_w > x1:                       # wrap to the next row
            x = x0
            y += block_h + mt.BLOCK_VGAP
        if y + block_h > y1:                       # wrap to the next page
            pages.append(page)
            page, x, y = [], x0, y0
        page.append((spec, x, y))
        x += block_w + mt.BLOCK_HGAP
    if page:
        pages.append(page)
    return pages


def generate(out_dir=OUT_DIR, n_variants: int = DEFAULT_VARIANTS, charset=None,
             specs=None, guide_scale: float = GUIDE_SCALE):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if charset is None and not specs:
        charset = load_charsets(CHARSETS)
    label_font = ImageFont.truetype(mt.FONT_PATH, 24)
    guide_fracs = _scaled_fracs(guide_scale)
    markers = mt._marker_centers()

    pages_img, pages_json = [], []
    for page_index, blocks in enumerate(_pack(specs or build_specs(charset, n_variants))):
        img = Image.new("RGB", mt.A4_PX, (255, 255, 255))
        d = ImageDraw.Draw(img)
        for cx, cy in markers:
            h = mt.MARKER_SIZE // 2
            d.rectangle([cx - h, cy - h, cx + h, cy + h], fill=MARKER_COLOR)

        cells = []
        for (key, label, cell_w, n), bx, by in blocks:
            cell_top = by + mt.LABEL_H
            guides = mt._guide_ys(cell_top, CELL_H, guide_fracs)
            block_w = n * cell_w + (n - 1) * mt.CELL_GAP
            for i in range(n):
                cx0 = bx + i * (cell_w + mt.CELL_GAP)
                rect = [cx0, cell_top, cx0 + cell_w, cell_top + CELL_H]
                d.rectangle(rect, outline=CELL_BORDER, width=CELL_BORDER_WIDTH)
                for name in ("ascender", "x_height", "descender"):
                    d.line([rect[0], guides[name], rect[2], guides[name]],
                           fill=GUIDE_COLOR, width=mt.GUIDE_WIDTH)
                d.line([rect[0], guides["baseline"], rect[2], guides["baseline"]],
                       fill=GUIDE_BASELINE_COLOR, width=BASELINE_WIDTH)
                _draw_size_guide(d, key, rect, guides)
                cells.append({"char": key, "key": key, "index": i,
                              "rect": rect, "guides": guides})
            d.text((bx + block_w / 2, cell_top - 4), f"write:  {label}",
                   font=label_font, fill=LABEL_COLOR, anchor="ms")

        pages_img.append(img)
        pages_json.append({"index": page_index, "markers": markers, "cells": cells})

    layout = {
        "version": 1,
        "dpi": mt.DPI,
        "page_px": list(mt.A4_PX),
        "native_size_px": CELL_H,
        "cell_w": CELL_W,
        "cell_h": CELL_H,
        "n_cells": n_variants,
        "marker_size_px": mt.MARKER_SIZE,
        "guide_fractions": dict(guide_fracs),
        "pages": pages_json,
    }
    # palette/Flate keeps the 1px cyan lines lossless (PIL's default JPEG path
    # chroma-subsamples them to gray and defeats the colour key)
    pages_img = [im.convert("P", palette=Image.ADAPTIVE, dither=Image.Dither.NONE)
                 for im in pages_img]
    pdf_path = out_dir / "template.pdf"
    json_path = out_dir / "template_layout.json"
    pages_img[0].save(pdf_path, save_all=True, append_images=pages_img[1:])
    json_path.write_text(json.dumps(layout, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    total = sum(len(p["cells"]) for p in pages_json)
    if specs:
        print(f"template: {len(specs)} entries = {total} cells across "
              f"{len(pages_img)} pages")
    else:
        n_entries = len(charset) + len(BIG_DELIMITERS) + len(STROKE_SPECS)
        print(f"collection template: {n_entries} entries ({len(charset)} characters "
              f"+ {len(BIG_DELIMITERS)} tall delimiters + {len(STROKE_SPECS)} stroke "
              f"lengths) = {total} cells across {len(pages_img)} pages")
    print(f"wrote {pdf_path} and {json_path}")
    return pdf_path, json_path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--charset", type=Path, nargs="+", default=CHARSETS,
                    help="one or more charset files, concatenated in order")
    ap.add_argument("--variants", type=int, default=DEFAULT_VARIANTS,
                    help=f"samples per symbol (default {DEFAULT_VARIANTS})")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    generate(args.out_dir, n_variants=args.variants,
             charset=load_charsets(args.charset))


if __name__ == "__main__":
    main()
