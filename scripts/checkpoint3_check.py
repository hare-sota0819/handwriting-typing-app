"""Checkpoint 3 verification: layout engine.

Checks: deterministic under a fixed seed (and different under another);
glyphs stay inside margins; baseline drift bounded by the style knob and
smooth (no per-glyph jumps); long documents overflow onto multiple pages.
Also renders bounding-box debug images to out/ for visual sanity-checking.
Exit 0 = pass.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw

import make_samples
from handwriting.document_model import Document, Paragraph, TextRun
from handwriting.glyphstore import GlyphStore
from handwriting.layout import PageSpec, layout_document
from handwriting.parser import parse_docx
from handwriting.style import HandwritingStyle
from handwriting.synthglyphs import DEFAULT_STORE

OUT = Path(__file__).resolve().parents[1] / "out"

_WORDS = (
    "signal filter voltage current circuit sample phase noise gain amplifier "
    "resistor capacitor frequency response impulse discrete transform linear "
    "system stable output input feedback loop design analysis model equation"
).split()


def long_document(n_paragraphs: int = 18, words_per: int = 42) -> Document:
    paragraphs = []
    for p in range(n_paragraphs):
        words = [_WORDS[(p * 7 + i) % len(_WORDS)] for i in range(words_per)]
        paragraphs.append(Paragraph(runs=[TextRun(text=" ".join(words) + ".")]))
    return Document(paragraphs=paragraphs)


def as_tuples(pages):
    return [
        [(g.char, g.variant, g.x, g.y, g.scale, g.rotation_deg) for g in p.glyphs]
        for p in pages
    ]


def draw_debug(pages, store, style, prefix: str) -> list[Path]:
    OUT.mkdir(exist_ok=True)
    paths = []
    for i, page in enumerate(pages, start=1):
        spec = page.spec
        img = Image.new("RGB", (spec.width_px, spec.height_px), (255, 255, 255))
        d = ImageDraw.Draw(img)
        m = spec.margin_px
        d.rectangle(
            [m, m, spec.width_px - m, spec.height_px - m], outline=(220, 60, 60)
        )
        for g in page.glyphs:
            v = store.entry(g.char).variants[g.variant]
            with Image.open(store.root / v.file) as glyph_img:
                w, h = glyph_img.size
            x0 = g.x + v.left_bearing * g.scale
            y0 = g.y - v.baseline_y * g.scale
            d.rectangle([x0, y0, x0 + w * g.scale, y0 + h * g.scale],
                        outline=(120, 120, 220))
            d.line([g.x, g.y, g.x + v.advance_width * g.scale, g.y],
                   fill=(60, 160, 60))
        path = OUT / f"{prefix}_page{i}.png"
        img.save(path)
        paths.append(path)
    return paths


def main() -> int:
    failures: list[str] = []
    store = GlyphStore(DEFAULT_STORE)
    # Geometry invariants (straight nominal lines, fixed margins) are checked
    # with the page-rhythm knobs zeroed; the rhythm itself is asserted in
    # section 7 against the real defaults.
    style = HandwritingStyle(word_drift_px=0.0, line_rise_px=0.0,
                             line_step_jitter_frac=0.0, margin_drift_px=0.0)
    spec = PageSpec()

    if not (make_samples.SAMPLES / "multi.docx").exists():
        make_samples.main()
    multi = parse_docx(make_samples.SAMPLES / "multi.docx")
    long_doc = long_document()

    # 1. determinism
    a = layout_document(multi, store, style, spec, seed=7)
    b = layout_document(multi, store, style, spec, seed=7)
    c = layout_document(multi, store, style, spec, seed=8)
    if as_tuples(a) != as_tuples(b):
        failures.append("same seed produced different layouts")
    if as_tuples(a) == as_tuples(c):
        failures.append("different seeds produced identical layouts")

    pages = layout_document(long_doc, store, style, spec, seed=7)

    # 2. multi-page overflow
    if len(pages) < 2:
        failures.append(f"long document stayed on {len(pages)} page(s), expected >=2")

    left, right = spec.margin_px, spec.width_px - spec.margin_px
    first_baseline = spec.margin_px + style.base_size_px
    line_step = style.line_height * style.base_size_px
    drift_cap = style.baseline_drift_px + 0.01
    # Steepest slope the two-sinusoid drift can have (d/dx of each term).
    max_slope = (
        style.baseline_drift_px
        * (2 * 3.141592653589793 / style.baseline_drift_period_px)
        * (0.7 + 0.3 * 2.3)
    )

    total = 0
    for pi, page in enumerate(pages, start=1):
        prev = None
        for g in page.glyphs:
            total += 1
            adv = store.entry(g.char).variants[g.variant].advance_width * g.scale
            # 3. horizontal bounds
            if g.x < left - 0.01 or g.x + adv > right + 0.01:
                failures.append(f"page {pi}: {g.char!r} at x={g.x:.1f} outside column")
                break
            # 4. drift bounded around a nominal line, inside vertical margins
            line_index = round((g.y - first_baseline) / line_step)
            nominal = first_baseline + line_index * line_step
            if abs(g.y - nominal) > drift_cap:
                failures.append(
                    f"page {pi}: {g.char!r} drifted {g.y - nominal:+.2f}px "
                    f"(cap {style.baseline_drift_px})"
                )
                break
            if not (spec.margin_px <= g.y <= spec.height_px - spec.margin_px):
                failures.append(f"page {pi}: baseline y={g.y:.1f} outside margins")
                break
            # 5. smoothness: neighbours on the same line move gradually
            if prev is not None and abs(g.x - prev.x) < 60 and abs(
                round((prev.y - first_baseline) / line_step) - line_index
            ) == 0:
                if abs(g.y - prev.y) > max_slope * abs(g.x - prev.x) * 1.05 + 0.05:
                    failures.append(
                        f"page {pi}: baseline jump {abs(g.y - prev.y):.2f}px "
                        f"between {prev.char!r} and {g.char!r}"
                    )
                    break
            prev = g
        else:
            continue
        break

    # 6. unicode superscripts: drawn as a raised, shrunken digit — no ghost gap
    sup_doc = Document(paragraphs=[Paragraph(runs=[TextRun(text="oil (kg/m³)")])])
    sup_glyphs = layout_document(sup_doc, store, style, spec, seed=3)[0].glyphs
    threes = [g for g in sup_glyphs if g.char == "3"]
    if len(threes) != 1:
        failures.append(f"superscript ³ produced {len(threes)} '3' glyphs, want 1")
    else:
        t = threes[0]
        m = [g for g in sup_glyphs if g.char == "m"][-1]
        paren = [g for g in sup_glyphs if g.char == ")"][-1]
        if t.scale >= 0.8 * m.scale:
            failures.append(f"superscript not shrunken: scale {t.scale:.2f} vs body {m.scale:.2f}")
        if not (t.y < m.y - 3):
            failures.append(f"superscript not raised: y {t.y:.1f} vs body baseline {m.y:.1f}")
        if paren.x - t.x > style.base_size_px:
            failures.append(
                f"ghost gap before ')': paren x {paren.x:.1f} vs ³ x {t.x:.1f}"
            )

    # 7. page rhythm at the real defaults: every line climbs to the right,
    # line starts wander (bounded), line steps vary, per-word height offsets
    # are uniform within a word and bounded; all of it OFF when snapping.
    from handwriting.layout import LineGrid
    from handwriting.variation import apply_variation

    rhythm = HandwritingStyle()
    rpages = layout_document(long_doc, store, rhythm, spec, seed=7)
    lines: list[list] = []
    for page in rpages:
        prev_x = None
        for g in page.glyphs:
            if prev_x is None or g.x < prev_x - 1:
                lines.append([])
            lines[-1].append(g)
            prev_x = g.x
    wide = [ln for ln in lines if ln[-1].x - ln[0].x > 300]
    if not all(ln[-1].y < ln[0].y for ln in wide):
        failures.append("line_rise: some wide line does not climb to the right")
    starts = [ln[0].x for ln in lines]
    if max(starts) - min(starts) < 1.0:
        failures.append("margin_drift: line starts do not vary")
    if any(abs(s - spec.margin_px) > rhythm.margin_drift_px + 1 for s in starts):
        failures.append("margin_drift: a line start left the clamped band")
    nominal_step = rhythm.line_height * rhythm.base_size_px
    steps = [b[0].y - a[0].y for a, b in zip(lines, lines[1:])
             if 0 < b[0].y - a[0].y < 2 * nominal_step]  # same-page neighbours
    if len({round(s, 3) for s in steps}) < 3:
        failures.append("line_step_jitter: line steps are metronome-even")
    vpages = apply_variation(rpages, {}, rhythm, seed=7)
    offsets: dict[int, set] = {}
    for lp, vp in zip(rpages, vpages):
        for lg, vg in zip(lp.glyphs, vp.glyphs):
            offsets.setdefault(lg.word, set()).add(round(vg.y - lg.y, 6))
    if not all(len(v) == 1 for v in offsets.values()):
        failures.append("word_drift: letters of one word got different offsets")
    vals = [next(iter(v)) for v in offsets.values()]
    if max(abs(v) for v in vals) > rhythm.word_drift_px + 1e-6:
        failures.append("word_drift: offset escaped the amplitude bound")
    if len(set(vals)) < 5:
        failures.append("word_drift: offsets barely vary across words")
    grid = LineGrid(spacing_px=40.0, offset_px=150.0)
    spages = layout_document(long_doc, store, rhythm, spec, seed=7, grid=grid)
    sfirsts = []
    for page in spages:
        prev_x = None
        for g in page.glyphs:
            if prev_x is None or g.x < prev_x - 1:
                sfirsts.append(g.x)
            prev_x = g.x
    if len({round(x, 3) for x in sfirsts}) != 1:
        failures.append("snapping must disable the margin walk (line starts differ)")

    debug_paths = draw_debug(pages[:2], store, style, "layout_long")
    debug_paths += draw_debug(
        layout_document(multi, store, style, spec, seed=7), store, style, "layout_multi"
    )

    print(f"pages: {len(pages)}, placed glyphs: {total}")
    print("debug images:", ", ".join(str(p) for p in debug_paths))
    print()
    if failures:
        print(f"FAIL ({len(failures)} problems):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: checkpoint 3 checks all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
