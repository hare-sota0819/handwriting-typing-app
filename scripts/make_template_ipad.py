"""Generate the iPad collection PILOT template (10 chars x 2 variants).

Per the pilot brief: EVERYTHING printed on the template (guides, cell
borders, labels, corner markers) is light CYAN — nothing black — so Tool 2b
(split_ipad.py) removes template furniture by COLOR KEY, never by brightness,
and dark Apple-Pencil ink can never collide with it. Otherwise the geometry
is identical to the print template (A4 @ 150 dpi, cell 84x132, same guide
fractions and layout-JSON schema).

Markers are saturated cyan: still trivially detectable by hue for the ±2px
placement sanity check, but excluded from ink by color.

Workflow: import template/ipad_pilot/template.pdf into GoodNotes, write one
glyph per cell (letter BODY on the thick baseline guide, descenders below,
dark default pen), then export the SAME written page in every available
{Editable, Flattened} x {Include Page Background on/off} combination and
hand all exports to scripts/split_ipad.py --inspect first.

Run: .venv/bin/python scripts/make_template_ipad.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_template  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CHARSET = REPO / "template" / "charset_ipad_pilot.txt"
OUT_DIR = REPO / "template" / "ipad_pilot"
N_CELLS = 2

# Cyan palette (brief divergence #1): hue-keyed furniture, no black anywhere.
MARKER_COLOR = (0, 165, 175)          # saturated cyan fiducials
CELL_BORDER = (140, 205, 210)
GUIDE_COLOR = (175, 225, 230)         # ascender / x-height / descender
GUIDE_BASELINE_COLOR = (140, 205, 210)  # baseline: same hue, thicker line
LABEL_COLOR = (90, 180, 190)


def generate():
    # module-level overrides scoped to the pilot generator; the print
    # template path (make_template.main) is untouched on disk
    make_template.MARKER_COLOR = MARKER_COLOR
    make_template.CELL_BORDER = CELL_BORDER
    make_template.GUIDE_COLOR = GUIDE_COLOR
    make_template.GUIDE_BASELINE_COLOR = GUIDE_BASELINE_COLOR
    make_template.LABEL_COLOR = LABEL_COLOR
    charset = make_template.load_charset(CHARSET)
    return make_template.generate(
        out_dir=OUT_DIR, n_cells=N_CELLS, charset=charset, lossless_pdf=True)


def main():
    pdf_path, json_path = generate()
    print()
    print("GoodNotes steps for the pilot:")
    print(f"  1. Import {pdf_path} as a document.")
    print("  2. Write each cell's character with the Apple Pencil: body on the")
    print("     thick baseline guide, descender below it, dark default pen.")
    print("  3. Export the SAME written page in EVERY available combination of")
    print("     {Editable, Flattened} x {Include Page Background on/off}.")
    print("  4. Run: .venv/bin/python scripts/split_ipad.py --inspect <exports...>")


if __name__ == "__main__":
    main()
