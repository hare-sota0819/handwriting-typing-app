"""Paper compositor: lay ink-only page renders onto a paper background.

Its own reusable stage — the renderer produces transparent ink; this stage
produces the finished page. Kept separate so paper style can evolve (lined
paper, scans, user PDFs) without touching the renderer.

Two backgrounds:
- default: off-white with a faint, seedable noise texture (procedural)
- optional: a user-supplied PDF, rasterized to the page resolution and fitted
  under the ink (PaperStyle.background_pdf)
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

FIT_MODES = ("cover", "stretch", "contain")


@dataclass(frozen=True)
class PaperStyle:
    paper_rgb: tuple[int, int, int] = (250, 249, 243)  # warm off-white
    texture_amp: int = 4  # +/- per-channel noise amplitude; 0 disables texture

    # Optional user-supplied background PDF. When set, its rasterized page(s)
    # replace the procedural off-white paper.
    background_pdf: Path | None = None
    # How a background page is fitted to the output page raster:
    #   cover   - scale to fill, center-crop overflow (default; no empty margins)
    #   stretch - scale to exact page size (may distort aspect)
    #   contain - fit whole image, letterbox margins in the average edge color
    fit: str = "cover"


def _paper(size: tuple[int, int], paper: PaperStyle, seed: int) -> Image.Image:
    w, h = size
    base = np.array(paper.paper_rgb, dtype=np.int16)
    if paper.texture_amp > 0:
        rng = np.random.default_rng(seed)
        noise = rng.integers(
            -paper.texture_amp, paper.texture_amp + 1, size=(h, w, 1)
        )
        arr = np.clip(base + noise, 0, 255).astype(np.uint8)
        arr = np.broadcast_to(arr, (h, w, 3)).copy()
    else:
        arr = np.broadcast_to(base.astype(np.uint8), (h, w, 3)).copy()
    return Image.fromarray(arr, mode="RGB").convert("RGBA")


def rasterize_pdf(path: str | Path, target_size: tuple[int, int]) -> list[Image.Image]:
    """Rasterize every page of a PDF to RGB images covering target_size.

    Each page is rendered at a zoom large enough that its raster is at least
    target_size in both axes (so the later fit only ever downsamples — crisp,
    never upscaled-blurry). pymupdf (fitz) is imported lazily so the procedural
    paper path never needs the dependency.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "a --paper PDF was given but PyMuPDF is not installed; "
            "run: .venv/bin/pip install -r requirements.txt"
        ) from exc

    tw, th = target_size
    images: list[Image.Image] = []
    with fitz.open(str(path)) as doc:
        if doc.page_count == 0:
            raise ValueError(f"background PDF has no pages: {path}")
        for page in doc:
            pw, ph = page.rect.width, page.rect.height
            zoom = max(tw / pw, th / ph) if pw and ph else 1.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            images.append(
                Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            )
    return images


def detect_rule_grid(
    image: Image.Image,
    min_rules: int = 5,
    cover_frac: float = 0.5,
    dark_delta: int = 3,
    var_tol: float = 0.25,
) -> tuple[float, float, float | None, float] | None:
    """Detect ruled-paper lines in a rasterized background page.

    Returns (spacing_px, offset_px, margin_x_px, last_rule_px) — median rule
    gap, y of the first rule, the vertical margin line's x (or None) and y of
    the last rule — or None if the
    paper doesn't look reliably ruled. On failure it logs a warning telling the
    user to pass --rule-spacing/--rule-offset manually; it never guesses.

    A rule is a long, roughly-horizontal run darker than the background. Rows
    are rule candidates when more than `cover_frac` of their width is darker
    than (background - dark_delta) — robust to faint, low-contrast rules.
    """
    arr = np.asarray(image.convert("RGB")).astype(np.int16)
    gray = arr.mean(axis=2)
    bg = float(np.median(gray))
    dark = gray < (bg - dark_delta)

    # Group consecutive candidate rows (a rule may be 1-3px thick) into centers.
    cand = np.where(dark.mean(axis=1) > cover_frac)[0]
    if len(cand) == 0:
        logger.warning(
            "line-snap: no ruled lines detected on the paper; not snapping "
            "(pass --rule-spacing/--rule-offset to snap manually)"
        )
        return None
    row_dark = bg - gray.mean(axis=1)
    groups: list[list[int]] = [[int(cand[0])]]
    for r in cand[1:]:
        if r - groups[-1][-1] <= 3:
            groups[-1].append(int(r))
        else:
            groups.append([int(r)])
    centers = np.array([
        float(np.average(g, weights=row_dark[g])) if row_dark[g].sum() > 0
        else float(np.mean(g))
        for g in groups
    ])

    if len(centers) < min_rules:
        logger.warning(
            "line-snap: only %d ruled line(s) detected (need >=%d); not snapping "
            "(pass --rule-spacing/--rule-offset to snap manually)",
            len(centers), min_rules,
        )
        return None
    diffs = np.diff(centers)
    spacing = float(np.median(diffs))
    rel_var = float(diffs.std() / spacing) if spacing > 0 else 9.9
    if rel_var > var_tol:
        logger.warning(
            "line-snap: ruled-line spacing is irregular (rel. variance %.2f > %.2f); "
            "not snapping (pass --rule-spacing/--rule-offset to snap manually)",
            rel_var, var_tol,
        )
        return None

    col_cover = dark.mean(axis=0)
    margin_cols = np.where(col_cover > cover_frac)[0]
    margin_x = float(np.median(margin_cols)) if len(margin_cols) else None

    offset = float(centers[0])
    logger.info(
        "line-snap: detected %d rules, spacing %.1fpx, first at y=%.0fpx%s",
        len(centers), spacing, offset,
        f", margin x={margin_x:.0f}px" if margin_x is not None else "",
    )
    return spacing, offset, margin_x, float(centers[-1])


def _avg_edge_color(img: Image.Image) -> tuple[int, int, int]:
    arr = np.asarray(img.convert("RGB"))
    edges = np.concatenate(
        [arr[0, :, :], arr[-1, :, :], arr[:, 0, :], arr[:, -1, :]], axis=0
    )
    return tuple(int(v) for v in edges.mean(axis=0).round())


def _fit(img: Image.Image, size: tuple[int, int], mode: str) -> Image.Image:
    w, h = size
    if mode == "stretch":
        return img.resize((w, h), Image.Resampling.BICUBIC)
    iw, ih = img.size
    if mode == "cover":
        scale = max(w / iw, h / ih)
        nw, nh = max(w, round(iw * scale)), max(h, round(ih * scale))
        resized = img.resize((nw, nh), Image.Resampling.BICUBIC)
        left, top = (nw - w) // 2, (nh - h) // 2
        return resized.crop((left, top, left + w, top + h))
    if mode == "contain":
        scale = min(w / iw, h / ih)
        nw, nh = max(1, round(iw * scale)), max(1, round(ih * scale))
        resized = img.resize((nw, nh), Image.Resampling.BICUBIC)
        canvas = Image.new("RGB", (w, h), _avg_edge_color(img))
        canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2))
        return canvas
    raise ValueError(f"unknown fit mode: {mode!r} (expected one of {FIT_MODES})")


def compose_page(
    ink: Image.Image, paper: PaperStyle = PaperStyle(), seed: int = 0
) -> Image.Image:
    """Composite one ink-only RGBA page over the procedural paper; return RGB."""
    background = _paper(ink.size, paper, seed)
    return Image.alpha_composite(background, ink).convert("RGB")


def _compose_over(ink: Image.Image, background_rgb: Image.Image) -> Image.Image:
    return Image.alpha_composite(background_rgb.convert("RGBA"), ink).convert("RGB")


def _scanner_tone(page: Image.Image, amp: int, seed: int) -> Image.Image:
    """Add a low-frequency +/-amp luminance field — uneven scanner lighting.

    Deliberately texture-free (a 4x3 grid upsampled bilinearly): the paper
    background may itself be a real scan, so this stays a broad tone wash,
    never a second grain layer.
    """
    rng = np.random.default_rng(seed)
    grid = rng.uniform(-1.0, 1.0, size=(4, 3))
    field = Image.fromarray(((grid + 1.0) * 127.5).astype(np.uint8), mode="L").resize(
        page.size, Image.Resampling.BILINEAR
    )
    offset = (np.asarray(field, dtype=np.float32) / 127.5 - 1.0) * amp
    arr = np.asarray(page, dtype=np.int16) + offset[..., None].round().astype(np.int16)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="RGB")


def compose_pages(
    ink_pages: list[Image.Image], paper: PaperStyle = PaperStyle(), seed: int = 0,
    scanner_tone_amp: int = 0,
) -> list[Image.Image]:
    """Composite ink pages onto paper (procedural, or a user PDF background).

    Multi-page policy for a PDF background with B pages and N output pages:
    - B == 1        -> reuse that page for every output page
    - B >= N        -> output page i uses background page i
    - 1 < B < N     -> reuse the last background page for the overflow (logged)
    """
    if paper.background_pdf is None:
        # Procedural path unchanged; per-page seed keeps noise distinct.
        out = [compose_page(ink, paper, seed + i) for i, ink in enumerate(ink_pages)]
    else:
        if paper.fit not in FIT_MODES:
            raise ValueError(
                f"unknown fit mode: {paper.fit!r} (expected one of {FIT_MODES})"
            )
        bg_raster = rasterize_pdf(paper.background_pdf, ink_pages[0].size)
        n_bg = len(bg_raster)
        if 1 < n_bg < len(ink_pages):
            logger.warning(
                "background PDF has %d page(s) but the document has %d; "
                "reusing the last background page for the overflow",
                n_bg, len(ink_pages),
            )
        out = [
            _compose_over(ink, _fit(bg_raster[min(i, n_bg - 1)], ink.size, paper.fit))
            for i, ink in enumerate(ink_pages)
        ]

    if scanner_tone_amp > 0:
        out = [
            _scanner_tone(pg, scanner_tone_amp, seed + 7919 * (i + 1))
            for i, pg in enumerate(out)
        ]
    return out
