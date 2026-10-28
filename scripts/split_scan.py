"""Tool 2 — scan splitter: scanned filled template -> real glyph store.

Consumes scanned filled page image(s) + template/template_layout.json and writes
a glyph store at glyphs/real/ using the EXISTING manifest.json schema (identical
to the synthetic store; Phase 1 renders from it with zero code changes).

Pipeline (see module functions):
  1. register()  -- detect the 4 black corner markers, fit an AFFINE transform
     (translation/rotation/scale/shear) mapping the scan into template-layout
     coordinates. This straightens the SHEET only. It NEVER touches per-glyph
     slant. Near-identity fits skip the warp to avoid resampling artefacts.
  2. crop cells by the registered layout rects; blank cells are detected and
     skipped (partial fills supported; a real glyph is never overwritten by a
     blank).
  3. remove printed furniture with a HYBRID method: density threshold drops the
     LIGHT-gray guides; the cell border is removed by position; the DARKER
     printed baseline is removed morphologically (thin horizontal component in a
     band at the known baseline y) while overlapping letter strokes survive.
  4. extract the ink mask and tight-crop it. The right-leaning handwriting slant
     is PRESERVED EXACTLY -- no deskew/normalise/rotate/shear of any glyph.
  5. vertical metrics come from the 4 guide-line y's (ascender/x-height/baseline/
     descender), so relative rise/drop is exact rather than estimated from ink.
  6. write glyphs/real/ per the existing schema (<=5 variants per character).

Run: .venv/bin/python scripts/split_scan.py SCAN_PAGE... [--layout PATH] [--out DIR]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handwriting.glyphstore import MANIFEST_NAME, MANIFEST_VERSION
from handwriting.synthglyphs import folder_name

# --- tuning constants (template px unless noted) --------------------------------
MARKER_DARK = 150         # a pixel darker than this (0-255) may be marker ink. Set
                          # high enough that a marker still reads as a full solid
                          # square under a scan shadow/lighting gradient (real pages
                          # 4-7 darken the lower markers); thin strokes/residue that
                          # slip in are erased by the square erosion below. Detection
                          # only -- unrelated to INK_THRESH used for glyph extraction.
MARKER_ERODE_HALF = 9     # square-erosion half-width: keeps only SOLID blocks
                          # (the markers) and erases thin glyph strokes/labels
MARKER_BORDER_MARGIN = 15  # blobs whose bbox is within this of the image edge are
                           # scanner-edge artefacts, not markers -> dropped
MARKER_MIN_AREA = 60       # eroded-core area below this is a speck, not a marker
AFFINE_SKIP_RESIDUAL = 0.8   # px: below this max residual + near-identity => skip warp
INK_THRESH = 190          # gray < this survives the density step (keeps ink AND the
                          # printed lines that are darker than mid-grey)
BORDER_INSET = 4          # px cropped inside the cell rect to drop the printed border
# Printed furniture is removed conservatively: the light guide lines by the
# density threshold above (they are much lighter than pen ink) and the cell border
# by position (BORDER_INSET). Faint dotted baseline residue darker than INK_THRESH
# is left in the extracted glyph on purpose -- removing it in the baseline band
# risks cutting glyph strokes that terminate there. It is dropped later at final
# render by an alpha threshold. See docs/STATUS.md (final-render residue threshold).
MIN_INK_PIXELS = 40       # a cell with fewer DARK ink px in the frame is blank -> skip
DARK_INK_CAP = 100        # gray < this is real pen ink (not faint printed residue);
                          # used for the blank test, horizontal glyph extent, and
                          # ink_bbox so residue can't stretch the crop to full width
INK_SOLID_FLOOR = 80      # gray <= this renders at FULL alpha (bold/dark ink);
                          # alpha fades to 0 at INK_THRESH for soft anti-aliased edges
CROP_MARGIN = 2           # transparent horizontal margin around the tight ink crop
GUIDE_FRAME_PAD = 8       # px above ascender / below descender for the vertical
                          # crop frame; the frame is guide-derived (constant per
                          # row) so baseline_y comes from layout, never from ink
SIDE_BEARING_FRAC = 0.03  # nominal L/R side bearing as a fraction of cell height;
                          # small so letters sit close together like real writing


# --- Step 1: registration -------------------------------------------------------
def _erode_square(mask: np.ndarray, half: int) -> np.ndarray:
    """Binary erosion with a (2*half+1) square SE (separable H then V).

    Each shift reads from the FIXED prior-stage array, not the array being
    accumulated, so the SE width is 2*half+1 (not a cumulative over-erosion)."""
    h = mask.copy()
    for k in range(1, half + 1):  # horizontal, all shifts from `mask`
        left = np.zeros_like(mask); left[:, :-k] = mask[:, k:]
        right = np.zeros_like(mask); right[:, k:] = mask[:, :-k]
        h &= left & right
    v = h.copy()
    for k in range(1, half + 1):  # vertical, all shifts from `h`
        up = np.zeros_like(h); up[:-k, :] = h[k:, :]
        down = np.zeros_like(h); down[k:, :] = h[:-k, :]
        v &= up & down
    return v


def _label_blobs(ys, xs):
    """8-connected components over a sparse set of pixel coords. Returns dicts with
    centroid (cx,cy), bbox (x0,y0,x1,y1) and area. Cheap: only core pixels."""
    pts = set(zip(ys.tolist(), xs.tolist()))
    seen = set()
    blobs = []
    for p0 in pts:
        if p0 in seen:
            continue
        stack = [p0]
        comp = []
        while stack:
            q = stack.pop()
            if q in seen:
                continue
            seen.add(q)
            comp.append(q)
            qy, qx = q
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    n = (qy + dy, qx + dx)
                    if n in pts and n not in seen:
                        stack.append(n)
        yy = [c[0] for c in comp]; xx = [c[1] for c in comp]
        blobs.append({"cx": sum(xx) / len(xx), "cy": sum(yy) / len(yy),
                      "x0": min(xx), "y0": min(yy), "x1": max(xx) + 1, "y1": max(yy) + 1,
                      "area": len(comp)})
    return blobs


def _merge_close(blobs, dist):
    """Merge blobs whose centroids are within `dist` (fragments of one marker
    split by erosion/scan noise). Area-weighted centroid, unioned bbox."""
    groups = []
    for b in sorted(blobs, key=lambda z: -z["area"]):
        for g in groups:
            if abs(b["cx"] - g["cx"]) < dist and abs(b["cy"] - g["cy"]) < dist:
                tot = g["area"] + b["area"]
                g["cx"] = (g["cx"] * g["area"] + b["cx"] * b["area"]) / tot
                g["cy"] = (g["cy"] * g["area"] + b["cy"] * b["area"]) / tot
                g["x0"] = min(g["x0"], b["x0"]); g["y0"] = min(g["y0"], b["y0"])
                g["x1"] = max(g["x1"], b["x1"]); g["y1"] = max(g["y1"], b["y1"])
                g["area"] = tot
                break
        else:
            groups.append(dict(b))
    return groups


def detect_markers(gray: np.ndarray) -> list:
    """Detect the 4 corner markers; returns centroids [TL, TR, BR, BL] (scan px).

    The markers are the only SOLID SQUARE black blocks on the printed sheet.
    Eroding the near-black mask by a square SE keeps their cores and erases thin
    glyph strokes/labels. Erosion can fragment a marker into pieces and the scan
    can carry black scanner-edge bands, so: connected cores are grouped into
    blobs, nearby fragments are merged, blobs touching the image border (scanner
    edges) or non-square (edge bands) or too small (specks) are dropped, and the
    4 corner-extreme survivors (min/max of x+y and x-y) are the markers. Robust to
    the sheet being offset within a larger scan and to a few degrees of rotation.
    """
    H, W = gray.shape
    dark = gray < MARKER_DARK
    cores = _erode_square(dark, MARKER_ERODE_HALF)
    ys, xs = np.where(cores)
    if len(xs) == 0:
        raise ValueError("registration failed: no solid corner markers found")
    blobs = _merge_close(_label_blobs(ys, xs), dist=0.03 * (W + H) / 2)
    bm = MARKER_BORDER_MARGIN
    cand = []
    for b in blobs:
        w, h = b["x1"] - b["x0"], b["y1"] - b["y0"]
        touches = b["x0"] < bm or b["y0"] < bm or b["x1"] > W - bm or b["y1"] > H - bm
        if (not touches and 0.4 <= w / h <= 2.5
                and b["area"] >= MARKER_MIN_AREA
                and w < 0.15 * W and h < 0.15 * H):
            cand.append(b)
    if len(cand) < 4:
        raise ValueError(f"registration failed: found {len(cand)} square marker "
                         f"candidates, need 4")
    tl = min(cand, key=lambda b: b["cx"] + b["cy"])
    tr = min(cand, key=lambda b: -b["cx"] + b["cy"])
    br = min(cand, key=lambda b: -b["cx"] - b["cy"])
    bl = min(cand, key=lambda b: b["cx"] - b["cy"])
    chosen = [tl, tr, br, bl]
    if len({(b["cx"], b["cy"]) for b in chosen}) != 4:
        raise ValueError("registration failed: could not resolve 4 distinct corners")
    return [(b["cx"], b["cy"]) for b in chosen]


def _fit_affine(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares 2x3 affine A with dst ~ A @ [x,y,1]. src/dst: (N,2)."""
    n = src.shape[0]
    M = np.hstack([src, np.ones((n, 1))])          # (N,3)
    sol, *_ = np.linalg.lstsq(M, dst, rcond=None)  # (3,2)
    return sol.T                                    # (2,3)


def register(img: Image.Image, layout_markers: list):
    """Register a scanned page into template coordinates using the 4 markers.

    Returns (registered_rgb_image, info). The image is in template page space
    (page_px). A near-identity fit skips the warp. `info` carries the detected
    markers and the residual so the caller can report it.
    """
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    scan_pts = np.array(detect_markers(gray), dtype=np.float64)   # scan px  (src)
    tmpl_pts = np.array(layout_markers, dtype=np.float64)         # template px (dst)

    # Fit template->scan so we can inverse-sample the scan for each template pixel.
    A_t2s = _fit_affine(tmpl_pts, scan_pts)                       # 2x3
    # residual measured where markers should land back in scan space
    proj = (A_t2s @ np.hstack([tmpl_pts, np.ones((4, 1))]).T).T
    resid = np.linalg.norm(proj - scan_pts, axis=1)
    linear = A_t2s[:, :2]
    near_identity = (
        resid.max() < AFFINE_SKIP_RESIDUAL
        and abs(linear[0, 0] - 1) < 2e-3 and abs(linear[1, 1] - 1) < 2e-3
        and abs(linear[0, 1]) < 2e-3 and abs(linear[1, 0]) < 2e-3
    )
    info = {
        "markers_scan": scan_pts.tolist(),
        "markers_template": tmpl_pts.tolist(),
        "residual_px": {"max": float(resid.max()), "mean": float(resid.mean())},
        "warp_applied": not near_identity,
    }
    if near_identity:
        return img.convert("RGB"), info

    # warp needed: hand back the template->scan affine for PIL to inverse-sample
    # (a,b,c,d,e,f); the caller warps to the full layout page size.
    a, b, c = A_t2s[0]
    d, e, f = A_t2s[1]
    return None, {**info, "affine_t2s": (float(a), float(b), float(c),
                                         float(d), float(e), float(f))}


# --- Step 3: furniture removal (density only; strokes are never touched) --------
def remove_furniture(cell_gray: np.ndarray):
    """Return (ink_mask bool, debug dict). SAFE furniture removal only.

    cell_gray is the cell crop (the printed border is already excluded by the
    position inset in extract_cell). The only removal here is a DENSITY/brightness
    threshold: pixels lighter than INK_THRESH are dropped, which clears the light
    printed guide lines (much lighter than pen ink) while keeping every ink pixel.

    There is NO position-based deletion inside the baseline band. Faint dotted
    baseline residue darker than INK_THRESH is intentionally KEPT here so a glyph
    stroke terminating/resting on the baseline is never touched -- an earlier
    in-band removal misjudged tapering i-stems as residue and cut them. That faint
    residue is dropped later at final render by an alpha/brightness threshold (ink
    is dark ~0-60, residue faint ~150-200); see docs/STATUS.md.
    """
    ink = cell_gray < INK_THRESH
    dbg = {"candidate_px": int(ink.sum()), "ink_px": int(ink.sum())}
    return ink, dbg


# --- Steps 2/4/5: per-cell extraction ------------------------------------------
def extract_cell(reg_gray: np.ndarray, cell: dict):
    """Extract one cell -> (rgba_image, metrics) or (None, reason) if blank.

    reg_gray: full registered page as grayscale float array (template coords).
    """
    x0, y0, x1, y1 = cell["rect"]
    g = cell["guides"]
    # Step 2/3a: crop INSIDE the border to drop the printed cell frame by position
    cx0, cy0 = x0 + BORDER_INSET, y0 + BORDER_INSET
    cx1, cy1 = x1 - BORDER_INSET, y1 - BORDER_INSET
    crop = reg_gray[cy0:cy1, cx0:cx1]
    baseline_row = g["baseline"] - cy0

    ink_mask, dbg = remove_furniture(crop)     # candidate (<INK_THRESH): image alpha
    dark = crop < DARK_INK_CAP                  # real pen ink: extent / metrics / blank

    # Vertical crop frame from the GUIDE LINES (ascender..descender + pad),
    # constant for every cell in the row -> baseline_y is read from layout, never
    # estimated from ink. NO rotation/shear anywhere.
    asc_row = g["ascender"] - cy0
    desc_row = g["descender"] - cy0
    ft = max(0, int(round(asc_row - GUIDE_FRAME_PAD)))
    fb = min(crop.shape[0], int(round(desc_row + GUIDE_FRAME_PAD)))

    # Emptiness + horizontal extent come from DARK pen ink only, so faint printed
    # residue (which spans the whole cell width) can neither be mistaken for a
    # filled cell nor stretch the glyph crop to full width.
    dys, dxs = np.where(dark)
    in_frame = (dys >= ft) & (dys < fb)
    if int(in_frame.sum()) < MIN_INK_PIXELS:
        return None, {"blank": True, **dbg}
    fxs = dxs[in_frame]
    ink_l, ink_r = int(fxs.min()), int(fxs.max()) + 1
    m = CROP_MARGIN
    gx0 = max(0, ink_l - m)
    gx1 = min(crop.shape[1], ink_r + m)

    # Image alpha uses the full candidate mask within this crop, so faint residue
    # inside the glyph's own column span stays (low alpha) for the final-render
    # threshold; residue beside the glyph is already cropped away by the dark bounds.
    sub_mask = ink_mask[ft:fb, gx0:gx1]
    sub_gray = crop[ft:fb, gx0:gx1]
    h, w = sub_mask.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    # Map real pen ink to FULL opacity so strokes render bold/dark, not washed out:
    # gray <= INK_SOLID_FLOOR -> alpha 255, fading to 0 at INK_THRESH (soft edges).
    darkness = np.clip((INK_THRESH - sub_gray) / (INK_THRESH - INK_SOLID_FLOOR), 0, 1)
    alpha = (darkness * 255).astype(np.uint8)
    alpha[~sub_mask] = 0
    rgba[..., 3] = alpha
    image = Image.fromarray(rgba, "RGBA")

    # Step 5: baseline_y from the guide line (constant across variants). ink_bbox,
    # width and bearings come from the DARK ink extent (the real glyph).
    baseline_y = baseline_row - ft
    sub_dark = dark[ft:fb, gx0:gx1]
    diy, dix = np.where(sub_dark)
    ink_w = ink_r - ink_l
    side = round(SIDE_BEARING_FRAC * (y1 - y0))
    metrics = {
        "baseline_y": int(baseline_y),
        "advance_width": float(2 * side + ink_w),
        "left_bearing": float(side - (ink_l - gx0)),
        "right_bearing": float(side - (gx1 - ink_r)),
        "ink_bbox": [int(dix.min()), int(diy.min()), int(dix.max()) + 1, int(diy.max()) + 1],
    }
    return image, {"blank": False, **dbg}, metrics


# --- driver ---------------------------------------------------------------------
def _registered_page(img: Image.Image, page_px, layout_markers):
    """Register and return (grayscale array in template coords, rgb image, info)."""
    reg_img, info = register(img, layout_markers)
    if reg_img is None:  # warp needed
        a, b, c, d, e, f = info["affine_t2s"]
        reg_img = img.convert("RGB").transform(
            tuple(page_px), Image.AFFINE, (a, b, c, d, e, f),
            resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    gray = np.asarray(reg_img.convert("L"), dtype=np.float32)
    return gray, reg_img, info


def split(scan_paths, layout, out_dir: Path, debug_dir: Path | None = None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    page_px = layout["page_px"]
    pages_meta = {p["index"]: p for p in layout["pages"]}

    # Accept one OR MORE template sets: len(scan_paths) must be a multiple of the
    # layout's page count. Each set maps page-for-page to the layout and appends
    # its cells' glyphs, so N sets give up to N*n_cells variants per character
    # (more written samples -> more natural variety).
    ordered = sorted(pages_meta.items())
    n_pages = len(ordered)
    if len(scan_paths) % n_pages != 0:
        raise SystemExit(
            f"got {len(scan_paths)} page(s), not a multiple of the layout's "
            f"{n_pages} pages; pass whole template sets in page order"
        )

    per_char: dict[str, list] = {}
    reports = []
    for pos, path in enumerate(scan_paths):
        idx, pmeta = ordered[pos % n_pages]
        img = Image.open(path)
        gray, reg_img, info = _registered_page(img, page_px, pmeta["markers"])
        reports.append({"page": idx, "set": pos // n_pages, "path": str(path), **info})
        if debug_dir is not None:
            Path(debug_dir).mkdir(parents=True, exist_ok=True)
            reg_img.save(Path(debug_dir) / f"registered_s{pos // n_pages}_p{idx}.png")
        for cell in pmeta["cells"]:
            result = extract_cell(gray, cell)
            if result[0] is None:
                continue
            image, _dbg, metrics = result
            per_char.setdefault(cell["char"], []).append((image, metrics))

    # write store
    characters = {}
    for char, variants in per_char.items():
        folder = folder_name(char)
        (out_dir / folder).mkdir(parents=True, exist_ok=True)
        entries = []
        for i, (image, metrics) in enumerate(variants):
            rel = f"{folder}/v{i}.png"
            image.save(out_dir / rel)
            entries.append({"file": rel, **metrics})
        adv = float(np.mean([m["advance_width"] for _, m in variants]))
        characters[char] = {"folder": folder, "advance_width": adv, "variants": entries}

    # space carries advance only (nominal: half a cell width)
    characters.setdefault(" ", {"folder": None,
                                "advance_width": float(layout["cell_w"]) * 0.5,
                                "variants": []})

    # native_size_px must be the CAP HEIGHT of the stored glyphs (ascender line to
    # baseline), not the full ascender..descender frame -- the renderer scales by
    # style.base_size_px / native_size_px, treating native_size_px as the cap
    # height. Using the full frame (cell_h) rendered every letter ~1.8x too small.
    gf = layout["guide_fractions"]
    cap_height = round((gf["baseline"] - gf["ascender"]) * layout["cell_h"])
    manifest = {
        "version": MANIFEST_VERSION,
        "native_size_px": cap_height,
        "characters": characters,
    }
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    inked = [c for c in characters if characters[c]["variants"]]
    print(f"real store: {len(inked)} inked characters, "
          f"{sum(len(characters[c]['variants']) for c in inked)} variants -> {out_dir}")
    for r in reports:
        rp = r["residual_px"]
        print(f"  set {r['set']} page {r['page']}: residual max {rp['max']:.3f}px "
              f"mean {rp['mean']:.3f}px, warp_applied={r['warp_applied']}")
    return manifest, reports


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tool 2: split a scanned template into a glyph store.")
    ap.add_argument("scans", nargs="+", type=Path, help="scanned page image(s), in page order")
    ap.add_argument("--layout", type=Path,
                    default=Path(__file__).resolve().parents[1] / "template" / "template_layout.json")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parents[1] / "glyphs" / "real")
    ap.add_argument("--debug-dir", type=Path, default=None,
                    help="if set, write registered full pages here")
    args = ap.parse_args(argv)
    layout = json.loads(args.layout.read_text("utf-8"))
    split(args.scans, layout, args.out, debug_dir=args.debug_dir)


if __name__ == "__main__":
    main()
