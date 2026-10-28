"""Renderer: composite chosen glyph images into ink-only page images.

Consumes finalized PlacedGlyph pages (variant/scale/rotation/y already set by
the variation engine) and the glyph store, and paints each glyph onto a
transparent RGBA canvas — ink only, with alpha, no paper. Paper compositing,
output files, and the CLI are Checkpoint 5.

This module and the glyph store's loader are the ONLY places that touch glyph
images (Phase 2 extends exactly here with math-symbol glyphs).

Renderer contract (from layout.py):
- image left edge at x + left_bearing*scale, baseline_y*scale row on y
- rotation_deg is applied about the pen point (x, y); positive leans right
"""

import math
import random

import numpy as np
from PIL import Image, ImageFilter

from . import metrics
from .glyphstore import GlyphStore
from .layout import PageLayout
from .style import HandwritingStyle

# edge_soften_px is calibrated on the default 150-dpi A4 page; scale the blur
# radius with the actual page width so higher-dpi renders soften identically.
_REF_PAGE_WIDTH_PX = 1240

# A glyph whose captured ink reaches deeper below the printed guide than this
# fraction of the store x-height is a true descender: seat it by the captured
# baseline (its natural tail depth), not by reference-font depth.
_TRUST_GUIDE_MIN_XH = 0.2

# The ink value jitters are ASYMMETRIC: the darkening side is scaled down so
# the composited dark tail (gray 10-20 bin) stays on the measured scan target
# (2.2% of ink px) — symmetric jitter overfilled it 3x (6.5%). Review-tuned
# sweep: 0.8 lands the bin at 2.1% with median 45 (clean also 45, target 42).
_JITTER_DARK_FRAC = 0.8


def _paste_rotated(
    canvas: Image.Image,
    glyph_img: Image.Image,
    scale: float,
    anchor: tuple[float, float],
    angle_deg: float,
    dest: tuple[float, float],
    embolden: bool = False,
) -> None:
    """Scale, rotate about `anchor`, and paste so `anchor` lands on `dest`.

    anchor is the pen point expressed in the unscaled glyph image's pixels.
    embolden dilates the scaled ink by 1px — superscripts shrink below the
    body pen width, this brings their strokes back toward it.
    """
    w = max(1, round(glyph_img.width * scale))
    h = max(1, round(glyph_img.height * scale))
    scaled = glyph_img.resize((w, h), Image.Resampling.BICUBIC)
    if embolden:
        scaled.putalpha(scaled.getchannel("A").filter(ImageFilter.MaxFilter(3)))
    ax, ay = anchor[0] * scale, anchor[1] * scale

    if abs(angle_deg) < 1e-3:
        x = round(dest[0] - ax)
        y = round(dest[1] - ay)
        canvas.paste(scaled, (x, y), scaled)
        return

    # rotate() expands symmetrically about the image center, so the new center
    # is the center of the returned image; track the anchor through that.
    ocx, ocy = scaled.width / 2.0, scaled.height / 2.0
    rotated = scaled.rotate(angle_deg, resample=Image.Resampling.BICUBIC, expand=True)
    ncx, ncy = rotated.width / 2.0, rotated.height / 2.0
    # Negative angle: rotate glyph clockwise so positive slant_deg leans right.
    a = math.radians(-angle_deg)
    dx, dy = ax - ocx, ay - ocy
    rx = ncx + dx * math.cos(a) - dy * math.sin(a)
    ry = ncy + dx * math.sin(a) + dy * math.cos(a)
    canvas.paste(rotated, (round(dest[0] - rx), round(dest[1] - ry)), rotated)


def _colorize(
    glyph_img: Image.Image, ink_rgb, ink_shade: float, alpha_cutoff: int = 0
) -> Image.Image:
    """Recolor a glyph image to the ink color, using its alpha as ink coverage.

    ink_shade in (0, 1] fades the glyph (via alpha) for faint per-glyph
    darkness variation without shifting the hue. alpha_cutoff > 0 zeroes alpha
    below it FIRST (residue threshold, before any ink effect) so faint printed-
    guide residue kept in the store never reaches the page.
    """
    alpha = glyph_img.getchannel("A")
    shade = max(0.0, min(1.0, ink_shade))
    if alpha_cutoff > 0 or shade < 1.0:
        alpha = alpha.point(
            lambda a: 0 if a < alpha_cutoff else round(a * shade)
        )
    ink = Image.new("RGBA", glyph_img.size, (*ink_rgb, 0))
    ink.putalpha(alpha)
    return ink


def _shift_ink(ink_rgb, offset: float):
    """Shift the ink color's value by offset gray levels (hue preserved)."""
    return tuple(max(0, min(255, round(c + offset))) for c in ink_rgb)


def _apply_pressure(img: Image.Image, rng: random.Random, amp: float) -> None:
    """Add a low-frequency +/-amp gray-value field to one glyph's ink color.

    A seeded 3x3 grid upsampled bilinearly — smooth intra-glyph darkness
    variation approximating pen pressure, far below stroke frequency.
    Two-sided (darker AND lighter patches) so the page's matched ink
    histogram keeps its median; only alpha edits would ratchet it lighter.
    """
    lo, hi = -amp * _JITTER_DARK_FRAC, amp
    grid = np.array([[rng.uniform(lo, hi) for _ in range(3)] for _ in range(3)])
    field = Image.fromarray(
        ((grid - lo) / (hi - lo) * 255.0).astype(np.uint8), mode="L"
    ).resize(img.size, Image.Resampling.BILINEAR)
    offset = np.asarray(field, dtype=np.float32) / 255.0 * (hi - lo) + lo
    arr = np.array(img)
    rgb = np.clip(arr[..., :3].astype(np.float32) + offset[..., None], 0, 255)
    arr[..., :3] = rgb.astype(np.uint8)
    img.paste(Image.fromarray(arr, mode="RGBA"))


def _soften_edges(canvas: Image.Image, radius: float) -> Image.Image:
    """Gaussian-blur the ink layer in premultiplied space (no dark fringes).

    Premultiplying lets color and coverage blur together, so alpha bleeding
    into unpainted (black-RGB) pixels can't darken edges even though glyph
    ink colors vary per glyph/pixel.
    """
    arr = np.asarray(canvas, dtype=np.float32)
    a = arr[..., 3:4] / 255.0
    prem = np.concatenate([arr[..., :3] * a, arr[..., 3:4]], axis=2)
    blurred = np.stack(
        [
            np.asarray(
                Image.fromarray(
                    prem[..., i].round().astype(np.uint8), mode="L"
                ).filter(ImageFilter.GaussianBlur(radius)),
                dtype=np.float32,
            )
            for i in range(4)
        ],
        axis=2,
    )
    alpha = blurred[..., 3:4]
    with np.errstate(divide="ignore", invalid="ignore"):
        rgb = np.where(alpha > 0.5, blurred[..., :3] / (alpha / 255.0), 0.0)
    out = np.concatenate([np.clip(rgb, 0, 255), alpha], axis=2)
    return Image.fromarray(out.astype(np.uint8), mode="RGBA")


def _store_x_height(store: GlyphStore) -> float:
    """The store's own x-height in native px, measured from ink alone."""
    hs = []
    for ch in "xaez":
        if ch in store:
            hs += [v.ink_bbox[3] - v.ink_bbox[1] for v in store.entry(ch).variants]
    hs.sort()
    return float(hs[len(hs) // 2]) if hs else float(store.native_size_px) * 0.4


def render_page(
    page: PageLayout, store: GlyphStore, style: HandwritingStyle, seed: int = 0
) -> Image.Image:
    """Render one page of placed glyphs to a transparent ink-only RGBA image."""
    spec = page.spec
    canvas = Image.new("RGBA", (spec.width_px, spec.height_px), (0, 0, 0, 0))
    store_x_height = _store_x_height(store)
    fx = style.effects
    cutoff = style.residue_alpha_cutoff if fx else 0
    base_ink = style.ink_rgb
    if fx and style.ink_tone_value > 0:
        base_ink = _shift_ink(base_ink, style.ink_tone_value - sum(base_ink) / 3.0)
    # Stage-2 randomness lives on its own stream so the clean path (and the
    # stage-1 variation stream) stays byte-identical.
    rng = random.Random(f"fx2-{seed}")
    for g in page.glyphs:
        entry = store.entry(g.char)
        if not entry.variants:
            continue
        variant = entry.variants[g.variant]
        ink = base_ink
        if fx and style.ink_density_jitter > 0:
            # Two-sided per-glyph darkness (darker AND lighter glyphs) with a
            # reduced darkening side (_JITTER_DARK_FRAC), keeping both the
            # page median and the dark-tail bin on the matched scan target.
            ink = _shift_ink(
                ink,
                rng.uniform(
                    -style.ink_density_jitter * _JITTER_DARK_FRAC,
                    style.ink_density_jitter,
                ),
            )
        # The per-glyph fade is part of the scanned look only. On a clean page
        # it left random letters of a word visibly grey (the `i` and `u` of
        # "minutes", 2026-09-16 user report) next to equations, which never
        # take it: a tablet pen lays down one colour.
        glyph_img = _colorize(store.load_image(variant), ink,
                              g.ink_shade if fx else 1.0, cutoff)
        if fx and style.ink_pressure > 0:
            _apply_pressure(glyph_img, rng, style.ink_pressure)
        # Seat the glyph by its OWN ink, at the depth a typeface would give this
        # character, instead of by the printed guide recorded at capture time.
        # The guide is where the writer was aiming: digits and colons in this hand
        # were written clear of it and floated above the line in the output.
        # EXCEPT when the captured ink itself crosses the guide by a real margin
        # (descenders g/j/p/q/y): the writer respected the line there, and this
        # hand's tails run deeper than the reference font's, so font-depth
        # seating lifted those letters visibly off the baseline.
        depth = metrics.depth_in_x_heights(g.char)
        ink_below_guide = variant.ink_bbox[3] - variant.baseline_y
        if depth is None or ink_below_guide > _TRUST_GUIDE_MIN_XH * store_x_height:
            anchor = (-variant.left_bearing, float(variant.baseline_y))
            dest = (g.x, g.y)
        else:
            anchor = (-variant.left_bearing, float(variant.ink_bbox[3]))
            dest = (g.x, g.y + depth * store_x_height * g.scale)
        _paste_rotated(canvas, glyph_img, g.scale, anchor, g.rotation_deg, dest,
                       embolden=g.embolden)
    for m in page.maths:
        # Equation ink comes pre-composed (mathrender.py): recolour, scale as
        # one unit (LANCZOS — it is a large downscale) and seat its baseline
        # row on (x, y). Page-level effects below apply to it like any ink.
        img = _colorize(m.ink.image, base_ink, 1.0, 0)
        w = max(1, round(img.width * m.scale))
        h = max(1, round(img.height * m.scale))
        img = img.resize((w, h), Image.Resampling.LANCZOS)
        canvas.alpha_composite(
            img, (round(m.x), round(m.y - m.ink.baseline_y * m.scale)))
    if fx and style.edge_soften_px > 0:
        canvas = _soften_edges(
            canvas, style.edge_soften_px * spec.width_px / _REF_PAGE_WIDTH_PX
        )
    return canvas


def render_pages(
    pages: list[PageLayout], store: GlyphStore, style: HandwritingStyle,
    seed: int = 0,
) -> list[Image.Image]:
    return [render_page(p, store, style, seed=seed + i) for i, p in enumerate(pages)]
