"""Stack the pixel-matched MathJax reference over the handwriting-substituted
render -> spike/debug/geom_<id>.png (geometry-validation evidence).

Run: .venv/bin/python spike/compose_compare.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SPIKE = Path(__file__).resolve().parent
FONT = ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)

IDS = ["eq1_pendulum", "eq2_alpha", "eq3_k", "eq4_inertia", "eq5a_omega",
       "eq5b_smallangle", "eq6_stretchy", "eq7_integral"]

for eq_id in IDS:
    ref = Image.open(SPIKE / "out" / "ref" / f"ref_{eq_id}.png").convert("RGB")
    hand = Image.open(SPIKE / "out" / "hand" / f"hand_{eq_id}.png").convert("RGB")
    w = max(ref.width, hand.width)
    label_h = 26
    out = Image.new("RGB", (w, ref.height + hand.height + 2 * label_h + 12),
                    (255, 255, 255))
    d = ImageDraw.Draw(out)
    d.text((8, 4), f"{eq_id} — MathJax reference", fill=(80, 80, 90), font=FONT)
    out.paste(ref, (0, label_h))
    y2 = label_h + ref.height + 12
    d.text((8, y2 + 4 - label_h + label_h - 26 + 4),
           "handwriting substitution (gray = to-collect placeholder)",
           fill=(80, 80, 90), font=FONT)
    out.paste(hand, (0, y2 + label_h))
    out.save(SPIKE / "debug" / f"geom_{eq_id}.png")
    print(f"geom_{eq_id}.png {out.size}")
