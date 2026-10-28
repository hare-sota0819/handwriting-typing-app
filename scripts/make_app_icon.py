"""Build the app icon from a glyph store's `a`.

Takes lower_a v0 from a store (default: handwriting.stores.default_store —
your own handwriting if imported, else the demo store), places it on a
rounded white card with a soft gray border, and writes packaging/app_icon.ico
(multi-size, used as the exe icon) plus packaging/app_icon.png (window icon).

    python scripts/make_app_icon.py [--store glyphs/mine] [--local]

--local writes app_icon.local.{ico,png} instead: a gitignored private icon
that the build and the window prefer when present (so a public checkout
ships the demo-store icon and your own build keeps your handwriting).
"""

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from handwriting.stores import default_store  # noqa: E402

OUT_ICO = ROOT / "packaging" / "app_icon.ico"
OUT_PNG = ROOT / "packaging" / "app_icon.png"

SIZE = 256          # master raster; .ico sizes are downscaled from it
CARD_INSET = 10
CORNER_RADIUS = 48
GLYPH_FRAC = 0.58   # glyph ink height/width as a fraction of the card


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", type=Path, default=None)
    ap.add_argument("--local", action="store_true")
    args = ap.parse_args(argv)
    store = args.store or default_store()
    glyph_path = store / "lower_a" / "v0.png"
    out_ico = OUT_ICO.with_name("app_icon.local.ico") if args.local else OUT_ICO
    out_png = OUT_PNG.with_name("app_icon.local.png") if args.local else OUT_PNG
    card = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle(
        [CARD_INSET, CARD_INSET, SIZE - CARD_INSET, SIZE - CARD_INSET],
        radius=CORNER_RADIUS,
        fill=(255, 255, 255, 255),
        outline=(178, 178, 178, 255),
        width=6,
    )

    glyph = Image.open(glyph_path).convert("RGBA")
    box = glyph.getbbox()
    glyph = glyph.crop(box)
    target = int(SIZE * GLYPH_FRAC)
    scale = target / max(glyph.size)
    glyph = glyph.resize(
        (max(1, round(glyph.width * scale)), max(1, round(glyph.height * scale))),
        Image.Resampling.LANCZOS,
    )
    card.alpha_composite(
        glyph, ((SIZE - glyph.width) // 2, (SIZE - glyph.height) // 2)
    )

    out_png.parent.mkdir(parents=True, exist_ok=True)
    card.save(out_png)
    card.save(
        out_ico,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
               (128, 128), (256, 256)],
    )
    print(f"wrote {out_ico} and {out_png}")


if __name__ == "__main__":
    main()
