"""The maths letterforms, as a short sheet of their own.

`math:x` / `math:y` — the user writes these letters differently in an equation
than in prose. They are collected under their own keys so the maths form and the
prose form can never substitute for each other; the renderer picks the maths form
for MathJax's italic variables.

NOT folded into the collection template, even though one file would beat two: the
user was already most of the way through writing the 31-page sheet when this came
up, and changing its layout would put every cell out of register with what they
had written. The integrals (∫ ∬ ∭ ∮) are already in the collection charset, so
this sheet is the two letters and nothing else.

Everything else about the sheet — cell size, guides, marker geometry, the cyan
colour key — is the collection template's, so the export recipe and split_ipad
work unchanged.

Run:  .venv/bin/python scripts/make_template_rewrite.py
Then: .venv/bin/python scripts/split_ipad.py <export.pdf> \
        --layout template/rewrite/template_layout.json --out glyphs/ipad_rewrite
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import make_template_collection as mtc  # noqa: E402

OUT_DIR = REPO / "template" / "rewrite"

ENTRIES = [
    ("math:x", "x   as you write it IN AN EQUATION"),
    ("math:y", "y   as you write it IN AN EQUATION"),
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
