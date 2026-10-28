"""Checkpoint 1 verification.

Checks: manifest loads; every expected char present; every inked char has >=3
variants; all PNGs open as RGBA with a transparent background AND visible ink;
HandwritingStyle instantiates. Prints the coverage report. Exit 0 = pass.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handwriting.glyphstore import GlyphStore
from handwriting.style import HandwritingStyle
from handwriting.synthglyphs import CHARSET, DEFAULT_STORE


def main() -> int:
    failures: list[str] = []

    try:
        store = GlyphStore(DEFAULT_STORE)
    except Exception as exc:
        print(f"FAIL: manifest did not load: {exc}")
        return 1

    expected = CHARSET + " "
    for char in expected:
        if char not in store:
            failures.append(f"missing character: {char!r}")
            continue
        entry = store.entry(char)
        if char != " " and len(entry.variants) < 3:
            failures.append(
                f"{char!r} has only {len(entry.variants)} variants (need >=3)"
            )

    checked_images = 0
    for char in store.characters:
        for variant in store.entry(char).variants:
            try:
                img = store.load_image(variant)
            except Exception as exc:
                failures.append(f"{variant.file}: failed to open: {exc}")
                continue
            lo, hi = img.getchannel("A").getextrema()
            if lo != 0:
                failures.append(f"{variant.file}: no transparent background")
            if hi != 255:
                failures.append(f"{variant.file}: no visible ink")
            w, h = img.size
            bx0, by0, bx1, by1 = variant.ink_bbox
            if not (0 <= bx0 < bx1 <= w and 0 <= by0 < by1 <= h):
                failures.append(f"{variant.file}: ink_bbox {variant.ink_bbox} outside {w}x{h}")
            checked_images += 1

    style = HandwritingStyle()

    print("=== Coverage report ===")
    print(store.coverage_report(expected=expected))
    print(f"checked {checked_images} PNG images")
    print(f"HandwritingStyle defaults: base_size_px={style.base_size_px}, "
          f"slant_deg={style.slant_deg}, variant_selection={style.variant_selection!r}")
    print()
    if failures:
        print(f"FAIL ({len(failures)} problems):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: checkpoint 1 checks all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
