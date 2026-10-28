"""Checkpoint 4 verification: variation engine + renderer.

Checks:
- same sentence + same seed  => pixel-identical render (byte-for-byte)
- same sentence + different seeds => visibly different renders
- no-immediate-repeat: a character never gets the same variant twice in a row
- renders are ink-only RGBA (transparent background, visible ink)
Writes viewable (white-matted) sample images to out/ for the handwriting
sanity check. Exit 0 = pass.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from handwriting.document_model import Document, Paragraph, TextRun
from handwriting.glyphstore import GlyphStore
from handwriting.layout import PageSpec, layout_document
from handwriting.renderer import render_pages
from handwriting.style import HandwritingStyle
from handwriting.synthglyphs import DEFAULT_STORE
from handwriting.variation import apply_variation

OUT = Path(__file__).resolve().parents[1] / "out"
SPEC = PageSpec(width_px=1000, height_px=360, margin_px=60)


def variant_counts(store: GlyphStore) -> dict[str, int]:
    return {c: len(store.entry(c).variants) for c in store.characters}


def render(doc, store, style, counts, seed):
    pages = layout_document(doc, store, style, SPEC, seed=seed)
    pages = apply_variation(pages, counts, style, seed=seed)
    return pages, render_pages(pages, store, style)


def matte(img: Image.Image) -> Image.Image:
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    return Image.alpha_composite(bg, img).convert("RGB")


def main() -> int:
    failures: list[str] = []
    store = GlyphStore(DEFAULT_STORE)
    style = HandwritingStyle()
    counts = variant_counts(store)

    doc = Document(paragraphs=[
        Paragraph(runs=[TextRun(text="mississippi bookkeeper letters aaa")]),
        Paragraph(runs=[TextRun(text="The quick brown fox jumps over 12 lazy dogs.")]),
    ])

    # 1. determinism: same seed => identical pixels
    _, imgs_a = render(doc, store, style, counts, seed=42)
    _, imgs_b = render(doc, store, style, counts, seed=42)
    if imgs_a[0].tobytes() != imgs_b[0].tobytes():
        failures.append("same seed produced different pixels (non-deterministic)")

    # 2. different seeds => different pixels
    pages_c, imgs_c = render(doc, store, style, counts, seed=7)
    if imgs_a[0].tobytes() == imgs_c[0].tobytes():
        failures.append("different seeds produced identical pixels")

    # 3. no immediate repeat of a variant for the same character
    for pi, page in enumerate(pages_c):
        prev: dict[str, int] = {}
        for g in page.glyphs:
            if counts.get(g.char, 1) > 1 and prev.get(g.char) == g.variant:
                failures.append(
                    f"page {pi}: {g.char!r} repeated variant {g.variant} immediately"
                )
                break
            prev[g.char] = g.variant

    # 4. ink-only RGBA: transparent background, visible ink
    for label, img in (("seed42", imgs_a[0]), ("seed7", imgs_c[0])):
        if img.mode != "RGBA":
            failures.append(f"{label}: render not RGBA")
        lo, hi = img.getchannel("A").getextrema()
        if lo != 0:
            failures.append(f"{label}: background not transparent")
        if hi != 255:
            failures.append(f"{label}: no visible ink")

    OUT.mkdir(exist_ok=True)
    saved = []
    for seed in (42, 7, 99):
        _, imgs = render(doc, store, style, counts, seed=seed)
        p = OUT / f"render_seed{seed}.png"
        matte(imgs[0]).save(p)
        saved.append(p)

    print(f"rendered {len(imgs_a)} page(s); sample glyphs page0: {len(imgs_a)}")
    print("sample images:", ", ".join(str(p) for p in saved))
    print()
    if failures:
        print(f"FAIL ({len(failures)} problems):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: checkpoint 4 checks all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
