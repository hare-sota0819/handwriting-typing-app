"""Render a LIST of LaTeX equations as handwriting, into one labelled PDF.

The docx-free sibling of render_docx_math.py: same spike chain, same contact
sheet, but the equations come from a plain text file (one LaTeX string per
line, `#` comments and blanks skipped) instead of a document. Exists so a
test set can be re-rendered from ANY session with one command — the sqrt
before/after work of 2026-08-10 was first driven from a session-local script,
which a later chat could not see or reproduce.

Run: .venv/bin/python scripts/render_math_set.py samples/eqs_sqrt_test.txt --out out/sqrt_test.pdf
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_docx_math import SPIKE, ROOT, contact_sheet, run  # noqa: E402


def load_equations(path: Path) -> list[dict]:
    eqs = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        eqs.append({"id": f"eq{len(eqs):03d}", "latex": line, "display": True})
    if not eqs:
        raise SystemExit(f"no equations in {path}")
    return eqs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("eqfile", type=Path,
                    help="text file, one LaTeX equation per line")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--store", type=Path, default=None,
                    help="glyph store (default: handwriting.stores.default_store)")
    args = ap.parse_args()

    equations = load_equations(args.eqfile)
    print(f"{args.eqfile.name}: {len(equations)} equations")
    (SPIKE / "out").mkdir(parents=True, exist_ok=True)
    (SPIKE / "out" / "equations.json").write_text(
        json.dumps(equations, ensure_ascii=False, indent=1), encoding="utf-8")

    run(["node", str(SPIKE / "tex2svg.js")])
    run([sys.executable, str(SPIKE / "parse_svg.py")])
    run([sys.executable, str(SPIKE / "render_placement.py"),
         *([f"--store={args.store}"] if args.store else [])])

    images = []
    for eq in equations:
        p = SPIKE / "out" / "hand" / f"hand_{eq['id']}.png"
        if p.exists():
            images.append((eq["id"].replace("eq", "#"), Image.open(p)))
    if not images:
        print("no equations rendered", file=sys.stderr)
        return 1

    pages = contact_sheet(images)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(args.out, save_all=True, append_images=pages[1:])
    print(f"{len(images)} equations -> {args.out} ({len(pages)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
