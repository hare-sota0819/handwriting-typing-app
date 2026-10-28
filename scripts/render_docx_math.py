"""Render EVERY equation in a .docx as handwriting, into one contact-sheet PDF.

Drives the spike chain end to end so a whole document can be eyeballed at once:

    .docx --pandoc--> LaTeX --tex2svg.js--> SVG --parse_svg--> placement JSON
          --render_placement--> one PNG per equation --> a single PDF

One PDF rather than a pile of PNGs: reviewing 50+ equations by opening 50+ files
is what makes render defects go unnoticed. Each equation is numbered so a
problem can be reported by index.

Run: .venv/bin/python scripts/render_docx_math.py samples/foo.docx --out out/foo.pdf
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SPIKE = ROOT / "spike"
sys.path.insert(0, str(ROOT))
from handwriting.mathrender import fix_latex, quiet_run, _default_pandoc  # noqa: E402
PANDOC = _default_pandoc()

# pandoc writes inline math as \( .. \) and display math as \[ .. \]
MATH_RE = re.compile(r"\\\((.+?)\\\)|\\\[(.+?)\\\]", re.S)

# Resolution is never traded against anything: "랜더는 무조건무조건무조건
# 최고해상도로 뽑아야 해." Glyph size is a separate axis the user controls; big
# letters on a coarse raster still look bad, so the sheet is built at 400 dpi.
DPI = 400
PAGE_W, PAGE_H = round(8.27 * DPI), round(11.69 * DPI)      # A4
PAGE_MARGIN = round(0.4 * DPI)
GAP = round(0.19 * DPI)
LABEL_W = round(0.6 * DPI)


def extract_latex(docx_path: Path, pandoc: Path = PANDOC) -> list[dict]:
    """Every equation in document order, as MathJax-ready LaTeX."""
    tex = quiet_run(
        [str(pandoc), str(docx_path), "-t", "latex"],
        capture_output=True, text=True, encoding="utf-8", check=True).stdout
    out = []
    for i, m in enumerate(MATH_RE.finditer(tex)):
        inline, display = m.groups()
        latex = fix_latex(" ".join((inline or display).split()))
        out.append({"id": f"eq{i:03d}", "latex": latex,
                    "display": display is not None})
    return out


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL if "-q" in sys.argv else None)


def contact_sheet(images: list[tuple[str, Image.Image]]) -> list[Image.Image]:
    """Stack the rendered equations down A4 pages, each tagged with its index."""
    try:
        font = ImageFont.truetype(
            str(ROOT / "handwriting" / "data" / "DejaVuSans.ttf"),
            round(DPI / 7))
    except OSError:
        font = ImageFont.load_default()

    max_w = PAGE_W - 2 * PAGE_MARGIN - LABEL_W
    # ONE scale for every equation. Shrinking only the wide ones made a long
    # equation render smaller than a short one on the same sheet, which the user
    # called out: "수식을 들쭉날쭉한 사이즈로 쳐뽑지말고 다 같은 사이즈로".
    widest = max(im.width for _, im in images)
    sheet_scale = min(1.0, max_w / widest) if widest else 1.0
    pages, page, y = [], None, 0
    for label, im in images:
        if sheet_scale < 1.0:
            im = im.resize((max(1, round(im.width * sheet_scale)),
                            max(1, round(im.height * sheet_scale))), Image.LANCZOS)
        if page is None or y + im.height > PAGE_H - PAGE_MARGIN:
            page = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
            pages.append(page)
            y = PAGE_MARGIN
        draw = ImageDraw.Draw(page)
        draw.text((PAGE_MARGIN, y + im.height // 2 - DPI // 14), label,
                  fill=(190, 60, 60), font=font)
        page.paste(im.convert("RGB"), (PAGE_MARGIN + LABEL_W, y))
        y += im.height + GAP
    return pages


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("docx", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--store", type=Path, default=None,
                    help="glyph store (default: handwriting.stores.default_store)")
    ap.add_argument("--raw-pen", action="store_true",
                    help="leave stroke weight exactly as written (by default it is "
                         "re-weighted to one width after scaling, because per-glyph "
                         "scaling otherwise mixes weights inside a single word)")
    args = ap.parse_args()

    equations = extract_latex(args.docx)
    print(f"{args.docx.name}: {len(equations)} equations")
    (SPIKE / "out").mkdir(parents=True, exist_ok=True)
    (SPIKE / "out" / "equations.json").write_text(
        json.dumps(equations, ensure_ascii=False, indent=1), encoding="utf-8")

    run(["node", str(SPIKE / "tex2svg.js")])
    run([sys.executable, str(SPIKE / "parse_svg.py")])
    cmd = [sys.executable, str(SPIKE / "render_placement.py"),
           *([f"--store={args.store}"] if args.store else [])]
    if args.raw_pen:
        cmd.append("--raw-pen")
    run(cmd)

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
