"""Synthetic filled-scan generator — test fixture for Tool 2 (split_scan.py).

Renders the real Tool 1 template (template/template.pdf, with its exact printed
furniture: cell borders, the 4 guide lines, labels, corner markers) and fills
every writing cell with a FONT glyph — deliberately sheared to the RIGHT to
mimic slanted handwriting. This is NOT real handwriting; it exists only so Tool 2
can be validated end-to-end before any real scan exists.

Two knobs matter for the checkpoints:
  * ink is dark GRAY (not pure black) and the baseline guide is printed darker
    than the other guides, so Tool 2's hybrid furniture removal has real work to
    do (density alone can't separate the baseline from ink).
  * --rotate DEG rotates the whole rendered sheet (about its center, white fill)
    to simulate a crooked sheet on the scanner bed — used at STOP B to prove the
    marker-based affine registration recovers alignment WITHOUT touching the
    per-glyph slant.

Run: .venv/bin/python scripts/make_fake_scan.py [--rotate DEG] [--out-dir DIR]
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handwriting.compositor import rasterize_pdf

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "template"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
INK = (45, 45, 45)        # dark gray "pen", not pure black
SLANT = 0.28              # rightward shear (~15deg); the signal Tool 2 must keep


def _slanted_glyph(char: str, cell_w_px: int, cell_h_px: int, guides: dict,
                   cell_top: int, font: ImageFont.FreeTypeFont):
    """Render one glyph on a transparent CELL-sized tile (so it never spills into
    a neighbouring cell), baseline on the guide, then shear it right about the
    baseline row. Returns an RGBA tile to be pasted at the cell's top-left."""
    tile = Image.new("RGBA", (cell_w_px, cell_h_px), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    baseline_row = guides["baseline"] - cell_top
    # left-baseline anchor, centred in the cell width
    adv = font.getlength(char)
    d.text(((cell_w_px - adv) / 2, baseline_row), char, font=font,
           fill=INK + (255,), anchor="ls")
    # shear right about the baseline row: output(x,y) samples input(x + s*y - s*base, y)
    s = SLANT
    sheared = tile.transform(
        tile.size, Image.AFFINE, (1, s, -s * baseline_row, 0, 1, 0),
        resample=Image.BICUBIC,
    )
    return sheared


def generate(out_dir: Path, rotate: float = 0.0):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    layout = json.loads((TEMPLATE_DIR / "template_layout.json").read_text("utf-8"))
    page_px = tuple(layout["page_px"])
    cell_w, cell_h = layout["cell_w"], layout["cell_h"]
    # font sized so its ascent ~ the ascender->baseline zone height, kept modest so
    # even wide glyphs (m, w) stay inside the cell width
    zone = layout["guide_fractions"]["baseline"] - layout["guide_fractions"]["ascender"]
    font = ImageFont.truetype(FONT_PATH, max(8, round(zone * cell_h * 1.05)))

    pages = rasterize_pdf(TEMPLATE_DIR / "template.pdf", page_px)
    out_paths = []
    for page, meta in zip(pages, layout["pages"]):
        canvas = page.convert("RGBA")
        for cell in meta["cells"]:
            x0, y0, x1, y1 = cell["rect"]
            tile = _slanted_glyph(cell["char"], cell_w, cell_h, cell["guides"], y0, font)
            canvas.alpha_composite(tile, (x0, y0))
        img = canvas.convert("RGB")
        if rotate:
            img = img.rotate(rotate, resample=Image.BICUBIC, expand=True,
                             fillcolor=(255, 255, 255))
        p = out_dir / f"fake_scan_p{meta['index']}.png"
        img.save(p)
        out_paths.append(p)
    tag = f" rotated {rotate}deg" if rotate else ""
    print(f"wrote {len(out_paths)} fake-scan page(s){tag} to {out_dir}")
    return out_paths


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate a synthetic filled scan for Tool 2.")
    ap.add_argument("--rotate", type=float, default=0.0, help="rotate whole sheet (deg)")
    ap.add_argument("--out-dir", type=Path,
                    default=Path(__file__).resolve().parents[1] / "out" / "tool2" / "fake_scan")
    args = ap.parse_args(argv)
    generate(args.out_dir, rotate=args.rotate)


if __name__ == "__main__":
    main()
