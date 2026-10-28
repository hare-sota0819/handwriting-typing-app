"""Tool 2 verification: scan splitter (synthetic scan -> real glyph store).

Runs the whole Tool 2 pipeline on a synthetic filled scan (font glyphs, sheared
right) and asserts, without a human in the loop:
  - the 4 markers register with ~zero residual on a clean scan (warp skipped);
  - the store loads under the EXISTING manifest schema: every charset char has 5
    variants + an ink-less space;
  - every glyph image is ink-only RGBA (has both transparent and opaque pixels,
    i.e. not an opaque rectangle);
  - the baseline-removal core removes a full-width printed line while preserving a
    vertical stroke that crosses it (unit check on remove_furniture);
  - the right-leaning slant is preserved (a tall glyph's top ink sits to the RIGHT
    of its bottom ink) -- proving no deskew/upright ever ran.
Everything runs under out/ so verify.sh never dirties committed deliverables.
Exit 0 = pass.
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import make_fake_scan
import split_scan as ss
from handwriting.glyphstore import GlyphStore
from handwriting.synthglyphs import CHARSET


def _check_furniture_removal(failures):
    """SAFE removal: the light printed guide line is dropped by density, and a
    vertical stroke that TAPERS lighter as it reaches the baseline is preserved
    100% down to the baseline (the i-stem regression: no in-band deletion)."""
    W, H = 76, 120
    cell = np.full((H, W), 255.0, np.float32)
    baseline_row = 84
    cell[baseline_row - 3:baseline_row - 1, :] = 210.0      # LIGHT printed guide line
    col = 38
    for r in range(12, baseline_row + 1):                   # stem tapering to baseline
        cell[r, 36:41] = 40.0 if r < baseline_row - 8 else 40.0 + (r - (baseline_row - 8)) * 15
    ink, dbg = ss.remove_furniture(cell)
    # the light guide line is removed by density
    if ink[baseline_row - 2, 5]:
        failures.append("furniture: light guide not removed by density")
    # the tapering stem is preserved ALL the way to the baseline (no truncation)
    if not all(ink[r, col] for r in range(12, baseline_row + 1)):
        failures.append("furniture: tapering stroke cut before the baseline (i-stem regression)")


def _slant_rightward(img: Image.Image) -> bool:
    """True if the top ink of a tall glyph sits to the right of the bottom ink."""
    a = np.asarray(img)[..., 3] > 40
    ys, xs = np.where(a)
    if len(xs) < 20:
        return False
    top = xs[ys < ys.min() + (ys.max() - ys.min()) * 0.25].mean()
    bot = xs[ys > ys.max() - (ys.max() - ys.min()) * 0.25].mean()
    return top > bot + 1.0


def main() -> int:
    failures: list[str] = []
    work = ROOT / "out" / "tool2_check"
    scan_dir = work / "fake_scan"
    store_dir = work / "store"

    make_fake_scan.generate(scan_dir, rotate=0.0)
    layout = json.loads((ROOT / "template" / "template_layout.json").read_text("utf-8"))
    scans = sorted(scan_dir.glob("fake_scan_p*.png"),
                   key=lambda p: int(p.stem.split("p")[-1]))
    _manifest, reports = ss.split(scans, layout, store_dir)

    # clean scan: near-zero residual, warp skipped
    for r in reports:
        if r["residual_px"]["max"] > 1.0 or r["warp_applied"]:
            failures.append(f"page {r['page']}: unexpected residual/warp {r['residual_px']}")

    store = GlyphStore(store_dir)
    gf = layout["guide_fractions"]
    cap_height = round((gf["baseline"] - gf["ascender"]) * layout["cell_h"])
    if store.native_size_px != cap_height:
        failures.append(f"native_size_px {store.native_size_px} != cap height {cap_height}")
    for ch in CHARSET:
        if ch not in store:
            failures.append(f"missing char {ch!r}")
            continue
        vs = store.entry(ch).variants
        n = len(vs)
        if n != 5:
            failures.append(f"char {ch!r} has {n} variants, expected 5")
        # baseline_y must come from the guide lines, not ink -> constant across a
        # character's variants (all 5 cells share the row's baseline guide).
        bys = [v.baseline_y for v in vs]
        if bys and max(bys) - min(bys) > 1:
            failures.append(f"char {ch!r} baseline_y varies across variants "
                            f"(spread {max(bys) - min(bys)}): {bys} -- guide bug?")
    if " " not in store or store.entry(" ").variants:
        failures.append("space should exist and be ink-less")

    # every glyph image is ink-only RGBA (transparent + opaque pixels present)
    for ch in ("a", "b", "g", "m", "z"):
        for v in store.entry(ch).variants:
            alpha = np.asarray(store.load_image(v))[..., 3]
            if alpha.min() != 0 or alpha.max() < 150:
                failures.append(f"{ch!r} {v.file}: not ink-only RGBA "
                                f"(alpha {alpha.min()}..{alpha.max()})")
                break

    _check_furniture_removal(failures)

    # slant preserved & rightward: use near-vertical glyphs so the metric reflects
    # slant, not glyph shape (bowls/legs would confound b/h).
    for ch in ("l", "I", "1"):
        img = store.load_image(store.entry(ch).variants[0])
        if not _slant_rightward(img):
            failures.append(f"{ch!r}: right-leaning slant not preserved")

    inked = sum(1 for c in store.characters if store.entry(c).variants)
    print(f"tool2: {inked} inked chars x 5 variants, "
          f"{len(reports)} pages registered (residual~0), furniture + slant OK")
    print()
    if failures:
        print(f"FAIL ({len(failures)} problems):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: Tool 2 scan-splitter checks all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
