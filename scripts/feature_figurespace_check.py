"""Feature verification: reserved figure space is never split across pages.

A run of two or more blank paragraphs is space the writer left on purpose (a
figure to paste in later), usually under a one-line caption. Pages are filled
to the bottom, but such a block stays whole:

- it does not fit in what is left of the page -> the caption and its blank
  lines move to the next page together;
- the caption landed on the very last line (the page turned right after it)
  -> the caption is carried over to sit above its space;
- the text before the space is a long paragraph, not a caption -> the text
  stays, the space opens the next page;
- it fits -> nothing changes; a single blank line is never a block; a run
  longer than a page is left to flow.
Checked unsnapped and snapped to a rule grid. Exit 0 = pass.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handwriting.document_model import Document, Paragraph, TextRun
from handwriting.glyphstore import GlyphStore
from handwriting.layout import LineGrid, PageSpec, layout_document
from handwriting.style import HandwritingStyle
from handwriting.synthglyphs import DEFAULT_STORE

CAPTION = "Fig"
AFTER = "End"
BLANKS = 5


def text(page) -> str:
    return "".join(g.char for g in page.glyphs)


def line_ys(page, tol: float) -> list[float]:
    """Baseline y of each written line on the page, top to bottom."""
    ys: list[float] = []
    for g in sorted(page.glyphs, key=lambda g: g.y):
        if not ys or g.y - ys[-1] > tol:
            ys.append(g.y)
    return ys


def run_case(label, grid, failures) -> None:
    store = GlyphStore(DEFAULT_STORE)
    style = HandwritingStyle()
    spec = PageSpec()

    def layout(paragraphs):
        doc = Document([Paragraph([TextRun(t)] if t else []) for t in paragraphs])
        return layout_document(doc, store, style, spec, seed=3, grid=grid)

    # how many one-line paragraphs a page holds, and the line pitch
    probe = layout(["a"] * 200)
    per_page = len(probe[0].glyphs)
    ys = line_ys(probe[0], 1.0)
    pitch = (ys[-1] - ys[0]) / (len(ys) - 1)
    top = ys[0]
    tol = 0.45 * pitch
    if per_page < BLANKS + 4:
        failures.append(f"{label}: page holds only {per_page} lines, fixture too big")
        return

    def line_no(y: float) -> int:
        return round((y - top) / pitch)

    block = [CAPTION] + [""] * BLANKS + [AFTER]

    # 1. the block does not fit under the caption -> both move together
    pages = layout(["a"] * (per_page - 3) + block)
    if len(pages) != 2:
        failures.append(f"{label} split: want 2 pages, got {len(pages)}")
    else:
        if CAPTION in text(pages[0]):
            failures.append(f"{label} split: caption left behind on page one")
        p2 = text(pages[1])
        if not p2.startswith(CAPTION) or not p2.endswith(AFTER):
            failures.append(f"{label} split: page two reads {p2!r}")
        else:
            got = [line_no(y) for y in line_ys(pages[1], tol)]
            if got != [0, BLANKS + 1]:
                failures.append(f"{label} split: caption/next text on lines {got}, "
                                f"want [0, {BLANKS + 1}]")

    # 2. the caption took the very last line -> carried over above its space
    pages = layout(["a"] * (per_page - 1) + block)
    if len(pages) != 2:
        failures.append(f"{label} last-line: want 2 pages, got {len(pages)}")
    else:
        if CAPTION in text(pages[0]):
            failures.append(f"{label} last-line: caption stranded at the page foot")
        got = [line_no(y) for y in line_ys(pages[1], tol)]
        if got != [0, BLANKS + 1]:
            failures.append(f"{label} last-line: lines {got}, want [0, {BLANKS + 1}]")

    # 3. a long paragraph is not a caption: it stays, the space opens page two
    long_para = " ".join(["word"] * 40)
    n_long = len(line_ys(layout([long_para])[0], tol))
    if n_long < 3:
        failures.append(f"{label} long: fixture paragraph only {n_long} lines")
    pages = layout(["a"] * (per_page - n_long - 2) + [long_para] + [""] * BLANKS + [AFTER])
    if len(pages) != 2:
        failures.append(f"{label} long: want 2 pages, got {len(pages)}")
    else:
        if "word" in text(pages[1]):
            failures.append(f"{label} long: body text was dragged to page two")
        got = [line_no(y) for y in line_ys(pages[1], tol)]
        if got != [BLANKS]:
            failures.append(f"{label} long: next text on lines {got}, want [{BLANKS}]")

    # 4. it fits -> untouched
    pages = layout(["a"] * 2 + block)
    got = [line_no(y) for y in line_ys(pages[0], tol)]
    if len(pages) != 1 or got != [0, 1, 2, BLANKS + 3]:
        failures.append(f"{label} fits: {len(pages)} page(s), lines {got}")

    # 5. one blank line is a paragraph gap, not a block: it may end a page
    pages = layout(["a"] * (per_page - 1) + [CAPTION, "", AFTER])
    if CAPTION not in text(pages[0]):
        failures.append(f"{label} single: a lone blank line moved the text before it")

    # 6. a run longer than a page just flows
    pages = layout(["a", CAPTION] + [""] * (per_page + 3) + [AFTER])
    if CAPTION not in text(pages[0]):
        failures.append(f"{label} oversize: caption moved for a run no page can hold")


def main() -> int:
    failures: list[str] = []
    run_case("unsnapped", None, failures)
    run_case("snapped", LineGrid(spacing_px=40.0, offset_px=150.0), failures)
    if failures:
        print(f"FAIL ({len(failures)} problems):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: reserved figure space stays whole")
    return 0


if __name__ == "__main__":
    sys.exit(main())
