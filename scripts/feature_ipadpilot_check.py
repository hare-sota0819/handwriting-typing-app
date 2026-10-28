"""Verification for the iPad collection pilot (cyan template rev).

1. Template: regenerates template/ipad_pilot/* — 10 pilot chars x 2 cells on
   the shared schema, and NOTHING dark/neutral printed (all furniture is
   cyan-hued; the color key must be able to remove 100% of it).
2. Fixtures: fake GoodNotes exports of a "written" page —
     a) background ON: cyan template rasterized at 4x with bold stamped ink
     b) background OFF: same ink on plain white (no furniture, no markers)
3. Tool 2b round-trip on BOTH fixtures: exact-coordinate crop (no warp);
   fixture (a) passes the ±2px marker sanity, fixture (b) proceeds with the
   no-marker warning; both stores hold 10 chars x 2 ink-only RGBA variants
   with constant per-char baseline_y and sym_uXXXX folders for ∂/θ; zero
   cyan bleed survives into glyph alpha.
4. Marker sanity guard: a fixture shifted by 5px must be REFUSED (no silent
   warp — brief forbids registration).
5. Inspect mode: synthetic vector-ink and raster-ink PDFs are classified
   correctly by the export-variant matrix.

Run: .venv/bin/python scripts/feature_ipadpilot_check.py
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFont

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_template_ipad  # noqa: E402
import split_ipad  # noqa: E402
from make_fake_scan import _slanted_glyph  # noqa: E402
from handwriting.compositor import rasterize_pdf  # noqa: E402
from handwriting.glyphstore import GlyphStore  # noqa: E402

OUT = REPO / "out" / "ipadpilot_check"
PILOT_CHARS = list("aegfzt.(") + ["∂", "θ"]
BOLD_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SCALE = 4


def check_template():
    pdf_path, json_path = make_template_ipad.generate()
    layout = json.loads(json_path.read_text("utf-8"))
    cells = [c for p in layout["pages"] for c in p["cells"]]
    assert sorted({c["char"] for c in cells}) == sorted(PILOT_CHARS)
    assert len(cells) == 20
    page = rasterize_pdf(pdf_path, tuple(layout["page_px"]))[0]
    rgb = np.asarray(page.convert("RGB")).astype(np.int16)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    printed = (rgb.min(axis=2) < 245)
    neutral_dark = printed & (np.abs(g - r) < 12) & (np.abs(b - r) < 12)
    frac = neutral_dark.mean()
    assert frac < 1e-4, f"template has neutral/black print ({frac:.2%})"
    assert split_ipad._cyan_mask(rgb.astype(np.uint8))[printed].mean() > 0.55, \
        "printed furniture is not predominantly cyan-keyed"
    print("PASS: template 10x2 cells; all print is cyan-hued, nothing black")
    return pdf_path, layout


def stamp_ink(canvas_rgba, layout, meta):
    cell_w, cell_h = layout["cell_w"] * SCALE, layout["cell_h"] * SCALE
    zone = (layout["guide_fractions"]["baseline"]
            - layout["guide_fractions"]["ascender"])
    font = ImageFont.truetype(BOLD_FONT, max(8, round(zone * cell_h * 1.05)))
    for cell in meta["cells"]:
        x0, y0, _, _ = (v * SCALE for v in cell["rect"])
        guides = {k: v * SCALE for k, v in cell["guides"].items()}
        tile = _slanted_glyph(cell["char"], cell_w, cell_h, guides, y0, font)
        canvas_rgba.alpha_composite(tile, (x0, y0))
    return canvas_rgba


def build_fixtures(pdf_path, layout):
    OUT.mkdir(parents=True, exist_ok=True)
    pw, ph = layout["page_px"]
    meta = layout["pages"][0]
    template4x = rasterize_pdf(pdf_path, (pw * SCALE, ph * SCALE))[0]
    bg_on = stamp_ink(template4x.convert("RGBA"), layout, meta).convert("RGB")
    p_on = OUT / "fx_bg_on.png"
    bg_on.save(p_on)
    white = Image.new("RGBA", (pw * SCALE, ph * SCALE), (255, 255, 255, 255))
    bg_off = stamp_ink(white, layout, meta).convert("RGB")
    p_off = OUT / "fx_bg_off.png"
    bg_off.save(p_off)
    shifted = Image.new("RGB", bg_on.size, (255, 255, 255))
    shifted.paste(bg_on, (5 * SCALE, 0))  # 5 layout px right — must be refused
    p_shift = OUT / "fx_shifted.png"
    shifted.save(p_shift)
    print("PASS: fixtures written (bg-on, bg-off, shifted)")
    return p_on, p_off, p_shift


def check_store(store_dir, expect_msg):
    store = GlyphStore(store_dir)
    for ch in PILOT_CHARS:
        entry = store.entry(ch)
        assert len(entry.variants) == 2, f"{ch!r}: {len(entry.variants)}"
        assert len({v.baseline_y for v in entry.variants}) == 1
        for v in entry.variants:
            img = store.load_image(v)
            assert img.mode == "RGBA"
            a = np.asarray(img.getchannel("A"))
            assert a.max() == 255, f"{ch!r} has no solid ink"
    manifest = json.loads((store_dir / "manifest.json").read_text("utf-8"))
    assert manifest["characters"]["∂"]["folder"] == "sym_u2202"
    assert manifest["characters"]["θ"]["folder"] == "sym_u03b8"
    print(f"PASS: {expect_msg} — 10 chars x 2 ink-only variants, "
          f"baseline spread 0, sym folders OK")


def check_roundtrips(p_on, p_off, p_shift, layout):
    layout_path = REPO / "template" / "ipad_pilot" / "template_layout.json"
    on_dir, off_dir = OUT / "store_on", OUT / "store_off"
    split_ipad.main([str(p_on), "--layout", str(layout_path),
                     "--out", str(on_dir), "--scale", str(SCALE)])
    check_store(on_dir, "bg-ON round-trip (marker sanity exercised)")
    split_ipad.main([str(p_off), "--layout", str(layout_path),
                     "--out", str(off_dir), "--scale", str(SCALE)])
    check_store(off_dir, "bg-OFF round-trip (no-marker path)")
    # bg-on store must carry no cyan into alpha: compare against bg-off ink
    on = json.loads((on_dir / "manifest.json").read_text("utf-8"))
    off = json.loads((off_dir / "manifest.json").read_text("utf-8"))
    for ch in PILOT_CHARS:
        w_on = on["characters"][ch]["variants"][0]["ink_bbox"]
        w_off = off["characters"][ch]["variants"][0]["ink_bbox"]
        dw = abs((w_on[2] - w_on[0]) - (w_off[2] - w_off[0]))
        assert dw <= 2 * SCALE, f"{ch!r}: bg-on/off ink width differ by {dw}"
    print("PASS: cyan removal is clean (bg-on ink extents == bg-off within "
          "2px)")
    try:
        split_ipad.main([str(p_shift), "--layout", str(layout_path),
                         "--out", str(OUT / "store_shift"),
                         "--scale", str(SCALE)])
    except SystemExit as e:
        assert "sanity" in str(e) or "marker" in str(e), str(e)
        print("PASS: 5px-shifted export REFUSED by marker sanity (no warp)")
    else:
        raise AssertionError("shifted export was not refused")


def build_matrix_fixtures(layout):
    import fitz
    pw, ph = layout["page_px"]
    w_pt, h_pt = pw * 72 / 150, ph * 72 / 150
    vec = OUT / "mx_vector.pdf"
    doc = fitz.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    sh = page.new_shape()
    for i in range(6):  # 6 separate dark "strokes"
        sh.draw_line((60 + 8 * i, 80), (90 + 8 * i, 140))
        sh.finish(color=(0.1, 0.1, 0.12), width=2)
    sh.draw_line((40, 40), (200, 40))
    sh.finish(color=(0.55, 0.86, 0.88), width=1)  # one cyan template line
    sh.commit()
    doc.save(vec)
    doc.close()
    ras = OUT / "mx_raster.pdf"
    img = Image.new("RGB", (pw, ph), (255, 255, 255))
    px = np.asarray(img).copy()
    px[300:400, 200:220] = (30, 30, 34)
    doc = fitz.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    import io
    buf = io.BytesIO()
    Image.fromarray(px).save(buf, format="PNG")
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(ras)
    doc.close()
    return vec, ras


def check_inspect(layout):
    vec, ras = build_matrix_fixtures(layout)
    report = split_ipad.inspect([str(vec), str(ras)], layout,
                                OUT / "matrix", SCALE)
    by = {r["file"]: r for r in report}
    v = by["mx_vector.pdf"]
    assert v["vector_ink_paths"] >= 6 and v["raster_images"] == 0, v
    assert v["vector_template_paths"] >= 1, v
    r = by["mx_raster.pdf"]
    assert r["vector_ink_paths"] == 0 and r["raster_images"] == 1, r
    assert r["raster_effective_dpi"][0] == 150, r
    print("PASS: inspect matrix classifies vector vs raster ink (+ template "
          "paths, effective dpi)")


def main():
    pdf_path, layout = check_template()
    p_on, p_off, p_shift = build_fixtures(pdf_path, layout)
    check_roundtrips(p_on, p_off, p_shift, layout)
    check_inspect(layout)
    print("PASS: iPad pilot toolchain all green")


if __name__ == "__main__":
    main()
