"""Build side-by-side verification pages: MathJax's own render (left) vs the
same SVG with red boxes/labels drawn at OUR computed absolute coordinates
(right, in root viewBox space — i.e. AFTER resolving the transform chains).
If the parser's coordinate math is wrong, the boxes miss their symbols.

Writes spike/out/overlay/<id>.html (screenshotted to spike/debug/ separately).

Run: .venv/bin/python spike/make_overlays.py
"""

import json
import re
from pathlib import Path

SPIKE = Path(__file__).resolve().parent
OUT = SPIKE / "out" / "overlay"

PAGE = """<!doctype html><meta charset="utf-8">
<body style="margin:20px;font-family:sans-serif;background:#fff">
<h3 style="margin:0 0 4px">{id}</h3>
<code style="font-size:12px">{latex}</code>
<div style="display:flex;gap:40px;margin-top:12px;align-items:flex-start">
<div><div style="font-size:12px;color:#555">MathJax render</div>{plain}</div>
<div><div style="font-size:12px;color:#555">parsed placements overlay</div>{overlay}</div>
</div></body>"""


def overlay_svg(svg_text, placement):
    """Append an overlay <g> in ROOT viewBox coordinates (y-down, em*1000)."""
    parts = []
    for el in placement["elements"]:
        if el["kind"] == "rule":
            x, y, w, h = el["x"] * 1000, el["y"] * 1000, el["w"] * 1000, el["h"] * 1000
            label = el["role"]
            color = "#0a0"
        else:
            bb = el["bbox"]
            x, y, w, h = bb["x"] * 1000, bb["y"] * 1000, bb["w"] * 1000, bb["h"] * 1000
            label = el["codepoint"].replace("U+", "")
            color = "#c00" if el["kind"] == "symbol" else "#06c"
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" '
            f'stroke="{color}" stroke-width="14"/>'
            f'<text x="{x}" y="{y - 25}" font-size="120" fill="{color}" '
            f'font-family="monospace">{label}</text>'
        )
        if el["kind"] != "rule":
            # glyph origin (pen position) as a crosshair
            ox, oy = el["x"] * 1000, el["y"] * 1000
            parts.append(
                f'<line x1="{ox - 60}" y1="{oy}" x2="{ox + 60}" y2="{oy}" '
                f'stroke="#f80" stroke-width="14"/>'
                f'<line x1="{ox}" y1="{oy - 60}" x2="{ox}" y2="{oy + 60}" '
                f'stroke="#f80" stroke-width="14"/>'
            )
    # faded ink underneath the boxes
    svg_text = svg_text.replace(
        '<g stroke="currentColor"', '<g opacity="0.35" stroke="currentColor"', 1)
    return svg_text.replace("</svg>", "<g>" + "".join(parts) + "</g></svg>")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    eqs = json.loads((SPIKE / "out" / "equations.json").read_text())
    for eq in eqs:
        svg_text = (SPIKE / "out" / "svg" / f"{eq['id']}.svg").read_text()
        placement = json.loads(
            (SPIKE / "out" / "placements" / f"{eq['id']}.json").read_text())
        # render both at a fixed large size for pixel comparison
        big = re.sub(r'width="[\d.]+ex" height="[\d.]+ex"',
                     f'width="{placement["width"] * 60}px" '
                     f'height="{placement["em_height"] * 60}px"', svg_text)
        html = PAGE.format(id=eq["id"], latex=eq["latex"].replace("\\", "\\\\"),
                           plain=big, overlay=overlay_svg(big, placement))
        (OUT / f"{eq['id']}.html").write_text(html)
        print(f"{eq['id']}.html")


if __name__ == "__main__":
    main()
