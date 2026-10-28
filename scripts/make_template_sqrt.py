"""The radical sign, rewritten — a short sheet of its own.

Why this sheet exists: the stored √ was written WITH its top bar, and the
renderer assembles radicals from a bare hook plus a separately drawn overbar
(the bar must stretch to the operand's width, the hook must not). Stretching
the stored glyph therefore smears its baked-in bar into a blob at the join.
Two entries fix that at the source:

  * `√`     — the hook alone, no top bar, at normal symbol size.
  * `big:√` — the same hook written to fill the cell height, so tall radicals
              (fractions inside) start from a tall original instead of a 2-3x
              stretch of the small one (same reason big:( exists).

Each cell carries a faint CYAN guide hook in the background showing the exact
shape and size to write — the user asked for this explicitly ("어느정도
사이즈로 그려야 하는지를 같이 뽑아줘"). It is printed in the same cyan as the
guide lines, so Tool 2b's colour key strips it from the captured ink exactly
as it strips them; the user's dark pen stroke on top survives untouched.

Everything else — cell size, guides, markers, the cyan colour key — is the
collection template's, so the export recipe and split_ipad work unchanged.

Run:  .venv/bin/python scripts/make_template_sqrt.py
Then: .venv/bin/python scripts/split_ipad.py <export.pdf> \
        --layout template/sqrt_rewrite/template_layout.json --out glyphs/ipad_sqrt
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import make_template_collection as mtc  # noqa: E402
from handwriting import metrics  # noqa: E402

OUT_DIR = REPO / "template" / "sqrt_rewrite"

ENTRIES = [
    ("√", "√   hook ONLY — stop at the top, NO bar"),
    ("big:√", "√   TALL — fill the cell, hook only, NO bar"),
]

GUIDE_STROKE_W = 5   # ~ Apple-Pencil weight at the template's 150 dpi


def _draw_hook_guide(draw, key, rect, guides):
    """Faint cyan hook (√ minus its top bar) at the size the renderer expects.

    `√` is seated by the reference-font metrics the renderer itself uses, so
    the guide and the substitution can't drift apart. `big:√` fills the cell
    height, matching the TALL delimiters' brief. The up-stroke ENDS at the
    top with no horizontal continuation — that absence is the whole point of
    the resheet, so the guide must model it.
    """
    if key not in ("√", "big:√"):
        return mtc._orig_draw_size_guide(draw, key, rect, guides)
    x0, y0, x1, y1 = rect
    xh = (guides["baseline"] - guides["ascender"]) / mtc.TALLEST_XH
    if key == "√":
        top = guides["baseline"] - metrics.height_in_x_heights("√") * xh
        bot = guides["baseline"] + metrics.depth_in_x_heights("√") * xh
        slant = 0.52          # print-like slant for the symbol-size hook
    else:
        top, bot = y0 + 6, y1 - 6
        slant = 0.36          # tall radicals run nearly vertical
    h = bot - top
    w = min(x1 - x0 - 16, slant * h)
    lx = (x0 + x1) / 2 - w / 2
    pts = [(lx, top + 0.60 * h),          # short lead-in tick...
           (lx + 0.30 * w, bot),          # ...down to the bottom point,
           (lx + w, top)]                 # long up-stroke — and STOP.
    draw.line(pts, fill=mtc.GUIDE_GLYPH_COLOR, width=GUIDE_STROKE_W,
              joint="curve")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    variants = 10
    for a in argv:
        if a.startswith("--variants="):
            variants = int(a.split("=", 1)[1])
    mtc._orig_draw_size_guide = mtc._draw_size_guide
    mtc._draw_size_guide = _draw_hook_guide
    specs = mtc.build_specs_explicit(ENTRIES, variants)
    mtc.generate(out_dir=OUT_DIR, n_variants=variants, specs=specs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
