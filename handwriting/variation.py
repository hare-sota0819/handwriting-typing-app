"""Variation engine: turn layout's neutral placed glyphs into final transforms.

Layout emits every glyph with its variant already chosen (ink-extent spacing
needs the variant at placement time) and rotation=0. This stage applies the
*structured* randomness that makes assembled glyphs read as handwriting:

- slant: a mean lean (style.slant_deg) plus a SMOOTH low-frequency wander
  across the line (style.slant_jitter_deg) — not per-glyph noise — written
  into rotation_deg together with a small per-glyph rotation jitter
- size jitter: per-glyph multiplier on scale (style.size_jitter)
- word drift: a smooth low-frequency baseline offset per WORD
  (style.word_drift_px) — letters within a word move together, neighbouring
  words stay continuous — on top of the smooth drift layout baked into y

Seedable: a fixed seed reproduces identical transforms. The renderer consumes
the result without knowing text vs (Phase 2) math produced the glyphs.
"""

import math
import random

from .layout import PageLayout, PlacedGlyph, PlacedMath
from .style import HandwritingStyle

TWO_PI = 2.0 * math.pi


def _make_slant_wander(rng: random.Random, style: HandwritingStyle):
    """Smooth low-frequency slant wander around the mean lean, in degrees."""
    phase = rng.uniform(0.0, TWO_PI)
    # Period unrelated to the baseline drift period so the two don't lock step.
    period = style.baseline_drift_period_px * 1.7

    def wander(x: float) -> float:
        return style.slant_jitter_deg * math.sin(TWO_PI * x / period + phase)

    return wander


# Word-walk shape: step size and pull-to-center, as fractions of the
# amplitude. A mean-reverting random walk is smooth word-to-word (adjacent
# words sit at nearby values) but has NO period — sinusoidal drift was
# droppable as a visible pattern once a document ran long enough.
_WALK_STEP_FRAC = 0.45
_WALK_PULL = 0.25


def _make_word_walk(rng: random.Random, amp: float):
    """Bounded mean-reverting random walk sampled at the word index.

    Every letter of one word shares the exact same value; neighbouring words
    move gradually. Values stay within [-amp, amp]. Deterministic for a
    fixed seed: values are generated in word order and cached.
    """
    values: list[float] = []

    def offset(word: int) -> float:
        if amp == 0.0:
            return 0.0
        while len(values) <= word:
            prev = values[-1] if values else rng.gauss(0.0, 0.3) * amp
            step = rng.gauss(0.0, _WALK_STEP_FRAC * amp)
            nxt = prev + step - _WALK_PULL * prev
            values.append(max(-amp, min(amp, nxt)))
        return values[word]

    return offset


def apply_variation(
    pages: list[PageLayout],
    variant_counts: dict[str, int],
    style: HandwritingStyle,
    seed: int = 0,
) -> list[PageLayout]:
    """Return new pages with scale/rotation/y finalized per glyph.

    The glyph's variant is chosen by layout (ink-extent spacing needs it early)
    and preserved here. variant_counts is retained for API compatibility; this
    stage never touches glyph images.
    """
    rng = random.Random(seed)
    slant_wander = _make_slant_wander(rng, style)
    word_drift = _make_word_walk(rng, style.word_drift_px)
    word_tilt = _make_word_walk(rng, style.word_tilt_deg)

    out: list[PageLayout] = []
    for page in pages:
        new_page = PageLayout(spec=page.spec)
        for g in page.glyphs:
            variant = g.variant

            # Slant varies per WORD (one word keeps one lean; the user writes a
            # word in one posture) and is clamped at 0 so the lean NEVER flips
            # to the other side — direction stays consistent, only the amount
            # breathes. Per-glyph rotation jitter stays available but off.
            rotation = max(0.0, (
                style.slant_deg
                + word_tilt(g.word)
                + slant_wander(g.x)
                + rng.uniform(0.0, style.rotation_jitter_deg)
            ))
            scale = g.scale * (1.0 + rng.uniform(-style.size_jitter, style.size_jitter))
            y = g.y + word_drift(g.word)
            ink_shade = 1.0 - rng.uniform(0.0, style.ink_shade_jitter)

            new_page.glyphs.append(
                PlacedGlyph(
                    char=g.char,
                    variant=variant,
                    x=g.x,
                    y=y,
                    scale=scale,
                    rotation_deg=rotation,
                    ink_shade=ink_shade,
                    word=g.word,
                    embolden=g.embolden,
                )
            )
        # Equations ride the same per-word height walk as the words around
        # them (no slant/size jitter: the image is one composed unit).
        for m in page.maths:
            new_page.maths.append(PlacedMath(
                ink=m.ink, x=m.x, y=m.y + word_drift(m.word), scale=m.scale,
                word=m.word))
        out.append(new_page)
    return out
