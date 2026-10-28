"""Geometry validation: substitute REAL handwriting glyphs (a glyph store) into
the MathJax placement lists at the computed (x, y, scale).

For every placement JSON:
  - symbol whose base_char exists in the store -> paste a real glyph variant:
      * scaled so the store's cap height (native_size_px=74) equals
        CAP_EM (0.68 em) * element scale
      * baseline row (variant.baseline_y) anchored on the element's pen y
      * ink centered horizontally in the MathJax ink bbox
  - symbol NOT in the store (Greek, ∫, √ ... = the 63 to collect) -> light
    gray placeholder box at the bbox + the char as a label
  - rule -> solid ink bar at (x, y, w, h)

Outputs spike/out/hand/hand_<id>.png and a pixel-matched MathJax reference
page spike/out/ref/<id>.html (same px-per-em) for side-by-side composition.

Run: .venv/bin/python spike/render_placement.py
"""

import json
import math
import os
import random
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SPIKE = Path(__file__).resolve().parent
# HW_MATH_OUT overrides the working dir (see tex2svg.js).
OUT_ROOT = Path(os.environ.get("HW_MATH_OUT") or SPIKE / "out")
sys.path.insert(0, str(SPIKE.parent))
from handwriting.glyphstore import GlyphStore  # noqa: E402

PPE = 300          # pixels per em: resolution is never traded off (2026-08-07)
CAP_EM = 0.68      # MathJax TeX cap height in em (measured: T bbox h = 0.677)
XH_EM = 0.442      # MathJax TeX x-height in em (measured: π bbox h = 0.442)
MARGIN = 30
INK = (40, 38, 45, 255)
SEED = 7

# Ink metrics are MEASURED from the store being used, never taken from its
# nominal frame: native_size_px overstates real letter height, and anchoring on
# it renders everything ~32% small (first-run finding). Different stores have
# different metrics, so --store requires re-measuring rather than a constant.
def measure_store_ink(store):
    """median cap-letter and x-height ink heights above baseline, native px."""
    def median_ink(chars):
        hs = []
        for ch in chars:
            if ch not in store:
                continue
            for v in store.entry(ch).variants:
                hs.append(v.baseline_y - v.ink_bbox[1])
        hs.sort()
        return hs[len(hs) // 2] if hs else None

    cap = median_ink("THELFB")
    xh = median_ink("aexz")
    if cap is None or xh is None:
        raise SystemExit("store lacks the letters needed to measure ink metrics")
    return float(cap), float(xh)

# anchor mode: 'cap' maps real cap ink -> TeX cap height (default);
# 'xheight' maps real x-height ink -> TeX x-height (renders caps oversized —
# kept as A/B evidence for the report)
ANCHOR = "xheight" if "--anchor=xheight" in sys.argv else "cap"

FONT = None
for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
    if Path(cand).exists():
        FONT = ImageFont.truetype(cand, 22)
        break


RULE_KEYS = ("rule:short", "rule:med", "rule:long")

# Codepoints MathJax emits that a hand does not write differently from one we
# already collected. Aliasing beats collecting the same shape twice.
ALIASES = {
    "−": "-",    # MINUS SIGN -> ASCII hyphen (Word's minus is U+2212)
    "∘": "°",  # RING OPERATOR -> degree (REPORT §5.1)
    "∗": "*",    # ASTERISK OPERATOR -> asterisk
    "′": "'",    # PRIME -> apostrophe
    "⋅": "·",  # DOT OPERATOR -> middle dot
    "∙": "·",  # BULLET OPERATOR -> middle dot
    "⟹": "⇒",  # LONG DOUBLE ARROW -> double arrow (a hand draws one length)
    "⟸": "⇐",
    "⟶": "→",
    "⟵": "←",
    "⊊": "⊂",  # PROPER SUBSET -> subset; the strike is not collected
    "⊋": "⊃",
    "∖": "\\",  # SET MINUS -> backslash
    "∣": "|",    # DIVIDES (\mid) -> vertical bar
    "⋯": "…",    # MIDLINE ELLIPSIS (\cdots, Word's equation-number lead-in) -> ellipsis
    "⊤": "T",    # DOWN TACK (\top, transpose x^⊤) -> the T a hand writes there
    # Greek "symbol" codepoints. TeX/Word emit these for \epsilon, \phi,
    # \vartheta, \varrho, \varpi, \varkappa, while the collection sheet
    # holds the ordinary letter (U+03B5 ε, U+03C6 φ, ...). One hand writes
    # one epsilon, so the variant codepoints take the collected letter
    # instead of a grey box (reported 2026-09-20: ϵ₀ in Ch14).
    "ϵ": "ε",    # GREEK LUNATE EPSILON SYMBOL (\epsilon)
    "ϕ": "φ",    # GREEK PHI SYMBOL (\phi)
    "ϑ": "θ",    # GREEK THETA SYMBOL (\vartheta)
    "ϱ": "ρ",    # GREEK RHO SYMBOL (\varrho)
    "ϖ": "π",    # GREEK PI SYMBOL (\varpi)
    "ϰ": "κ",    # GREEK KAPPA SYMBOL (\varkappa)
    "ς": "σ",    # GREEK FINAL SIGMA
    # Relations with no glyph of their own: the nearest one collected
    # (same table as the prose parser's; a ≳ in ch13 was lost, 2026-09-30).
    "≳": "≥",
    "⩾": "≥",
    "≧": "≥",
    "≲": "≤",
    "⩽": "≤",
    "≦": "≤",
}


def store_key(store, ch, el=None):
    """The key to draw `ch` with; None if the store has nothing for it.

    A variable (MathJax font `I`) prefers the `math:` form of the letter when one
    has been collected — the user writes some letters differently in an equation
    than in prose, and the two must never substitute for each other. Falls back
    to the prose glyph, then to an alias.
    """
    keys = []
    if el is not None and el.get("font") == "I":
        keys.append(f"math:{ch}")
    keys += [ch, ALIASES.get(ch)]
    for k in keys:
        if k and k in store and store.entry(k).variants:
            return k
    return None


# Delimiters and relations are drawn wider in this hand than MathJax's boxes
# (a written `[` is ~0.45 as wide as tall; TeX's is 0.16). MathJax places the
# neighbours for ITS width, so the wide glyph ran into them — `E[|f|]` came out
# as `E▯f▯`, the bracket and the bar overprinting into a box. Such a glyph is
# squeezed sideways to at most _WIDTH_CAP_RATIO x the box width (plus a small
# absolute allowance for hairline boxes like `|`); letters are never squeezed.
_WIDTH_CAPPED = set("(){}|‖⟨⟩⌊⌋⌈⌉≠≤≥=<>≈≡")
_WIDTH_CAP_RATIO = 1.5
_WIDTH_CAP_PAD_EM = 0.10


# Square brackets are NOT squeezed to MathJax's box (2026-09-16 user report):
# this hand writes `[` about 0.45 as wide as tall against TeX's 0.16, and the
# squeeze shortened the top and bottom arms into stubby blobs. The bracket keeps
# its written width instead, and the extra is made room for: it moves right by
# its left overhang, and everything after it by both overhangs, so it neither
# lands on the glyph before it nor on the content it encloses.
BRACKETS_PUSH = set("[]")


def bracket_overflow(el, ink_w):
    """px a bracket's ink overhangs MathJax's box on EACH side (0 otherwise)."""
    if el.get("base_char") not in BRACKETS_PUSH:
        return 0.0
    return max(0.0, (ink_w - el["bbox"]["w"] * PPE) / 2)


def width_cap_px(el):
    """Max ink width (px) for this element, or None if it is not capped."""
    if el.get("base_char") not in _WIDTH_CAPPED:
        return None
    bw = el["bbox"]["w"] * PPE
    return max(_WIDTH_CAP_RATIO * bw, bw + _WIDTH_CAP_PAD_EM * el["scale"] * PPE)


# Large operators whose shape is two-dimensional (∑ ∏ ⋃ ...): growing them means
# scaling the whole letterform, so width follows height. Everything else that
# stretches is a delimiter built around a vertical stroke.
_UNIFORM_STRETCH = set("∑∏∐⋃⋂⋁⋀⨁⨂⨀⨄⨆")
# Glyphs with a middle feature (the brace tip, the closed integral's circle)
# have TWO straight runs; both grow by the same amount so the feature stays
# centred. Grown in one run only, a display ∮ sank its circle to the foot.
_TWO_BAND = set("{}∮")
_MIN_BAND_FRAC = 0.12    # a detected straight run shorter than this is noise
_STRAIGHT_TOL = 1.4      # row span within this factor of the thinnest row counts as straight


def _straight_bands(mask, ch):
    """Row ranges [a, b) inside the glyph's straight vertical run(s).

    A delimiter's straight stem is where every row spans about the same, and
    the least, ink width; serifs, hooks and the curved ends span more. The
    longest such run (two, on either side of the middle, for braces) is what
    stretching may lengthen without changing any stroke's thickness.
    """
    import numpy as np
    h = mask.shape[0]
    rows = np.nonzero(mask.any(axis=1))[0]
    if len(rows) == 0:
        return []
    span = np.full(h, np.inf)
    for r in rows:
        cols = np.nonzero(mask[r])[0]
        span[r] = cols[-1] - cols[0] + 1
    # Reference width = a low percentile, not the minimum: a stroke tapers to
    # a pixel or two at its very ends, which would rule every other row out.
    lim = np.percentile(span[rows], 15) * _STRAIGHT_TOL + 2
    straight = span <= lim
    runs, start = [], None
    for r in range(h + 1):
        on = r < h and straight[r]
        if on and start is None:
            start = r
        elif not on and start is not None:
            runs.append((start, r))
            start = None
    runs = [r for r in runs if r[1] - r[0] >= _MIN_BAND_FRAC * h]
    if not runs:
        return []
    if ch in _TWO_BAND:
        upper = [r for r in runs if (r[0] + r[1]) / 2 < h / 2]
        lower = [r for r in runs if (r[0] + r[1]) / 2 >= h / 2]
        if upper and lower:
            return [max(upper, key=lambda r: r[1] - r[0]),
                    max(lower, key=lambda r: r[1] - r[0])]
    return [max(runs, key=lambda r: r[1] - r[0])]


def _stretch_bands(ink, bands, extra):
    """Lengthen `ink` by `extra` px by resizing only the given row bands."""
    w, h = ink.size
    share = [extra // len(bands)] * len(bands)
    share[-1] += extra - sum(share)
    out = Image.new("RGBA", (w, h + extra))
    y_src = 0
    y_dst = 0
    for (a, b), d in zip(bands, share):
        out.paste(ink.crop((0, y_src, w, a)), (0, y_dst))
        y_dst += a - y_src
        band_h = max(1, b - a + d)
        out.paste(ink.crop((0, a, w, b)).resize((w, band_h), Image.LANCZOS),
                  (0, y_dst))
        y_dst += band_h
        y_src = b
    out.paste(ink.crop((0, y_src, w, h)), (0, y_dst))
    return out


def pick_stretchy(store, rng, ch, target_h, max_w=None):
    """A delimiter sized to the height MathJax computed for it.

    The store holds two sizes (normal and the separately written full-height
    one), MathJax's sizes are continuous, so take the nearer captured size and
    stretch only the remainder — a big residual is what makes a blown-up pen
    stroke look smeared. The remainder is added INSIDE the straight vertical
    run only (_straight_bands): stretching the whole glyph vertically thickened
    every horizontal part — bracket serifs, paren ends — by the stretch factor,
    after which pen normalisation, reading one average width, thinned the stem
    to compensate (blobby ends on a thin stem, or the reverse when shrinking).
    Two-dimensional operators (∑ ∏) scale uniformly instead.
    """
    base_s = (CAP_EM * PPE) / STORE_CAP_INK
    best = None
    for key in (f"big:{ch}", store_key(store, ch)):
        if not key or key not in store or not store.entry(key).variants:
            continue
        vs = store.entry(key).variants
        natural = sum((v.ink_bbox[3] - v.ink_bbox[1]) for v in vs) / len(vs) * base_s
        err = abs(math.log(target_h / natural)) if natural else 1e9
        if best is None or err < best[0]:
            best = (err, vs)
    if best is None:
        return None

    v = rng.choice(best[1])
    ix0, iy0, ix1, iy1 = v.ink_bbox
    ink = store.load_image(v).crop((ix0, iy0, ix1, iy1))
    scaled_w = max(1, round(ink.width * base_s))
    natural_h = max(1, round(ink.height * base_s))
    extra = round(target_h) - natural_h
    if ch in _UNIFORM_STRETCH:
        s = target_h / max(1, ink.height)
        out = ink.resize((max(1, round(ink.width * s)),
                          max(1, round(target_h))), Image.LANCZOS)
    elif ch == "√" and extra > 1:
        # Growing a radical hook: extend ONLY the straight vertical run.
        # Whole-glyph stretching deforms the parts that carry the letterform —
        # the bottom check flattens into a long spike (and, before the resheet,
        # the baked-in top bar smeared into a corner blob). A band well inside
        # the vertical stroke is stretched instead; the ends keep their shape.
        ink = ink.resize((scaled_w, natural_h), Image.LANCZOS)
        out = _stretch_bands(
            ink, [(round(0.15 * natural_h), round(0.45 * natural_h))], extra)
    elif abs(extra) > 1:
        import numpy as np
        ink = ink.resize((scaled_w, natural_h), Image.LANCZOS)
        bands = _straight_bands(np.array(ink)[..., 3] > 128, ch)
        room = sum(b - a for a, b in bands)
        if bands and (extra > 0 or -extra < 0.6 * room):
            out = _stretch_bands(ink, bands, extra)
        else:
            # No straight run to work with (angle brackets, slashes): the old
            # whole-glyph vertical stretch is all that is left.
            out = ink.resize((scaled_w, max(1, round(target_h))), Image.LANCZOS)
    else:
        out = ink.resize((scaled_w, max(1, round(target_h))), Image.LANCZOS)
    if max_w is not None and out.width > max_w:
        out = out.resize((max(1, round(max_w)), out.height), Image.LANCZOS)
    return normalize_pen(out, PEN_PX)


def pick_rule_stroke(store, rng, target_w):
    """A handwritten horizontal stroke stretched to exactly target_w px.

    MathJax draws fraction and radical bars as rectangles; substituting a real
    pen stroke is what keeps them from reading as ruler lines. The bucket whose
    natural width is nearest the target is chosen so the residual stretch stays
    small — a long bar built from the 'short' stroke would smear its texture.
    Vertical scale is the store's own glyph scale, so the bar carries the same
    pen weight as the letters around it.
    """
    base_s = (CAP_EM * PPE) / STORE_CAP_INK
    best = None
    for key in RULE_KEYS:
        if key not in store or not store.entry(key).variants:
            continue
        for v in store.entry(key).variants:
            ix0, iy0, ix1, iy1 = v.ink_bbox
            natural_w = (ix1 - ix0) * base_s
            err = abs(math.log(target_w / natural_w)) if natural_w else 1e9
            if best is None or err < best[0]:
                best = (err, v)
    if best is None:
        return None

    v = best[1]
    ix0, iy0, ix1, iy1 = v.ink_bbox
    ink = store.load_image(v).crop((ix0, iy0, ix1, iy1))
    h = max(1, round(ink.height * base_s))
    return ink.resize((max(1, round(target_w)), h), Image.LANCZOS)





# MathJax builds a horizontal brace (\underbrace / \overbrace) from private-use
# pieces: two ends, a middle tip pair and a stretched extender.
_BRACE_PIECES = {chr(c) for c in range(0xE150, 0xE155)}


def brace_groups(elements):
    """Consecutive runs of brace pieces -> [(first_index, last_index, x0, y0,
    x1, y1, tip_down)] in placement em units. Pieces are drawn as ONE
    handwritten brace turned sideways; the store has no glyph for them, so
    they used to come out as grey placeholder boxes."""
    groups = []
    i = 0
    n = len(elements)
    while i < n:
        el = elements[i]
        if el["kind"] in ("symbol", "stretchy") and el.get("base_char") in _BRACE_PIECES:
            j = i
            while (j + 1 < n and elements[j + 1]["kind"] in ("symbol", "stretchy")
                   and elements[j + 1].get("base_char") in _BRACE_PIECES):
                j += 1
            run = elements[i:j + 1]
            x0 = min(e["bbox"]["x"] for e in run)
            x1 = max(e["bbox"]["x"] + e["bbox"]["w"] for e in run)
            y0 = min(e["bbox"]["y"] for e in run)
            y1 = max(e["bbox"]["y"] + e["bbox"]["h"] for e in run)
            ends = [e for e in run if e["base_char"] in ("\ue150", "\ue151",
                                                          "\ue152", "\ue153")]
            tops = sorted(set(round(e["bbox"]["y"], 3) for e in ends))
            # The middle tip pair sits lower than the ends on an underbrace
            # (tip pointing down), higher on an overbrace.
            tip_down = True
            if len(tops) >= 2:
                lowest = [e for e in ends if round(e["bbox"]["y"], 3) == tops[-1]]
                mid = (x0 + x1) / 2
                tip_down = all(abs(e["bbox"]["x"] + e["bbox"]["w"] / 2 - mid)
                               < (x1 - x0) / 4 for e in lowest)
            groups.append((i, j, x0, y0, x1, y1, tip_down))
            i = j + 1
        else:
            i += 1
    return groups


def draw_brace(img, store, rng, x0, y0, w, h, tip_down):
    """A horizontal brace built from pen strokes: a long bar with both ends
    hooked toward the content and a small V tip at the middle pointing away
    from it. (Laying the written `{` flat did not work: this hand's brace has
    its halves staggered, which read as a step, not a tip.)"""
    depth = h
    hook = 0.5 * depth
    tip = 0.75 * depth
    y_bar = y0 + (0.35 * depth if tip_down else 0.65 * depth)
    bar = pick_rule_stroke(store, rng, w)
    if bar is None:
        return
    pen = bar.height
    img.alpha_composite(bar, (round(x0), round(y_bar - pen / 2)))
    up = -1.0 if tip_down else 1.0          # direction of the end hooks
    for x in (x0, x0 + w):
        seg = pick_rule_stroke(store, rng, hook).rotate(90, expand=True)
        top = y_bar if up > 0 else y_bar - hook
        img.alpha_composite(seg, (round(x - pen / 2), round(top)))
    # tip: two short strokes at 45°, meeting at the apex a half-tip past the bar
    half = tip / math.sqrt(2)
    cx = x0 + w / 2
    apex_y = y_bar + (half if tip_down else -half)
    for sign in (-1, 1):
        seg = pick_rule_stroke(store, rng, tip)
        # left segment slopes "\" for a down tip, "/" for an up tip
        # (PIL rotates counter-clockwise on screen)
        ang = -45 if (sign < 0) == tip_down else 45
        rot = seg.rotate(ang, expand=True)
        ccx = cx + sign * half / 2
        ccy = (y_bar + apex_y) / 2
        img.alpha_composite(rot, (round(ccx - rot.width / 2),
                                  round(ccy - rot.height / 2)))


def _draw_frame(img, draw, store, rng, x0, y0, w, h):
    """Hand-drawn rectangle: a horizontal pen stroke for the top and bottom
    edges, the same stroke turned upright for the sides; corners overlap by
    half a pen so the box closes."""
    top = pick_rule_stroke(store, rng, w)
    if top is None:
        draw.rectangle([x0, y0, x0 + w, y0 + h], outline=INK, width=3)
        return
    pen = top.height
    bottom = pick_rule_stroke(store, rng, w)
    left = pick_rule_stroke(store, rng, h).rotate(90, expand=True)
    right = pick_rule_stroke(store, rng, h).rotate(-90, expand=True)
    img.alpha_composite(top, (round(x0), round(y0 - pen / 2)))
    img.alpha_composite(bottom, (round(x0), round(y0 + h - pen / 2)))
    img.alpha_composite(left, (round(x0 - pen / 2), round(y0)))
    img.alpha_composite(right, (round(x0 + w - pen / 2), round(y0)))


def variant_size_correction(store, key, variant):
    """Factor that brings one variant up/down to its character's typical size.

    Cells were written by hand, so the ten `x` samples differ in size by far more
    than a reader reads as natural variation once they are scattered through one
    equation — the same letter appearing large in one term and small in the next
    looks like a rendering fault. Normalising against the character's OWN median
    (not the store's) removes that while leaving the genuine size difference
    BETWEEN characters, which is part of the hand.
    """
    med = _char_size_cache.get(key)
    if med is None:
        hs = sorted(v.baseline_y - v.ink_bbox[1] for v in store.entry(key).variants)
        med = hs[len(hs) // 2] or 1
        _char_size_cache[key] = med
    own = variant.baseline_y - variant.ink_bbox[1]
    return med / own if own > 0 else 1.0


# An integral's limits are placed by MathJax against the width and depth of ITS
# operator glyph. Every operator we substitute has different proportions — worst
# for the multi-integrals — so the limits landed on top of the tail on one
# equation and floated away on the next. Both are repositioned against the
# MEASURED ink of the operator actually drawn, which also makes the spacing
# identical for the whole family.
LIMIT_GAP_EM = 0.06
JOIN_OVERLAP_EM = 0.02   # bar starts just inside the hook so the join is solid


def is_limit(el):
    """Shape of a sub/superscript hung on a large operator.

    Only meaningful for elements that IMMEDIATELY follow the operator: a later
    superscript such as the exponent in e^{-x^2} looks identical here, and
    treating it as a limit drags it back onto the integral sign.
    """
    return el["kind"] == "symbol" and el["scale"] < 0.95 and abs(el["y"]) > 0.3


# A letter that follows another letter is pulled very slightly toward it. That
# tightens a word without touching anything else on the line, and the gap to
# whatever symbol comes next grows by the same amount — which is what separates
# `cl(A)` from reading as `c |(A)`. The user's point: their `l` and their `|` are
# the same stroke, so this is a spacing problem, not a recognition one. Nudging
# the letter is deliberate: shifting everything downstream instead would drag
# fraction numerators out of line with their denominators.
WORD_TIGHTEN_EM = 0.05


# MathJax reserves the box ITS font needs. A hand glyph fitted to that box by
# height can be far wider — this hand's `2` measures 1.7x the width MathJax
# allots — and, centred on the box, it spills to both sides. The spill lands on
# whatever stands beside it: the decimal point of `0.273` vanished under the
# following `2`. A glyph that would come closer than MIN_INK_GAP_EM to the ink
# already placed beside it on the same baseline is nudged right by exactly the
# shortfall, and never by more than MAX_NUDGE_EM — no glyph ends up far enough
# from the spot MathJax chose to pull a numerator off its denominator.
MIN_INK_GAP_EM = 0.05
MAX_NUDGE_EM = 0.15


def nudge_x(prev_right, ink_left, scale):
    """px to move a glyph right so it clears the ink already drawn beside it."""
    if prev_right is None:
        return 0
    short = prev_right + MIN_INK_GAP_EM * PPE * scale - ink_left
    return max(0, round(min(short, MAX_NUDGE_EM * PPE * scale)))


# The same mismatch as nudge_x, the other way round. MathJax puts a subscript
# after the advance width ITS `v` needs; this hand's `v` is narrower, and the
# script is then centred in a box wider than its own ink, so the slack falls
# between the two: `kv_r` measured 0.17 em of air and `F_fr` 0.20, which reads
# as "kv , r" rather than as one symbol. A script is pulled back to
# SCRIPT_GAP_EM from the ink it belongs to — the gap letters inside a word get
# (intra_word_gap_frac 0.12 of the x-height = 0.053 em) — and never by more
# than MAX_SCRIPT_PULL_EM, so a script can not walk off its own base.
SCRIPT_GAP_EM = 0.06
MAX_SCRIPT_PULL_EM = 0.20

# Air a fraction bar keeps beyond the widest ink it separates.
FRAC_BAR_PAD_EM = 0.10


def script_pull(base_right, ink_left, scale):
    """px (negative) to move a sub/superscript left so it hugs its base."""
    if base_right is None or scale >= 1.0:
        return 0
    slack = ink_left - base_right - SCRIPT_GAP_EM * PPE
    return -max(0, round(min(slack, MAX_SCRIPT_PULL_EM * PPE)))


def is_letter(el):
    return (el is not None and el["kind"] == "symbol"
            and (el.get("base_char") or " ").isalpha())


# Pen weight must survive scaling. Every glyph is resized by a different factor
# — a `y` is sized by its small bowl and so is blown up ~1.8x more than an `x`,
# and a large operator written big is shrunk — and the stroke thickens or thins
# with it. Measured on the re-write sheet before this existed: x rendered at
# 6.6 px, y at 16.8 px, the integrals at 2.8 px. Re-writing the cells cannot fix
# that; it is the scaling, not the pen. So the stroke is brought back to one
# target after resizing.
PEN_EM = 0.0955          # measured: pen thickness / x-height 0.216 x 0.442 em
# The pen every equation glyph is brought to. main() replaces this with the
# stroke width the store's own letters have at body size — the width the prose
# around the equation is drawn with — so maths and text carry one weight.
PEN_PX = PEN_EM * PPE
PEN_TOLERANCE_PX = 0.4   # tight: a visible 1.5x spread survived a loose one
# BACK ON by default (2026-08-07). The user switched this off on 2026-08-05 in the
# belief that a ballpoint would make it unnecessary. It did not: their round-2
# review reports the chemistry `+` and `→` far thicker than the letters, subscript
# digits thicker than the letters beside them, and `a`/`t`/`o` inside one word at
# three different weights. That is this exact defect, and they diagnosed the cause
# themselves — "설마 확대해서 이지랄이 일어나는건가?" Yes: every glyph is scaled by
# a different factor to fit its box, and stroke weight scales with it.
# Turning it back on is a reversal of their instruction, so it is a switch, not a
# hard-coding: --raw-pen restores untouched strokes.
# The real cure is the guide-based re-collection (they have agreed to write again),
# which makes the scale factors equal at source; until those pages exist this is
# what keeps a line from mixing three weights.
PEN_NORMALISE = "--raw-pen" not in sys.argv
PEN_EDGE_BLUR_PX = 0.8   # antialiasing of the re-stroked centre-line pen


def _pen_px(ink):
    """Stroke thickness estimate: 2*area/boundary ~= width for a stroke."""
    import numpy as np
    area = int(ink.sum())
    if area == 0:
        return None
    # Ink flush with the image edge (a delimiter cropped to its ink box has
    # its stem ON the edge) has no neighbour there and counted as interior:
    # the boundary came out half-length and the pen twice as thick, so the
    # stem was thinned to correct a fatness it never had — the tall `[` with
    # a thin stem under fat ends. Pad with background first.
    ink = np.pad(ink, 1)
    edge = ink.copy()
    edge[1:, :] &= ink[:-1, :]
    edge[:-1, :] &= ink[1:, :]
    edge[:, 1:] &= ink[:, :-1]
    edge[:, :-1] &= ink[:, 1:]
    boundary = area - int(edge.sum())
    return (2.0 * area / boundary) if boundary else None


def _thin(mask):
    """Zhang-Suen thinning: the one-pixel centre lines of a binary mask."""
    import numpy as np
    img = np.pad(mask.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            P = img
            p2 = P[:-2, 1:-1]; p3 = P[:-2, 2:]; p4 = P[1:-1, 2:]; p5 = P[2:, 2:]
            p6 = P[2:, 1:-1]; p7 = P[2:, :-2]; p8 = P[1:-1, :-2]; p9 = P[:-2, :-2]
            c = P[1:-1, 1:-1]
            n = (p2.astype(np.int16) + p3 + p4 + p5 + p6 + p7 + p8 + p9)
            seq = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            a = np.zeros_like(n)
            for i in range(8):
                a += ((seq[i] == 0) & (seq[i + 1] == 1))
            if step == 0:
                cond = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                cond = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            kill = (c == 1) & (n >= 2) & (n <= 6) & (a == 1) & cond
            if kill.any():
                img[1:-1, 1:-1][kill] = 0
                changed = True
        if not changed:
            break
    return img[1:-1, 1:-1].astype(bool)


def _disk(r):
    """(dy, dx) offsets of a filled disk of radius r."""
    import numpy as np
    R = int(math.floor(r))
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    keep = yy * yy + xx * xx <= r * r
    return yy[keep], xx[keep]


def _restroke(mask, pen_px):
    """Re-draw a binary glyph as its skeleton painted with a round pen of
    `pen_px` diameter; returns a hard-edged 8-bit alpha array.

    The skeleton of a big glyph is found at half resolution (thinning cost grows
    with area x stroke width), but the pen is always painted at FULL resolution
    around the doubled skeleton points. The old version painted at half
    resolution and bilinear-upscaled the result, which left a stair-stepped,
    lumpy edge that the page downscale could not hide.
    """
    import numpy as np
    h, w = mask.shape
    if max(h, w) > 160:
        m = mask[:h - h % 2, :w - w % 2]
        small = m.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3)) >= 0.5
        ys, xs = np.nonzero(_thin(small))
        ys, xs = ys * 2, xs * 2
    else:
        ys, xs = np.nonzero(_thin(mask))
    r = max(1.0, pen_px / 2.0)
    R = int(math.floor(r))
    dy, dx = _disk(r)
    out = np.zeros((h + 2 * R + 2, w + 2 * R + 2), bool)
    out[(ys[:, None] + dy + R + 1).ravel(), (xs[:, None] + dx + R + 1).ravel()] = True
    return (out[R + 1:R + 1 + h, R + 1:R + 1 + w] * 255).astype(np.uint8)


def _dilate_alpha(a, r):
    """Grey-level dilation of an alpha array by a disk of radius r (fractional
    radii blend the two neighbouring whole-pixel disks). Moving the whole
    antialiased edge outward keeps it exactly as smooth as the original."""
    import numpy as np

    def whole(rr):
        R = int(math.floor(rr))
        if R < 1:
            return a.astype(np.float32)
        h, w = a.shape
        src = np.pad(a, R).astype(np.float32)
        out = np.zeros_like(src)
        for dy, dx in zip(*_disk(rr)):
            np.maximum(out[R + dy:R + dy + h, R + dx:R + dx + w],
                       src[R:R + h, R:R + w],
                       out=out[R + dy:R + dy + h, R + dx:R + dx + w])
        return out[R:R + h, R:R + w]

    lo = math.floor(r)
    t = r - lo
    res = whole(lo)
    if t > 1e-3:
        res = (1 - t) * res + t * whole(lo + 1)
    return res


def measure_store_pen(store):
    """Median stroke width of the store's plain letters, native px."""
    import numpy as np
    ws = []
    for ch in "aenosrtuchmlTHE":
        if ch in store:
            for v in store.entry(ch).variants:
                w = _pen_px(np.array(store.load_image(v))[..., 3] > 128)
                if w:
                    ws.append(w)
    ws.sort()
    return ws[len(ws) // 2]


def normalize_pen(glyph, target_px):
    """Re-weight a scaled glyph so its stroke lands on the target width.

    The edge must stay as clean as the prose glyphs, which are only resized
    (2026-09-16 user report: equation glyphs looked lumpy and lower-res next to
    the text, and digits read as shaved). The old blur-and-rethreshold search
    redrew every edge from a blurred field, and its square MaxFilter / half-res
    skeleton steps left boxy or stair-stepped outlines. Now:
    - thickening moves the ORIGINAL antialiased edge outward by a round
      grey-level dilation, so its profile is unchanged;
    - thinning keeps the original ink only within a round pen of the target
      width around the stroke's centre line (the minimum of the two alphas):
      thick parts come down to the target, parts the hand already drew thinner
      than the target are left exactly as written — nothing is shaved.
    """
    import numpy as np
    if not PEN_NORMALISE:
        return glyph
    a = np.array(glyph)[..., 3]
    cur = _pen_px(a > 128)
    if cur is None or abs(target_px - cur) <= PEN_TOLERANCE_PX:
        return glyph
    if target_px > cur:
        out = _dilate_alpha(a, (target_px - cur) / 2.0)
    else:
        core = Image.fromarray(_restroke(a > 128, target_px))
        core = np.array(core.filter(ImageFilter.GaussianBlur(PEN_EDGE_BLUR_PX)))
        out = np.minimum(a, core)
    r, g, b, _ = glyph.split()
    return Image.merge("RGBA", (r, g, b, Image.fromarray(
        np.clip(out, 0, 255).astype("uint8"))))





MIN_BOX_EM = 0.02        # below this MathJax gives no usable box to match


def fit_scale(el, variant):
    """Uniform scale putting the variant's ink box on MathJax's box for this element.

    ONE rule for every glyph, and uniform on both axes. The previous version had a
    special path for descenders plus `fit_descender()`, which squashed the part of
    the letter below the baseline to fit — that is a shape modification, it thinned
    the `g`'s tail visibly, and the user asked for it gone. Scaling the whole glyph
    can only make it smaller; it can never deform it.

    Nothing here consults the printed guide. It records where the writer was aiming,
    not where the ink landed, and has now caused three separate bugs.
    """
    ink_h = variant.ink_bbox[3] - variant.ink_bbox[1]
    box_h = el["bbox"]["h"]
    if ink_h <= 0 or box_h < MIN_BOX_EM:
        return None
    return (box_h * PPE) / ink_h


# MathJax's em_height/ascent describe ITS glyphs. A substituted hand-written tall
# paren reaches higher than the font's, and ran off the top of the bitmap (the user
# caught `(ΔT = q/mc)` with its parentheses sliced). The canvas is drawn oversized
# and then cropped to the ink that actually landed, so nothing can be clipped
# whatever the substituted glyph does.
OVERDRAW = 2.0           # extra canvas, as a multiple of MARGIN, on every side
CROP_PAD = 6             # px of white kept around the ink after cropping


def render(eq_id, placement, store, rng):
    pad = int(MARGIN * OVERDRAW)
    # Brackets are drawn at the hand's own width and push what follows right
    # (see BRACKETS_PUSH); the canvas gets room for the widest they can be.
    push_room = sum(e["bbox"]["h"] for e in placement["elements"]
                    if e.get("base_char") in BRACKETS_PUSH and "bbox" in e) * PPE
    w = int(placement["width"] * PPE + push_room) + 2 * MARGIN + 2 * pad
    h = int(placement["em_height"] * PPE) + 2 * MARGIN + 2 * pad
    base_y = MARGIN + pad + placement["ascent"] * PPE
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    missing = []
    prev_el = None     # previous element, for word tightening
    prev_ink = None    # (right edge px, baseline y) of the last glyph drawn
    prev_row = None    # (y, scale) of that glyph: a change starts a new script
    base_ink_right = None  # ink right of the glyph a starting script hangs off
    script_shift = 0   # px the current run of script-sized glyphs was pulled
    tail = (-1.0, False)  # (rightmost ink x, and whether a subscript drew it)
    drawn = []         # (MathJax box centre em, ink x0, ink x1) per mark drawn
    op_ink = None      # measured ink box of the last large operator drawn
    surd_ink = None    # ... and of the last radical hook, for its overbar
    limit_shift = {}   # per-side offset applied to every glyph of one limit
    push = 0.0         # px every later element moves right, from wide brackets

    skip = set()
    for i0, i1, bx0, by0, bx1, by1, tip_down in brace_groups(placement["elements"]):
        skip.update(range(i0, i1 + 1))
        draw_brace(img, store, rng, MARGIN + pad + bx0 * PPE, base_y + by0 * PPE,
                   (bx1 - bx0) * PPE, (by1 - by0) * PPE, tip_down)

    for idx, el in enumerate(placement["elements"]):
        if idx in skip:
            continue
        if el["kind"] == "rule":
            x0 = MARGIN + pad + push + el["x"] * PPE
            target_w = el["w"] * PPE
            # MathJax's rule is a hairline; centre the pen stroke on it rather
            # than filling the rule's own height, which is thinner than any pen.
            y_mid = base_y + (el["y"] + el["h"] / 2) * PPE
            if el.get("role") == "sqrt_bar" and surd_ink is not None:
                # Join the overbar to the hook we actually drew. MathJax's rule
                # position was computed for ITS surd, whose height and shape are
                # not ours, which is why the bar floated free of the hook and the
                # radical read as an overline on the operand.
                right = x0 + target_w
                x0 = surd_ink[2] - JOIN_OVERLAP_EM * PPE
                target_w = max(1.0, right - x0)
                y_mid = surd_ink[1]
            elif el.get("role") == "frac_bar":
                # MathJax sized this rule for the numerator ITS font draws. A
                # hand's letters are wider — the V of `qV/d` overhung the bar
                # by 0.04 em and read as a stray arm — so the bar is grown (it
                # is never shortened) to cover the ink actually drawn above and
                # below it, plus the air TeX leaves at the ends.
                inside = [(a, b) for cx, a, b in drawn
                          if el["x"] <= cx <= el["x"] + el["w"]]
                if inside:
                    air = FRAC_BAR_PAD_EM * PPE * el.get("scale", 1.0)
                    right = max(x0 + target_w, max(b for _, b in inside) + air)
                    x0 = min(x0, min(a for a, _ in inside) - air)
                    target_w = right - x0
            stroke = pick_rule_stroke(store, rng, target_w)
            if stroke is None:
                y0 = base_y + el["y"] * PPE
                draw.rectangle(
                    [x0, y0, x0 + target_w,
                     y0 + max(el["h"] * PPE, 2.5)], fill=INK)
            else:
                img.alpha_composite(
                    stroke, (round(x0), round(y_mid - stroke.height / 2)))
            drawn.append((el["x"] + el["w"] / 2, x0, x0 + target_w))
            prev_el = None
            prev_ink = None
            prev_row = base_ink_right = None
            continue

        if el["kind"] == "frame":
            # \boxed{}: four pen strokes around the content. MathJax's stroked
            # rect used to be read as a filled rule and drew ONE bar through
            # the middle of the boxed expression (a strike-through).
            x0 = MARGIN + pad + push + el["x"] * PPE
            y0 = base_y + el["y"] * PPE
            fw, fh = el["w"] * PPE, el["h"] * PPE
            _draw_frame(img, draw, store, rng, x0, y0, fw, fh)
            prev_el = None
            prev_ink = None
            prev_row = base_ink_right = None
            continue

        ch = el["base_char"]
        bb = el["bbox"]
        cx = MARGIN + pad + push + (bb["x"] + bb["w"] / 2) * PPE    # ink center x
        if (is_letter(el) and is_letter(prev_el)
                and el["scale"] == prev_el["scale"]
                and abs(el["y"] - prev_el["y"]) < 1e-6):
            cx -= WORD_TIGHTEN_EM * PPE * el["scale"]
        prev_el = el
        pen_y = base_y + el["y"] * PPE                        # its baseline

        # Elements MathJax grew to fit their content (stretchy delimiters, and
        # large operators in display style) are sized by the height it computed,
        # not by the store's cap-height rule — that rule would draw a normal
        # ∑ or ( where the layout expects a tall one.
        if el["kind"] == "stretchy" or el.get("font") == "LO":
            tall = pick_stretchy(store, rng, ch, bb["h"] * PPE,
                                 max_w=width_cap_px(el))
            if tall is not None:
                ox, oy = round(cx - tall.width / 2), round(base_y + bb["y"] * PPE)
                tb = tall.getchannel("A").getbbox() or (0, 0, tall.width,
                                                        tall.height)
                over = bracket_overflow(el, tb[2] - tb[0])
                ox += round(over)
                push += 2 * over
                if ch == "√":
                    # A radical is not centred in its box: its stroke rises to
                    # the top RIGHT, where the vinculum takes over and the
                    # radicand begins. TeX's surd fills that box; this hand's
                    # is a narrow stem, and centring it left half an em of
                    # empty air (measured 0.49) between the stem and the
                    # radicand, which read as a box drawn around the operand.
                    ox = round(MARGIN + pad + push + (bb["x"] + bb["w"]) * PPE - tb[2])
                img.alpha_composite(tall, (ox, oy))
                if el.get("font") == "LO":
                    op_ink = (ox, oy, ox + tall.width, oy + tall.height)
                    limit_shift = {}
                if ch == "√":
                    # Measured ink, not the image edge: the overbar is joined to
                    # the stroke's top right corner, and clear ground around the
                    # glyph would float it off both ways.
                    surd_ink = (ox + tb[0], oy + tb[1], ox + tb[2], oy + tb[3])
                prev_ink = None
                prev_row = base_ink_right = None
                drawn.append((bb["x"] + bb["w"] / 2, ox + tb[0], ox + tb[2]))
                if ox + tb[2] > tail[0]:
                    tail = (ox + tb[2], False)
                continue

        key = store_key(store, ch, el)
        if key:
            variant = rng.choice(store.entry(key).variants)
            glyph = store.load_image(variant)
            s = fit_scale(el, variant)
            if s is None:
                if ANCHOR == "cap":
                    s = (CAP_EM * PPE * el["scale"]) / STORE_CAP_INK
                else:
                    s = (XH_EM * PPE * el["scale"]) / STORE_XH_INK
                s *= variant_size_correction(store, key, variant)
            ix0, iy0, ix1, iy1 = variant.ink_bbox
            sx = s
            cap_w = width_cap_px(el)
            if cap_w is not None and (ix1 - ix0) * s > cap_w:
                sx = cap_w / (ix1 - ix0)
            # Work on the ink box only (a store cell is mostly empty margin):
            # resize + pen normalisation cost scales with area.
            # NOT `pad`: that name holds the canvas padding this loop needs for
            # every later element's x. Shadowing it drew everything after the
            # first glyph 52 px left, which squeezed the decimal point of
            # `0.273` under the `2` (2026-09-04).
            crop_pad = 12  # room for the pen to thicken (dilation) without clipping
            cx0, cy0 = max(0, ix0 - crop_pad), max(0, iy0 - crop_pad)
            cx1, cy1 = (min(glyph.width, ix1 + crop_pad),
                        min(glyph.height, iy1 + crop_pad))
            glyph = glyph.crop((cx0, cy0, cx1, cy1))
            gw = max(1, round(glyph.width * sx))
            gh = max(1, round(glyph.height * s))
            glyph = glyph.resize((gw, gh), Image.LANCZOS)
            # One pen for the whole equation, NOT scaled by el["scale"]:
            # scaling the target with the element made subscripts, fraction
            # numerators and every other reduced part come out visibly thinner
            # than the body text beside them (2026-09-14 user report). A hand
            # writes a subscript with the same pen it writes the line with, and
            # the fraction bars (pick_rule_stroke) and stretchy delimiters were
            # already normalised unscaled — this brings symbols in line.
            glyph = normalize_pen(glyph, PEN_PX)
            over = bracket_overflow(el, (ix1 - ix0) * sx)
            cx += over
            push += 2 * over
            ink_cx = (ix0 + ix1) / 2 * sx
            px = round(cx - ink_cx)
            ink_bottom_y = base_y + (bb["y"] + bb["h"]) * PPE
            py = round(ink_bottom_y - iy1 * s)
            gx, gy = px + round(cx0 * sx), py + round(cy0 * s)
            # Collide on the ink that actually landed, not on the variant's
            # recorded box: pen normalisation thickens the stroke past that box,
            # and it is the thickened edge that swallows a neighbour.
            gb = glyph.getchannel("A").getbbox()
            if gb is not None:
                # A run of script-sized glyphs (the `fr` of F_fr) moves as one:
                # the first is pulled onto its base, the rest keep the spacing
                # MathJax gave them by taking the same shift.
                row = (el["y"], el["scale"])
                if row != prev_row:
                    script_shift = script_pull(base_ink_right, gx + gb[0],
                                               el["scale"])
                gx += script_shift
                px += script_shift
                same_row = prev_ink is not None and prev_ink[1] == el["y"]
                d = nudge_x(prev_ink[0] if same_row else None,
                            gx + gb[0], el["scale"])
                gx += d
                px += d
                prev_ink = (gx + gb[2], el["y"])
                prev_row = row
                base_ink_right = gx + gb[2]
                drawn.append((bb["x"] + bb["w"] / 2, gx + gb[0], gx + gb[2]))
                if gx + gb[2] > tail[0]:
                    tail = (gx + gb[2], el["scale"] < 1.0 and el["y"] > 0)
            img.alpha_composite(glyph, (gx, gy))
            if ch == "√":
                # A symbol-sized radical still gets an overbar rule; record its
                # measured ink so the sqrt_bar join applies here exactly as it
                # does for stretchy hooks — MathJax placed that bar for ITS
                # surd shape, and without the join it floats off ours.
                surd_ink = (px + ix0 * s, py + iy0 * s,
                            px + ix1 * s, py + iy1 * s)
        else:
            missing.append(ch)
            prev_ink = None
            x0 = MARGIN + pad + push + bb["x"] * PPE
            y0 = base_y + bb["y"] * PPE
            x1 = x0 + bb["w"] * PPE
            y1 = y0 + bb["h"] * PPE
            draw.rectangle([x0, y0, x1, y1], fill=(225, 225, 232, 255),
                           outline=(150, 150, 165, 255), width=2)
            if FONT:
                tb = draw.textbbox((0, 0), ch, font=FONT)
                draw.text(((x0 + x1 - tb[2]) / 2, (y0 + y1 - tb[3]) / 2), ch,
                          fill=(90, 90, 110, 255), font=FONT)
    import numpy as np
    a = np.array(img.convert("L"))
    ink = a < 240
    crop_top = 0
    if ink.any():
        ys, xs = np.nonzero(ink)
        crop_top = max(0, ys.min() - CROP_PAD)
        img = img.crop((max(0, xs.min() - CROP_PAD), crop_top,
                        min(img.width, xs.max() + 1 + CROP_PAD),
                        min(img.height, ys.max() + 1 + CROP_PAD)))
    # Where the equation's baseline sits inside the cropped image, and the
    # cap height it was drawn at: what a document layout needs to seat the
    # image on a text line and scale it to the body letters.
    meta = {"baseline_y": base_y - crop_top, "cap_px": CAP_EM * PPE,
            "store_cap_ink": STORE_CAP_INK, "missing": sorted(set(missing)),
            # The last ink on the right is a subscript, so a comma set against
            # it lands above it and reads as a prime ("F_fr," -> "F_fr'"):
            # the document layout gives that punctuation more air.
            "ends_subscript": bool(tail[1])}
    return img, missing, meta


def main():
    global STORE_CAP_INK, STORE_XH_INK, PEN_PX
    root = None
    seed = SEED
    for a in sys.argv[1:]:
        if a.startswith("--store="):
            root = Path(a.split("=", 1)[1])
        elif a.startswith("--seed="):
            seed = int(a.split("=", 1)[1])
    if root is None:
        from handwriting.stores import default_store
        root = default_store()
    store = GlyphStore(root)
    STORE_CAP_INK, STORE_XH_INK = measure_store_ink(store)
    PEN_PX = measure_store_pen(store) * CAP_EM * PPE / STORE_CAP_INK
    print(f"store {root}: cap ink {STORE_CAP_INK:.1f}px, "
          f"x-height ink {STORE_XH_INK:.1f}px")
    hand_dir = OUT_ROOT / "hand"
    ref_dir = OUT_ROOT / "ref"
    hand_dir.mkdir(parents=True, exist_ok=True)
    ref_dir.mkdir(parents=True, exist_ok=True)
    for eq in json.loads((OUT_ROOT / "equations.json").read_text(encoding="utf-8")):
        placement = json.loads(
            (OUT_ROOT / "placements" / f"{eq['id']}.json").read_text(encoding="utf-8"))
        # One RNG per equation, seeded by the seed AND the LaTeX: the same
        # equation always draws the same way for a seed, whatever else is in
        # the document — which is what lets mathrender cache renders per
        # equation instead of re-running the chain on every conversion.
        rng = random.Random(f"{seed}:{eq.get('display', False)}:{eq['latex']}")
        img, missing, meta = render(eq["id"], placement, store, rng)
        suffix = "" if ANCHOR == "cap" else "_xh"
        # grayscale + light compression: these are big (300 px/em) and the
        # PNG encode was a third of the chain's time as RGBA
        img.convert("L").save(hand_dir / f"hand_{eq['id']}{suffix}.png",
                              compress_level=1)
        (hand_dir / f"hand_{eq['id']}{suffix}.json").write_text(
            json.dumps(meta), encoding="utf-8")
        # pixel-matched MathJax reference (same px width incl. margins)
        svg = (OUT_ROOT / "svg" / f"{eq['id']}.svg").read_text(encoding="utf-8")
        svg = re.sub(r'width="[\d.]+ex" height="[\d.]+ex"',
                     f'width="{placement["width"] * PPE}px" '
                     f'height="{placement["em_height"] * PPE}px"', svg)
        (ref_dir / f"{eq['id']}.html").write_text(
            f'<!doctype html><meta charset="utf-8">'
            f'<body style="margin:{MARGIN}px;background:#fff">{svg}</body>',
            encoding="utf-8")
        print(f"{eq['id']}: rendered; placeholders for "
              f"{sorted(set(missing))!r}")


if __name__ == "__main__":
    main()
