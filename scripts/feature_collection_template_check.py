"""Verification for the full collection template (scripts/make_template_collection.py).

1. Full template schema (English set + maths set + 7 tall delimiters + 3
   stroke lengths): every cell shares ONE height and one guide frame — only
   the width varies — so the whole store keeps a single baseline and
   native_size_px; cells stay inside the marker region and never overlap;
   every entry gets its declared number of samples; the tall-delimiter and
   stroke entries carry non-codepoint store keys so they can never be mixed
   with the normal-size character of the same codepoint.
2. Nothing dark/neutral is printed — all furniture is cyan-hued, so Tool 2b's
   colour key can remove 100% of it (same contract as the pilot template).
3. Round-trip on a MINIATURE template (few symbols, both special cell
   kinds, 2 pages): stamped ink extracts to a store whose keys and folders are
   the math keys, with ink-only RGBA and a constant baseline_y.

Everything is generated under out/ — the committed template/collection/* is never
rewritten by this check, so running verify.sh leaves the tree clean.

Run: .venv/bin/python scripts/feature_collection_template_check.py
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_template_collection as mtm  # noqa: E402
import split_ipad  # noqa: E402
from make_fake_scan import _slanted_glyph  # noqa: E402
from handwriting.compositor import rasterize_pdf  # noqa: E402
from handwriting.glyphstore import GlyphStore  # noqa: E402

OUT = REPO / "out" / "collection_template_check"
BOLD_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SCALE = 2                       # round-trip only; the real run uses 4 (600 dpi)
MINI_SYMBOLS = ["α", "θ", "∫", "√"]


def check_full_template():
    pdf_path, json_path = mtm.generate(out_dir=OUT / "full")
    layout = json.loads(json_path.read_text("utf-8"))
    cells = [c for p in layout["pages"] for c in p["cells"]]
    charset = mtm.load_charsets(mtm.CHARSETS)

    keys = {}
    for c in cells:
        keys.setdefault(c["key"], []).append(c)
    expected = ([(ch, mtm.DEFAULT_VARIANTS) for ch in charset]
                + [(f"big:{ch}", mtm.DEFAULT_VARIANTS) for ch in mtm.BIG_DELIMITERS]
                + [(k, n) for k, _, _, n in mtm.STROKE_SPECS])
    n_entries = len(charset) + len(mtm.BIG_DELIMITERS) + len(mtm.STROKE_SPECS)
    assert len(keys) == len(expected) == n_entries, (len(keys), len(expected))
    for key, n in expected:
        got = keys[key]
        assert len(got) == n, f"{key!r}: {len(got)} cells, expected {n}"
        assert sorted(c["index"] for c in got) == list(range(n)), key
    assert len([k for k in keys if k.startswith("big:")]) == 7
    assert len([k for k in keys if k.startswith("rule:")]) == 3
    # every store key maps to a distinct folder, and a big/normal pair never collide
    folders = {k: split_ipad._folder_name_with_symbols(k) for k in keys}
    assert len(set(folders.values())) == len(folders), "folder name collision"
    # { } | are collected at normal size here too, so the pair is in one layout
    assert folders["{"] != folders["big:{"], "tall and normal { share a folder"

    # ONE height and ONE guide frame everywhere; only width varies
    heights = {c["rect"][3] - c["rect"][1] for c in cells}
    assert heights == {layout["cell_h"]}, heights
    widths = {c["rect"][2] - c["rect"][0] for c in cells}
    assert widths == {mtm.CELL_W} | {w for _, _, w, _ in mtm.STROKE_SPECS}, widths
    for c in cells:
        g = c["guides"]
        assert (c["rect"][1] < g["ascender"] < g["x_height"] < g["baseline"]
                < g["descender"] < c["rect"][3]), c["key"]
        assert g["baseline"] - c["rect"][1] == round(
            layout["guide_fractions"]["baseline"] * layout["cell_h"]), c["key"]

    # inside the marker region, and no two cells on a page overlap
    for page in layout["pages"]:
        xs = [m[0] for m in page["markers"]]
        ys = [m[1] for m in page["markers"]]
        lo_x, hi_x, lo_y, hi_y = min(xs), max(xs), min(ys), max(ys)
        rects = [c["rect"] for c in page["cells"]]
        for x0, y0, x1, y1 in rects:
            assert lo_x < x0 and x1 < hi_x and lo_y < y0 and y1 < hi_y
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]

    n_cells = len(cells)
    print(f"PASS: collection template schema — {n_entries} entries, {n_cells} cells, "
          f"{len(layout['pages'])} pages, one shared cell height + guide frame, "
          f"distinct folders for tall vs normal delimiters")
    return pdf_path, layout


def check_nothing_black(pdf_path, layout):
    page = rasterize_pdf(pdf_path, tuple(layout["page_px"]))[0]
    rgb = np.asarray(page.convert("RGB")).astype(np.int16)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    printed = rgb.min(axis=2) < 245
    neutral_dark = printed & (np.abs(g - r) < 12) & (np.abs(b - r) < 12)
    assert neutral_dark.mean() < 1e-4, \
        f"template has neutral/black print ({neutral_dark.mean():.2%})"
    assert split_ipad._cyan_mask(rgb.astype(np.uint8))[printed].mean() > 0.55, \
        "printed furniture is not predominantly cyan-keyed"
    print("PASS: nothing black/neutral is printed — all furniture is cyan-keyed")


def _stamp(canvas, layout, meta, font):
    """Stamp plausible dark ink into every cell of one page."""
    d = ImageDraw.Draw(canvas)
    for cell in meta["cells"]:
        x0, y0, x1, y1 = (v * SCALE for v in cell["rect"])
        guides = {k: v * SCALE for k, v in cell["guides"].items()}
        key = cell["key"]
        if key.startswith("rule:"):                       # a drawn pen stroke
            pad = (x1 - x0) // 10
            d.line([x0 + pad, guides["baseline"], x1 - pad, guides["baseline"]],
                   fill=(20, 20, 24, 255), width=3 * SCALE)
        elif key.startswith("big:"):                      # full-height delimiter
            pad = (y1 - y0) // 12
            cx = (x0 + x1) // 2
            d.line([cx, y0 + pad, cx, y1 - pad], fill=(20, 20, 24, 255),
                   width=3 * SCALE)
            d.line([cx, y0 + pad, cx + 6 * SCALE, y0 + pad],
                   fill=(20, 20, 24, 255), width=3 * SCALE)
        else:
            tile = _slanted_glyph(key, x1 - x0, y1 - y0, guides, y0, font)
            canvas.alpha_composite(tile, (x0, y0))
    return canvas


def check_roundtrip():
    """Miniature template so the round-trip stays small but exercises
    both special cell kinds alongside ordinary symbols."""
    mini_dir = OUT / "mini"
    pdf_path, json_path = mtm.generate(out_dir=mini_dir, n_variants=2,
                                       charset=MINI_SYMBOLS)
    layout = json.loads(json_path.read_text("utf-8"))
    pw, ph = layout["page_px"]
    zone = (layout["guide_fractions"]["baseline"]
            - layout["guide_fractions"]["ascender"])
    font = ImageFont.truetype(BOLD_FONT,
                              max(8, round(zone * layout["cell_h"] * SCALE * 1.05)))
    pages = rasterize_pdf(pdf_path, (pw * SCALE, ph * SCALE))
    assert len(pages) == len(layout["pages"])
    fixtures = []
    for meta, page in zip(layout["pages"], pages):
        img = _stamp(page.convert("RGBA"), layout, meta, font)
        p = OUT / f"fx_p{meta['index'] + 1}.png"
        img.convert("RGB").save(p)
        fixtures.append(str(p))

    store_dir = OUT / "store"
    split_ipad.main(fixtures + ["--layout", str(json_path),
                                "--out", str(store_dir), "--scale", str(SCALE)])
    manifest = json.loads((store_dir / "manifest.json").read_text("utf-8"))
    chars = manifest["characters"]
    for key in MINI_SYMBOLS + [f"big:{c}" for c in mtm.BIG_DELIMITERS] \
            + [k for k, _, _, _ in mtm.STROKE_SPECS]:
        assert key in chars, f"{key!r} missing from the store"
    assert chars["big:("]["folder"] == "big_lparen", chars["big:("]["folder"]
    assert chars["rule:long"]["folder"] == "rule_long"
    assert chars["("]["folder"] != chars["big:("]["folder"] if "(" in chars else True
    assert chars["α"]["folder"] == "sym_u03b1"

    store = GlyphStore(store_dir)
    for key in chars:
        entry = store.entry(key)
        if not entry.variants:
            continue
        assert len({v.baseline_y for v in entry.variants}) == 1, key
        for v in entry.variants:
            img = store.load_image(v)
            assert img.mode == "RGBA", key
            assert np.asarray(img.getchannel("A")).max() == 255, f"{key}: no ink"
    print(f"PASS: round-trip — {len(chars)} keys extracted (symbols + tall "
          f"delimiters + stroke lengths), ink-only RGBA, baseline spread 0")


def main():
    pdf_path, layout = check_full_template()
    check_nothing_black(pdf_path, layout)
    check_roundtrip()
    print("PASS: collection template all green")


if __name__ == "__main__":
    main()
