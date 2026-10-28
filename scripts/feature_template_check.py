"""Tool 1 verification: grid template generator.

Checks the generated template PDF + template_layout.json: every store character
gets N cell rects, 4 corner markers per page at the expected corners, cells lie
inside the page and don't overlap, and the PDF has the recorded page count.
Exit 0 = pass.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_template
from handwriting.compositor import rasterize_pdf

N_CELLS = 5
# Charset comes from the same data file the generator uses — no hardcoded set,
# so this check stays correct for ANY charset the file is swapped to.
CHARSET = make_template.load_charset(make_template.DEFAULT_CHARSET)


def overlaps(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def main() -> int:
    failures: list[str] = []
    # Generate into a throwaway dir so verify.sh never dirties the committed
    # template/ deliverable.
    out_dir = Path(__file__).resolve().parents[1] / "out" / "template_check"
    pdf, jpath = make_template.generate(out_dir, n_cells=N_CELLS)
    layout = json.loads(Path(jpath).read_text(encoding="utf-8"))

    cell_w = layout.get("cell_w")
    cell_h = layout.get("cell_h")
    if layout.get("native_size_px") != cell_h:
        failures.append("native_size_px should equal cell_h")
    if not (cell_w and cell_h and cell_h > cell_w):
        failures.append(f"cells must be portrait (cell_h > cell_w): {cell_w}x{cell_h}")

    # guide fractions ordered, with visible top/bottom padding and roomy zones.
    gf = layout.get("guide_fractions")
    if not gf or not (gf.get("ascender") < gf.get("x_height") < gf.get("baseline") < gf.get("descender")):
        failures.append(f"guide_fractions missing or not ordered: {gf}")
    else:
        if not (gf["ascender"] > 0.05):
            failures.append(f"no top padding above ascender: {gf['ascender']}")
        if not (gf["descender"] < 0.95):
            failures.append(f"no bottom padding below descender: {gf['descender']}")
        if not (gf["baseline"] - gf["x_height"] >= 0.15):
            failures.append(f"x-body band too cramped: {gf['baseline'] - gf['x_height']:.3f}")
        if not (gf["descender"] - gf["baseline"] >= 0.12):
            failures.append(f"descender zone too cramped: {gf['descender'] - gf['baseline']:.3f}")

    # every character present with exactly N cell rects
    per_char: dict[str, int] = {}
    W, H = layout["page_px"]
    for page in layout["pages"]:
        if len(page["markers"]) != 4:
            failures.append(f"page {page['index']}: expected 4 markers")
        # markers at the four corners (top-left smallest, bottom-right largest)
        xs = [m[0] for m in page["markers"]]
        ys = [m[1] for m in page["markers"]]
        if not (min(xs) < W / 2 < max(xs) and min(ys) < H / 2 < max(ys)):
            failures.append(f"page {page['index']}: markers don't span the page corners")
        cells = page["cells"]
        for c in cells:
            per_char[c["char"]] = per_char.get(c["char"], 0) + 1
            x0, y0, x1, y1 = c["rect"]
            if not (0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H):
                failures.append(f"cell {c['char']}#{c['index']} out of page bounds")
            # four writing guides present, strictly top-to-bottom, inside the cell
            g = c.get("guides")
            if not g or any(k not in g for k in ("ascender", "x_height", "baseline", "descender")):
                failures.append(f"cell {c['char']}#{c['index']} missing guides")
            else:
                ys = [g["ascender"], g["x_height"], g["baseline"], g["descender"]]
                if not (ys[0] < ys[1] < ys[2] < ys[3]):
                    failures.append(
                        f"cell {c['char']}#{c['index']} guides not ordered "
                        f"ascender<x_height<baseline<descender: {ys}")
                # visible padding: ascender below the top, descender above the bottom
                if not (ys[0] > y0 and ys[3] < y1):
                    failures.append(
                        f"cell {c['char']}#{c['index']} guides touch cell border {ys} vs [{y0},{y1}]")
        # no two cells on a page overlap
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                if overlaps(cells[i]["rect"], cells[j]["rect"]):
                    failures.append(
                        f"page {page['index']}: cells overlap "
                        f"({cells[i]['char']}#{cells[i]['index']} & "
                        f"{cells[j]['char']}#{cells[j]['index']})"
                    )
                    break
            else:
                continue
            break

    missing = [c for c in CHARSET if per_char.get(c, 0) != N_CELLS]
    if missing:
        failures.append(f"chars without exactly {N_CELLS} cells: {missing!r}")
    if set(per_char) != set(CHARSET):
        failures.append("layout characters differ from the store charset")

    pages = rasterize_pdf(pdf, tuple(layout["page_px"]))
    if len(pages) != len(layout["pages"]):
        failures.append(f"PDF pages {len(pages)} != layout pages {len(layout['pages'])}")

    total = sum(len(p["cells"]) for p in layout["pages"])
    print(f"template: {len(CHARSET)} chars x {N_CELLS} = {total} cells, "
          f"{len(layout['pages'])} pages, cell {layout['cell_w']}x{layout['cell_h']}px")
    print()
    if failures:
        print(f"FAIL ({len(failures)} problems):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: template generator checks all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
