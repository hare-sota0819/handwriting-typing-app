"""Parse MathJax v3 SVG output into absolute per-symbol placement lists.

Reads spike/out/svg/<id>.svg (produced by tex2svg.js), resolves every
<use>/<rect> through its transform chain (translate/scale/matrix, including
the root scale(1,-1) y-flip) and writes spike/out/placements/<id>.json.

COORDINATE CONVENTION of the output (documented in REPORT.md):
  - units: em (MathJax viewBox units / 1000)
  - x grows right; y grows DOWN; y = 0 is the equation's main baseline
  - each symbol's (x, y) is its glyph ORIGIN (pen position on its own
    baseline); bbox is the transformed ink bounding box {x, y, w, h} with
    y = top edge.

Run: .venv/bin/python spike/parse_svg.py
"""

import json
import os
import math
import re
import unicodedata
from pathlib import Path
from xml.etree import ElementTree as ET

SPIKE = Path(__file__).resolve().parent
# HW_MATH_OUT overrides the working dir (see tex2svg.js).
OUT_ROOT = Path(os.environ.get("HW_MATH_OUT") or SPIKE / "out")
SVG_DIR = OUT_ROOT / "svg"
OUT_DIR = OUT_ROOT / "placements"

SVG_NS = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"

# ---------------------------------------------------------------- transforms


def mat_mul(a, b):
    """3x3 (as 6-tuple a,b,c,d,e,f svg-style) multiply: a then apply b? No —
    result = a @ b, i.e. b is applied first, then a (SVG child order)."""
    a0, a1, a2, a3, a4, a5 = a
    b0, b1, b2, b3, b4, b5 = b
    return (
        a0 * b0 + a2 * b1,
        a1 * b0 + a3 * b1,
        a0 * b2 + a2 * b3,
        a1 * b2 + a3 * b3,
        a0 * b4 + a2 * b5 + a4,
        a1 * b4 + a3 * b5 + a5,
    )


IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def parse_transform(s):
    """SVG transform attribute -> 6-tuple matrix."""
    m = IDENT
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(t) for t in re.split(r"[\s,]+", args.strip()) if t]
        if name == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "matrix":
            t = tuple(v)
        else:
            raise ValueError(f"unhandled transform {name}")
        m = mat_mul(m, t)
    return m


def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


# ---------------------------------------------------------------- path bbox


def path_bbox(d):
    """Bounding box of an SVG path's anchor+sampled-curve points.
    Supports the commands MathJax TeX fonts emit (M L H V Q T C S Z, abs+rel).
    Curves are sampled, so the box is the true ink box within ~1 unit."""
    tokens = re.findall(r"[A-Za-z]|-?\d*\.?\d+(?:e-?\d+)?", d)
    i = 0
    cx = cy = 0.0  # current point
    sx = sy = 0.0  # subpath start
    pqx = pqy = None  # previous quadratic control (for T)
    pcx = pcy = None  # previous cubic control (for S)
    xs, ys = [], []
    cmd = None

    def num():
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    def add(x, y):
        xs.append(x)
        ys.append(y)

    def sample_q(x0, y0, qx, qy, x1, y1):
        for t in (0.25, 0.5, 0.75):
            mt = 1 - t
            add(mt * mt * x0 + 2 * mt * t * qx + t * t * x1,
                mt * mt * y0 + 2 * mt * t * qy + t * t * y1)

    def sample_c(x0, y0, c1x, c1y, c2x, c2y, x1, y1):
        for t in (0.25, 0.5, 0.75):
            mt = 1 - t
            add(mt**3 * x0 + 3 * mt * mt * t * c1x + 3 * mt * t * t * c2x + t**3 * x1,
                mt**3 * y0 + 3 * mt * mt * t * c1y + 3 * mt * t * t * c2y + t**3 * y1)

    while i < len(tokens):
        if re.match(r"[A-Za-z]", tokens[i]):
            cmd = tokens[i]
            i += 1
        rel = cmd.islower()
        c = cmd.upper()
        if c == "Z":
            cx, cy = sx, sy
            continue
        if c == "M":
            x, y = num(), num()
            if rel:
                x, y = cx + x, cy + y
            cx, cy = sx, sy = x, y
            add(cx, cy)
            cmd = "l" if rel else "L"  # implicit lineto after moveto
            pqx = pcx = None
            continue
        if c == "L":
            x, y = num(), num()
            if rel:
                x, y = cx + x, cy + y
            cx, cy = x, y
            add(cx, cy)
            pqx = pcx = None
            continue
        if c == "H":
            x = num()
            cx = cx + x if rel else x
            add(cx, cy)
            pqx = pcx = None
            continue
        if c == "V":
            y = num()
            cy = cy + y if rel else y
            add(cx, cy)
            pqx = pcx = None
            continue
        if c == "Q":
            qx, qy, x, y = num(), num(), num(), num()
            if rel:
                qx, qy, x, y = cx + qx, cy + qy, cx + x, cy + y
            sample_q(cx, cy, qx, qy, x, y)
            pqx, pqy = qx, qy
            cx, cy = x, y
            add(cx, cy)
            pcx = None
            continue
        if c == "T":
            x, y = num(), num()
            if rel:
                x, y = cx + x, cy + y
            qx = 2 * cx - pqx if pqx is not None else cx
            qy = 2 * cy - pqy if pqy is not None else cy
            sample_q(cx, cy, qx, qy, x, y)
            pqx, pqy = qx, qy
            cx, cy = x, y
            add(cx, cy)
            pcx = None
            continue
        if c == "C":
            c1x, c1y, c2x, c2y, x, y = (num() for _ in range(6))
            if rel:
                c1x, c1y, c2x, c2y, x, y = (cx + c1x, cy + c1y, cx + c2x,
                                            cy + c2y, cx + x, cy + y)
            sample_c(cx, cy, c1x, c1y, c2x, c2y, x, y)
            pcx, pcy = c2x, c2y
            cx, cy = x, y
            add(cx, cy)
            pqx = None
            continue
        if c == "S":
            c2x, c2y, x, y = num(), num(), num(), num()
            if rel:
                c2x, c2y, x, y = cx + c2x, cy + c2y, cx + x, cy + y
            c1x = 2 * cx - pcx if pcx is not None else cx
            c1y = 2 * cy - pcy if pcy is not None else cy
            sample_c(cx, cy, c1x, c1y, c2x, c2y, x, y)
            pcx, pcy = c2x, c2y
            cx, cy = x, y
            add(cx, cy)
            pqx = None
            continue
        if c == "A":
            # arcs don't occur in MathJax TeX fonts; endpoint only (coarse)
            for _ in range(5):
                num()
            x, y = num(), num()
            if rel:
                x, y = cx + x, cy + y
            cx, cy = x, y
            add(cx, cy)
            continue
        raise ValueError(f"unhandled path cmd {cmd}")
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------- extraction

RULE_ROLES = {"mfrac": "frac_bar", "msqrt": "sqrt_bar", "mroot": "sqrt_bar",
              "munder": "underline", "mover": "overline"}


def base_char(ch):
    """Math-alphanumeric (e.g. U+1D447 MATH ITALIC T) -> plain char 'T'."""
    d = unicodedata.decomposition(ch)
    m = re.fullmatch(r"<font> ([0-9A-F]{4,6})", d)
    return chr(int(m.group(1), 16)) if m else ch


def font_variant(href):
    """'#MJX-1-TEX-I-1D447' -> 'I' (italic); S1..S4 = size variants."""
    m = re.search(r"-TEX-([A-Z0-9]+)-[0-9A-F]+$", href or "")
    return m.group(1) if m else "?"


def extract(svg_path):
    text = svg_path.read_text(encoding="utf-8")
    root = ET.fromstring(text)
    vb = [float(v) for v in root.get("viewBox").split()]
    defs = {}
    for p in root.iter(f"{SVG_NS}path"):
        if p.get("id"):
            defs[p.get("id")] = path_bbox(p.get("d"))

    elements = []

    def walk(node, m, mml_stack):
        tag = node.tag.replace(SVG_NS, "")
        if tag == "defs":
            return
        mml = node.get("data-mml-node")
        stack = mml_stack + [mml] if mml else mml_stack
        m = mat_mul(m, parse_transform(node.get("transform")))
        if tag == "use":
            ox = float(node.get("x") or 0)
            oy = float(node.get("y") or 0)
            ax, ay = apply(m, ox, oy)
            sx = math.hypot(m[0], m[1])
            href = node.get(XLINK) or node.get("href")
            cp = int(node.get("data-c"), 16)
            ch = chr(cp)
            bb = defs.get(href.lstrip("#")) if href else None
            if bb is None:
                # empty path = invisible operator (U+2061 function application,
                # U+2062 invisible times, ...): no ink, nothing to place
                return
            el = {
                "kind": "symbol",
                "codepoint": f"U+{cp:04X}",
                "char": ch,
                "base_char": base_char(ch),
                "font": font_variant(href),
                "x": ax / 1000,
                "y": ay / 1000,
                "scale": sx,
                "mml": stack[-1] if stack else None,
            }
            if bb:
                corners = [apply(m, bb[0] + ox, bb[1] + oy),
                           apply(m, bb[2] + ox, bb[1] + oy),
                           apply(m, bb[0] + ox, bb[3] + oy),
                           apply(m, bb[2] + ox, bb[3] + oy)]
                x0 = min(c[0] for c in corners) / 1000
                x1 = max(c[0] for c in corners) / 1000
                y0 = min(c[1] for c in corners) / 1000
                y1 = max(c[1] for c in corners) / 1000
                el["bbox"] = {"x": round(x0, 4), "y": round(y0, 4),
                              "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}
            # size-variant fonts (S1..S4) = stretched/large forms
            if el["font"].startswith("S") and el["font"][1:].isdigit():
                el["kind"] = "stretchy"
            el["x"] = round(el["x"], 4)
            el["y"] = round(el["y"], 4)
            el["scale"] = round(el["scale"], 4)
            elements.append(el)
        elif tag == "rect":
            x, y = float(node.get("x") or 0), float(node.get("y") or 0)
            w, h = float(node.get("width")), float(node.get("height"))
            corners = [apply(m, x, y), apply(m, x + w, y),
                       apply(m, x, y + h), apply(m, x + w, y + h)]
            x0 = min(c[0] for c in corners) / 1000
            x1 = max(c[0] for c in corners) / 1000
            y0 = min(c[1] for c in corners) / 1000
            y1 = max(c[1] for c in corners) / 1000
            # A stroked, unfilled rect is a FRAME (\boxed{}, menclose box):
            # only its outline is ink. Recorded with the stroke width so the
            # renderer draws four strokes, not one filled bar across the box.
            fill = (node.get("fill") or "").strip().lower()
            if fill == "none":
                sw = float(node.get("stroke-width") or 0) * abs(m[0]) / 1000
                elements.append({
                    "kind": "frame",
                    "x": round(x0, 4), "y": round(y0, 4),
                    "w": round(x1 - x0, 4), "h": round(y1 - y0, 4),
                    "stroke": round(sw, 4),
                })
                return
            role = "unknown"
            for anc in reversed(mml_stack):
                if anc in RULE_ROLES:
                    role = RULE_ROLES[anc]
                    break
            elements.append({
                "kind": "rule",
                "x": round(x0, 4), "y": round(y0, 4),
                "w": round(x1 - x0, 4), "h": round(y1 - y0, 4),
                "role": role,
            })
        for child in node:
            walk(child, m, stack)

    walk(root, IDENT, [])
    return {
        "em_height": round(vb[3] / 1000, 4),
        "ascent": round(-vb[1] / 1000, 4),
        "descent": round((vb[3] + vb[1]) / 1000, 4),
        "width": round(vb[2] / 1000, 4),
        "elements": elements,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    eqs = json.loads((OUT_ROOT / "equations.json").read_text(encoding="utf-8"))
    for eq in eqs:
        res = extract(SVG_DIR / f"{eq['id']}.svg")
        res = {"id": eq["id"], "latex": eq["latex"], **res}
        out = OUT_DIR / f"{eq['id']}.json"
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        kinds = [e["kind"] for e in res["elements"]]
        print(f"{eq['id']}: {len(res['elements'])} elements "
              f"({kinds.count('symbol')} sym, {kinds.count('rule')} rule, "
              f"{kinds.count('stretchy')} stretchy)")


if __name__ == "__main__":
    main()
