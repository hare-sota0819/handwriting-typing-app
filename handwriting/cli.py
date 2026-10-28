"""Command-line interface: input.docx [--style s.json] [--seed N] --out path.

--out ending in .pdf writes a single combined PDF; otherwise pages are written
as PNGs (one page => that exact path; multiple pages => <stem>_p1.png, ...).
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from PIL import Image

from .compositor import FIT_MODES, PaperStyle
from .layout import PageSpec
from .mathrender import MathTools
from .pipeline import render_document, resolve_line_grid
from .stores import default_store
from .style import HandwritingStyle


def save_pages(pages: list[Image.Image], out: Path) -> list[Path]:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".pdf":
        # Tag the PDF at the true raster DPI so viewers/printers get an A4-sized
        # page instead of Pillow's default 72-dpi (which makes a ~17-inch page
        # that renders soft). Pages are A4, so DPI = width_px / A4-width-inches.
        dpi = round(pages[0].width / (210.0 / 25.4))
        pages[0].save(out, save_all=True, append_images=pages[1:], resolution=dpi)
        return [out]
    if len(pages) == 1:
        target = out if out.suffix else out.with_suffix(".png")
        pages[0].save(target)
        return [target]
    stem = out.with_suffix("")
    written = []
    for i, page in enumerate(pages, start=1):
        p = stem.parent / f"{stem.name}_p{i}.png"
        page.save(p)
        written.append(p)
    return written


def render_with_options(
    input_path: Path,
    style_path: Path | None = None,
    seed: int = 0,
    store: Path | None = None,
    paper_pdf: Path | None = None,
    paper_fit: str = "cover",
    snap_lines: bool = False,
    rule_spacing: float | None = None,
    rule_offset: float | None = None,
    rule_margin_x: float | None = None,
    dpi: int = 400,
    effects: bool = True,
    style_overrides: dict | None = None,
    paper_style: PaperStyle | None = None,
    math_tools: MathTools = MathTools(),
    math_raw_pen: bool = False,
) -> list[Image.Image]:
    """The CLI's option→pages core, callable without argparse (used by the GUI).

    style_overrides are raw HandwritingStyle field values (e.g. line_height,
    base_size_px at the 150-dpi reference scale) applied on top of the loaded
    style, before the dpi scaling below.
    """
    style = HandwritingStyle()
    if style_path:
        style = HandwritingStyle.from_dict(json.loads(style_path.read_text()))
    for field, value in (style_overrides or {}).items():
        setattr(style, field, value)
    if not effects:
        style.effects = False

    paper = paper_style or PaperStyle()
    if paper_pdf:
        paper = PaperStyle(background_pdf=paper_pdf, fit=paper_fit)

    # Resolution and glyph size are INDEPENDENT axes, at the user's insistence:
    # "해상도는 극상, 글자 크기는 내가 고를 수 있게." The style's px values describe
    # the page at 150 dpi, so raising the resolution alone would shrink the writing
    # on the page instead of sharpening it. Scale them with the raster.
    dpi_scale = dpi / 150.0
    if dpi_scale != 1.0:
        for field in ("base_size_px", "word_drift_px", "baseline_drift_px",
                      "baseline_drift_period_px", "snap_wobble_px",
                      "line_rise_px", "margin_drift_px"):
            setattr(style, field, getattr(style, field) * dpi_scale)

    # A4 page at the requested DPI (defaults reproduce the 150-dpi PageSpec).
    page = PageSpec(
        width_px=round(210.0 / 25.4 * dpi),
        height_px=round(297.0 / 25.4 * dpi),
        margin_px=round(120 * dpi / 150),
    )

    grid = resolve_line_grid(
        paper_pdf, snap_lines,
        rule_spacing=rule_spacing,
        rule_offset=rule_offset,
        rule_margin_x=rule_margin_x,
        page=page,
    )

    return render_document(input_path, style=style, seed=seed, paper=paper,
                           grid=grid, store_root=store, page=page,
                           math_tools=math_tools, math_raw_pen=math_raw_pen)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="handwriting",
        description="Convert a plain-text .docx into handwriting-style page images.",
    )
    parser.add_argument("input", type=Path, help="input .docx file")
    parser.add_argument("--style", type=Path, help="HandwritingStyle JSON file")
    parser.add_argument("--seed", type=int, default=0, help="random seed")
    parser.add_argument("--out", type=Path, required=True, help="output .png or .pdf path")
    parser.add_argument("--store", type=Path, default=None,
                        help="glyph store root (default: the first store under "
                             "glyphs/ — your imported handwriting, else the demo store)")
    parser.add_argument(
        "--paper", type=Path,
        help="background PDF; its page(s) replace the default off-white paper",
    )
    parser.add_argument(
        "--paper-fit", choices=FIT_MODES, default="cover",
        help="how to fit the background PDF to the page (default: cover)",
    )
    parser.add_argument(
        "--snap-lines", action="store_true",
        help="snap text baselines onto the paper's ruled lines "
             "(auto-detects rules from the --paper PDF)",
    )
    parser.add_argument("--rule-spacing", type=float,
                        help="manual rule spacing in px (overrides auto-detect, implies snapping)")
    parser.add_argument("--rule-offset", type=float,
                        help="manual y of the first rule in px (default: one spacing)")
    parser.add_argument("--rule-margin-x", type=float,
                        help="manual x of the vertical margin line in px (optional)")
    parser.add_argument("--dpi", type=int, default=400,
                        help="output resolution in DPI (default 150; e.g. 300 for a "
                             "sharper, higher-res page). Everything scales with it.")
    parser.add_argument("--no-effects", action="store_true",
                        help="disable the scanned-look effects chain (residue "
                             "threshold, ink/page effects); plain clean render")
    parser.add_argument("--word-pages", action="store_true",
                        help="mirror Word's own pages: start a new page wherever "
                             "Word's last layout did")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not args.input.exists():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 2
    if args.paper and not args.paper.exists():
        print(f"error: paper PDF not found: {args.paper}", file=sys.stderr)
        return 2

    pages = render_with_options(
        args.input,
        style_path=args.style,
        seed=args.seed,
        store=args.store,
        paper_pdf=args.paper,
        paper_fit=args.paper_fit,
        snap_lines=args.snap_lines,
        rule_spacing=args.rule_spacing,
        rule_offset=args.rule_offset,
        rule_margin_x=args.rule_margin_x,
        dpi=args.dpi,
        effects=not args.no_effects,
        style_overrides={"word_pages": True} if args.word_pages else None,
    )
    written = save_pages(pages, args.out)
    print(f"wrote {len(pages)} page(s): {', '.join(str(p) for p in written)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
