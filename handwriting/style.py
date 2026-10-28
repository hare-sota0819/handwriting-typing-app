"""HandwritingStyle: every variation knob in one seedable config.

These knobs become per-mood presets later (upright vs slanted, tall vs squat),
so all variation behavior must read from here — never hardcode amounts in the
layout/variation engines. All randomness driven by these knobs must come from
a seeded RNG so a fixed seed reproduces identical output.
"""

from dataclasses import dataclass, fields


@dataclass
class HandwritingStyle:
    # Base glyph size the page is set in: cap height target, in pixels.
    # Jitters below with _px units are expressed at this size.
    base_size_px: float = 64.0

    # Letter slant: mean lean in degrees (positive = leaning right), plus a
    # small smooth low-frequency wander that stays well below the mean so the
    # lean never crosses back past vertical (direction stays consistently right).
    slant_deg: float = 1.5
    slant_jitter_deg: float = 0.0

    # Per-glyph variation. size_jitter 0.08 was set from measurement: the
    # ground-truth photo's x-height CV is ~15.5% (perspective-inflated; target
    # roughly half), and the store's 10 written variants already carry ~10% CV,
    # so the jitter tops it up rather than dominating.
    size_jitter: float = 0.0  # fraction of glyph scale (0.08 = ±8%)
    rotation_jitter_deg: float = 0.0  # one-sided (0..+this): only leans further right

    # Per-WORD baseline drift: a bounded random-walk offset sampled per word
    # (letters of one word move together; some words sit slightly higher or
    # lower). A walk, not a sinusoid: periodic wobble reads as a pattern once
    # the document is long enough (user: the sqrt "always wobbles at the 2:1
    # point" was spotted by a friend).
    # Default 6.0 chosen by the user from a per-knob A/B ladder (2026-08-13).
    word_drift_px: float = 6.0

    # Per-WORD slant deviation (degrees) around slant_deg, again a bounded
    # random walk over the word index. One word keeps one lean; the lean
    # NEVER crosses below 0 (letters lean consistently one way — the user
    # writes with a steady rightward lean whose amount varies per word).
    # Default 0: at realistic amplitudes the effect proved invisible in A/B
    # (user chose to drop it); the knob stays for style files / the GUI.
    word_tilt_deg: float = 0.0

    # Page rhythm (all inert at 0, and all disabled while snapping to ruled
    # paper — on lines the writer aligns to the printed rules):
    # line_rise_px: lines climb slightly to the RIGHT (the user's habit),
    # by a per-line random fraction (0.35-1.0) of this amount over the full
    # text width — one-directional, never downward.
    # Defaults chosen by the user from a per-knob A/B ladder (2026-08-13).
    line_rise_px: float = 4.5
    # line_step_jitter_frac: per-line variation of the baseline step, as a
    # fraction of the step (real line spacing is never metronome-even).
    line_step_jitter_frac: float = 0.035
    # margin_drift_px: the left margin wanders down the page (bounded random
    # walk, clamped to +/- this many px around the true margin).
    margin_drift_px: float = 10.0

    # Baseline drift: smooth low-frequency wander of the baseline across a
    # line — amplitude of the wander and its horizontal period.
    baseline_drift_px: float = 0.0
    baseline_drift_period_px: float = 400.0

    # Spacing. Placement is ink-extent based: within a word, glyphs are packed
    # so the gap between the rightmost ink of one letter and the leftmost ink of
    # the next equals intra_word_gap (letters touch/near-touch, as in real
    # writing). Word gaps are a distinctly larger, controllable space. All gaps
    # are fractions of the store's median x-height, so they scale with glyph
    # size. word_gap must stay clearly larger than intra_word_gap (readability).
    intra_word_gap_frac: float = 0.12  # ink-to-ink gap within a word (x-heights)
    intra_word_gap_jitter_frac: float = 0.0
    word_gap_frac: float = 1.2  # space between words (x-heights; target 0.6-1.5)
    word_gap_jitter_frac: float = 0.12
    # Symbol spacing. Operators (* + = - / < >) get symbol_gap_scale times the
    # intra-word gap against any neighbour (brackets-vs-letters and trailing
    # punctuation get a reduced share of it); a spaced bare operator ("I / k")
    # is not a real word break, so its word gaps shrink by symbol_word_gap_scale.
    symbol_gap_scale: float = 2.0
    symbol_word_gap_scale: float = 0.65
    line_height: float = 1.8  # multiple of base_size_px, baseline to baseline
    # Extra air above AND below a display equation (its own centred line), as
    # a multiple of base_size_px — beyond what keeps it from touching the text.
    display_math_gap: float = 0.35
    # Mirror Word's own pages: start a fresh page wherever Word's last layout
    # did (w:lastRenderedPageBreak), and drop the blank lines typed to pad the
    # end of a Word page. A Word page too long for one page here spills over.
    word_pages: bool = False

    # How to pick among a character's glyph variants.
    # "no_immediate_repeat": random, but never the same variant twice in a row
    # for the same character.
    variant_selection: str = "no_immediate_repeat"

    # Line-snapping wobble (only used when snapping baselines to ruled paper).
    # snap_wobble_px: small per-line vertical jitter around the printed rule so
    # snapped text doesn't look mechanically perfect. snap_drift_scale: factor
    # the smooth intra-line baseline drift is multiplied by while snapping (the
    # rule now dominates the line's vertical position, so drift is dialed down).
    snap_wobble_px: float = 2.5
    snap_drift_scale: float = 0.3

    # Ink appearance. ink_rgb is the pen color; ink_shade_jitter fades each
    # glyph's ink by up to this fraction (faint per-glyph darkness variation,
    # like real pen ink). Applied by the renderer via per-glyph alpha.
    ink_rgb: tuple[int, int, int] = (24, 28, 42)
    ink_shade_jitter: float = 0.12

    # Scanned-look effects chain (master switch). False reproduces the plain
    # clean render byte-identically: no residue threshold, no ink/page effects.
    effects: bool = True
    # Stage 0 — residue threshold, applied to glyph alpha at render time (never
    # to stored glyphs). Store alpha encodes source darkness: gray<=80 -> 255,
    # fading to 0 at gray 190. Cutoff 100 corresponds to source gray ~147: true
    # ink (gray 0-60 -> alpha 255) is untouched, printed-guide residue
    # (gray 150-200 -> alpha <=93) is dropped. Residue dots that scanned as dark
    # as pen ink are indistinguishable by ANY global threshold and survive.
    residue_alpha_cutoff: int = 100
    # Stage-2 ink/scanner effects (scanned-look pass). All are inert when
    # effects=False; each is individually disabled at 0. Targets measured from
    # the real 1200 DPI template scans at 300 dpi (scripts/measure_scan_ink.py):
    # ink core gray median 42 / mean 45.9 / std 18; edge transition 0-1 px
    # @300dpi (~0-0.55 px at 150-dpi render). The CLEAN render already matches
    # both (core median 45 / std 18.6; edges 96% <=1 px) because the store's
    # alpha carries the same scans' AA edges — so tone shift and edge softening
    # default OFF (knobs kept for other stores), and the darkness jitters are
    # two-sided gray-VALUE offsets, which restore the spatial darkness
    # variation the store's solid-alpha floor flattened WITHOUT moving the
    # matched histogram median (one-sided alpha fades shifted it +28 gray).
    # Jitter amplitudes are the weakest setting visible in a 4x A/B.
    ink_tone_value: int = 0  # target mean ink gray (0 = keep ink_rgb; measured: matched)
    ink_density_jitter: float = 12.0  # per-glyph ink value offset, +/- gray levels
    ink_pressure: float = 10.0  # intra-glyph low-freq value field, +/- gray levels
    edge_soften_px: float = 0.0  # alpha blur radius at 150-dpi page (measured: matched)
    scanner_tone_amp: int = 3  # page luminance +/- from a low-freq scanner field

    @classmethod
    def from_dict(cls, data: dict) -> "HandwritingStyle":
        """Build a style from a JSON-loaded dict, ignoring unknown keys."""
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown style keys: {sorted(unknown)}")
        kwargs = dict(data)
        if "ink_rgb" in kwargs:
            kwargs["ink_rgb"] = tuple(kwargs["ink_rgb"])
        return cls(**kwargs)
