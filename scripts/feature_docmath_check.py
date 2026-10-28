"""Feature check: equations inside a .docx render on the page with the text.

Covers the whole seam, plus the stretchy-delimiter weight fix that came with it:

1. Stretchy delimiters (spike/render_placement.pick_stretchy): a bracket grown
   to 2.3 em keeps its written ends — only the straight vertical run gets
   longer — so the horizontal parts do not thicken and the stem does not thin
   (max local thickness in the end zones vs the middle within 1.25x).
2. Parser: a paragraph mixing text and OMML yields TextRun/MathBlock in run
   order, inline vs display, indices in body order (real 55-equation sample).
3. mathrender: pandoc pairing (count agrees with the parser) and every block
   gets an ink-only RGBA image with a baseline row.
4. Layout: an inline equation sits on its line's baseline after the preceding
   word; a display equation is alone on a centred line; tall equations push
   the neighbouring lines clear instead of overlapping them. A display
   equation follows Word's justification: its own m:jc, else the document's
   m:defJc, else centred; left/right put its ink box on the column edge.
5. End to end: CLI core and GUI runner (docx-text mode) render the fixture.
6. Coursework constructs (2026-08-18 review of a real HW): boxed{} draws a
   frame (was a strike-through bar); underbrace draws a brace (was grey
   placeholder boxes); `x prime` becomes the raised `x'`; ⊤ draws as T; a
   wide written `[` next to `|` is squeezed to MathJax's box instead of
   overprinting; display-size ∑ ∏ are re-stroked, not eroded (no notched
   strokes); punctuation after an inline equation is glued to it; Word
   page breaks start a new page; ① renders as "(1)".

Text-only documents take the unchanged Phase 1 path (goldens in the other
checks prove byte-identity). Exit 0 = pass.
"""

import importlib.util
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import docx  # noqa: E402
from docx.oxml import parse_xml  # noqa: E402

from handwriting.document_model import MathBlock, TextRun  # noqa: E402
from handwriting.glyphstore import GlyphStore  # noqa: E402
from handwriting.layout import PageSpec, layout_document  # noqa: E402
from handwriting.mathrender import (  # noqa: E402
    MathTools, extract_latex, measure_cap_ink, render_document_math,
)
from handwriting.parser import parse_docx  # noqa: E402
from handwriting.style import HandwritingStyle  # noqa: E402

from handwriting.stores import default_store  # noqa: E402

STORE = default_store()
OUT = ROOT / "out" / "docmath"
FIXTURE = OUT / "fixture.docx"
_M = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'


def _frac(num: str, den: str) -> str:
    return (f"<m:oMath {_M}><m:f><m:num><m:r><m:t>{num}</m:t></m:r></m:num>"
            f"<m:den><m:r><m:t>{den}</m:t></m:r></m:den></m:f></m:oMath>")


def _sym(text: str) -> str:
    return f"<m:oMath {_M}><m:r><m:t>{text}</m:t></m:r></m:oMath>"


def make_fixture() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    d = docx.Document()
    d.add_paragraph("First line of text before any maths.")
    p = d.add_paragraph("An inline fraction ")
    p._p.append(parse_xml(_frac("a", "b")))
    p.add_run(" sits in this sentence with words after it.")
    p = d.add_paragraph("")
    p._p.append(parse_xml(f"<m:oMathPara {_M}>" + _frac("x+1", "y-1")
                          + "</m:oMathPara>"))
    d.add_paragraph("Text after the display equation.")
    d.save(FIXTURE)
    return FIXTURE


def load_spike():
    spec = importlib.util.spec_from_file_location(
        "render_placement", ROOT / "spike" / "render_placement.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    store = GlyphStore(STORE)
    mod.STORE_CAP_INK, mod.STORE_XH_INK = mod.measure_store_ink(store)
    return mod, store


def _max_thickness(mask: np.ndarray) -> int:
    """Erosion count until the ink is gone: ~ the thickest stroke in px."""
    im = Image.fromarray((mask * 255).astype("uint8"))
    k = 0
    while np.array(im).max() > 0 and k < 300:
        im = im.filter(ImageFilter.MinFilter(3))
        k += 1
    return 2 * k


def check_stretchy(failures: list[str]) -> None:
    rp, store = load_spike()
    # unit: bands are inside the glyph, ends are copied verbatim
    v = store.entry("[").variants[0]
    ink = store.load_image(v).crop(v.ink_bbox)
    mask = np.array(ink)[..., 3] > 128
    bands = rp._straight_bands(mask, "[")
    if len(bands) != 1 or bands[0][0] <= 0 or bands[0][1] >= mask.shape[0]:
        failures.append(f"stretchy: '[' straight band not inside glyph: {bands}")
    else:
        a, b = bands[0]
        out = rp._stretch_bands(ink, bands, 200)
        top_same = np.array_equal(np.array(out)[:a], np.array(ink)[:a])
        bot_same = np.array_equal(np.array(out)[b + 200:], np.array(ink)[b:])
        if out.height != ink.height + 200 or not (top_same and bot_same):
            failures.append("stretchy: band stretch altered the glyph ends")
    for ch in "{}":
        v = store.entry(ch).variants[0]
        m = np.array(store.load_image(v).crop(v.ink_bbox))[..., 3] > 128
        if len(rp._straight_bands(m, ch)) != 2:
            failures.append(f"stretchy: brace {ch!r} should get two bands")
    # A closed integral grows on BOTH sides of its circle. Grown in its one
    # longest straight run (above the circle), a display-size ∮ came out as a
    # long stem with the circle sunk to the foot (user report 2026-09-21).
    for i, v in enumerate(store.entry(rp.store_key(store, "∮")).variants):
        ink = store.load_image(v).crop(v.ink_bbox)
        m = np.array(ink)[..., 3] > 128
        bands = rp._straight_bands(m, "∮")
        if len(bands) != 2:
            failures.append(f"stretchy: ∮ variant {i} got {len(bands)} band(s), "
                            "want one above and one below the circle")
            continue
        extra = round(1.2 * ink.height)  # natural -> 2.2x, a display integral
        circle = (bands[0][1] + bands[1][0]) / 2 + extra // 2
        where = circle / (ink.height + extra)
        if not 0.35 <= where <= 0.65:
            failures.append(f"stretchy: ∮ variant {i} circle at {where:.2f} of "
                            "the stretched height, want it near the middle")
    # integration: ends stay pen-weight after a 2.3 em stretch (was 1.3-1.8x)
    worst = 0.0
    for ch in "[]":
        for seed in (1, 2, 3):
            img = rp.pick_stretchy(store, random.Random(seed), ch, 2.3 * rp.PPE)
            if abs(img.height - round(2.3 * rp.PPE)) > 1:
                failures.append(f"stretchy: {ch!r} height {img.height} != target")
            a = np.array(img)[..., 3] > 128
            h = a.shape[0]
            ends = max(_max_thickness(a[:int(h * 0.25)]),
                       _max_thickness(a[int(h * 0.75):]))
            mid = _max_thickness(a[int(h * 0.35):int(h * 0.65)])
            worst = max(worst, ends / max(1, mid))
    if worst > 1.25:
        failures.append(f"stretchy: bracket ends {worst:.2f}x thicker than stem")
    print(f"stretchy: OK (worst end/stem thickness ratio {worst:.2f})")


def check_parser(failures: list[str]) -> None:
    doc = parse_docx(ROOT / "samples" / "math_render_test_en.docx")
    blocks = [r for p in doc.paragraphs for r in p.runs if isinstance(r, MathBlock)]
    idx = [b.index for b in blocks]
    if idx != list(range(55)):
        failures.append(f"parser: expected indices 0..54 in order, got {idx[:8]}...")
    n_disp = sum(b.display for b in blocks)
    if (n_disp, len(blocks) - n_disp) != (27, 28):
        failures.append(f"parser: display/inline = {n_disp}/{len(blocks) - n_disp}, "
                        "expected 27/28")
    mixed = next(p for p in doc.paragraphs
                 if any(isinstance(r, MathBlock) for r in p.runs)
                 and any(isinstance(r, TextRun) for r in p.runs))
    kinds = ["M" if isinstance(r, MathBlock) else "T" for r in mixed.runs]
    if kinds != ["T", "M", "T"] or mixed.runs[1].display:
        failures.append(f"parser: mixed paragraph runs {kinds}, expected T M T inline")
    for name in ("plain.docx", "multi.docx"):
        d = parse_docx(ROOT / "samples" / name)
        if any(isinstance(r, MathBlock) for p in d.paragraphs for r in p.runs):
            failures.append(f"parser: {name} grew a MathBlock")
    print("parser: OK (55 blocks, 27 display / 28 inline, T-M-T paragraph)")


def check_mathrender(failures: list[str]):
    tools = MathTools()
    eqs = extract_latex(ROOT / "samples" / "math_render_test_en.docx", tools.pandoc)
    if len(eqs) != 55:
        failures.append(f"mathrender: pandoc found {len(eqs)} equations, parser 55")
    doc = parse_docx(FIXTURE)
    render_document_math(doc, FIXTURE, STORE, seed=3, tools=tools)
    blocks = [r for p in doc.paragraphs for r in p.runs if isinstance(r, MathBlock)]
    if len(blocks) != 2 or any(b.ink is None for b in blocks):
        failures.append("mathrender: fixture blocks not all rendered")
        return None
    for b in blocks:
        im = b.ink.image
        a = np.array(im)[..., 3]
        if im.mode != "RGBA" or a.max() < 200 or a[0, 0] != 0:
            failures.append("mathrender: ink image is not ink-only RGBA")
        if not (0 < b.ink.baseline_y < im.height):
            failures.append("mathrender: baseline row outside the image")
        if "frac" not in b.latex:
            failures.append(f"mathrender: latex pairing wrong: {b.latex!r}")
    print(f"mathrender: OK (55 paired; fixture inks "
          f"{[b.ink.image.size for b in blocks]})")
    return doc


def check_layout(failures: list[str], doc) -> None:
    store = GlyphStore(STORE)
    style = HandwritingStyle()
    style.line_height = 0.5  # the GUI default: tight lines, the hard case
    page = PageSpec()
    pages = layout_document(doc, store, style, page, seed=0)
    pg = pages[0]
    if len(pages) != 1 or len(pg.maths) != 2:
        failures.append(f"layout: {len(pages)} pages / {len(pg.maths)} maths")
        return None
    scale = style.base_size_px / store.native_size_px
    cap = measure_cap_ink(store) * scale
    inline, display = pg.maths
    # inline: same baseline as its line's letters, right after "fraction"
    line = [g for g in pg.glyphs if abs(g.y - inline.y) < 0.6 * cap]
    before = [g for g in line if g.x < inline.x]
    after = [g for g in line if g.x > inline.x]
    if not before or not after:
        failures.append("layout: inline equation not between words on its line")
    if not any(abs(g.y - inline.y) < 3.0 for g in before):
        failures.append("layout: inline equation off its line's baseline")
    ov = [g for g in line if inline.x < g.x < inline.x + inline.ink.image.width * inline.scale]
    if ov:
        failures.append("layout: text overlaps the inline equation")
    # display: alone on its line, centred in the column
    col_c = (page.margin_px + page.width_px - page.margin_px) / 2
    w = display.ink.image.width * display.scale
    if abs(display.x + w / 2 - col_c) > style.margin_drift_px + 2:
        failures.append(f"layout: display equation not centred "
                        f"({display.x + w / 2:.1f} vs {col_c:.1f})")
    if any(abs(g.y - display.y) < 0.6 * cap for g in pg.glyphs):
        failures.append("layout: text shares the display equation's line")
    # tall content pushes neighbours clear
    ys = sorted({round(g.y) for g in pg.glyphs})
    for m in (inline, display):
        top = m.y - m.ink.ascent * m.scale
        bot = m.y + m.ink.descent * m.scale
        # neighbouring LINES (this line's own letters jitter a few px)
        prev = max((y for y in ys if y < m.y - 0.6 * cap), default=None)
        nxt = min((y for y in ys if y > m.y + 0.6 * cap), default=None)
        if prev is not None and top - prev < 0.15 * style.base_size_px:
            failures.append(f"layout: equation top {top:.0f} into line above {prev}")
        if nxt is not None and nxt - 1.2 * cap < bot:
            failures.append(f"layout: line below {nxt} runs into equation bottom {bot:.0f}")
    # display equations get style.display_math_gap of air on both sides, and
    # the knob is live (0 pulls the prose closer)
    gap = style.display_math_gap * style.base_size_px
    d_top = display.y - display.ink.ascent * display.scale
    d_bot = display.y + display.ink.descent * display.scale
    prev = max(y for y in ys if y < display.y - 0.6 * cap)
    nxt = min(y for y in ys if y > display.y + 0.6 * cap)
    if d_top - prev < gap or (nxt - 1.2 * cap) - d_bot < gap:
        failures.append(f"layout: display gap {d_top - prev:.0f}/"
                        f"{(nxt - 1.2 * cap) - d_bot:.0f} < {gap:.0f}")
    tight = HandwritingStyle()
    tight.line_height = 0.5
    tight.display_math_gap = 0.0
    tpg = layout_document(doc, store, tight, page, seed=0)[0]
    t_disp = tpg.maths[1]
    tys = sorted({round(g.y) for g in tpg.glyphs})
    t_next = min(y for y in tys if y > t_disp.y + 0.6 * cap)
    if not (t_next - t_disp.y) < (nxt - display.y) - 0.5 * gap:
        failures.append("layout: display_math_gap=0 did not tighten the spacing")
    print(f"layout: OK (inline on baseline y={inline.y:.0f}, display centred, "
          f"lines pushed clear, display gap {d_top - prev:.0f}px)")
    return display


def check_math_align(failures: list[str], doc) -> None:
    """Display equations keep Word's left/right/centre justification."""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "align.docx"
    d = docx.Document()
    for jc in ("left", "right", "centerGroup", None):
        pr = (f'<m:oMathParaPr><m:jc m:val="{jc}"/></m:oMathParaPr>'
              if jc else "")
        d.add_paragraph("")._p.append(parse_xml(
            f"<m:oMathPara {_M}>{pr}" + _frac("a", "b") + "</m:oMathPara>"))
    d.save(path)
    got = [b.align for p in parse_docx(path).paragraphs for b in p.runs]
    if got != ["left", "right", "center", "center"]:
        failures.append(f"align: per-equation jc read as {got}")
    # the document default (settings m:defJc) fills in where m:jc is absent
    d = docx.Document(str(path))
    m_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
    for old in d.settings.element.findall(f"{m_ns}mathPr"):
        d.settings.element.remove(old)
    d.settings.element.append(parse_xml(
        f'<m:mathPr {_M}><m:defJc m:val="left"/></m:mathPr>'))
    d.save(path)
    got = [b.align for p in parse_docx(path).paragraphs for b in p.runs]
    if got != ["left", "right", "center", "left"]:
        failures.append(f"align: defJc=left read as {got}")
    # layout: the display equation's ink box sits on the matching column edge
    store = GlyphStore(STORE)
    style = HandwritingStyle()
    style.line_height = 0.5
    style.margin_drift_px = 0.0
    page = PageSpec()
    display = [r for p in doc.paragraphs for r in p.runs
               if isinstance(r, MathBlock) and r.display][0]
    left, right = page.margin_px, page.width_px - page.margin_px
    xs = {}
    for align in ("left", "center", "right"):
        display.align = align
        m = layout_document(doc, store, style, page, seed=0)[0].maths[1]
        xs[align] = (m.x, m.x + m.ink.image.width * m.scale)
    display.align = "center"
    if abs(xs["left"][0] - left) > 1.0:
        failures.append(f"align: left equation starts at {xs['left'][0]:.1f}, "
                        f"column at {left}")
    if abs(xs["right"][1] - right) > 1.0:
        failures.append(f"align: right equation ends at {xs['right'][1]:.1f}, "
                        f"column at {right}")
    if not xs["left"][0] < xs["center"][0] < xs["right"][0]:
        failures.append(f"align: left/centre/right x not ordered: {xs}")
    print(f"align: OK (jc + defJc parsed; left x={xs['left'][0]:.0f}, "
          f"right end={xs['right'][1]:.0f})")


def check_end_to_end(failures: list[str], display) -> None:
    from handwriting.cli import render_with_options
    # same seed/size as check_layout, so the display equation lands where
    # the layout put it (plus a few px of word drift)
    pages = render_with_options(FIXTURE, seed=0, store=STORE, dpi=150,
                                style_overrides={"line_height": 0.5})
    if len(pages) != 1:
        failures.append(f"e2e: {len(pages)} pages")
    im = pages[0]
    im.save(OUT / "fixture_page.png")
    a = np.array(im.convert("L"))
    if display is not None:
        w = display.ink.image.width * display.scale
        top = display.y - display.ink.ascent * display.scale
        bot = display.y + display.ink.descent * display.scale
        band = a[int(top) - 8:int(bot) + 8,
                 int(display.x):int(display.x + w)]
        if (band < 128).sum() < 200:
            failures.append("e2e: no ink where the display equation should be")
    from gui.runner import JobConfig, run_job
    gpages = run_job(JobConfig(input=FIXTURE, mode="docx-text", seed=1, dpi=150))
    if len(gpages) != 1 or np.array(gpages[0].convert("L")).min() > 100:
        failures.append("e2e: GUI runner produced no page ink")
    # CLI entry point on the shipped equation sample
    r = subprocess.run([sys.executable, "-m", "handwriting",
                        str(ROOT / "samples" / "equation.docx"),
                        "--store", str(STORE), "--dpi", "150",
                        "--out", str(OUT / "equation_sample.png")],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0 or not (OUT / "equation_sample.png").exists():
        failures.append(f"e2e: CLI failed: {r.stderr[-400:]}")
    print("e2e: OK (CLI core, GUI runner, CLI entry point)")


FIXTURE2 = OUT / "fixture2.docx"


def make_fixture2() -> Path:
    """Punctuation after inline maths, an enclosed digit, and a page break."""
    d = docx.Document()
    p = d.add_paragraph("Take ")
    p._p.append(parse_xml(_frac("a", "b")))
    p.add_run(", then continue with more words here.")
    d.add_paragraph("① first item")
    d.add_paragraph("a ≳ b ≲ c ⩾ d ⩽ e ≧ f ≦ g")
    d.add_paragraph("Last line of page one.")
    d.add_page_break()
    d.add_paragraph("First line of page two.")
    d.save(FIXTURE2)
    return FIXTURE2


def check_constructs(failures: list[str]) -> None:
    """The math-chain fixes from the HW review, straight through run_chain."""
    from handwriting.mathrender import fix_latex, run_chain
    import json
    mod, store = load_spike()
    # skeleton re-stroke: a thick bar with a thin bar attached comes back at
    # ONE pen weight with neither part broken
    mask = np.zeros((80, 300), bool)
    mask[20:60, 10:290] = True          # 40 px thick
    mask[36:44, 200:290] = True         # 8 px thin tail (already thin)
    out = mod._restroke(mask, 10.0) > 0
    pen = mod._pen_px(out[:, 20:180])
    if pen is None or abs(pen - 10.0) > 2.5:
        failures.append(f"restroke: pen {pen} px, wanted ~10")
    if not out[:, 40:270].any(axis=0).all():
        failures.append("restroke: stroke broke somewhere along the bar")
    # normalize_pen thinning never shaves: the thick bar comes down toward
    # the pen, the already-thin tail keeps every pixel it was written with
    from PIL import Image
    rgba = np.zeros((80, 300, 4), np.uint8)
    rgba[20:60, 10:180, 3] = 255        # 40 px thick bar
    rgba[36:44, 180:290, 3] = 255       # 8 px tail, thinner than the pen
    thin = np.array(mod.normalize_pen(Image.fromarray(rgba), 20.0))[..., 3]
    if not (thin[36:44, 200:280] == 255).all():
        failures.append("normalize_pen: thinning shaved the thin tail")
    if (thin[:, 30:170] > 128).sum(axis=0).mean() > 24:
        failures.append("normalize_pen: thick bar not thinned toward the pen")
    # pen estimate must not depend on where the ink sits: a stem flush with
    # the image edge (every cropped delimiter) read as twice as thick and
    # was thinned to a hairline under fat ends
    flush = np.zeros((300, 60), bool)
    flush[:, :28] = True
    inner = np.zeros((300, 60), bool)
    inner[:, 16:44] = True
    p_flush, p_inner = mod._pen_px(flush), mod._pen_px(inner)
    if abs(p_flush - p_inner) > 0.5 or abs(p_inner - 28) > 3:
        failures.append(f"_pen_px: flush {p_flush:.1f} vs inner {p_inner:.1f} (want ~28)")
    # a stretched [ has ONE stroke weight: mid-stem width == its pen target
    tall = mod.pick_stretchy(store, random.Random(1), "[", 2.5 * mod.PPE)
    tm = np.array(tall)[..., 3] > 128
    stem_w = int(tm[tm.shape[0] // 2].sum())
    if abs(stem_w - mod.PEN_PX) > 3:
        failures.append(f"stretched [ stem {stem_w}px, pen target {mod.PEN_PX:.1f}")
    # width cap: only delimiters/relations, 1.5x the box (+ pad for hairlines)
    el = {"base_char": "(", "bbox": {"w": 0.2}, "scale": 1.0}
    cap = mod.width_cap_px(el)
    if cap is None or abs(cap - max(1.5 * 0.2, 0.3) * mod.PPE) > 1e-6:
        failures.append(f"width cap for ( = {cap}")
    # square brackets keep their written width (the squeeze shortened the
    # arms into blobs) and report the overhang that pushes neighbours clear
    br_el = {"base_char": "[", "bbox": {"w": 0.2}, "scale": 1.0}
    if mod.width_cap_px(br_el) is not None:
        failures.append("[ must not be width-capped")
    if abs(mod.bracket_overflow(br_el, 0.4 * mod.PPE) - 0.1 * mod.PPE) > 1e-6:
        failures.append("bracket_overflow: wrong overhang for a 2x-wide [")
    if mod.width_cap_px({"base_char": "m", "bbox": {"w": 0.2}, "scale": 1.0}) is not None:
        failures.append("width cap must not apply to letters")
    # \prime -> '
    if fix_latex(r"x\prime + y\prime^{2}") != "x' + y'^{2}":
        failures.append(f"fix_latex: {fix_latex(r'x\prime + y\prime^{2}')!r}")
    work = OUT / "constructs"
    eqs = [
        {"id": "boxed", "latex": r"\boxed{A(x)}", "display": True},
        {"id": "brace", "latex": r"\underbrace{a + b + c + d}_{S} + \overbrace{e + f}^{T}",
         "display": True},
        {"id": "top", "latex": fix_latex(r"x^{\top}x\prime"), "display": False},
        {"id": "delim", "latex": r"E\left\lbrack \left| f(x) \right| \right\rbrack",
         "display": True},
        {"id": "brk", "latex": r"k\left\lbrack \text{ClO}_{2} \right\rbrack^{2}",
         "display": False},
    ]
    inks = run_chain(eqs, STORE, seed=3, tools=MathTools(work_dir=work))
    if set(inks) != {"boxed", "brace", "top", "delim", "brk"}:
        failures.append(f"constructs: rendered {sorted(inks)}")
        return
    for eq in eqs:
        meta = json.loads((work / "hand" / f"hand_{eq['id']}.json").read_text())
        if meta["missing"]:
            failures.append(f"constructs: {eq['id']} placeholders {meta['missing']}")
    pl = json.loads((work / "placements" / "boxed.json").read_text())
    kinds = [e["kind"] for e in pl["elements"]]
    if "frame" not in kinds or "rule" in kinds:
        failures.append(f"boxed: element kinds {kinds}")
    # the frame: ink runs down the whole left edge (a bar through the middle
    # would leave the top-left and bottom-left corners empty)
    a = np.array(inks["boxed"].image)[..., 3] > 128
    ys, xs = np.nonzero(a)
    left = a[:, xs.min():xs.min() + 12].any(axis=1)
    if left[ys.min() + 5:ys.max() - 5].mean() < 0.9:
        failures.append("boxed: no continuous left edge — frame not drawn")
    # the brace: ink spans the underbrace's full width below the letters
    pl = json.loads((work / "placements" / "brace.json").read_text())
    groups = mod.brace_groups(pl["elements"])
    if len(groups) != 2 or [g[6] for g in groups] != [True, False]:
        failures.append(f"brace: groups {[(g[0], g[1], g[6]) for g in groups]}")
    # full-width brackets push their neighbours clear: every mark of
    # E[|f(x)|] and k[ClO_2]^2 stands in its own ink columns, none overprints
    for eid, marks in (("delim", 9), ("brk", 8)):
        n = len(_ink_clusters(inks[eid].image))
        if n != marks:
            failures.append(f"{eid}: {n} ink clusters, want {marks} — "
                            "a bracket overlaps its neighbour")
    print("constructs: OK (restroke pen, width cap, prime, boxed frame, "
          "braces, ⊤, delimiters)")


def _ink_clusters(img) -> list[tuple[int, int]]:
    """(left, right) of each run of columns that carry ink."""
    a = np.array(img)
    a = a[..., 3] if a.ndim == 3 else a
    cols = (a > 60).any(axis=0)
    runs, start = [], None
    for i, on in enumerate(cols):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(cols)))
    return runs


def check_spacing(failures: list[str]) -> None:
    """Every glyph lands in the same coordinate frame, and none eats its
    neighbour (2026-09-04: `0.273` printed as `0273`).

    Two independent defects made that one symptom, so there are two checks.
    """
    from handwriting.mathrender import run_chain
    work = OUT / "spacing"
    eqs = [
        # equal MathJax spacing -> equal gaps on the page. A name shadowed
        # inside render() once dropped the canvas padding from 60 px to 8 px
        # partway through the loop, which moved everything after the first
        # glyph 52 px left; the first gap alone came out short.
        {"id": "frame", "latex": r"0\quad 0\quad 0\quad 0", "display": True},
        # the reported string: the decimal point must stay a mark of its own
        {"id": "decimal", "latex": r"0.273", "display": True},
    ]
    inks = run_chain(eqs, STORE, seed=5, tools=MathTools(work_dir=work))
    if set(inks) != {"frame", "decimal"}:
        failures.append(f"spacing: rendered {sorted(inks)}")
        return

    runs = _ink_clusters(inks["frame"].image)
    if len(runs) != 4:
        failures.append(f"spacing: 0 quad 0 quad 0 quad 0 gave {len(runs)} ink runs")
    else:
        gaps = [runs[i + 1][0] - runs[i][1] for i in range(3)]
        if max(gaps) - min(gaps) > 15:
            failures.append(f"spacing: equal quads drew unequal gaps {gaps} px "
                            "— the glyphs are not in one coordinate frame")

    # the nudge itself: a glyph whose ink would land on its neighbour's is
    # moved right to exactly the minimum gap, one already clear is left alone,
    # and no glyph is moved further than the cap from where MathJax put it.
    rp, _ = load_spike()
    gap = rp.MIN_INK_GAP_EM * rp.PPE
    if rp.nudge_x(None, 0.0, 1.0) != 0:
        failures.append("nudge: first glyph on a row must not move")
    if rp.nudge_x(100.0, 100.0 + 3 * gap, 1.0) != 0:
        failures.append("nudge: a glyph already clear must not move")
    if rp.nudge_x(100.0, 90.0, 1.0) != round(gap + 10):
        failures.append(f"nudge: overlap not cleared to the gap "
                        f"({rp.nudge_x(100.0, 90.0, 1.0)} != {round(gap + 10)})")
    if rp.nudge_x(1000.0, 0.0, 1.0) != round(rp.MAX_NUDGE_EM * rp.PPE):
        failures.append("nudge: not capped at MAX_NUDGE_EM")

    # ... and the mirror of it: a script left stranded by a box wider than this
    # hand's ink is pulled back onto its base (2026-09-07: "kv_r" read "kv , r").
    sgap = rp.SCRIPT_GAP_EM * rp.PPE
    if rp.script_pull(None, 500.0, 0.707) != 0:
        failures.append("script: nothing to hang off must not move")
    if rp.script_pull(100.0, 500.0, 1.0) != 0:
        failures.append("script: a full-size glyph is not a script")
    if rp.script_pull(100.0, 100.0 + sgap / 2, 0.707) != 0:
        failures.append("script: one already tight must not move")
    if rp.script_pull(100.0, 150.0, 0.707) != -round(50.0 - sgap):
        failures.append(f"script: not closed to the gap "
                        f"({rp.script_pull(100.0, 150.0, 0.707)})")
    if rp.script_pull(0.0, 5000.0, 0.707) != -round(rp.MAX_SCRIPT_PULL_EM * rp.PPE):
        failures.append("script: not capped at MAX_SCRIPT_PULL_EM")

    # end to end: the reported subscripts, measured on the drawn ink
    inks = run_chain([{"id": "sub", "latex": r"F_{fr} = kv_r", "display": True}],
                     STORE, seed=1, tools=MathTools(work_dir=work))
    runs = _ink_clusters(inks["sub"].image)  # F f r = k v r
    if len(runs) != 7:
        failures.append(f"script: F_fr = kv_r drew {len(runs)} ink runs")
    else:
        base_to_script = [(runs[1][0] - runs[0][1]) / rp.PPE,   # F -> f
                          (runs[6][0] - runs[5][1]) / rp.PPE]   # v -> r
        if max(base_to_script) > 2 * rp.SCRIPT_GAP_EM:
            failures.append(f"script: subscripts sit {base_to_script} em from "
                            "their bases — they read as separate symbols")
    print("spacing: OK (quad gaps even, collision nudge clears to the gap and "
          "stays under the cap, scripts pulled onto their base)")


def check_tight_math(failures: list[str]) -> None:
    """An equation Word wrote with no space beside it is part of the word.

    Reported 2026-09-07 on the Millikan report: units came out as "kg/m ³"
    and "Pa · s = N · s/m ²" because every inline equation opened a word gap
    on its left, whatever the .docx said.
    """
    fixture = OUT / "tight.docx"
    d = docx.Document()
    p = d.add_paragraph("oil density in kg/m")   # no space before the maths
    p._p.append(parse_xml(_sym("3")))
    p.add_run(") and Pa")                        # nor after it
    p._p.append(parse_xml(_sym("⋅")))
    p.add_run("s here")
    d.save(fixture)

    doc = parse_docx(fixture)
    maths = [r for para in doc.paragraphs for r in para.runs
             if isinstance(r, MathBlock)]
    tight = [(m.tight_left, m.tight_right) for m in maths]
    if tight != [(True, True), (True, True)]:
        failures.append(f"parser: tight flags {tight}, wanted both sides tight")
    spaced = [r for para in parse_docx(FIXTURE).paragraphs for r in para.runs
              if isinstance(r, MathBlock) and not r.display]
    if any(m.tight_left or m.tight_right for m in spaced):
        failures.append("parser: an equation with spaces around it read as tight")

    render_document_math(doc, fixture, STORE, seed=3, tools=MathTools())
    store = GlyphStore(STORE)
    style = HandwritingStyle()

    def neighbour_gaps() -> tuple[float, float]:
        """Distance from "kg/m" to the exponent, and from "Pa·" to the "s".

        Two different equations: trailing ")" was already pulled in as
        punctuation, so only a letter after the equation tests the new path.
        """
        page = layout_document(doc, store, style, PageSpec(), seed=0)[0]
        xs = [g.x for g in page.glyphs]
        exp, dot = page.maths[0], page.maths[1]
        return (exp.x - max(x for x in xs if x < exp.x),
                min(x for x in xs if x > dot.x) - dot.x)

    before, after = neighbour_gaps()
    for m in maths:  # the same document read as if Word had spaced them
        m.tight_left = m.tight_right = False
        m.ink._bounds = None
    loose_before, loose_after = neighbour_gaps()
    xh = style.base_size_px / store.native_size_px * 62  # store x-height, page px
    shrink = 0.5 * style.word_gap_frac * xh
    if before > loose_before - shrink:
        failures.append(f"layout: tight equation still {before:.1f}px from the "
                        f"letter before it (spaced: {loose_before:.1f}px)")
    if after > loose_after - shrink:
        failures.append(f"layout: the letter after a tight equation is still "
                        f"{after:.1f}px away (spaced: {loose_after:.1f}px)")
    print(f"tight maths: OK (kg/m|3|) closes to {before:.1f}/{after:.1f}px "
          f"from {loose_before:.1f}/{loose_after:.1f}px when spaced)")


def check_radical_and_bar(failures: list[str]) -> None:
    """The radical hugs its radicand, and a fraction bar covers its numerator.

    Both are the same mismatch: MathJax sized a box for ITS glyphs. Centring
    this hand's narrow surd in TeX's wide surd box left 0.49 em of air inside
    the radical, and a rule sized for TeX's `V` left this hand's `V` hanging
    over the end of the fraction bar.
    """
    from handwriting.mathrender import run_chain
    work = OUT / "radical"
    inks = run_chain(
        [{"id": "sqrt", "latex": r"r = \sqrt{\frac{9\eta v_f}{2\rho g}}",
          "display": True},
         {"id": "frac", "latex": r"qE = \frac{qV}{d}", "display": True}],
        STORE, seed=1, tools=MathTools(work_dir=work))
    if set(inks) != {"sqrt", "frac"}:
        failures.append(f"radical: rendered {sorted(inks)}")
        return
    rp, _ = load_spike()

    a = np.array(inks["sqrt"].image.getchannel("A")) > 40
    h = a.shape[0]
    stem = int(np.argmax(a.sum(0)))          # the radical's tall stroke
    top = a[:int(h * 0.06)]                  # the vinculum runs along the top
    bar = np.where(top.any(0))[0]
    body = np.where(a[int(h * 0.15):, stem + 40:].any(0))[0] + stem + 40
    inside = (body.min() - stem) / rp.PPE    # air between the stem and the radicand
    if inside > 0.30:
        failures.append(f"radical: {inside:.2f} em of air between the stem and "
                        "the radicand — the surd is not against its content")
    if not (bar.min() <= stem + 0.05 * rp.PPE):
        failures.append("radical: the overbar does not reach the stem")

    # the fraction bar covers every mark it separates, plus air at both ends
    b = np.array(inks["frac"].image.getchannel("A")) > 40
    rows = [y for y in range(b.shape[0])
            if _row_runs(b[y], 150)]           # a row holding one long stroke
    if not rows:
        failures.append("fraction: no bar found")
    else:
        y = rows[len(rows) // 2]
        run = max(_row_runs(b[y], 150), key=lambda r: r[1] - r[0])
        num = np.where(b[:y - 8, run[0]:run[1]].any(0))[0] + run[0]
        if num.size and not (run[0] <= num.min() and num.max() <= run[1]):
            failures.append(f"fraction: numerator ink {num.min()}..{num.max()} "
                            f"hangs over the bar {run[0]}..{run[1]}")
    print(f"radical/fraction bar: OK ({inside:.2f} em inside the radical, "
          "numerator covered by the bar)")


def _row_runs(row, min_len):
    """Contiguous ink runs in one pixel row that are at least min_len long."""
    out, start = [], None
    for x, on in enumerate(row):
        if on and start is None:
            start = x
        elif not on and start is not None:
            if x - start >= min_len:
                out.append((start, x - 1))
            start = None
    if start is not None and len(row) - start >= min_len:
        out.append((start, len(row) - 1))
    return out


def check_punct_after_subscript(failures: list[str]) -> None:
    """A comma after an equation ending in a subscript must not read as a prime.

    Reported 2026-09-07: `F_{fr},` drew the comma tight against the subscript,
    which puts it ABOVE that subscript's baseline — "F_fr'". The chain reports
    `ends_subscript`; layout gives the punctuation more air on the strength of it.
    """
    fixture = OUT / "subpunct.docx"
    d = docx.Document()
    p = d.add_paragraph("so from ")
    p._p.append(parse_xml(
        f"<m:oMath {_M}><m:sSub><m:e><m:r><m:t>F</m:t></m:r></m:e>"
        f"<m:sub><m:r><m:t>fr</m:t></m:r></m:sub></m:sSub></m:oMath>"))
    p.add_run(", and on it goes.")
    p2 = d.add_paragraph("plain ")
    p2._p.append(parse_xml(_frac("a", "b")))
    p2.add_run(", and on it goes.")
    d.save(fixture)

    doc = parse_docx(fixture)
    render_document_math(doc, fixture, STORE, seed=3, tools=MathTools())
    maths = [r for para in doc.paragraphs for r in para.runs
             if isinstance(r, MathBlock)]
    if [m.ink.ends_subscript for m in maths] != [True, False]:
        failures.append("chain: ends_subscript is not set by the trailing ink "
                        f"({[m.ink.ends_subscript for m in maths]})")
        return
    store = GlyphStore(STORE)
    style = HandwritingStyle()
    page = layout_document(doc, store, style, PageSpec(), seed=0)[0]
    xh = style.base_size_px / store.native_size_px * 62  # store x-height, page px
    gaps = []
    for m in page.maths:
        m_right = m.x + m.ink.ink_bounds[1] * m.scale
        comma = min((g for g in page.glyphs if g.char == "," and g.x > m.x),
                    key=lambda g: g.x)
        gaps.append(comma.x - m_right)
    sub_gap, frac_gap = gaps
    if not (sub_gap > frac_gap + 0.1 * xh):
        failures.append(f"layout: comma after a subscript got {sub_gap:.1f}px, "
                        f"no more than after a fraction ({frac_gap:.1f}px)")
    if sub_gap > style.word_gap_frac * xh:
        failures.append(f"layout: comma pushed a full word gap away "
                        f"({sub_gap:.1f}px) — it reads as a separate word")
    print(f"punctuation after a subscript: OK ({sub_gap:.1f}px vs {frac_gap:.1f}px "
          f"after a fraction, word gap {style.word_gap_frac * xh:.1f}px)")


def check_parser_layout2(failures: list[str]) -> None:
    doc = parse_docx(FIXTURE2)
    texts = [r.text for p in doc.paragraphs for r in p.runs if isinstance(r, TextRun)]
    if "(1) first item" not in texts:
        failures.append(f"parser: enclosed digit not written as (1): {texts}")
    if "a ≥ b ≤ c ≥ d ≤ e ≥ f ≤ g" not in texts:
        failures.append(f"parser: ≳/≲ not written as ≥/≤ (no glyph of their own): "
                        f"{texts}")
    flags = [p.page_break_before for p in doc.paragraphs]
    if sum(flags) != 1:
        failures.append(f"parser: page_break_before flags {flags}")
    render_document_math(doc, FIXTURE2, STORE, seed=3, tools=MathTools())
    store = GlyphStore(STORE)
    style = HandwritingStyle()
    pages = layout_document(doc, store, style, PageSpec(), seed=0)
    if len(pages) != 2:
        failures.append(f"layout: page break gave {len(pages)} pages, wanted 2")
        return
    # page two starts at the top with the text after the break
    p2 = pages[1]
    if not p2.glyphs or p2.glyphs[0].y > PageSpec().margin_px + 2 * style.base_size_px:
        failures.append("layout: page-two text not at the top of the page")
    if any(p2.glyphs) and p2.glyphs[0].char != "F":
        failures.append(f"layout: page two starts with {p2.glyphs[0].char!r}")
    # the comma after the inline fraction is glued: closer than a word gap
    m = pages[0].maths[0]
    m_right = m.x + m.ink.image.width * m.scale
    comma = next(g for g in pages[0].glyphs if g.char == "," and g.x > m.x)
    xh = style.base_size_px / store.native_size_px * 62  # store x-height, page px
    gap = comma.x - m_right
    if not (-6 <= gap < style.word_gap_frac * xh * 0.6):
        failures.append(f"layout: comma {gap:.1f}px after the equation (not glued)")
    print(f"parser/layout 2: OK ((1), page break -> 2 pages, comma {gap:.1f}px "
          "after inline maths)")


# Alias targets the hand has not written yet: the ONLY aliases allowed to
# resolve to nothing, and each must have a collection sheet waiting for it.
# Shrink this list — never grow it — as the sheets come back written.
PENDING_GLYPHS = {"⇐"}   # docs/BUGS.md [2026-09-20]


def check_aliases(failures: list[str]) -> None:
    """Every alias target exists in the store, and no Greek variant is a box.

    Reported 2026-09-20: ϵ₀ (permittivity) drew a grey placeholder because
    Word/TeX emit U+03F5, while the hand wrote U+03B5.
    """
    import json
    from handwriting.mathrender import run_chain
    mod, store = load_spike()
    for src, dst in mod.ALIASES.items():
        if mod.store_key(store, src) is None:
            if dst in PENDING_GLYPHS:
                continue   # handwriting on its way; docs/BUGS.md tracks it
            failures.append(f"alias: {src!r} -> {dst!r} resolves to nothing")
    for dst in PENDING_GLYPHS:  # the sheet that collects it must still exist
        sheet = ROOT / "scripts" / "make_template_arrows.py"
        if dst not in sheet.read_text(encoding="utf-8"):
            failures.append(f"alias: {dst!r} is pending but no sheet collects it")
    work = OUT / "aliases"
    latex = (r"\epsilon_0 \phi \vartheta \varrho \varpi "
             r"\varepsilon \varphi \theta \rho \pi \gtrsim \lesssim")
    run_chain([{"id": "greek", "latex": latex, "display": True}],
              STORE, seed=1, tools=MathTools(work_dir=work))
    meta = json.loads((work / "hand" / "hand_greek.json").read_text())
    if meta["missing"]:
        failures.append(f"alias: placeholders drawn for {meta['missing']}")
    print(f"aliases: OK ({len(mod.ALIASES)} aliases resolve, Greek variants "
          "draw the collected letter)")


def main() -> int:
    failures: list[str] = []
    make_fixture()
    make_fixture2()
    check_stretchy(failures)
    check_aliases(failures)
    check_constructs(failures)
    check_spacing(failures)
    check_tight_math(failures)
    check_punct_after_subscript(failures)
    check_radical_and_bar(failures)
    check_parser_layout2(failures)
    check_parser(failures)
    doc = check_mathrender(failures)
    display = check_layout(failures, doc) if doc is not None else None
    if doc is not None:
        check_math_align(failures, doc)
    check_end_to_end(failures, display)
    print()
    if failures:
        print(f"FAIL ({len(failures)} problems):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: document equations feature checks all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
