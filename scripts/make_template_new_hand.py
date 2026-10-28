"""Sheet for a whole new English hand: the prose set plus its maths letterforms.

The full English set (template/charset_default.txt: letters, digits,
punctuation) followed by the letters the user draws differently inside
equations. Those five were found by comparing the user's own homework notes
(MAS557 HW3) letter by letter: x is curled, y has no tail, the subscript i ends
in a right-curving hook, Z carries a crossbar, and C (the combinatorial
coefficient) is its own shape. Every other letter the equations use matched
the prose form, so it has no separate maths cell.

A separate sheet rather than an edit to make_template_rewrite.py: that sheet's
layout matches the x/y export the user already wrote, and changing it would put
the old export out of register.

Run:  .venv/bin/python scripts/make_template_new_hand.py
Then: .venv/bin/python scripts/split_ipad.py <export.pdf> \
        --layout template/new_hand/template_layout.json --out glyphs/<new_store>
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import make_template_collection as mtc  # noqa: E402

OUT_DIR = REPO / "template" / "new_hand"

ENTRIES = [(ch, ch) for ch in mtc.mt.load_charset(REPO / "template" / "charset_default.txt")] + [
    ("math:x", "x   as you write it IN AN EQUATION"),
    ("math:y", "y   as you write it IN AN EQUATION"),
    ("math:i", "i   as you write it IN AN EQUATION"),
    ("math:Z", "Z   as you write it IN AN EQUATION"),
    ("math:C", "C   as you write it IN AN EQUATION"),
]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    variants = 10
    for a in argv:
        if a.startswith("--variants="):
            variants = int(a.split("=", 1)[1])
    specs = mtc.build_specs_explicit(ENTRIES, variants)
    mtc.generate(out_dir=OUT_DIR, n_variants=variants, specs=specs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
