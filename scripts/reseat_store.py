"""Align a glyph store's captured baselines with how the engine actually
seats glyphs, so kerning (which reads baseline-relative ink rows) and
rendering (which may re-seat a glyph by font depth) agree.

Two passes over manifest.json (images are never touched):

1. Sunk descenders: g/j/p/q/y written with the body partly below the printed
   guide get their baseline_y moved so the ink above the baseline matches the
   hand's own proportions (measured from the user's approved first collection,
   glyphs/ipad) — the body sits on the line again, the deep tail stays.

2. Render-seating alignment: every glyph the renderer seats by font depth
   (ink bottom placed at depth*x_height below the baseline — digits, marks,
   ordinary letters) gets baseline_y = ink_bottom - depth*x_height, so the
   kerning profile sees the glyph at the height it is actually drawn. Without
   this a floating mark like '-' is kerned at its captured height (~0.8 xh up)
   but drawn lower, where the neighbour may be wider ("high-" hyphen on the
   h's foot).

Usage: .venv/bin/python scripts/reseat_store.py glyphs/ipad_v2
"""

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from handwriting import metrics  # noqa: E402
from handwriting.glyphstore import GlyphStore  # noqa: E402
from handwriting.renderer import _TRUST_GUIDE_MIN_XH, _store_x_height  # noqa: E402

# Ink-above-baseline per descender, in x-heights — the hand's own proportions,
# measured from glyphs/ipad (the approved first collection).
DESCENDER_ABOVE_XH = {"g": 0.855, "j": 1.073, "p": 1.000, "q": 0.944, "y": 0.798}


def main(store_root: str) -> None:
    manifest_path = Path(store_root) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    chars = manifest["characters"]

    xh = statistics.median(
        v["baseline_y"] - v["ink_bbox"][1]
        for c in "acemnorsuvwxz" if c in chars
        for v in chars[c]["variants"]
    )

    # Pass 1 — reseat sunk descenders to the hand's own body proportions.
    for ch, above_xh in DESCENDER_ABOVE_XH.items():
        for v in chars[ch]["variants"]:
            v["baseline_y"] = round(v["ink_bbox"][1] + above_xh * xh)

    # Pass 2 — align kern rows with render seating for font-depth glyphs.
    # Uses the same store x-height and branch test as the renderer.
    xh_render = _store_x_height(GlyphStore(store_root))
    aligned = 0
    for key, data in chars.items():
        if len(key) != 1:
            continue  # math:/big:/rule: entries never reach text layout
        depth = metrics.depth_in_x_heights(key)
        if depth is None:
            continue
        for v in data["variants"]:
            below = v["ink_bbox"][3] - v["baseline_y"]
            if below > _TRUST_GUIDE_MIN_XH * xh_render:
                continue  # deep descender: renderer trusts this baseline as-is
            v["baseline_y"] = round(v["ink_bbox"][3] - depth * xh_render)
            aligned += 1

    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print(f"reseated descenders {sorted(DESCENDER_ABOVE_XH)}, "
          f"aligned {aligned} font-depth variants (xh={xh:.1f}, "
          f"xh_render={xh_render:.1f}) -> {manifest_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "glyphs/ipad_v2")
