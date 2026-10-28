"""Stage-2 ink/scanner effects check (scanned-look pass).

Proves, on top of the CLEAN/EFFECTS goldens held by feature_paperpdf_check and
feature_snaplines_check:

1. GATING — with every stage-2 knob zeroed, the effects path is byte-identical
   to the pre-stage-2 (stage 0+1 only) golden: the new code is fully knob-gated.
2. DETERMINISM — same seed twice is byte-identical; a different seed differs.
3. COMPONENT ACTIVITY — density jitter, pressure field, and scanner tone each
   change the output on their own; tone shift and edge softening (default 0,
   measured as already matched by the store) engage when set.
4. TONE TARGET — on the real store + ruled-paper render, the composited
   ink-core gray distribution stays on the measured 1200 DPI scan target
   (median 42, std 18; see scripts/measure_scan_ink.py) on the effects path —
   stage 2 must add spatial variation without shifting tone. The clean path
   sits on the pen colour (no per-glyph fade).
"""

import hashlib
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from handwriting.compositor import PaperStyle
from handwriting.pipeline import render_document, resolve_line_grid


# Goldens here were baselined on the Phase 1 synthetic store; the pipeline's
# default store is now whatever glyphs/ holds, so pin it (the tone-target
# section passes its own store explicitly).
from handwriting.synthglyphs import DEFAULT_STORE as _SYNTH  # noqa: E402
_render_document = render_document


def render_document(*args, **kwargs):  # noqa: E302
    kwargs.setdefault("store_root", _SYNTH)
    return _render_document(*args, **kwargs)
from handwriting.style import HandwritingStyle

import make_samples  # noqa: E402  (scripts/ sibling)

# Stage-0+1-only EFFECTS output at seed=4 (the pre-stage-2 golden, formerly
# EFFECTS_BASELINE in feature_paperpdf_check / feature_snaplines_check).
# RE-BASELINED 2026-08-05 for the user-approved default look (bigger at
# base_size_px 64, every wobble source zeroed, intra-word gap 0.24 -> 0.12).
# The old hashes pinned the pre-approval style; this is a deliberate change of
# the default, not a relaxation — the check still refuses any later drift.
# RE-BASELINED 2026-08-07: glyphs are now seated by their own ink at the depth
# a reference font gives each character (handwriting/metrics.py), instead of by
# the printed guide recorded at capture time. Digits and colons in this hand were
# written clear of that guide and floated above the line. Deliberate change of
# rendering, not a relaxation; the check still refuses any later drift.
# RE-BASELINED 2026-08-13 (Millikan-render review, user-reported): descenders
# (g/j/p/q/y) are seated by their captured baseline again (their tails run
# deeper than the reference font's — font-depth seating lifted them off the
# line), trailing punctuation/brackets/hyphen get real air, and word_gap_frac
# tightened 1.5 -> 1.2. Deliberate change, not a relaxation.
# RE-BASELINED 2026-08-13 (2): handwriting rhythm defaults chosen by the
# user per-knob (word_drift 6, line_rise 4.5, step jitter 3.5%, margin
# drift 10; word tilt dropped) + the word-walk RNG replaced the sinusoid.
# Deliberate change of the default look, not a relaxation.
# RE-BASELINED 2026-08-14 (multi only): bracket-vs-alnum pair gap raised
# 1.2 -> 2.0; see feature_paperpdf_check.py for the record.
STAGE01_BASELINE = {
    "plain": "a401eaf617d74ee0c5943f442ceda7624544fca345b13816028448c868846edb",
    "multi": "688991b7d8305b9518a3ae51879b381f84a7533ba1e6be89041f86cb1f2d45cf",
}
ZEROED = dict(
    ink_tone_value=0, ink_density_jitter=0, ink_pressure=0,
    edge_soften_px=0, scanner_tone_amp=0,
)
REAL_STORE = ROOT / "glyphs" / "real"
RULED_PAPER = ROOT / "samples" / "ruled_paper_scan.pdf"
# Measured scan-ink core target (scripts/measure_scan_ink.py, gray<100 mask).
TONE_MEDIAN, TONE_MEDIAN_TOL = 42.0, 8.0
# The CLEAN path no longer fades glyphs one by one (2026-09-16, user report:
# random grey letters beside solid equations), so its ink core sits on the pen
# colour itself rather than on the scan: median within the same tolerance of
# ink_rgb's grey. The effects path keeps the scan target above.
CLEAN_TONE_MEDIAN = sum(HandwritingStyle().ink_rgb) / 3.0
TONE_STD_RANGE = (13.0, 26.0)
# Dark-tail bin (gray 10-20) of the effects render: the scan target holds
# 2.2% of ink px there; symmetric jitter overfilled it to 6.5% (review
# finding), the asymmetric darkening side (renderer._JITTER_DARK_FRAC) lands
# it at ~2.1%. Guard the band so neither regression direction sneaks back.
DARK_BIN_RANGE = (0.5, 4.5)


def digest(pages) -> str:
    return hashlib.sha256(b"".join(p.tobytes() for p in pages)).hexdigest()


def main() -> int:
    failures: list[str] = []
    if not (make_samples.SAMPLES / "plain.docx").exists():
        make_samples.main()

    # 1. gating: all stage-2 knobs zeroed == stage-0/1 golden
    for name, ref in STAGE01_BASELINE.items():
        pages = render_document(
            f"samples/{name}.docx", seed=4, style=HandwritingStyle(**ZEROED)
        )
        if digest(pages) != ref:
            failures.append(
                f"zeroed stage-2 knobs changed the {name} effects output "
                f"({digest(pages)[:12]}... != stage-0/1 golden) — gating broken"
            )

    # 2. determinism per seed
    base = render_document("samples/plain.docx", seed=4)
    again = render_document("samples/plain.docx", seed=4)
    if digest(base) != digest(again):
        failures.append("same-seed effects render not reproducible")
    other = render_document("samples/plain.docx", seed=5)
    if digest(other) == digest(base):
        failures.append("different seed produced identical effects output")

    # 3. each component alone changes the output vs all-zeroed
    zeroed_pages = render_document(
        "samples/plain.docx", seed=4, style=HandwritingStyle(**ZEROED)
    )
    solo = {
        "ink_density_jitter": 12.0,
        "ink_pressure": 10.0,
        "scanner_tone_amp": 3,
        "ink_tone_value": 60,
        "edge_soften_px": 0.5,
    }
    for knob, value in solo.items():
        style = HandwritingStyle(**{**ZEROED, knob: value})
        pages = render_document("samples/plain.docx", seed=4, style=style)
        if digest(pages) == digest(zeroed_pages):
            failures.append(f"{knob}={value} had no effect on the output")

    # 4. tone target on the real store (clean AND effects stay on the target).
    # The targets were measured against one specific scanned-handwriting store
    # (the author's, not published); without it there is nothing to compare.
    if not (REAL_STORE / "manifest.json").exists():
        print(f"  tone target: skipped (reference store {REAL_STORE.name} not present)")
    grid = resolve_line_grid(RULED_PAPER, snap=True)
    paper = PaperStyle(background_pdf=RULED_PAPER)
    for label, style in (
        ("clean", HandwritingStyle(effects=False)),
        ("effects", HandwritingStyle()),
    ) if (REAL_STORE / "manifest.json").exists() else ():
        pages = render_document(
            "samples/gt_sentences.docx", seed=0, style=style,
            paper=paper, store_root=REAL_STORE, grid=grid,
        )
        gray = np.asarray(pages[0].convert("L"), dtype=float)
        core = gray[gray < 100]
        med, std = float(np.median(core)), float(core.std())
        print(f"  {label}: ink-core median {med:.1f} std {std:.1f} (n={core.size})")
        target = CLEAN_TONE_MEDIAN if label == "clean" else TONE_MEDIAN
        if abs(med - target) > TONE_MEDIAN_TOL:
            failures.append(
                f"{label} ink-core median {med:.1f} off the target "
                f"{target:.1f}+/-{TONE_MEDIAN_TOL}"
            )
        if not (TONE_STD_RANGE[0] <= std <= TONE_STD_RANGE[1]):
            failures.append(
                f"{label} ink-core std {std:.1f} outside {TONE_STD_RANGE}"
            )
        if label == "effects":
            dark_bin = 100.0 * float(((core >= 10) & (core < 20)).sum()) / core.size
            print(f"  effects: dark bin (gray 10-20) {dark_bin:.1f}% of ink px")
            if not (DARK_BIN_RANGE[0] <= dark_bin <= DARK_BIN_RANGE[1]):
                failures.append(
                    f"effects dark bin {dark_bin:.1f}% outside {DARK_BIN_RANGE} "
                    f"(scan target 2.2%)"
                )

    if failures:
        print("FAIL: stage-2 effects checks")
        for f in failures:
            print(" -", f)
        return 1
    print("PASS: stage-2 effects — gating, determinism, components, tone target")
    return 0


if __name__ == "__main__":
    sys.exit(main())
