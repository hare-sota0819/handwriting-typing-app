"""Glyph store: on-disk handwriting glyph images + manifest.json loader.

Disk layout: a store root containing manifest.json plus one folder per
character (safe ASCII folder names — punctuation is mapped, never used
literally). Each folder holds the character's variant PNGs (transparent
background, ink only).

Manifest schema (version 1):

    {
      "version": 1,
      "native_size_px": 96,               // font/scan size the metrics are in;
                                           // layout scales everything by
                                           // style.base_size_px / native_size_px
      "characters": {
        "a": {
          "folder": "lower_a",
          "advance_width": 53.0,          // nominal pen advance, px
          "variants": [
            {
              "file": "lower_a/v0.png",   // relative to store root
              "baseline_y": 70,            // baseline row within the image
              "advance_width": 52.1,       // this variant's pen advance
              "left_bearing": 3.2,         // pen x -> image left edge
              "right_bearing": 2.9,        // image right edge -> next pen x
              "ink_bbox": [2, 2, 48, 68]   // ink bounds within the image
            }, ...
          ]
        },
        " ": {"folder": null, "advance_width": 30.0, "variants": []}
      }
    }

Ink-less characters (space) have no variant images; their entry-level
advance_width is what the layout engine uses. Renderer contract: paste a
variant image with its left edge at pen_x + left_bearing and its baseline_y
row on the line's baseline, then advance the pen by advance_width.

Only the glyph selector and renderer may load glyph images (Phase 2 will
extend exactly these components with math-symbol glyphs).
"""

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1


@dataclass(frozen=True)
class GlyphVariant:
    file: str
    baseline_y: int
    advance_width: float
    left_bearing: float
    right_bearing: float
    ink_bbox: tuple[int, int, int, int]


@dataclass(frozen=True)
class GlyphEntry:
    char: str
    advance_width: float
    variants: tuple[GlyphVariant, ...]


class GlyphStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        manifest_path = self.root / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version = manifest.get("version")
        if version != MANIFEST_VERSION:
            raise ValueError(
                f"unsupported manifest version {version!r} in {manifest_path}"
            )
        self.native_size_px: float = manifest["native_size_px"]
        self._entries: dict[str, GlyphEntry] = {}
        for char, data in manifest["characters"].items():
            variants = tuple(
                GlyphVariant(
                    file=v["file"],
                    baseline_y=v["baseline_y"],
                    advance_width=v["advance_width"],
                    left_bearing=v["left_bearing"],
                    right_bearing=v["right_bearing"],
                    ink_bbox=tuple(v["ink_bbox"]),
                )
                for v in data["variants"]
            )
            self._entries[char] = GlyphEntry(
                char=char, advance_width=data["advance_width"], variants=variants
            )

    def __contains__(self, char: str) -> bool:
        return char in self._entries

    def entry(self, char: str) -> GlyphEntry:
        return self._entries[char]

    @property
    def characters(self) -> list[str]:
        return list(self._entries)

    def load_image(self, variant: GlyphVariant) -> Image.Image:
        img = Image.open(self.root / variant.file)
        return img if img.mode == "RGBA" else img.convert("RGBA")

    def coverage_report(self, expected: str | None = None) -> str:
        inked = {c: e for c, e in self._entries.items() if e.variants}
        inkless = [c for c, e in self._entries.items() if not e.variants]
        lines = [
            f"characters: {len(self._entries)} total "
            f"({len(inked)} with ink variants, ink-less: {inkless!r})",
        ]
        if inked:
            counts = sorted(len(e.variants) for e in inked.values())
            total = sum(counts)
            lines.append(
                f"variants per inked char: min {counts[0]}, max {counts[-1]}, "
                f"total {total} images"
            )
            under = [c for c, e in inked.items() if len(e.variants) < 3]
            if under:
                lines.append(f"chars with <3 variants: {under!r}")
        if expected is not None:
            missing = [c for c in expected if c not in self._entries]
            lines.append(f"missing from expected set: {missing!r}" if missing
                         else "missing from expected set: none")
        return "\n".join(lines)
