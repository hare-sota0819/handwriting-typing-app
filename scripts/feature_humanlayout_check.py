"""Feature verification: on ruled paper the layout does what a person copying
by hand would do (user report 2026-09-30: an empty rule inside one Word
paragraph, "easily." alone on the next page).

Room above a line is measured against the ink really written there:
- an inline equation taller than text (H⁺, 10⁻¹⁴) whose columns have nothing
  written above lands on the very next rule — no empty rule;
- the same equation under ink it would really touch still moves its line;
- a word under an equation's deep descent is kept clear of it;
- at the top of a sheet nothing is above: the line is written on the first
  rule;
- an author's blank line before such a line stays exactly one empty rule.
Exit 0 = pass.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

from handwriting.document_model import Document, MathBlock, Paragraph, TextRun
from handwriting.glyphstore import GlyphStore
from handwriting.layout import LineGrid, PageSpec, layout_document
from handwriting.mathrender import MathInk, measure_cap_ink
from handwriting.style import HandwritingStyle
from handwriting.synthglyphs import DEFAULT_STORE

# The user's ruled template at 150 dpi (탬플릿.pdf as detected).
GRID = LineGrid(spacing_px=33.33, offset_px=104.2, margin_x_px=133.5,
                last_rule_px=1704.2)
LAST_RULE = round((GRID.last_rule_px - GRID.offset_px) / GRID.spacing_px)
CAP_ROWS = 100  # cap height of the test equations, in image rows

store = GlyphStore(DEFAULT_STORE)
style = HandwritingStyle()
spec = PageSpec()


def layout(paragraphs):
    return layout_document(Document(paragraphs), store, style, spec, seed=5,
                           grid=GRID)


def rule(rec) -> int:
    return round((rec.y - GRID.offset_px) / GRID.spacing_px)


def ink(asc_caps: float, desc_caps: float = 0.05, width: int = 400,
        left: int = 0) -> MathInk:
    """An equation image: a cap-high body plus a raised script reaching
    asc_caps cap heights above the baseline, ink hanging desc_caps below it,
    drawn over columns [left, width)."""
    base = round(asc_caps * CAP_ROWS)
    h = base + max(1, round(desc_caps * CAP_ROWS))
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((left, base - CAP_ROWS, width - 1, h - 1), fill=(0, 0, 0, 255))
    d.rectangle((left + (width - left) // 2, 0, width - 1, base - CAP_ROWS),
                fill=(0, 0, 0, 255))
    return MathInk(image=img, baseline_y=float(base), cap_px=float(CAP_ROWS),
                   store_cap_ink=float(CAP_ROWS))


def para(*runs) -> Paragraph:
    return Paragraph([TextRun(r) if isinstance(r, str) else
                      MathBlock(omml_xml="", ink=r) for r in runs])


def main() -> int:
    failures: list[str] = []

    # page cap height and the text-size limit, read back from a probe
    probe = layout([para("x", ink(1.0))])[0].maths[0]
    cap = probe.scale * CAP_ROWS
    pad = 0.15 * cap + 2 * style.word_drift_px * style.snap_drift_scale
    lane = GRID.spacing_px - pad          # tallest ascent measured by ink
    # A superscript (H⁺, 10⁻¹⁴): inside one lane, but over the old fixed
    # budget (a worst-case descender assumed above at every x), which moved
    # such a line down a whole rule.
    base_size = cap / measure_cap_ink(store) * store.native_size_px
    old_room = GRID.spacing_px - 0.25 * base_size - 0.15 * cap
    sup = max(1.25 * cap, (old_room + lane) / 2) / cap
    if not old_room + 0.5 < sup * cap < lane - 0.5:
        failures.append(f"test superscript {sup * cap:.1f}px is not between the "
                        f"old budget {old_room:.1f}px and the lane {lane:.1f}px")

    # 1. nothing written above the equation's columns -> next rule
    pages = layout([para("ab"), para("cd", ink(sup))])
    k0, k1 = rule(pages[0].glyphs[0]), rule(pages[0].maths[0])
    if k1 != k0 + 1:
        failures.append(f"superscript under an empty stretch skipped rules: "
                        f"{k0} -> {k1}")
    if abs(pages[0].maths[0].scale / probe.scale - 1.0) > 1e-9:
        failures.append("an equation with nothing above it was written smaller")

    # 2. an equation above that it would really touch -> the line moves;
    #    the same pair side by side -> it does not
    deep = ink(1.0, desc_caps=24.0 / cap, width=600)
    tall = (lane - 1.0) / cap
    pages = layout([para(deep), para(ink(tall, width=300))])
    k0, k1 = rule(pages[0].maths[0]), rule(pages[0].maths[1])
    if k1 < k0 + 2:
        failures.append(f"equation under touching ink was not moved: {k0} -> {k1}")
    words_under = layout([para(deep), para("Hello")])
    if rule(words_under[0].glyphs[0]) < rule(words_under[0].maths[0]) + 2:
        failures.append("a word under an equation's deep descent was not moved")
    side = layout([para("x", ink(1.0, desc_caps=24.0 / cap, width=200)),
                   para("H")])
    if rule(side[0].glyphs[-1]) != rule(side[0].maths[0]) + 1:
        failures.append("a word clear of the equation above was moved")
    # a text-height equation under that descent is cleared like a word
    pages = layout([para(deep), para(ink(1.0, width=300))])
    if rule(pages[0].maths[1]) < rule(pages[0].maths[0]) + 2:
        failures.append("a text-height equation under a deep descent was not moved")
    # a word just inside the pad of the ink above still moves
    near = ink(1.0, desc_caps=12.7 / cap, width=600)
    pages = layout([para(near), para("Hello")])
    if rule(pages[0].glyphs[0]) < rule(pages[0].maths[0]) + 2:
        failures.append("a word within the pad of the equation above was not moved")

    # 3. top of a sheet: the continuation is written on the first rule (the
    #    last sheet's ink, descenders across the width, must not carry over)
    fill = [para("a") for _ in range(LAST_RULE + 1)]
    gfill = [para("g" * 40) for _ in range(LAST_RULE + 1)]
    pages = layout(gfill + [para("see", ink(sup))])
    if len(pages) != 2:
        failures.append(f"page-top case: want 2 pages, got {len(pages)}")
    else:
        first = min(rule(r) for r in pages[1].glyphs + pages[1].maths)
        if first != 0:
            failures.append(f"page-top line starts on rule {first}, not rule 0")
    broken = Paragraph([TextRun("see"), MathBlock(omml_xml="", ink=ink(sup))],
                       page_break_before=True)
    pages = layout([para("g" * 40) for _ in range(10)] + [broken])
    if len(pages) != 2 or min(rule(r) for r in pages[1].glyphs
                              + pages[1].maths) != 0:
        failures.append("after a page break the line did not start on rule 0")

    # 4. an author's blank line stays exactly one empty rule
    pages = layout([para("ab"), Paragraph([]), para("cd", ink(sup))])
    k0, k1 = rule(pages[0].glyphs[0]), rule(pages[0].maths[0])
    if k1 != k0 + 2:
        failures.append(f"one blank line became {k1 - k0 - 1} empty rules")
    if abs(pages[0].maths[0].scale / probe.scale - 1.0) > 1e-9:
        failures.append("an equation under a blank line was written smaller")
    # ... also for an equation taller than a lane: the blank lane is its room
    taller = ink((lane + 0.3 * cap) / cap, width=300)
    for n_blank in (1, 2):
        pages = layout([para("ab cd")] + [Paragraph([])] * n_blank
                       + [para("ab", taller)])
        k0, k1 = rule(pages[0].glyphs[0]), rule(pages[0].maths[0])
        if k1 - k0 - 1 != n_blank:
            failures.append(f"{n_blank} blank line(s) above a tall equation became "
                            f"{k1 - k0 - 1} empty rules")

    # 5. a near miss is written a little smaller, never below 0.9x
    pages = layout([para("g" * 30), para(ink(sup, width=600))])
    got = pages[0].maths[0].scale / probe.scale
    if got < 0.9 - 1e-9:
        failures.append(f"inline equation shrunk to {got:.2f}x (limit 0.9x)")
    # a real miss (more than 10% smaller can fix) moves the line instead
    pages = layout([para("g" * 30), para(ink(30.0 / cap, width=600))])
    k0, k1 = rule(pages[0].glyphs[0]), rule(pages[0].maths[0])
    if k1 != k0 + 2 or abs(pages[0].maths[0].scale / probe.scale - 1.0) > 1e-9:
        failures.append(f"a real miss: rule {k0} -> {k1}, scale "
                        f"{pages[0].maths[0].scale / probe.scale:.2f} "
                        "(want the next-but-one rule at full size)")

    # a caption pushed down under a deep equation, carried to a fresh page,
    # starts on its first rule; the author's blank lines after it stay whole
    pages = layout([para("a") for _ in range(LAST_RULE - 2)] + [para(deep)]
                   + [para("Hello"), Paragraph([]), Paragraph([]), para("next")])
    p2 = pages[-1]
    ks = sorted({rule(g) for g in p2.glyphs})
    if len(pages) != 2 or ks[:2] != [0, 3]:
        failures.append(f"carried caption: page-2 rules {ks[:2]}, want [0, 3]")

    # Display equations (user's choice 2026-09-30): one blank rule between
    # prose and an equation block, the steps of a derivation on the next
    # free rules, an author's blank line counted toward the air, not added.
    row = ink(1.0, width=300)                                   # one line
    frac = ink(1.9, desc_caps=1.15, width=300)                  # a fraction

    def disp(i):
        return Paragraph([MathBlock(omml_xml="", ink=i, display=True)])

    def gaps(paragraphs):
        """Empty rules between consecutive written lines of page 1."""
        ks = sorted({rule(r) for r in layout(paragraphs)[0].glyphs
                     + layout(paragraphs)[0].maths})
        return [b - a - 1 for a, b in zip(ks, ks[1:])]

    got = gaps([para("Lead in:"), disp(row), disp(row), disp(row), para("After.")])
    if got != [1, 0, 0, 1]:
        failures.append(f"prose/steps/prose gaps {got}, want [1, 0, 0, 1]")
    got = gaps([para("Lead in:"), disp(row), Paragraph([]), para("After.")])
    if got != [1, 1]:
        failures.append(f"author blank after an equation: gaps {got}, want [1, 1]")
    # a fraction fills its own lane and the one under its rule: the blank
    # rule below it comes after the denominator's lane
    got = gaps([para("Lead in:"), disp(frac), para("After.")])
    if got != [1, 2]:
        failures.append(f"fraction gaps {got}, want [1, 2]")

    # foot of a page: the air goes before the page is turned
    pages = layout([para("a") for _ in range(LAST_RULE)] + [disp(row)])
    if len(pages) != 1 or rule(pages[0].maths[0]) != LAST_RULE:
        failures.append("an equation that fits the last rule without its air "
                        "was sent to the next page")
    # top of a page: a display equation starts on the first rule
    pages = layout(fill + [disp(frac)])
    if len(pages) != 2 or rule(pages[1].maths[0]) != 0:
        failures.append("a display equation opening a page did not start on rule 0")

    # Line ends (user's choice 2026-09-30): the last 1-3 words of a paragraph
    # that miss the line are squeezed in, up to 6 mm from the paper's edge.
    tail_right = spec.width_px * (1 - 6.0 / 210.0)
    # n "xx" fill one line (counted on the first line of a long paragraph,
    # far from any tail that could be squeezed)
    first = [g for g in layout([para("xx " * 200)])[0].glyphs if rule(g) == 0]
    n = len(first) // 2
    def ink_end(glyphs) -> float:
        ends = []
        for g in glyphs:
            v = store.entry(g.char).variants[g.variant]
            ends.append(g.x + (v.left_bearing + v.ink_bbox[2]) * g.scale)
        return max(ends)

    ends = []
    for tail in ("tail", "tailtail", "tailtailtail", "tailtailtailtail"):
        squeezed = layout([para("xx " * n + tail)])[0].glyphs
        if len({rule(g) for g in squeezed}) == 1:
            ends.append(ink_end(squeezed))
    if not ends:
        failures.append("a one-word paragraph tail was put on a line of its own")
    elif max(ends) > tail_right or max(ends) <= spec.width_px - spec.margin_px:
        failures.append(f"squeezed tails end at x={[round(e) for e in ends]}: "
                        f"want one past the column, none past {tail_right:.0f}")
    long_tail = layout([para("xx " * n + "tail tail tail tail")])
    if len({rule(g) for g in long_tail[0].glyphs}) != 2:
        failures.append("a four-word tail was squeezed instead of wrapped")
    # ... and on the last rule it keeps the page from turning ("easily.")
    foot = layout([para("a") for _ in range(LAST_RULE)] + [para("xx " * n + "tail")])
    if len(foot) != 1:
        failures.append("a one-word tail on the last rule turned the page")

    # a problem number is not left alone on the last rule
    pages = layout([para("a") for _ in range(LAST_RULE)]
                   + [para("16.136"), para("Each target reaction.")])
    if len(pages) != 2 or "".join(g.char for g in pages[1].glyphs)[:6] != "16.136" \
            or rule(pages[1].glyphs[0]) != 0:
        failures.append("a problem number on the last rule was not moved over "
                        "with its body")

    # the text before reserved figure space goes along only if it is a caption
    blanks = [Paragraph([]) for _ in range(5)]
    before = [para("a") for _ in range(LAST_RULE - 2)]
    for text, moves in (("So the reaction is second order.", False),
                        ("Fig 1 A charged capacitor.", True)):
        pages = layout(before + [para(text)] + blanks + [para("End")])
        on_first = text.replace(" ", "")[:4] in "".join(g.char for g in pages[0].glyphs)
        if on_first == moves:
            failures.append(f"{text!r} {'stayed' if on_first else 'moved'} at a "
                            "page end before figure space")
    # numbered captions are captions; unruled pages keep the old rule (any
    # 1-2 line paragraph goes along with the space)
    pages = layout(before + [para("(d) Plot the rate vs. time.")] + blanks
                   + [para("End")])
    if "(d)Plot" in "".join(g.char for g in pages[0].glyphs):
        failures.append("a numbered caption '(d) Plot ...' was left behind")
    def page_of_s(paragraphs):
        pgs = layout_document(Document(paragraphs), store, style, spec, seed=5,
                              grid=None)
        return next(i for i, pg in enumerate(pgs)
                    if any(g.char == "S" for g in pg.glyphs))

    moved = False
    for k in range(10, 45):  # some k puts the space past an unruled page end
        head = [para("a") for _ in range(k)] + [para("So the reaction is second order.")]
        alone = page_of_s(head + [para("End")])
        spaced = page_of_s(head + [Paragraph([]) for _ in range(12)] + [para("End")])
        moved = moved or spaced > alone
    if not moved:
        failures.append("unruled layout changed: a short sentence before figure "
                        "space no longer goes along with it")

    # review of steps 2-4 (2026-09-30)
    # - headings written together move together; an answer line ending in an
    #   equation ("base: H2O") and a file name are not headings
    pages = layout([para("a") for _ in range(LAST_RULE - 1)]
                   + [para("Theory"), para("1. Capacitors"), para("A capacitor is.")])
    if len(pages) != 2 or "".join(g.char for g in pages[1].glyphs)[:6] != "Theory":
        failures.append("a heading pair at the page foot was split")
    for runs in ((TextRun("Acid: HBrO, base:"), ink(1.0)),
                 (TextRun("202_Capacitor_KOR"),)):
        p = Paragraph([r if isinstance(r, TextRun) else
                       MathBlock(omml_xml="", ink=r) for r in runs])
        pages = layout([para("a") for _ in range(LAST_RULE)] + [p, para("Next.")])
        if rule((pages[0].glyphs + pages[0].maths)[-1]) != LAST_RULE:
            failures.append(f"{runs[0].text!r} was carried as if it were a heading")
    # - a Word page break inside a squeezed tail ends the squeeze
    wp_style = HandwritingStyle()
    wp_style.word_pages = True
    from handwriting.document_model import WordPageBreak
    wp = layout_document(
        Document([Paragraph([TextRun("xx " * n + "tail"), WordPageBreak(),
                             TextRun("after " * 12)])]),
        store, wp_style, spec, seed=5, grid=GRID)
    if max(ink_end([g]) for pg in wp for g in pg.glyphs) > tail_right:
        failures.append("words after a Word page break ran past the paper edge")
    # - manual rule grid (no last rule known): text after an equation near the
    #   foot turns the page instead of running below it
    manual = LineGrid(spacing_px=GRID.spacing_px, offset_px=GRID.offset_px,
                      margin_x_px=GRID.margin_x_px)
    for k in range(38, 46):
        pages = layout_document(
            Document([para("ab") for _ in range(k)] + [disp(frac), para("after")]),
            store, style, spec, seed=5, grid=manual)
        low = max(r.y for pg in pages for r in pg.glyphs + pg.maths)
        if low > spec.height_px - spec.margin_px:
            failures.append(f"manual grid: a line at y={low:.0f} runs below the "
                            f"page's writing area (k={k})")
            break
    # - consecutive displays: the next one starts below the whole line above
    #   (tucked into its gaps, a numerator reads as a subscript)
    left_row = Paragraph([MathBlock(omml_xml="", display=True, align="left",
                                    ink=ink(1.0, desc_caps=0.45, width=300))])
    right_frac = Paragraph([MathBlock(omml_xml="", display=True, align="right",
                                      ink=frac)])
    m = layout([para("Lead in:"), left_row, right_frac])[0].maths
    low0 = m[0].y + (m[0].ink.image.height - m[0].ink.baseline_y) * m[0].scale
    top1 = m[1].y - m[1].ink.baseline_y * m[1].scale
    if top1 < low0:
        failures.append("a display equation tucked into the line above it")
    # - a numerator's tip a few px over its lane is not a second blank rule
    tip = ink(1.1 * GRID.spacing_px / cap, desc_caps=1.0, width=300)
    got = gaps([para("Lead in:"), disp(tip)])
    if got != [1]:
        failures.append(f"a display with a tip over its lane: gaps {got}, want [1]")
    # - a lone blank line that a page turn already made is not written again
    pages = layout(fill + [Paragraph([]), para("b")])
    if len(pages) != 2 or rule(pages[1].glyphs[0]) != 0:
        failures.append("a lone blank at a page turn left page 2's first rule empty")

    print(f"cap {cap:.1f}px, pad {pad:.1f}px, lane limit {lane:.1f}px, "
          f"old budget {old_room:.1f}px, test superscript {sup * cap:.1f}px")
    if failures:
        print("FAIL:")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS: ruled-paper layout checks all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
