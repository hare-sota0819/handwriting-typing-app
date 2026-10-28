"""The leftwards double arrow, as a short sheet of its own.

`⇐` was never in any collection charset, so `\\Leftarrow` (and `\\Longleftarrow`,
which aliases onto it) drew a grey placeholder box — the same failure the
permittivity `ϵ` hit on 2026-09-20. Its partner `⇒` was collected; this one
simply got missed.

Not folded into the collection charset: the 31-page sheet is already written,
and adding a cell would put every page of it out of register. One entry, one
page, split into its own store and merged like the other resheets.

Run:  .venv/bin/python scripts/make_template_arrows.py
Then: .venv/bin/python scripts/split_ipad.py <export.pdf> \
        --layout template/arrows/template_layout.json --out glyphs/ipad_arrows
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import make_template_collection as mtc  # noqa: E402

OUT_DIR = REPO / "template" / "arrows"

ENTRIES = [
    ("⇐", "⇐   leftwards DOUBLE arrow (same weight as your ⇒)"),
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
