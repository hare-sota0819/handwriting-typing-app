"""Demo glyph store: the FULL collection charset rendered from the bundled font.

The pipeline is handwriting-agnostic — it draws whatever glyph store it is
pointed at. This generator builds a complete store (English, Greek, maths
symbols, tall delimiters, straight strokes) from DejaVu Sans, so the whole
product — text, equations, GUI, checks — runs out of the box before anyone
has written a single letter. Replace it with your own handwriting by filling
the collection template and importing it (see README, "Your own
handwriting"); the store layout and manifest are identical.

Run: python -m handwriting.demostore [--out glyphs/demo]
"""

import argparse
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .glyphstore import MANIFEST_NAME, MANIFEST_VERSION
from .synthglyphs import DIGITS, LOWER, PUNCT_NAMES, UPPER

ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = ROOT / "handwriting" / "data" / "DejaVuSans.ttf"
CHARSETS = (ROOT / "template" / "charset_default.txt",
            ROOT / "template" / "charset_math.txt")
DEFAULT_OUT = ROOT / "glyphs" / "demo"

FONT_SIZE = 96          # font size the glyphs are drawn at (px)
# The store's native size is the CELL height a hand writes into, and letters
# fill only its middle (a written x-height is ~0.21 of the cell). Declaring
# the cell rather than the font size keeps the demo letters the same size on
# the page as real handwriting stores (style.base_size_px is per cell).
NATIVE_SIZE_PX = 250
N_VARIANTS = 3
SEED = 4242
PAD = 40
CROP_MARGIN = 2
BIG_DELIMITERS = "()[]{}|√"
BIG_SCALE = 2.6         # tall delimiter = the normal one drawn this much taller
# (key, ink width px, samples): straight pen strokes for fraction bars etc.
STROKE_SPECS = (("rule:short", 120, 3), ("rule:med", 300, 2), ("rule:long", 460, 2))
STROKE_PEN = 8

_DELIM_NAMES = {"(": "lparen", ")": "rparen", "[": "lbracket", "]": "rbracket",
                "{": "lbrace", "}": "rbrace", "|": "bar", "√": "sqrt"}


def load_charset(path: Path) -> list[str]:
    """One entry per line; blank lines and `#` comments skipped (a lone `#`
    is the hash character itself)."""
    entries = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or (stripped.startswith("#") and stripped != "#"):
            continue
        entries.append(raw.rstrip())
    return entries


def folder_for_key(key: str) -> str:
    if key.startswith("big:"):
        return f"big_{_DELIM_NAMES[key[4:]]}"
    if key.startswith("rule:"):
        return f"rule_{key[5:]}"
    if key in PUNCT_NAMES:
        return "punct_" + PUNCT_NAMES[key]
    if key in LOWER:
        return "lower_" + key
    if key in UPPER:
        return "upper_" + key.lower()
    if key in DIGITS:
        return "digit_" + key
    if len(key) == 1:
        return f"sym_u{ord(key):04x}"
    raise ValueError(f"no folder rule for key {key!r}")


def _render_char(char: str, size: int, rng: random.Random):
    """One perturbed variant of `char`: (RGBA ink image, metrics) or None
    when the font has no glyph for it."""
    scale = rng.uniform(0.96, 1.05)
    font = ImageFont.truetype(str(FONT_PATH), round(size * scale))
    if font.getmask(char).getbbox() is None:
        return None
    ascent, descent = font.getmetrics()
    advance = font.getlength(char)
    pen_x = PAD
    baseline_y = PAD + ascent
    canvas = Image.new("RGBA", (int(math.ceil(advance)) + 2 * PAD,
                                ascent + descent + 2 * PAD), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((pen_x, PAD), char, font=font, fill=(0, 0, 0, 255))
    angle = rng.uniform(-2.0, 2.0)
    canvas = canvas.rotate(angle, resample=Image.Resampling.BICUBIC,
                           center=(pen_x, baseline_y))
    ink = canvas.getbbox()
    if ink is None:
        return None
    x0, y0 = max(ink[0] - CROP_MARGIN, 0), max(ink[1] - CROP_MARGIN, 0)
    x1, y1 = min(ink[2] + CROP_MARGIN, canvas.width), min(ink[3] + CROP_MARGIN, canvas.height)
    meta = {
        "baseline_y": baseline_y - y0,
        "advance_width": advance,
        "left_bearing": x0 - pen_x,
        "right_bearing": (pen_x + advance) - x1,
        "ink_bbox": [ink[0] - x0, ink[1] - y0, ink[2] - x0, ink[3] - y0],
    }
    return canvas.crop((x0, y0, x1, y1)), meta


def _render_stroke(width: int, rng: random.Random):
    """A near-horizontal pen stroke of `width` px with a hint of hand wobble."""
    h = STROKE_PEN * 4
    canvas = Image.new("RGBA", (width + 2 * CROP_MARGIN, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    y_mid = h / 2
    pts = []
    for i in range(0, width + 1, 8):
        wob = rng.uniform(-1.0, 1.0) + 2.0 * math.sin(i / max(1, width) * math.pi * rng.uniform(0.5, 1.5))
        pts.append((CROP_MARGIN + i, y_mid + wob))
    draw.line(pts, fill=(0, 0, 0, 255), width=STROKE_PEN, joint="curve")
    ink = canvas.getbbox()
    meta = {
        "baseline_y": h - 1,
        "advance_width": float(width),
        "left_bearing": 0.0,
        "right_bearing": 0.0,
        "ink_bbox": list(ink),
    }
    return canvas, meta


def generate(out: Path = DEFAULT_OUT, n_variants: int = N_VARIANTS,
             seed: int = SEED, charsets=CHARSETS) -> Path:
    rng = random.Random(seed)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    nominal = ImageFont.truetype(str(FONT_PATH), FONT_SIZE)
    characters: dict = {}
    skipped = []

    def add(key: str, renders: list) -> None:
        folder = folder_for_key(key)
        (out / folder).mkdir(exist_ok=True)
        variants = []
        for i, (img, meta) in enumerate(renders):
            rel = f"{folder}/v{i}.png"
            img.save(out / rel)
            variants.append({"file": rel, **meta})
        characters[key] = {
            "folder": folder,
            "advance_width": variants[0]["advance_width"] if variants else 0.0,
            "variants": variants,
        }

    entries: list[str] = []
    for path in charsets:
        entries += load_charset(path)
    for key in entries:
        if key.startswith("math:") or key in characters:
            continue  # the plain letter serves; nothing to write differently
        renders = [_render_char(key, FONT_SIZE, rng) for _ in range(n_variants)]
        renders = [r for r in renders if r is not None]
        if not renders:
            skipped.append(key)
            continue
        add(key, renders)
    for ch in BIG_DELIMITERS:
        renders = [_render_char(ch, round(FONT_SIZE * BIG_SCALE), rng)
                   for _ in range(n_variants)]
        renders = [r for r in renders if r is not None]
        if renders:
            add(f"big:{ch}", renders)
    for key, width, n in STROKE_SPECS:
        add(key, [_render_stroke(width, rng) for _ in range(n)])
    characters[" "] = {"folder": None, "advance_width": nominal.getlength(" "),
                       "variants": []}
    manifest = {"version": MANIFEST_VERSION, "native_size_px": NATIVE_SIZE_PX,
                "characters": characters}
    (out / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"demo store: {len(characters) - 1} entries x up to {n_variants} "
          f"variants -> {out}" + (f" (no font glyph for: {' '.join(skipped)})"
                                  if skipped else ""))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--variants", type=int, default=N_VARIANTS)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args(argv)
    generate(args.out, args.variants, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
