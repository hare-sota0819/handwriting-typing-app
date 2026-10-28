"""Merge one glyph store into another, entry by entry.

Used when a short re-write sheet is collected separately from the main sheet:
the new entries replace same-key entries in the target and are added otherwise,
and everything else in the target is left alone. Both stores must share the same
native_size_px, since every downstream measurement is in those units.

Run: .venv/bin/python scripts/merge_store.py glyphs/ipad_rewrite glyphs/ipad
"""

import argparse
import json
import shutil
import sys
from pathlib import Path


def merge(src: Path, dst: Path) -> int:
    src_m = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    dst_m = json.loads((dst / "manifest.json").read_text(encoding="utf-8"))
    if src_m["native_size_px"] != dst_m["native_size_px"]:
        raise SystemExit(
            f"native_size_px differs ({src_m['native_size_px']} vs "
            f"{dst_m['native_size_px']}); the stores are not comparable")

    for key, entry in src_m["characters"].items():
        folder = entry.get("folder")
        if not folder or not entry.get("variants"):
            continue          # e.g. the space entry, which owns no images
        target = dst / folder
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src / folder, target)
        dst_m["characters"][key] = entry
        print(f"  {key!r} -> {folder} ({len(entry['variants'])} variants)")

    (dst / "manifest.json").write_text(
        json.dumps(dst_m, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(src_m["characters"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", type=Path, help="store to merge FROM")
    ap.add_argument("dst", type=Path, help="store to merge INTO (modified)")
    args = ap.parse_args(argv)
    n = merge(args.src, args.dst)
    print(f"merged {n} entries into {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
