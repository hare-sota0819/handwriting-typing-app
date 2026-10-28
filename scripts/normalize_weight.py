"""Normalize stroke weight of the rescaled ipad_v2 alphabet to the store's
own pen weight.

The 2026-08-13 size merge scaled the new lowercase by 0.855 and uppercase by
0.679 to match the old store's letter proportions — which also thinned the
strokes by the same factors (lowercase ~11px, caps ~8px vs 12px everywhere
else in the store). A fixed-width pen doesn't do that, and the user sees it
("E thinner than q, S thinner than ubstituting").

Fix: dilate the alpha channel of the 54 rescaled entries back to the store
median (~12px) — the same MaxFilter technique validated in the pilot weight
study (kerning is unaffected because layout reads ink extents from the
image). Lowercase (+1px) gets sub-pixel dilation via 2x upsample /
MaxFilter(3) / downsample; caps (+4px) get MaxFilter(5) at native size.
ink_bbox is recomputed from the dilated alpha. Run reseat_store.py AFTER
this script (baselines derive from ink_bbox).

Usage: .venv/bin/python scripts/normalize_weight.py glyphs/ipad_v2
"""

import json
import string
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

# Per-entry dilation in native px of added stroke width (must be even for
# native MaxFilter; odd amounts use the 2x round-trip).
LOWERCASE_ADD = 1   # 11px -> ~12px
UPPERCASE_ADD = 4   # 8px  -> ~12px
ENTRIES = {c: LOWERCASE_ADD for c in string.ascii_lowercase}
ENTRIES.update({c: UPPERCASE_ADD for c in string.ascii_uppercase})
ENTRIES.update({"math:x": LOWERCASE_ADD, "math:y": LOWERCASE_ADD})


def dilate_alpha(img: Image.Image, add_px: int) -> Image.Image:
    alpha = img.getchannel("A")
    if add_px % 2 == 0:
        alpha = alpha.filter(ImageFilter.MaxFilter(add_px + 1))
    else:  # sub-pixel: dilate at 2x, where add_px native = 2*add_px pixels
        big = alpha.resize((alpha.width * 2, alpha.height * 2), Image.LANCZOS)
        big = big.filter(ImageFilter.MaxFilter(2 * add_px + 1))
        alpha = big.resize(alpha.size, Image.LANCZOS)
    out = img.copy()
    out.putalpha(alpha)
    return out


def main(store_root: str) -> None:
    root = Path(store_root)
    manifest = json.loads((root / "manifest.json").read_text())
    chars = manifest["characters"]
    for key, add in ENTRIES.items():
        for v in chars[key]["variants"]:
            path = root / v["file"]
            img = Image.open(path).convert("RGBA")
            img = dilate_alpha(img, add)
            img.save(path)
            a = np.asarray(img.getchannel("A"))
            ys, xs = np.nonzero(a >= 8)
            v["ink_bbox"] = [int(xs.min()), int(ys.min()),
                             int(xs.max()) + 1, int(ys.max()) + 1]
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False))
    print(f"dilated {len(ENTRIES)} entries "
          f"(+{LOWERCASE_ADD}px lowercase/math, +{UPPERCASE_ADD}px caps) "
          f"-> {root}; now run reseat_store.py")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "glyphs/ipad_v2")
