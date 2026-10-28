"""End-to-end pipeline: .docx path → finished page images.

Wires the stages in order — parser → layout → variation → renderer →
compositor — so both the CLI and tests share one code path.
"""

import logging
from dataclasses import replace
from pathlib import Path

from PIL import Image

from .compositor import PaperStyle, compose_pages, detect_rule_grid, rasterize_pdf
from .glyphstore import GlyphStore
from .layout import LineGrid, PageSpec, layout_document
from .mathrender import MathTools, render_document_math
from .parser import parse_docx
from .renderer import render_pages
from .style import HandwritingStyle
from .stores import default_store
from .variation import apply_variation

logger = logging.getLogger(__name__)


def resolve_line_grid(
    paper_pdf: str | Path | None,
    snap: bool,
    rule_spacing: float | None = None,
    rule_offset: float | None = None,
    rule_margin_x: float | None = None,
    page: PageSpec = PageSpec(),
) -> LineGrid | None:
    """Decide the baseline grid to snap onto (or None = don't snap).

    Manual --rule-spacing overrides detection and implies snapping. Otherwise,
    when snapping is on and a paper PDF is given, auto-detect the rules; a
    detection failure logs a warning and returns None (un-snapped fallback).
    """
    if rule_spacing is not None:
        offset = rule_offset if rule_offset is not None else rule_spacing
        return LineGrid(spacing_px=rule_spacing, offset_px=offset, margin_x_px=rule_margin_x)
    if not snap:
        return None
    if paper_pdf is None:
        logger.warning(
            "--snap-lines needs a --paper PDF (or --rule-spacing/--rule-offset); "
            "not snapping"
        )
        return None
    raster = rasterize_pdf(paper_pdf, (page.width_px, page.height_px))[0]
    detected = detect_rule_grid(raster)
    if detected is None:
        return None  # detect_rule_grid already warned
    spacing, offset, margin_x, last_rule = detected
    return LineGrid(spacing_px=spacing, offset_px=offset, margin_x_px=margin_x,
                    last_rule_px=last_rule)


def render_document(
    docx_path: str | Path,
    style: HandwritingStyle | None = None,
    seed: int = 0,
    page: PageSpec = PageSpec(),
    paper: PaperStyle = PaperStyle(),
    store_root: str | Path | None = None,
    grid: LineGrid | None = None,
    math_tools: MathTools = MathTools(),
    math_raw_pen: bool = False,
) -> list[Image.Image]:
    """Convert a .docx into a list of finished RGB page images.

    Equations in the document are rendered through the math chain
    (mathrender.py) with the same store and seed and laid out among the text.
    """
    style = style or HandwritingStyle()
    store_root = Path(store_root) if store_root else default_store()
    store = GlyphStore(store_root)
    counts = {c: len(store.entry(c).variants) for c in store.characters}

    document = parse_docx(docx_path)
    render_document_math(document, Path(docx_path), Path(store_root), seed,
                         tools=math_tools, raw_pen=math_raw_pen)
    pages = layout_document(document, store, style, page, seed=seed, grid=grid)
    var_style = style
    if grid is not None and style.word_drift_px > 0:
        # On ruled paper the writer aligns to the printed lines: damp the
        # per-word height walk like the baseline drift is damped.
        var_style = replace(
            style, word_drift_px=style.word_drift_px * style.snap_drift_scale)
    pages = apply_variation(pages, counts, var_style, seed=seed)
    ink_pages = render_pages(pages, store, style, seed=seed)
    return compose_pages(
        ink_pages, paper, seed=seed,
        scanner_tone_amp=style.scanner_tone_amp if style.effects else 0,
    )
