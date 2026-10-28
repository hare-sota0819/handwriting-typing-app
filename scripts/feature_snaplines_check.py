"""Feature verification: snap text baselines to ruled-paper lines.

Checks:
- Regression: with no grid, output is byte-identical to the pre-feature baseline.
- Auto-detect on the user's real ruled paper: rules found; snapped baselines
  sit ON the rules (small residual = wobble), reproducible per seed.
- Manual override: --rule-spacing/--rule-offset move baselines accordingly.
- Wobble preserved: per-line distance to the nearest rule varies (not all equal)
  yet stays small; identical under a fixed seed, different across seeds.
- Snap sizing by x-height: the lowercase body fills a set fraction of the lane
  regardless of the requested base_size_px (huge/tiny base_size is overridden).
- Detection-failure fallback: snapping on a non-ruled background warns and
  returns no grid (un-snapped), rather than snapping to garbage.
Writes a viewable snapped PNG to out/. Exit 0 = pass.
"""

import hashlib
import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

import make_samples
from handwriting.compositor import PaperStyle
from handwriting.glyphstore import GlyphStore
from handwriting.layout import LineGrid, PageSpec, layout_document
from handwriting.parser import parse_docx
from handwriting.pipeline import render_document, resolve_line_grid


# These goldens were baselined on the Phase 1 synthetic store; the pipeline's
# default store is now whatever glyphs/ holds, so pin it here.
from handwriting.synthglyphs import DEFAULT_STORE as _SYNTH  # noqa: E402
_render_document = render_document


def render_document(*args, **kwargs):  # noqa: E302
    kwargs.setdefault("store_root", _SYNTH)
    return _render_document(*args, **kwargs)
from handwriting.style import HandwritingStyle
from handwriting.synthglyphs import DEFAULT_STORE

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
REAL_PAPER = ROOT / "samples" / "ruled_paper_scan.pdf"
NONRULED = ROOT / "samples" / "offaspect.pdf"

# Procedural output at seed=4, both render paths: CLEAN (effects=False) is the
# plain render, EFFECTS the default scanned-look chain (stage 0 residue alpha
# threshold). EFFECTS re-baselined for stage 2 (ink density/pressure value jitter,
# scanner tone); the stage-0/1-only output is pinned by feature_effects2_check.
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
# RE-BASELINED 2026-09-16 (clean only): per-glyph ink fade is effects-only;
# see feature_paperpdf_check.py for the record.
CLEAN_BASELINE = {
    "plain": "b2163f8af78390d743475343847bee35668670a9c145442c2540cd4ccfffad43",
    "multi": "791c173f357766887dece27539ab498bb6820c58aaeb01771e0f8a742c6fe305",
}
EFFECTS_BASELINE = {
    "plain": "0b45cf1d18ba63220795782b7a0f79612c719cb6abd0472fee53da8f14075ebc",
    "multi": "8aa52f117bf22dd716d47dee6bff2ab2a686bb37bc3d5abff5a6c17ad4e18c43",
}


def digest(pages):
    return hashlib.sha256(b"".join(p.tobytes() for p in pages)).hexdigest()


def capture_logs():
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    logging.getLogger("handwriting").addHandler(h)
    logging.getLogger("handwriting").setLevel(logging.INFO)
    return buf, h


def baseline_positions(document, style, grid, seed=1):
    """Return, per occupied rule, the mean glyph-baseline y (snapped layout).

    Glyphs are grouped by their rule index k = round((y - offset)/spacing) so a
    single physical line is never split by within-line drift.
    """
    store = GlyphStore(DEFAULT_STORE)
    pages = layout_document(document, store, style, PageSpec(), seed=seed, grid=grid)
    lines = []
    for page in pages:
        by_k: dict[int, list[float]] = {}
        for g in page.glyphs:
            k = round((g.y - grid.offset_px) / grid.spacing_px)
            by_k.setdefault(k, []).append(g.y)
        for k in sorted(by_k):
            lines.append(float(np.mean(by_k[k])))
    return lines


def nearest_rule_dist(y, spacing, offset):
    k = round((y - offset) / spacing)
    return y - (offset + k * spacing)


def main() -> int:
    failures: list[str] = []
    OUT.mkdir(exist_ok=True)
    if not (make_samples.SAMPLES / "plain.docx").exists():
        make_samples.main()
    if not REAL_PAPER.exists():
        print(f"FAIL: real ruled paper not found at {REAL_PAPER}")
        return 1

    # 1. regression: no grid => byte-identical, both render paths
    for label, baseline, st in (
        ("clean", CLEAN_BASELINE, HandwritingStyle(effects=False)),
        ("effects", EFFECTS_BASELINE, HandwritingStyle()),
    ):
        for name, h_ref in baseline.items():
            if digest(render_document(f"samples/{name}.docx", seed=4, style=st)) != h_ref:
                failures.append(f"no-snap {label} output for {name} changed vs baseline")

    # 2. auto-detect + baselines sit on rules
    grid = resolve_line_grid(str(REAL_PAPER), snap=True)
    if grid is None:
        failures.append("auto-detect failed on the real ruled paper")
        grid = LineGrid(33.33, 104.0, 133.5)
    # multi.docx spans several lines, so wobble across lines is measurable.
    doc = parse_docx("samples/multi.docx")
    style = HandwritingStyle()
    lines = baseline_positions(doc, style, grid, seed=1)
    if len(lines) < 3:
        failures.append(f"expected several snapped lines, got {len(lines)}")
    dists = [abs(nearest_rule_dist(y, grid.spacing_px, grid.offset_px)) for y in lines]
    if dists and max(dists) > style.snap_wobble_px + style.baseline_drift_px * style.snap_drift_scale + 3:
        failures.append(f"snapped baselines stray from rules: max dist {max(dists):.1f}px")

    # render a viewable snapped page over the real paper
    onpaper = render_document(
        "samples/multi.docx", seed=1,
        paper=PaperStyle(background_pdf=str(REAL_PAPER), fit="cover"), grid=grid,
    )
    onpaper[0].save(OUT / "snap_real_paper.png")

    # 3. manual override moves baselines
    manual = resolve_line_grid(None, snap=True, rule_spacing=60.0, rule_offset=300.0)
    mlines = baseline_positions(doc, style, manual, seed=1)
    if not mlines or abs(mlines[0] - 300.0) > style.snap_wobble_px + 4:
        failures.append(f"manual override first baseline off: {mlines[:1]} (want ~300)")
    if len(mlines) >= 2 and abs((mlines[1] - mlines[0]) - 60.0) > 2 * style.snap_wobble_px + 2:
        failures.append(f"manual override spacing off: {mlines[1]-mlines[0]:.1f} (want ~60)")

    # 4. wobble present, reproducible, seed-dependent
    signed = [nearest_rule_dist(y, grid.spacing_px, grid.offset_px) for y in lines]
    if len(signed) >= 3 and np.std(signed) < 0.3:
        failures.append("no wobble: baselines are all equidistant from the rules")
    if baseline_positions(doc, style, grid, seed=1) != lines:
        failures.append("snapped layout not reproducible under a fixed seed")
    if baseline_positions(doc, style, grid, seed=2) == lines:
        failures.append("wobble does not vary across seeds")

    # 5. Snapping sizes by X-HEIGHT, not the requested base_size_px: the lowercase
    #    body fills ~_SNAP_XHEIGHT_FRAC of the lane regardless of base_size, so a
    #    huge (or tiny) base_size can't blow out / crush the text in the lane.
    from handwriting.layout import _median_x_height, _SNAP_XHEIGHT_FRAC
    store = GlyphStore(DEFAULT_STORE)
    xh_native = _median_x_height(store)
    target_xh = _SNAP_XHEIGHT_FRAC * grid.spacing_px
    rendered = {}
    for bs in (18.0, 80.0):  # requested tiny and huge; snap should ignore both
        st = HandwritingStyle(base_size_px=bs)
        pages = layout_document(doc, store, st, PageSpec(), seed=1, grid=grid)
        scale = max((g.scale for pg in pages for g in pg.glyphs), default=0.0)
        rendered[bs] = scale * xh_native
    if abs(rendered[18.0] - rendered[80.0]) > 0.5:
        failures.append(
            f"snap size not base_size-independent: xh {rendered[18.0]:.1f} vs {rendered[80.0]:.1f}")
    if rendered[80.0] > target_xh + 1.0:
        failures.append(
            f"snap x-height {rendered[80.0]:.1f} exceeds lane target {target_xh:.1f} (ceiling failed)")
    # body must be a real, legible fraction of the lane (not crushed as before)
    if rendered[80.0] < 0.5 * target_xh:
        failures.append(f"snap x-height {rendered[80.0]:.1f} too small vs target {target_xh:.1f}")

    # 6. detection-failure fallback on a non-ruled background
    buf, h = capture_logs()
    fb = resolve_line_grid(str(NONRULED), snap=True)
    logging.getLogger("handwriting").removeHandler(h)
    if fb is not None:
        failures.append("snapping a non-ruled paper did not fall back (got a grid)")
    if "not snapping" not in buf.getvalue():
        failures.append("fallback did not log a clear warning")

    # 7. Ruled paper is written down to its LAST printed rule: the plain-page
    #    bottom margin must not strand the rules printed inside it (user report:
    #    every page left its bottom rules empty), nothing is written below that
    #    rule, and a line a tall equation pushes past it moves to the next page
    #    whole.
    from PIL import Image
    from handwriting.compositor import rasterize_pdf
    from handwriting.document_model import Document, MathBlock, Paragraph, TextRun
    from handwriting.mathrender import MathInk
    spec = PageSpec()
    gray = np.asarray(rasterize_pdf(str(REAL_PAPER), (spec.width_px, spec.height_px))[0]
                      .convert("L")).astype(float)
    row_mean = gray.mean(axis=1)
    printed_last = float(np.where(row_mean < np.median(row_mean) - 3)[0].max())
    k_last = round((printed_last - grid.offset_px) / grid.spacing_px)
    slack = style.snap_wobble_px + style.baseline_drift_px * style.snap_drift_scale + 3
    if grid.last_rule_px is None or abs(grid.last_rule_px - printed_last) > 2:
        failures.append(f"detected last rule {grid.last_rule_px} != printed {printed_last}")

    def rule_indices(pg):
        return [round((r.y - grid.offset_px) / grid.spacing_px)
                for r in list(pg.glyphs) + list(pg.maths)]

    long_doc = Document([Paragraph([TextRun("word " * 2500)])])
    lpages = layout_document(long_doc, store, style, spec, seed=1, grid=grid)
    if len(lpages) < 3:
        failures.append(f"fill check needs >=3 pages, got {len(lpages)}")
    for n, pg in enumerate(lpages[:-1], 1):
        if max(rule_indices(pg)) != k_last:
            failures.append(f"page {n} stops at rule {max(rule_indices(pg))}, "
                            f"last printed rule is {k_last}")
    for n, pg in enumerate(lpages, 1):
        low = max(r.y for r in list(pg.glyphs) + list(pg.maths))
        if low > printed_last + slack:
            failures.append(f"page {n} writes below the last rule: y={low:.0f}")

    tall = MathInk(image=Image.new("RGBA", (40, 300), (0, 0, 0, 255)),
                   baseline_y=200.0, cap_px=50.0, store_cap_ink=50.0)
    tall_doc = Document(
        [Paragraph([TextRun("a")]) for _ in range(k_last)]
        + [Paragraph([TextRun("see"), MathBlock(omml_xml="", ink=tall)])])
    tpages = layout_document(tall_doc, store, style, spec, seed=1, grid=grid)
    if len(tpages) != 2:
        failures.append(f"tall equation on the last rule: want 2 pages, got {len(tpages)}")
    else:
        if len(tpages[0].glyphs) != k_last or tpages[0].maths:
            failures.append("tall-equation line did not leave the full page whole")
        if len(tpages[1].glyphs) != 3 or len(tpages[1].maths) != 1:
            failures.append("tall-equation line did not arrive on the next page whole")
        elif abs(tpages[1].glyphs[0].y - tpages[1].maths[0].y) > slack:
            failures.append("moved line lost its shared baseline")
        low = max(r.y for pg in tpages for r in list(pg.glyphs) + list(pg.maths))
        if low > printed_last + slack:
            failures.append(f"tall-equation line sits below the last rule: y={low:.0f}")

    print(f"detected grid: spacing {grid.spacing_px:.1f}px, offset {grid.offset_px:.0f}px, "
          f"margin_x {grid.margin_x_px}")
    print(f"snapped {len(lines)} lines; max dist to rule {max(dists):.2f}px; "
          f"wobble std {np.std(signed):.2f}px")
    print("outputs in:", OUT)
    print()
    if failures:
        print(f"FAIL ({len(failures)} problems):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: line-snapping feature checks all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
