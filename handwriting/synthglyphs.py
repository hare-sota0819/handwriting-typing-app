"""Synthetic placeholder glyph generator.

The user has no scanned handwriting glyphs yet, so Phase 1 development runs on
placeholder glyphs rendered from a system font, with a small per-variant
perturbation (size + rotation) so variant selection is visible downstream.
Real scanned glyphs later drop into the same store layout + manifest schema.

Run: python -m handwriting.synthglyphs
"""

import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .glyphstore import MANIFEST_NAME, MANIFEST_VERSION

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEFAULT_STORE = Path(__file__).resolve().parents[1] / "glyphs" / "synthetic"
FONT_SIZE = 96
N_VARIANTS = 3
SEED = 12345
PAD = 32  # canvas padding so small rotations never clip ink
CROP_MARGIN = 2

LOWER = "abcdefghijklmnopqrstuvwxyz"
UPPER = LOWER.upper()
DIGITS = "0123456789"
PUNCT_NAMES = {
    ".": "dot", ",": "comma", ";": "semicolon", ":": "colon",
    "!": "exclaim", "?": "question", "'": "apostrophe", '"': "quote",
    "(": "lparen", ")": "rparen", "[": "lbracket", "]": "rbracket",
    "-": "hyphen", "_": "underscore", "/": "slash", "%": "percent",
    "+": "plus", "=": "equals", "<": "less", ">": "greater",
    "&": "ampersand", "*": "asterisk", "#": "hash", "@": "at", "$": "dollar",
}
CHARSET = LOWER + UPPER + DIGITS + "".join(PUNCT_NAMES)


def folder_name(char: str) -> str:
    """Safe ASCII folder name for a character (never literal punctuation)."""
    if char in PUNCT_NAMES:
        return "punct_" + PUNCT_NAMES[char]
    if char in LOWER:
        return "lower_" + char
    if char in UPPER:
        return "upper_" + char.lower()
    if char in DIGITS:
        return "digit_" + char
    raise ValueError(f"no folder mapping for character {char!r}")


def _render_variant(char: str, font_path: str, rng: random.Random):
    """Render one perturbed variant. Returns (RGBA image, metadata dict)."""
    scale = rng.uniform(0.96, 1.05)
    font = ImageFont.truetype(font_path, round(FONT_SIZE * scale))
    ascent, descent = font.getmetrics()
    advance = font.getlength(char)

    pen_x = PAD
    baseline_y = PAD + ascent
    canvas = Image.new(
        "RGBA",
        (int(math.ceil(advance)) + 2 * PAD, ascent + descent + 2 * PAD),
        (0, 0, 0, 0),
    )
    ImageDraw.Draw(canvas).text((pen_x, PAD), char, font=font, fill=(0, 0, 0, 255))

    # Rotate about the pen point on the baseline so baseline_y/pen_x stay valid.
    angle = rng.uniform(-2.5, 2.5)
    canvas = canvas.rotate(
        angle, resample=Image.Resampling.BICUBIC, center=(pen_x, baseline_y)
    )

    ink = canvas.getbbox()
    if ink is None:
        raise ValueError(f"character {char!r} rendered no ink")
    x0 = max(ink[0] - CROP_MARGIN, 0)
    y0 = max(ink[1] - CROP_MARGIN, 0)
    x1 = min(ink[2] + CROP_MARGIN, canvas.width)
    y1 = min(ink[3] + CROP_MARGIN, canvas.height)
    cropped = canvas.crop((x0, y0, x1, y1))

    meta = {
        "baseline_y": baseline_y - y0,
        "advance_width": advance,
        "left_bearing": x0 - pen_x,
        "right_bearing": (pen_x + advance) - x1,
        "ink_bbox": [ink[0] - x0, ink[1] - y0, ink[2] - x0, ink[3] - y0],
    }
    return cropped, meta


def generate(
    store_root: str | Path = DEFAULT_STORE,
    font_path: str = FONT_PATH,
    n_variants: int = N_VARIANTS,
    seed: int = SEED,
) -> Path:
    rng = random.Random(seed)
    store_root = Path(store_root)
    store_root.mkdir(parents=True, exist_ok=True)

    nominal_font = ImageFont.truetype(font_path, FONT_SIZE)
    characters = {}
    for char in CHARSET:
        folder = folder_name(char)
        (store_root / folder).mkdir(exist_ok=True)
        variants = []
        for i in range(n_variants):
            image, meta = _render_variant(char, font_path, rng)
            rel = f"{folder}/v{i}.png"
            image.save(store_root / rel)
            variants.append({"file": rel, **meta})
        characters[char] = {
            "folder": folder,
            "advance_width": nominal_font.getlength(char),
            "variants": variants,
        }

    # Space carries advance only — no ink, no images.
    characters[" "] = {
        "folder": None,
        "advance_width": nominal_font.getlength(" "),
        "variants": [],
    }

    manifest = {
        "version": MANIFEST_VERSION,
        "native_size_px": FONT_SIZE,
        "characters": characters,
    }
    (store_root / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"generated {len(CHARSET)} inked characters x {n_variants} variants "
        f"(+ space) into {store_root}"
    )
    return store_root


if __name__ == "__main__":
    generate()
