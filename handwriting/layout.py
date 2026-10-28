"""Layout engine: Document Model + HandwritingStyle + page spec → placed glyphs.

Computes WHERE every glyph goes — no pixels are touched here. Emits pages of
PlacedGlyph records that the variation engine (per-glyph transforms, variant
selection) and renderer consume. The renderer never needs to know whether a
glyph came from text or (in Phase 2) from a typeset equation.

PlacedGlyph semantics (the contract with the renderer):
- x: pen origin x in page pixels; the glyph image's left edge goes at
  x + left_bearing * scale
- y: baseline y in page pixels (drift already included); the image row at
  baseline_y * scale sits on this line
- scale: absolute image scale factor (style size / store native size; the
  variation engine multiplies its size jitter into this)
- rotation_deg: rotation about the pen point (x, y); 0 from layout, the
  variation engine adds slant + jitter
- variant: index into the store entry's variants; layout always emits 0,
  the variation engine re-selects (no-immediate-repeat)

Equations: a MathBlock arrives with a pre-rendered ink image (mathrender.py)
and is placed as ONE PlacedMath record — an inline equation flows like a word
on the current line, a display equation is centred on a line of its own. A
tall equation pushes its line down (and the next line further down) so it
clears the neighbouring lines; the renderer scales and pastes the image.
"""

import logging
import math
import random
import re
from dataclasses import dataclass, field

import numpy as np

from . import metrics
from .document_model import Document, MathBlock, TextRun, WordPageBreak
from .mathrender import MathInk, measure_cap_ink
from .glyphstore import GlyphStore
from .style import HandwritingStyle

logger = logging.getLogger(__name__)

TWO_PI = 2.0 * math.pi


@dataclass(frozen=True)
class PageSpec:
    """Page geometry in pixels. Default: A4 at 150 dpi."""

    width_px: int = 1240
    height_px: int = 1754
    margin_px: int = 120


@dataclass(frozen=True)
class LineGrid:
    """Ruled-paper baseline grid to snap text lines onto.

    Baselines land at offset_px + k*spacing_px (k = 0, 1, 2, ...). margin_x_px,
    when known, is the paper's vertical margin line x (text starts just right
    of it). Obtained by auto-detection from the paper PDF or from manual CLI
    flags. last_rule_px is the y of the paper's last printed rule (detection
    only): the page is written down to it. Without it (manual flags) the
    plain-page bottom margin ends the page.
    """

    spacing_px: float
    offset_px: float
    margin_x_px: float | None = None
    last_rule_px: float | None = None


# When snapping, glyphs are sized by X-HEIGHT (not the tall native cap frame, which
# overstates real letter height and crushes the body). The lowercase body fills this
# fraction of the rule spacing; ascenders/descenders overshoot into the neighbouring
# lanes as in real handwriting. Kept as a fraction so it tracks any rule spacing.
_SNAP_XHEIGHT_FRAC = 0.4
# Safety ceiling: snapped size never exceeds the requested base_size_px mapped through
# the cap frame (prevents a pathological tiny-x-height store from ballooning).
_SNAP_MAX_CAP_FRAC = 1.6
# Text starts this many px to the right of a detected vertical margin line.
_SNAP_MARGIN_PAD = 10.0


@dataclass
class PlacedGlyph:
    char: str
    variant: int
    x: float
    y: float
    scale: float
    rotation_deg: float
    # Ink darkness multiplier in (0, 1]; 1.0 = full ink. Layout leaves it at
    # 1.0; the variation engine fades it slightly per glyph.
    ink_shade: float = 1.0
    # Document-wide word index (consecutive words share a value). The variation
    # engine moves whole words together (per-word baseline drift), so it needs
    # to know which glyphs belong to one word.
    word: int = 0
    # Thicken the ink at render time (superscripts: shrinking the glyph thins
    # its strokes below the body pen width, so the renderer dilates them back).
    embolden: bool = False


@dataclass
class PlacedMath:
    """One equation image on the page: baseline of the image's baseline row on
    (x, y) — x is its left edge, scale multiplies the image's pixels."""

    ink: MathInk
    x: float
    y: float
    scale: float
    word: int = 0


@dataclass
class PageLayout:
    spec: PageSpec
    glyphs: list[PlacedGlyph] = field(default_factory=list)
    maths: list[PlacedMath] = field(default_factory=list)


# Text lines are assumed to reach this far above / below the baseline (cap
# height multiples / body-size fractions). An equation no taller than text
# never moves anything; a taller one may reach up to (step - the line above's
# descent) and down to (step - the line below's ascent), less a small pad,
# before it pushes lines apart.
_TEXT_ASCENT_CAPS = 1.2
_TEXT_DESCENT_FRAC = 0.25
_MATH_PAD_CAPS = 0.15

# On ruled paper the room above a line is measured against the ink really
# written there (the lowest ink per column of the lines above), not against
# a worst-case descender assumed at every x: a superscript that reaches into
# an empty stretch of the lane above never moves its line (a writer puts H⁺
# under the gap between two words above without skipping a rule).
# Ink counts where its alpha reaches this; slack widens every written
# stroke sideways by this many x-heights, for the slant added later.
_MATH_INK_ALPHA = 64
_INK_SLACK_XH = 0.25
# At the top of a sheet nothing is written above: an equation may rise this
# many rule spacings above the first rule, into the paper's top band.
_TOP_BAND_RULES = 1.5
# An inline equation that misses the room above by a little is written this
# much smaller (tried in order) before its line is moved down a whole rule.
_INLINE_SHRINK = (0.95, 0.9)
# Ink reaching this fraction of a rule spacing past what a line of text
# fills (its own lane, plus an ordinary descender below the rule) takes the
# neighbouring lane: a fraction's denominator does, a subscript does not.
_LANE_TOL = 0.25

# Line ends on ruled paper (user's choice 2026-09-30): when the last few
# words of a paragraph miss the line, a writer squeezes them in — tighter
# word gaps, and on past the usual right edge up to this far (mm) from the
# paper's edge — instead of starting a line (or a page) for them.
_TAIL_ITEMS = 3        # words / inline equations, counting the one that missed
_TAIL_EDGE_MM = 6.0
_TAIL_GAP_FRAC = 0.6   # squeezed word gaps, as a fraction of the usual one
_A4_WIDTH_MM = 210.0

# A one-line paragraph that is a heading is never left alone on the last rule
# of a page (its body starting the next one): a problem number ("16.136"),
# a short title with no sentence punctuation ("Theory"), or a lead-in that
# ends in ":".
_PROBLEM_NUMBER = re.compile(r"\d+(\.\d+)*[a-z]?\.?")
_HEADING_MAX_CHARS = 40
# The text right before reserved figure space goes along with it only when
# it belongs to the figure: a label (no sentence punctuation), a caption
# starting with a figure word, or a lead-in pointing at what follows. A
# concluding sentence stays with what it concludes.
_CAPTION_START = re.compile(
    r"(fig(ure)?|table|graph|plot|chart|trial|photo|그림|표|그래프|사진|도표)\b|<",
    re.IGNORECASE)
_LEAD_IN = re.compile(r"(:|다음과\s*같다\.?|as follows\.?|below\.?)$|아래", re.IGNORECASE)


def _para_text(runs) -> str:
    """The paragraph's text, with a space where an inline equation stands."""
    return " ".join("".join(r.text if isinstance(r, TextRun) else " "
                            for r in runs).split())


# A leading enumerator ("(d) ", "1. ", "a) ") before a caption word.
_ENUMERATOR = re.compile(r"\(?[0-9A-Za-z]{1,3}[.)]\s+")


def _keeps_with_next(runs) -> bool:
    """A heading or lead-in that belongs on the same page as what follows."""
    text = _para_text(runs)
    if not text:
        return False
    if isinstance(runs[-1], TextRun) and runs[-1].text.rstrip().endswith(":"):
        return True  # a lead-in ("Experiments 1 and 2:"), not "base: <H2O>"
    if any(isinstance(r, MathBlock) for r in runs):
        return False
    if _PROBLEM_NUMBER.fullmatch(text):
        return True
    # a title: short, not a sentence, starts like one ("Theory", "실험 준비"),
    # and is neither a relation written out in text ("HOI < HOBr < HOCl")
    # nor a file name ("202_Capacitor_KOR")
    first = text[0]
    return (len(text) <= _HEADING_MAX_CHARS and text[-1] not in ".!?;,:"
            and (first.isupper() or first.isdigit() or "가" <= first <= "힣")
            and not any(c in "<>=+*/_" for c in text))


def _reads_as_caption(runs) -> bool:
    """The paragraph before a run of blank lines belongs to that space."""
    text = _para_text(runs)
    if not text or text[-1] not in ".!?":
        return True  # an equation, or a label that is not a sentence
    body = _ENUMERATOR.sub("", text, count=1) if _ENUMERATOR.match(text) else text
    return bool(_CAPTION_START.match(body) or _LEAD_IN.search(text))


def _glyph_columns(store: GlyphStore, char: str, idx: int, cache: dict):
    """Image columns holding a glyph variant's pen ink, with each column's
    lowest ink row (a descender's tail is only as wide as the tail). Cached."""
    key = (char, idx)
    cols = cache.get(key)
    if cols is None:
        v = store.entry(char).variants[idx]
        a = np.asarray(store.load_image(v).getchannel("A")) >= _KERN_INK_ALPHA
        xs = np.nonzero(a.any(axis=0))[0]
        cols = (xs, a.shape[0] - 1 - a[::-1].argmax(axis=0)[xs])
        cache[key] = cols
    return cols


def _math_columns(ink: MathInk, cache: dict):
    """Image columns holding ink, with each column's top and bottom ink row.
    Cached per equation image."""
    cols = cache.get(id(ink))
    if cols is None:
        a = np.asarray(ink.image.getchannel("A")) >= _MATH_INK_ALPHA
        xs = np.nonzero(a.any(axis=0))[0]
        tops = a.argmax(axis=0)[xs]
        bottoms = a.shape[0] - 1 - a[::-1].argmax(axis=0)[xs]
        cols = (xs, tops, bottoms)
        cache[id(ink)] = cols
    return cols


def _make_drift(rng: random.Random, style: HandwritingStyle, amp: float | None = None):
    """Smooth low-frequency baseline wander for one line.

    Two sinusoids (base period + a faster harmonic) with random phases; the
    weights keep the total amplitude within `amp` (defaults to
    style.baseline_drift_px; reduced while snapping to a ruled grid).
    """
    if amp is None:
        amp = style.baseline_drift_px
    phase_a = rng.uniform(0.0, TWO_PI)
    phase_b = rng.uniform(0.0, TWO_PI)
    period = style.baseline_drift_period_px

    def drift(x: float) -> float:
        return amp * (
            0.7 * math.sin(TWO_PI * x / period + phase_a)
            + 0.3 * math.sin(TWO_PI * x * 2.3 / period + phase_b)
        )

    return drift


# Lowercase letters whose ink spans exactly the x-height band (no ascender or
# descender) — used to measure the store's median x-height for spacing.
_X_HEIGHT_CHARS = "acemnorsuvwxz"


def _median_x_height(store: GlyphStore) -> float:
    """Median x-height (baseline row - ink top) over the store's x-band letters,
    in native glyph pixels. Spacing gaps are expressed as fractions of this so
    they scale with glyph size. Falls back to half the native size if none."""
    heights: list[float] = []
    for char in _X_HEIGHT_CHARS:
        if char in store and store.entry(char).variants:
            for v in store.entry(char).variants:
                heights.append(v.baseline_y - v.ink_bbox[1])
    if not heights:
        return 0.5 * store.native_size_px
    heights.sort()
    return heights[len(heights) // 2]


# Alpha at/above this is treated as solid pen ink when profiling glyph shape for
# kerning (faint kept residue sits well below this, so it can't widen a profile).
_KERN_INK_ALPHA = 128
# Stray side-blob filter: a horizontal run of ink columns that is both tiny in
# absolute pixels and tiny relative to the main body, and sits OUTSIDE the main
# body's column span, is neighbour-cell bleed / noise — not part of the glyph.
# Dropping it fixes ink extents. (A dot/bar tittle overlaps the stem's columns,
# so it merges into the main run and is always kept.)
_STRAY_ABS_MAX = 20   # px; runs larger than this are never dropped
_STRAY_FRAC = 0.10    # and only drop runs under this fraction of the main run
_COL_GAP_TOL = 2      # columns; bridge gaps this small so one body stays one run
# A column whose ink is only this tall is a lone horizontal streak of the printed
# baseline that survived removal (a dotted 1-px remnant at the baseline row), not a
# pen stroke (real strokes are thicker). Such columns are dropped before profiling
# so the residue can't stretch a glyph's ink extent and blow out kerning.
_RESIDUE_MAX_PX = 1


def _column_runs(occupied: np.ndarray):
    """Group occupied columns into runs, bridging gaps <= _COL_GAP_TOL."""
    runs = []
    start = None
    gap = 0
    for x, on in enumerate(occupied):
        if on:
            if start is None:
                start = x
            end = x
            gap = 0
        elif start is not None:
            gap += 1
            if gap > _COL_GAP_TOL:
                runs.append((start, end))
                start = None
    if start is not None:
        runs.append((start, end))
    return runs


def _ink_profile(store: GlyphStore, char: str, idx: int, cache: dict):
    """Per-row ink extent of a glyph variant, keyed by native-pixel offset from
    the baseline. Returns {u: (leftmost_col, rightmost_col)} where cols are in
    native px measured from the pen origin (left_bearing already folded in), and
    u = image_row - baseline_y. Small disconnected side-blobs (neighbour bleed)
    are dropped so they can't corrupt extents. Cached per (char, variant)."""
    key = (char, idx)
    prof = cache.get(key)
    if prof is not None:
        return prof
    v = store.entry(char).variants[idx]
    alpha = np.asarray(store.load_image(v).getchannel("A"))
    solid = alpha >= _KERN_INK_ALPHA
    col_px = solid.sum(axis=0)
    # Drop lone 1-px-tall columns (dotted printed-baseline residue) so they can't
    # extend the ink profile; real strokes keep at least _RESIDUE_MAX_PX+1 rows.
    residue = (col_px > 0) & (col_px <= _RESIDUE_MAX_PX)
    if residue.any():
        solid[:, residue] = False
        col_px = solid.sum(axis=0)
    runs = _column_runs(col_px > 0)
    if runs:
        weights = [(int(col_px[a : b + 1].sum()), a, b) for a, b in runs]
        main_px = max(w for w, _, _ in weights)
        keep = np.zeros(solid.shape[1], dtype=bool)
        for w, a, b in weights:
            if w == main_px or not (w < _STRAY_ABS_MAX and w < _STRAY_FRAC * main_px):
                keep[a : b + 1] = True
        solid &= keep  # broadcast over rows
    lb = v.left_bearing
    by = v.baseline_y
    prof = {}
    for r in range(solid.shape[0]):
        cols = np.nonzero(solid[r])[0]
        if cols.size:
            prof[r - by] = (lb + int(cols[0]), lb + int(cols[-1]))
    cache[key] = prof
    return prof


def _kern_native(store: GlyphStore, prev_key, cur_key, cache) -> float:
    """Closest-approach offset (native px) to place cur just right of prev with
    zero ink gap: for every baseline-aligned row both occupy, cur's leftmost ink
    must clear prev's rightmost ink. Returns max over shared rows of
    (prev_right - cur_left); falls back to bbox extremes if they never share a
    row (e.g. a high tick beside a low comma)."""
    prev = _ink_profile(store, prev_key[0], prev_key[1], cache)
    cur = _ink_profile(store, cur_key[0], cur_key[1], cache)
    shared = prev.keys() & cur.keys()
    if shared:
        return max(prev[u][1] - cur[u][0] for u in shared)
    return max(r for _, r in prev.values()) - min(l for l, _ in cur.values())


# Symbol spacing. Uniform letter-letter gaps are wrong for symbols: real
# writers give math operators clear side room (x*y written tight reads as a
# scribble), give brackets air against their content ("(3)" written hugged
# reads as one scribbled glyph), and don't treat a spaced operator ("I / k")
# as a full word break. Trailing punctuation (period/comma/colon) needs a
# CLEAR positive gap — closest-approach kerning otherwise tucks it against
# the previous letter until it disappears ("Step 5." read as "Step 5").
# Quotes/apostrophes are deliberately NOT widened so contractions ("don't")
# stay snug.
_OP_CHARS = set("*+=-/<>&·×÷")
_WIDE_OPS = set("-·×÷")
_BRACKET_CHARS = set("()[]")
_TRAIL_PUNCT = set(".,;:!?")


# Punctuation that attaches to the inline equation before it (layout glue).
_GLUE_PUNCT = set(",.;:!?)]}")
# Multiplier on the intra-word gap for punctuation that follows an equation
# ending in a subscript (see punct_after_sub in layout_paragraph).
_PUNCT_AFTER_SUBSCRIPT = 3.0


def _pair_gap_scale(prev: str, cur: str, scale: float) -> float:
    """Multiplier on the intra-word gap for one adjacent glyph pair."""
    if prev in _WIDE_OPS or cur in _WIDE_OPS:
        # Hyphen and multiplication marks: widest air — kerned tight the
        # hyphen overstrikes its neighbour ("high-voltage" with the dash
        # through the v) and the dot in "Pa·s" merges into the a's tail.
        return 1.5 * scale
    if prev in _OP_CHARS or cur in _OP_CHARS:
        return scale
    if prev in _BRACKET_CHARS and cur in _TRAIL_PUNCT:
        return 1.2 * scale  # "(3)," — comma must clear the paren's curve
    if (prev in _BRACKET_CHARS and cur.isalnum()) or (
        cur in _BRACKET_CHARS and prev.isalnum()
    ):
        # digits included: "(1)" hugged reads as "0". 1.2 (Millikan round)
        # still read cramped to the user on "(1)"/"(5)" — raised 2026-08-14.
        return 2.0 * scale
    if prev in _TRAIL_PUNCT or cur in _TRAIL_PUNCT:
        return 1.75 * scale
    return 1.0


# Unicode superscript characters, drawn as a shrunken, raised copy of the
# mapped base glyph (kg/m³ etc. in body text; the math mode has its own
# typesetting). Kerning profiles don't apply across a scale change, so
# superscripts chain bounding-box-to-bounding-box instead.
_SUPERSCRIPTS = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁻": "-",
}
_SUP_SCALE = 0.6         # superscript glyph scale relative to body glyphs
_SUP_RAISE_XH = 0.55     # raised by this many x-heights above the baseline


def pick_variant(
    rng: random.Random, n_variants: int, last: int | None, mode: str
) -> int:
    """Choose a glyph variant index; no_immediate_repeat avoids the same variant
    twice in a row for one character. Owned by layout because ink-extent spacing
    needs the chosen variant's actual ink bounds at placement time."""
    if n_variants <= 1:
        return 0
    if mode == "no_immediate_repeat" and last is not None:
        choice = rng.randrange(n_variants - 1)
        return choice if choice < last else choice + 1
    return rng.randrange(n_variants)


def layout_document(
    document: Document,
    store: GlyphStore,
    style: HandwritingStyle,
    page: PageSpec = PageSpec(),
    seed: int = 0,
    grid: LineGrid | None = None,
) -> list[PageLayout]:
    rng = random.Random(seed)
    snapping = grid is not None

    if snapping:
        # Snap baselines to the paper's rules. Cap height is limited so
        # adjacent lines can't collide, and the drift is dialed down since the
        # rule now dominates each line's vertical position.
        # Size by x-height so the lowercase body fills a sensible share of the lane;
        # ascenders/descenders are then free to overshoot into adjacent lanes like
        # real writing, instead of being crushed to fit the cap frame in the lane.
        xh_native = _median_x_height(store)
        xh_scale = (_SNAP_XHEIGHT_FRAC * grid.spacing_px) / xh_native
        base_size = min(xh_scale * store.native_size_px,
                        grid.spacing_px * _SNAP_MAX_CAP_FRAC)
        drift_amp = style.baseline_drift_px * style.snap_drift_scale
        left = (
            float(grid.margin_x_px + _SNAP_MARGIN_PAD)
            if grid.margin_x_px is not None
            else float(page.margin_px)
        )
    else:
        base_size = style.base_size_px
        drift_amp = style.baseline_drift_px
        left = float(page.margin_px)

    scale = base_size / store.native_size_px
    line_step = grid.spacing_px if snapping else style.line_height * style.base_size_px
    # An equation image is drawn at its own cap height; scale it so its cap
    # equals the body letters' cap on this page (store cap ink x page scale).
    cap_px = measure_cap_ink(store) * scale
    normal_asc = _TEXT_ASCENT_CAPS * cap_px
    normal_desc = _TEXT_DESCENT_FRAC * base_size
    room_above = line_step - normal_desc - _MATH_PAD_CAPS * cap_px
    room_below = line_step - normal_asc - _MATH_PAD_CAPS * cap_px
    right = float(page.width_px - page.margin_px)
    # A baseline fits if the line's descenders still clear the bottom margin.
    bottom = float(page.height_px - page.margin_px)
    # Ruled paper ends at its last printed rule, not at the plain-page margin
    # (that margin stranded the rules printed inside it). Descenders hang
    # below that rule but stay on the sheet.
    hard_bottom = snapping and grid.last_rule_px is not None
    if hard_bottom:
        bottom = min(grid.last_rule_px + 0.5 * grid.spacing_px + 0.35 * base_size,
                     float(page.height_px))
    max_baseline = bottom - 0.35 * base_size
    fallback_advance = 0.6 * base_size  # for chars missing from the store

    # Ink-extent spacing gaps, in page pixels (fractions of the median x-height so
    # they track glyph size). Variant selection lives here now so word placement
    # and wrapping use each glyph's real ink bounds.
    x_height_px = _median_x_height(store) * scale
    intra_gap_mean = style.intra_word_gap_frac * x_height_px
    intra_gap_jit = style.intra_word_gap_jitter_frac * x_height_px
    word_gap_mean = style.word_gap_frac * x_height_px
    word_gap_jit = style.word_gap_jitter_frac * x_height_px
    last_variant: dict[str, int] = {}

    pages = [PageLayout(spec=page)]
    line_index = 0
    unknown: set[str] = set()

    # Ruled paper: the lowest ink written so far on this sheet, per page
    # column — all ink (floor_all) and equation ink alone (floor_eq). Tall
    # equations clear floor_all; words clear only floor_eq (text lines are
    # spaced to clear each other, an inline fraction's denominator is not).
    math_cols: dict = {}
    glyph_cols: dict = {}
    if snapping:
        # Imported here: renderer imports this module.
        from .renderer import _TRUST_GUIDE_MIN_XH, _store_x_height
        store_xh = _store_x_height(store)
        # Pad = the old collision pad plus the per-word height walk the
        # variation engine adds later (two neighbouring words, opposite ways).
        ink_pad = (_MATH_PAD_CAPS * cap_px
                   + 2.0 * style.word_drift_px * style.snap_drift_scale)
        ink_slack = max(1, round(_INK_SLACK_XH * x_height_px))
        top_limit = max(grid.offset_px - _TOP_BAND_RULES * grid.spacing_px,
                        0.2 * grid.offset_px)
        floor_all = np.full(page.width_px, top_limit)
        floor_eq = np.full(page.width_px, -np.inf)
        # A display equation is set off from prose by this many blank rules
        # (display_math_gap rounded up to whole rules: any air asked for is at
        # least one) and at least half that gap of white ink-to-ink;
        # consecutive display equations (the steps of one derivation) follow
        # each other on the next free rule.
        set_off = math.ceil(style.display_math_gap * base_size / grid.spacing_px
                            - 1e-6)
        display_air = 0.5 * style.display_math_gap * base_size
    eq_above = False  # floor_eq holds any equation ink on this sheet
    lane_above = False  # the line just finished wrote something (not blank)
    # The last line written on this sheet: (kind "text" / "display", its
    # rule, its lowest ink y, its baseline y); None at the top of a sheet.
    last_line = None
    line_is_display = False  # the line being written holds a display equation

    def glyph_box(char: str, idx: int, x: float, y: float, s: float):
        """Ink box (x0, x1, top, bottom) of a glyph at pen point (x, y) and
        scale s, seated the way renderer.render_page seats it."""
        v = store.entry(char).variants[idx]
        below = v.ink_bbox[3] - v.baseline_y
        depth = metrics.depth_in_x_heights(char)
        if depth is None or below > _TRUST_GUIDE_MIN_XH * store_xh:
            bot = y + below * s
        else:
            bot = y + depth * store_xh * s
        return (x + (v.left_bearing + v.ink_bbox[0]) * s,
                x + (v.left_bearing + v.ink_bbox[2]) * s,
                bot - (v.ink_bbox[3] - v.ink_bbox[1]) * s, bot)

    def math_span(ink: MathInk, x: float, y: float, s: float):
        """Page columns of an equation drawn at (x, y) with scale s, and the
        top and bottom y of its ink in each."""
        xs, tops, bots = _math_columns(ink, math_cols)
        px = np.round(x + (xs + 0.5) * s).astype(int)
        return (px, y + (tops - ink.baseline_y) * s,
                y + (bots + 1 - ink.baseline_y) * s)

    def fold_line() -> None:
        """Add the ink of the line just finished to the sheet's floors."""
        nonlocal eq_above, last_line, line_is_display, lane_above
        w = page.width_px
        low = -math.inf

        def raise_floor(floor, px, bots):
            for d in range(-ink_slack, ink_slack + 1):
                np.maximum.at(floor, np.clip(px + d, 0, w - 1), bots)

        for g in pages[-1].glyphs[line_start[0]:]:
            v = store.entry(g.char).variants[g.variant]
            xs, rows = _glyph_columns(store, g.char, g.variant, glyph_cols)
            # rows are image rows; glyph_box gives where the ink bottom
            # (image row ink_bbox[3]) lands on the page
            bot = glyph_box(g.char, g.variant, g.x, g.y, g.scale)[3]
            raise_floor(floor_all,
                        np.round(g.x + (v.left_bearing + xs + 0.5) * g.scale).astype(int),
                        bot - (v.ink_bbox[3] - rows - 1) * g.scale)
            low = max(low, bot)
        for m in pages[-1].maths[line_start[1]:]:
            px, _, bots = math_span(m.ink, m.x, m.y, m.scale)
            raise_floor(floor_all, px, bots)
            raise_floor(floor_eq, px, bots)
            eq_above = eq_above or len(px) > 0
            if len(bots):
                low = max(low, float(bots.max()))
        if low > -math.inf:
            last_line = ("display" if line_is_display else "text", line_index,
                         low, baseline)
        lane_above = low > -math.inf
        line_is_display = False

    def reset_floors() -> None:
        nonlocal eq_above, last_line, lane_above
        floor_all[:] = top_limit
        floor_eq[:] = -np.inf
        eq_above = False
        lane_above = False
        last_line = None

    def whole(need: float) -> float:
        """A downward push: nothing if need <= 0, whole rules when snapping."""
        if need <= 0:
            return 0.0
        if snapping:
            # (the epsilon keeps an exact whole-rule need from rounding up)
            need = math.ceil(need / grid.spacing_px - 1e-6) * grid.spacing_px
        return need

    def wobble() -> float:
        return (
            rng.uniform(-style.snap_wobble_px, style.snap_wobble_px)
            if snapping else 0.0
        )

    # Page rhythm (all zero-knob inert, and all OFF while snapping — on ruled
    # paper the writer aligns to the printed lines):
    # - rise_slope: this line climbs to the right by a random fraction of
    #   line_rise_px over the text width (one-directional: never downward)
    # - line_left: the left margin wanders down the page (bounded walk)
    # - the baseline step varies per line by line_step_jitter_frac
    rise_slope = 0.0
    line_left = left
    margin_off = 0.0
    usable_w = max(1.0, right - left)

    def new_rhythm() -> None:
        nonlocal rise_slope, line_left, margin_off
        if snapping:
            return
        if style.line_rise_px > 0:
            rise_slope = rng.uniform(0.35, 1.0) * style.line_rise_px / usable_w
        if style.margin_drift_px > 0:
            amp = style.margin_drift_px
            margin_off += rng.gauss(0.0, 0.45 * amp) - 0.25 * margin_off
            margin_off = max(-amp, min(amp, margin_off))
            line_left = left + margin_off

    def line_advance() -> float:
        if style.line_step_jitter_frac > 0:
            return line_step * (1.0 + rng.uniform(
                -style.line_step_jitter_frac, style.line_step_jitter_frac))
        return line_step

    if snapping:
        baseline = grid.offset_px + wobble()
        drift = _make_drift(rng, style, drift_amp)
    else:
        baseline = page.margin_px + style.base_size_px
        drift = _make_drift(rng, style)
    new_rhythm()

    # Tall-equation bookkeeping for the current line: how far its baseline was
    # already pushed down (line_lift), how far its content reaches below the
    # normal descent (line_extra_below: the next line steps that much further),
    # and where this line's records start in the page lists (so a lift can
    # move what is already placed on it).
    line_lift = 0.0
    line_extra_below = 0.0
    line_start = [0, 0]
    # How far the first line of the paragraph being written was pushed down
    # (None until that line ends): moved to a fresh page, where nothing is
    # above it, the paragraph drops that push again.
    first_lift = None

    def mark_line_start() -> None:
        nonlocal line_lift, line_extra_below, first_lift
        if first_lift is None:
            first_lift = line_lift
        line_lift = 0.0
        line_extra_below = 0.0
        line_start[0] = len(pages[-1].glyphs)
        line_start[1] = len(pages[-1].maths)

    # Mirroring Word's pages (style.word_pages): a Word page ended inside the
    # line being written, so the page ends when that line does.
    page_end_pending = False
    line_count = 0  # lines started so far (how many a paragraph took)

    def new_line() -> None:
        nonlocal baseline, drift, line_index, page_end_pending, line_count
        line_count += 1
        if page_end_pending:
            page_end_pending = False
            new_page()
            return
        if snapping:
            fold_line()
            line_index += 1 + math.ceil(line_extra_below / grid.spacing_px)
            base_y = grid.offset_px + line_index * grid.spacing_px
            if base_y > max_baseline:
                pages.append(PageLayout(spec=page))
                reset_floors()
                line_index = 0
                base_y = grid.offset_px
            baseline = base_y + wobble()
            drift = _make_drift(rng, style, drift_amp)
        else:
            baseline += line_advance() + line_extra_below
            if baseline > max_baseline:
                pages.append(PageLayout(spec=page))
                baseline = page.margin_px + style.base_size_px
            drift = _make_drift(rng, style)
        mark_line_start()
        new_rhythm()

    def new_page() -> None:
        nonlocal baseline, drift, line_index
        pages.append(PageLayout(spec=page))
        line_index = 0
        if snapping:
            reset_floors()
            baseline = grid.offset_px + wobble()
            drift = _make_drift(rng, style, drift_amp)
        else:
            baseline = page.margin_px + style.base_size_px
            drift = _make_drift(rng, style)
        mark_line_start()
        new_rhythm()

    # Reserved space (a run of blank paragraphs, usually under a one-line
    # caption, left for a figure) is kept whole rather than split by a page end.
    top_baseline = (grid.offset_px if snapping
                    else float(page.margin_px + style.base_size_px))
    lines_per_page = int((max_baseline - top_baseline) // line_step) + 1

    def lines_left() -> int:
        """Whole lines from the current one down to the foot of the page."""
        here = (grid.offset_px + line_index * grid.spacing_px if snapping
                else baseline)
        return int((max_baseline - here) // line_step) + 1

    def carry_over(g0: int, m0: int, baseline0: float, lines: int) -> None:
        """Move the short paragraph that ends the previous page (its records
        from g0/m0 on, first baseline baseline0) to the top of this fresh one."""
        src = pages[-2]
        moved = src.glyphs[g0:] + src.maths[m0:]
        for rec in moved:
            rec.y += baseline - baseline0
        pages[-1].glyphs.extend(src.glyphs[g0:])
        pages[-1].maths.extend(src.maths[m0:])
        del src.glyphs[g0:]
        del src.maths[m0:]
        for _ in range(lines):
            new_line()

    def keep_space_whole(n: int, caption) -> None:
        """Called at the first of `n` blank paragraphs. `caption` describes the
        paragraph just written — (g0, m0, baseline0, lines, turned, reads as
        a caption) — or None if it crossed a page."""
        short = (caption is not None and caption[3] <= 2
                 and (caption[5] or not snapping)
                 and (caption[0] or caption[1])
                 and caption[3] + n <= lines_per_page)
        if caption is not None and caption[4]:
            # The caption took the last line and the page has already turned.
            if short:
                carry_over(*caption[:4])
        elif n > lines_left():
            if short:
                new_page()
                carry_over(*caption[:4])
            elif n <= lines_per_page and (pages[-1].glyphs or pages[-1].maths):
                new_page()

    def ink_need(px, tops, floor) -> float:
        """How far ink with these per-column tops must drop to clear `floor`."""
        if not len(px):
            return 0.0
        idx = np.clip(px, 0, page.width_px - 1)
        return float((floor[idx] + ink_pad - tops).max())

    def push_for(ascent: float, tops=None) -> float:
        """How far the current line must drop so `ascent` px above its baseline
        clear the line above (whole rules when snapping). On ruled paper,
        `tops` = (page columns, ink top y relative to the baseline) measures
        that against the ink really written above instead."""
        if snapping and tops is not None:
            need = ink_need(tops[0], baseline + tops[1], floor_all)
            if ascent > line_step - ink_pad and lane_above:
                # Taller than a whole lane: it would stand in the line above
                # between its words, so it clears that line everywhere (an
                # empty lane above — a blank line — is room enough).
                need = max(need, ascent - room_above - line_lift)
            return whole(need)
        return whole(ascent - room_above - line_lift)

    def word_push(boxes) -> float:
        """Ruled paper: how far the line must drop so a word's glyphs (x0, x1,
        top y relative to the baseline) clear the equation ink above."""
        need = 0.0
        for x0, x1, top in boxes:
            a = max(0, math.floor(x0))
            b = min(page.width_px, math.ceil(x1) + 1)
            if a < b:
                need = max(need, float(floor_eq[a:b].max()) + ink_pad
                           - (baseline + top))
        return whole(need)

    def display_push(px, tops, air: bool) -> float:
        """Ruled paper: how far a display equation (columns px, ink tops
        relative to the baseline) must drop — clear of the ink above, and,
        with air, set off from the prose line above it."""
        need = ink_need(px, baseline + tops, floor_all)
        if last_line is not None and last_line[0] == "display" and len(tops):
            # the next step of a derivation starts below the whole line
            # above: tucked into its gaps, a numerator reads as a subscript
            need = max(need, last_line[2] + ink_pad - (baseline + float(tops.min())))
        if air and last_line is not None and last_line[0] == "text" and len(tops):
            # blank rules counted between the lanes both sides' ink fills
            first = (last_line[1] + 1 + lanes_below(last_line) + set_off
                     + lanes_above(-float(tops.min())))
            need = max(need,
                       (first - line_index) * grid.spacing_px,
                       last_line[2] + display_air - (baseline + float(tops.min())))
        return whole(need)

    def lanes_below(line) -> int:
        """Lanes under a written line's rule that its ink fills beyond an
        ordinary descender (a fraction's denominator: 1)."""
        return max(0, math.ceil((line[2] - line[3] - normal_desc
                                 - _LANE_TOL * grid.spacing_px) / grid.spacing_px))

    def lanes_above(ascent: float) -> int:
        """Lanes above its own that an equation's ink rises into."""
        return max(0, math.ceil((ascent - (1 + _LANE_TOL) * grid.spacing_px)
                                / grid.spacing_px))

    def place_display(ink: MathInk, x: float, s: float) -> None:
        """Ruled paper: move to the rule a display equation is written on.
        At the foot of a page its air goes before the page is turned."""
        px, tops, bots = math_span(ink, x, 0.0, s)
        low = float(bots.max()) if len(bots) else 0.0

        def fits(push: float) -> bool:
            return (baseline + push <= max_baseline
                    and baseline + push + low <= bottom)

        air = True
        if not fits(display_push(px, tops, True)):
            if fits(display_push(px, tops, False)):
                air = False
            else:
                new_page()
        drop_line(lambda: display_push(px, tops, air))

    def settle_after_display() -> None:
        """Ruled paper: the first thing on a line right after a display
        equation leaves the blank rule(s) and air the equation is owed (an
        author's blank line already there counts toward them)."""
        def push() -> float:
            if last_line is None or last_line[0] != "display":
                return 0.0  # (also on the fresh page a move may open)
            first = last_line[1] + 1 + lanes_below(last_line) + set_off
            return whole(max(
                (first - line_index) * grid.spacing_px,
                last_line[2] + display_air - (baseline - normal_asc)))

        drop_line(push)

    def make_room_above(ascent: float, force: bool = False, tops=None) -> None:
        """Push the current line down so `ascent` px above its baseline still
        clear the line above; whatever is already on the line moves with it.
        Text-sized content never pushes (unless force: display equations)."""
        if ascent <= normal_asc and not force:
            return
        drop_line(lambda: push_for(ascent, tops))

    def drop_line(push) -> None:
        """Move the current line down by push() (asked again if the line has
        to go to a fresh page); whatever is already on it moves along."""
        nonlocal baseline, line_lift, line_index, drift, line_extra_below
        need = push()
        if need <= 0:
            return
        if (snapping and baseline + need > max_baseline
                and (line_start[0] or line_start[1])):
            # Ruled paper has nothing to write on past its last rule: the line
            # moves to the next page whole, keeping its own drift and depth.
            moved_g = pages[-1].glyphs[line_start[0]:]
            moved_m = pages[-1].maths[line_start[1]:]
            del pages[-1].glyphs[line_start[0]:]
            del pages[-1].maths[line_start[1]:]
            old_baseline, old_drift, old_below = baseline, drift, line_extra_below
            new_page()
            drift, line_extra_below = old_drift, old_below
            for rec in moved_g + moved_m:
                rec.y += baseline - old_baseline
            pages[-1].glyphs.extend(moved_g)
            pages[-1].maths.extend(moved_m)
            need = push()
        if snapping:
            line_index += round(need / grid.spacing_px)
        for g in pages[-1].glyphs[line_start[0]:]:
            g.y += need
        for m in pages[-1].maths[line_start[1]:]:
            m.y += need
        baseline += need
        line_lift += need

    profile_cache: dict = {}

    def intra_gap() -> float:
        return intra_gap_mean + rng.uniform(-intra_gap_jit, intra_gap_jit)

    def plan_word(word: str):
        """Pack a word by per-row kerning: each letter is slid left until its ink
        just clears the previous letter's ink (plus a small intra_word gap), so
        crossbars/tails (f, t, j, r) nest instead of forcing a bounding-box gap.
        Selects each glyph's variant once so measurement and placement agree.

        Returns (glyphs, ink_left, ink_right, extent) with x's relative to the
        word origin (0): glyphs = [(char, variant, rel_x, glyph_scale, dy)] for
        drawable letters (glyph_scale multiplies the page scale, dy is a
        vertical offset in page px — both non-neutral only for superscripts);
        ink_left/ink_right = leftmost/rightmost ink x (for chaining the word
        gap); extent = furthest pen advance (for wrapping and column bounds).
        """
        glyphs: list[tuple[str, int, float, float, float, bool]] = []
        ink_left = math.inf
        ink_right = -math.inf
        extent = 0.0
        prev_key: tuple[str, int] | None = None
        prev_char: str | None = None
        prev_gx = 0.0
        for char in word:
            sup = char in _SUPERSCRIPTS
            char = _SUPERSCRIPTS.get(char, char)
            gscale = _SUP_SCALE if sup else 1.0
            dy = -_SUP_RAISE_XH * x_height_px if sup else 0.0
            if char not in store or not store.entry(char).variants:
                unknown.add(char)
                base = 0.0 if ink_right == -math.inf else ink_right + intra_gap()
                ink_left = min(ink_left, base)
                ink_right = max(ink_right, base + fallback_advance)
                extent = max(extent, base + fallback_advance)
                prev_key = None  # no shape to kern the next letter against
                prev_char = char
                continue
            entry = store.entry(char)
            idx = pick_variant(
                rng, len(entry.variants), last_variant.get(char), style.variant_selection
            )
            last_variant[char] = idx
            v = entry.variants[idx]
            cur_key = (char, idx)
            prof = _ink_profile(store, char, idx, profile_cache)
            if prof:  # extents from the stray-filtered ink, in native px from pen
                left_col = min(l for l, _ in prof.values())
                right_col = max(r for _, r in prof.values())
            else:  # all-faint fallback: use stored bbox
                left_col = v.left_bearing + v.ink_bbox[0]
                right_col = v.left_bearing + v.ink_bbox[2]
            left_off = left_col * scale * gscale
            right_off = right_col * scale * gscale
            pair_scale = (
                _pair_gap_scale(prev_char, char, style.symbol_gap_scale)
                if prev_char is not None
                else 1.0
            )
            if prev_key is None and ink_right == -math.inf:
                gx = 0.0  # first letter: pen origin at the word origin
            elif prev_key is None or sup:
                # bbox chaining: after a skipped char, or into a superscript
                # (row-kern profiles don't line up across a scale change)
                gx = ink_right + intra_gap() * pair_scale - left_off
            else:
                kern = _kern_native(store, prev_key, cur_key, profile_cache) * scale
                gx = prev_gx + kern + intra_gap() * pair_scale
            glyphs.append((char, idx, gx, gscale, dy, sup))
            ink_left = min(ink_left, gx + left_off)
            ink_right = max(ink_right, gx + right_off)
            extent = max(extent, gx + v.advance_width * scale * gscale)
            # a superscript's shrunken profile can't kern the next letter either
            prev_key = None if sup else cur_key
            prev_char = char
            prev_gx = gx
        # Shift so nothing sits left of the word origin (nesting can pull a letter
        # left of the first); keeps every glyph inside the left margin.
        shift = -min((gx for _, _, gx, _, _, _ in glyphs), default=0.0)
        if shift > 0:
            glyphs = [(c, i, gx + shift, gs, dy, sp)
                      for c, i, gx, gs, dy, sp in glyphs]
            ink_left += shift
            ink_right += shift
            extent += shift
        if ink_left == math.inf:
            ink_left = 0.0
        if ink_right == -math.inf:
            ink_right = 0.0
        return glyphs, ink_left, ink_right, extent

    # Word gaps never shrink below this multiple of the largest possible intra-word
    # gap, even at the low end of the word-gap jitter, so words always separate
    # clearly from letter spacing (readability floor, applied after jitter).
    _WORD_GAP_FLOOR_RATIO = 2.5
    word_gap_floor = _WORD_GAP_FLOOR_RATIO * (intra_gap_mean + intra_gap_jit)
    word_index = 0
    # A squeezed paragraph tail may end at tail_right; its word gaps shrink
    # to squeeze_gap — still a visible word space (at the floor, "more easily"
    # read as one word). tail_gap bounds every gap it can get, glued
    # punctuation included.
    tail_right = page.width_px * (1.0 - _TAIL_EDGE_MM / _A4_WIDTH_MM)
    squeeze_gap = max(word_gap_floor, _TAIL_GAP_FRAC * word_gap_mean)
    tail_gap = max(squeeze_gap,
                   _PUNCT_AFTER_SUBSCRIPT * (intra_gap_mean + intra_gap_jit))

    def layout_paragraph(runs) -> None:
        nonlocal word_index, line_extra_below, page_end_pending, line_is_display
        line_ink_right: float | None = None  # page x of rightmost ink on the line
        line_empty = True
        prev_word_sym = False  # previous word was a bare operator ("/", "=", "-")
        line_broken = False    # a display equation just ended the line
        after_math = False     # an inline equation was the last thing placed
        after_math_tight = False  # ... and Word left no space after it
        after_math_sub = False    # ... and its rightmost ink was a subscript
        # Ruled paper: the paragraph's words and inline equations in order;
        # None marks a display equation (or a mirrored Word page end), which
        # ends the line anyway, so a squeezed tail never reaches past it.
        seq: list = []
        if snapping:
            for ri, run in enumerate(runs):
                if isinstance(run, TextRun):
                    seq += [(ri, wi) for wi, wd in enumerate(run.text.split(" "))
                            if wd]
                elif isinstance(run, MathBlock) and run.ink is not None:
                    seq.append(None if run.display else (ri, None))
                elif isinstance(run, WordPageBreak) and style.word_pages:
                    seq.append(None)
        seq_pos = {item: n for n, item in enumerate(seq) if item is not None}
        tail_plans: dict = {}  # plans of the words in a squeezed tail
        squeezing = False      # the rest of this line's tail is squeezed in

        def tail_fits(item, end_x: float) -> bool:
            """Ruled paper: `item` missed the line, its ink would end at end_x
            written with the tightest gap. Does the rest of the paragraph (at
            most _TAIL_ITEMS items with this one) end by tail_right written
            the same way? Its words are planned only for keeps: on a no the
            random stream and variant memory are put back untouched."""
            n = seq_pos[item] + 1
            rest = []
            while n < len(seq) and seq[n] is not None:
                rest.append(seq[n])
                n += 1
            if len(rest) + 1 > _TAIL_ITEMS or end_x > tail_right:
                return False
            state, variants = rng.getstate(), dict(last_variant)
            plans, x = {}, end_x
            for ri, wi in rest:
                if wi is None:
                    eq = runs[ri].ink
                    x += tail_gap + eq.image.width * cap_px / eq.cap_px
                else:
                    plans[(ri, wi)] = plan = plan_word(runs[ri].text.split(" ")[wi])
                    x += tail_gap + plan[2] - plan[1]
            if x <= tail_right:
                tail_plans.update(plans)
                return True
            rng.setstate(state)
            last_variant.clear()
            last_variant.update(variants)
            return False

        for ri, run in enumerate(runs):
            if isinstance(run, WordPageBreak):
                # Word's page ended here. The line being written is finished
                # first, like a writer would; an empty line just moves over.
                squeezing = False  # a squeezed tail ends here
                if style.word_pages:
                    if not line_empty:
                        page_end_pending = True
                    elif pages[-1].glyphs or pages[-1].maths:
                        new_page()
                continue
            if isinstance(run, MathBlock):
                ink = run.ink
                if ink is None:
                    continue  # not rendered (mathrender warned)
                mscale = cap_px / ink.cap_px
                if run.display:
                    # Its own line, justified in the column as Word set it
                    # (centred by default); a too-wide equation shrinks to
                    # the column width.
                    if not line_empty:
                        new_line()
                    mscale = min(mscale, usable_w / ink.image.width)
                    w = ink.image.width * mscale
                    # A display equation is set off from the prose with extra
                    # air on both sides (style.display_math_gap), on top of the
                    # collision clearance.
                    gap = style.display_math_gap * base_size
                    asc = ink.ascent * mscale + gap
                    desc = ink.descent * mscale + gap
                    if snapping:
                        # Ruled paper: whole blank rules against the prose,
                        # the next free rule after another display equation
                        # (place_display / settle_after_display).
                        x = line_left + {"left": 0.0, "right": usable_w - w}.get(
                            run.align, (usable_w - w) / 2)
                        place_display(ink, x, mscale)
                        line_is_display = True
                    else:
                        if baseline + push_for(asc) + desc > bottom:
                            new_page()
                        make_room_above(asc, force=True)
                        x = line_left + {"left": 0.0, "right": usable_w - w}.get(
                            run.align, (usable_w - w) / 2)
                    pages[-1].maths.append(PlacedMath(
                        ink=ink, x=x, y=baseline, scale=mscale, word=word_index))
                    word_index += 1
                    if not snapping:
                        line_extra_below = max(line_extra_below, desc - room_below)
                    new_line()
                    line_ink_right = None
                    line_empty = True
                    prev_word_sym = False
                    line_broken = True
                    after_math = False
                    squeezing = False
                    continue
                # Inline: flows like a word.
                w = ink.image.width * mscale
                asc = ink.ascent * mscale
                desc = ink.descent * mscale
                # No space before it in Word ("kg/m" + "³"): the equation
                # continues the word, so kern it ink-to-ink like a letter
                # instead of opening a word gap.
                tight = run.tight_left and not line_empty
                mink_left, mink_right = (b * mscale for b in ink.ink_bounds)
                if line_empty:
                    origin = line_left
                elif tight:
                    origin = line_ink_right + intra_gap() - mink_left
                else:
                    gap = max(
                        word_gap_mean + rng.uniform(-word_gap_jit, word_gap_jit),
                        word_gap_floor,
                    )
                    origin = line_ink_right + gap
                    if squeezing:
                        origin = line_ink_right + min(gap, squeeze_gap)
                # Ruled paper: judged by where the ink ends, not the image.
                over = origin + (mink_right if snapping else w) > right
                if not line_empty and over and not tight and not squeezing:
                    tight_origin = line_ink_right + squeeze_gap
                    if snapping and tail_fits((ri, None), tight_origin + mink_right):
                        squeezing = True
                        origin = tight_origin
                    else:
                        new_line()
                        origin = line_left
                if snapping:
                    if line_empty:
                        settle_after_display()
                    px, tops, _ = math_span(ink, origin, drift(origin), mscale)
                    if asc > normal_asc and push_for(asc, (px, tops)) > 0:
                        # A writer short of room by a hair writes the formula
                        # a little smaller rather than skip a whole rule.
                        for f in _INLINE_SHRINK:
                            px2, tops2, _ = math_span(ink, origin, drift(origin),
                                                      mscale * f)
                            if push_for(asc * f, (px2, tops2)) == 0:
                                mscale *= f
                                w, asc, desc = w * f, asc * f, desc * f
                                mink_right *= f
                                px, tops = px2, tops2
                                break
                    make_room_above(asc, tops=(px, tops))
                    if eq_above and asc <= normal_asc:
                        # Text-height: clears equation ink hanging from the
                        # line above (a deep denominator) the way words do.
                        drop_line(lambda: whole(
                            ink_need(px, baseline + tops, floor_eq)))
                else:
                    make_room_above(asc)
                pages[-1].maths.append(PlacedMath(
                    ink=ink, x=origin,
                    y=baseline + drift(origin) - rise_slope * (origin - line_left),
                    scale=mscale, word=word_index))
                word_index += 1
                # On ruled paper the next line clears this one's real ink
                # itself (word_push / push_for), so nothing is reserved here.
                if desc > normal_desc and not snapping:
                    line_extra_below = max(line_extra_below, desc - room_below)
                line_ink_right = origin + (mink_right if tight else w)
                line_empty = False
                prev_word_sym = False
                line_broken = False
                after_math = True
                after_math_tight = run.tight_right
                after_math_sub = ink.ends_subscript
                continue
            assert isinstance(run, TextRun)
            for wi, word in enumerate(run.text.split(" ")):
                if not word:
                    continue
                # Text written right after an inline equation belongs to it —
                # either because Word left no space ("Pa" + "·" + "s") or
                # because it is trailing punctuation ("f(x),", ")." …), which
                # the stripped run edges can no longer show. No word gap, and
                # pure punctuation never wraps onto a line of its own.
                glued = (after_math and wi == 0 and not line_empty
                         and (after_math_tight or word[0] in _GLUE_PUNCT))
                # Set as tight as a letter, a comma after an equation that ends
                # in a subscript lands just above that subscript and reads as a
                # prime ("F_fr," -> "F_fr'"). Punctuation there gets a few
                # letter-gaps of air instead — still far short of a word space.
                punct_after_sub = (glued and after_math_sub
                                   and word[0] in _GLUE_PUNCT)
                after_math = False
                after_math_tight = False
                after_math_sub = False
                glyphs, ink_left, ink_right, extent = (
                    tail_plans.pop((ri, wi), None) or plan_word(word))
                word_sym = all(c in _OP_CHARS for c in word)
                if line_empty:
                    origin = line_left
                elif glued:
                    gap = intra_gap()
                    if punct_after_sub:
                        gap *= _PUNCT_AFTER_SUBSCRIPT
                    origin = line_ink_right + gap - ink_left
                else:
                    gap = max(
                        word_gap_mean + rng.uniform(-word_gap_jit, word_gap_jit),
                        word_gap_floor,
                    )
                    # A spaced bare operator ("I / k", "x = y") is not a real
                    # word break: pull its gaps in so it reads as one expression.
                    if word_sym or prev_word_sym:
                        gap = max(gap * style.symbol_word_gap_scale, word_gap_floor)
                    if squeezing:
                        gap = min(gap, squeeze_gap)
                    # Chain the gap ink-to-ink: this word's leftmost ink lands one
                    # word gap past the previous word's rightmost ink.
                    origin = line_ink_right + gap - ink_left
                keep = glued and all(c in _GLUE_PUNCT for c in word)
                # Ruled paper: judged by where the ink ends, not the pen.
                over = origin + (ink_right if snapping else extent) > right
                if not line_empty and over and not keep and not squeezing:
                    tight_origin = (origin if glued
                                    else line_ink_right + squeeze_gap - ink_left)
                    if snapping and tail_fits((ri, wi), tight_origin + ink_right):
                        squeezing = True
                        origin = tight_origin
                    else:
                        new_line()
                        origin = line_left
                        line_empty = True
                elif line_empty and extent > right - left:
                    logger.warning(
                        "word %r is wider than the text column; it will overflow",
                        word,
                    )
                if snapping and line_empty:
                    settle_after_display()
                if snapping and eq_above:
                    # Keep the word clear of an equation's ink hanging down
                    # from the line above (an inline fraction's denominator).
                    boxes = [glyph_box(c, i, origin + rx, drift(origin + rx) + dy,
                                       scale * gs)[:3]
                             for c, i, rx, gs, dy, _ in glyphs]
                    drop_line(lambda: word_push(boxes))
                for char, idx, rel_x, gscale, dy, sup in glyphs:
                    gx = origin + rel_x
                    pages[-1].glyphs.append(
                        PlacedGlyph(
                            char=char,
                            variant=idx,
                            x=gx,
                            # rise_slope lifts the line toward its right end
                            y=baseline + drift(gx) + dy
                            - rise_slope * (gx - line_left),
                            scale=scale * gscale,
                            rotation_deg=0.0,
                            word=word_index,
                            embolden=sup,
                        )
                    )
                word_index += 1
                line_ink_right = origin + ink_right
                line_empty = False
                prev_word_sym = word_sym
                line_broken = False
        if not line_broken:
            new_line()

    # Mirroring Word's pages, the blank paragraphs that only pad the end of a
    # Word page (typed to push the next part down) are dropped: Word shows
    # nothing for them, and here they would cost lines or a whole page.
    padding: set[int] = set()
    paras = document.paragraphs
    if style.word_pages:
        for i, para in enumerate(paras):
            if not (para.word_page_start or para.page_break_before):
                continue
            j = i - 1
            while j >= 0 and not (paras[j].runs or paras[j].word_page_start
                                  or paras[j].page_break_before):
                padding.add(j)
                j -= 1

    def starts_page(para) -> bool:
        return para.page_break_before or (style.word_pages and para.word_page_start)

    def blank_run(i: int) -> int:
        """How many blank paragraphs are written in a row from index i."""
        n = 1
        while (i + n < len(paras) and i + n not in padding
               and not paras[i + n].runs and not starts_page(paras[i + n])):
            n += 1
        return n

    caption = None  # the paragraph just written, while space may follow it
    # (page index, g0, m0, first baseline) of the one-line headings written
    # right before the current paragraph, on its page
    head_chain: list = []
    in_blank_run = False
    for i, para in enumerate(paras):
        if i in padding:
            continue
        if starts_page(para):
            # Word page break: the rest starts on a fresh page. A page that
            # holds nothing yet is already that page.
            if pages[-1].glyphs or pages[-1].maths:
                new_page()
            caption = None
            in_blank_run = False
            if para.page_break_before and not para.runs:
                continue  # a paragraph holding only the break: no blank line
        if not para.runs:
            if (snapping and not in_blank_run and blank_run(i) == 1
                    and not starts_page(para)
                    and len(pages) > 1 and line_index == 0
                    and not (pages[-1].glyphs or pages[-1].maths)):
                # a lone separator blank that the page turn already made
                in_blank_run = True
                caption = None
                head_chain = []
                continue
            if not in_blank_run and blank_run(i) >= 2:
                keep_space_whole(blank_run(i), caption)
            in_blank_run = True
            caption = None
            head_chain = []
            new_line()  # blank line
            continue
        in_blank_run = False
        n_pages, g0, m0 = len(pages), len(pages[-1].glyphs), len(pages[-1].maths)
        baseline0, count0 = baseline, line_count
        first_lift = None
        layout_paragraph(para.runs)
        # where the paragraph's first line really sat (after any push)
        baseline0 += first_lift or 0.0
        # Page turned only by the line feed that ended the paragraph?
        turned = (len(pages) == n_pages + 1
                  and not (pages[-1].glyphs or pages[-1].maths))
        caption = ((g0, m0, baseline0, line_count - count0, turned,
                    _reads_as_caption(para.runs))
                   if len(pages) == n_pages or turned else None)
        # Ruled paper: a one-line heading or lead-in that took the last rule
        # goes over to the new page with what it heads — together with the
        # headings written right above it ("Theory" / "1. Capacitors").
        heading = line_count - count0 == 1 and _keeps_with_next(para.runs)
        if (snapping and turned and heading
                and i + 1 < len(paras) and i + 1 not in padding
                and paras[i + 1].runs and not starts_page(paras[i + 1])):
            chain = [h for h in head_chain if h[0] == n_pages - 1]
            first = chain[0][1:] if chain else (g0, m0, baseline0)
            carry_over(*first, len(chain) + 1)
            caption = None
            head_chain = []
        elif heading and len(pages) == n_pages:
            head_chain = [h for h in head_chain if h[0] == n_pages - 1][-2:]
            head_chain.append((n_pages - 1, g0, m0, baseline0))
        else:
            head_chain = []

    # Ruled paper: the line feed after the last line can open a sheet nothing
    # is written on (reserved space at the very end keeps its sheet).
    if snapping and paras and paras[-1].runs:
        while len(pages) > 1 and not (pages[-1].glyphs or pages[-1].maths):
            pages.pop()
    if unknown:
        logger.warning(
            "characters with no glyphs, spaced over and skipped: %s",
            " ".join(sorted(unknown)),
        )
    return pages
