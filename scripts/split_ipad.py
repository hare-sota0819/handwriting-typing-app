"""Tool 2b: turn GoodNotes exports of the CYAN iPad pilot template into a
glyph store — and inspect export variants to pick the canonical recipe.

Differences from Tool 2 (split_scan.py), per the pilot brief:
  - Template furniture (guides/borders/labels/markers) is CYAN and removed by
    COLOR KEY (hue), never by brightness; there is NO deletion of any kind in
    the baseline band, so dark ink can never be collateral damage.
  - EXACT-coordinate cropping: a digital export preserves page geometry, so
    cells are cropped straight at layout rects (x a render scale). The cyan
    corner markers serve only as a ±2px placement SANITY CHECK — no affine
    registration/warp anywhere.
  - Digital exports are noise-free, so the blank-cell threshold is minimal.

Modes:
  extract (default):
      .venv/bin/python scripts/split_ipad.py <export.pdf|page.png ...>
          [--layout ...] [--out out/ipad_pilot/store] [--scale 4]
      PDF pages are rendered at --scale x the layout resolution (4 = 600 dpi);
      PNG pages may be at any integer multiple of the layout size.
  --inspect (export-variant matrix):
      .venv/bin/python scripts/split_ipad.py --inspect <exportA.pdf ...>
      For each export of the SAME written page: is the ink vector or raster
      (and at what effective dpi), does Editable keep per-stroke paths, is the
      cyan background included; emits a 600-dpi same-cell crop montage and a
      recommendation summary for the canonical full-collection recipe.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import split_scan  # noqa: E402  (shared ink thresholds + metric conventions)
import make_template_collection  # noqa: E402  (store-key -> folder rule)
from handwriting.synthglyphs import folder_name as _phase1_folder_name  # noqa: E402

DEFAULT_LAYOUT = REPO / "template" / "ipad_pilot" / "template_layout.json"
DEFAULT_OUT = REPO / "out" / "ipad_pilot" / "store"
DEFAULT_SCALE = 4                # 4 x 150 dpi layout = 600 dpi extraction

CYAN_KEY_DIFF = 18               # min(G,B)-R >= this -> template furniture
MARKER_TOL_LAYOUT_PX = 2.0       # brief: markers are a +-2px sanity check
BLANK_INK_PX_1X = 4              # noise-free digital export: near-zero blank bar


def _folder_name_with_symbols(char: str) -> str:
    # The collection template uses non-codepoint store keys for entries that
    # share a character with a differently-sized one ("big:(") or that are not
    # characters at all ("rule:long"); see make_template_collection.
    if ":" in char:
        return make_template_collection.folder_for_key(char)
    try:
        return _phase1_folder_name(char)
    except ValueError:
        return f"sym_u{ord(char):04x}"


# ------------------------------------------------------------- page loading

def _load_pages(inputs, layout, scale):
    """Yield (name, RGB ndarray at layout*scale) for every input page."""
    pw, ph = layout["page_px"]
    tw, th = pw * scale, ph * scale
    for src in map(Path, inputs):
        if src.suffix.lower() == ".pdf":
            import fitz
            doc = fitz.open(src)
            for i, page in enumerate(doc):
                aspect_pdf = page.rect.width / page.rect.height
                aspect_layout = pw / ph
                if abs(aspect_pdf / aspect_layout - 1) > 0.005:
                    raise SystemExit(
                        f"{src.name} p{i + 1}: page aspect {aspect_pdf:.4f} != "
                        f"template {aspect_layout:.4f} — the export did not "
                        f"preserve page geometry; exact cropping is unsafe")
                zoom = tw / page.rect.width
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                if img.size != (tw, th):
                    img = img.resize((tw, th), Image.LANCZOS)
                yield f"{src.name}:p{i + 1}", np.asarray(img)
        else:
            img = Image.open(src).convert("RGB")
            k = img.width / pw
            if abs(k - round(k)) > 0.01 or img.height != round(ph * round(k)):
                raise SystemExit(
                    f"{src.name}: {img.size} is not an integer multiple of the "
                    f"layout page {pw}x{ph}")
            if round(k) != scale:
                img = img.resize((tw, th), Image.LANCZOS)
            yield src.name, np.asarray(img)


# --------------------------------------------------- cyan furniture removal

def _cyan_mask(rgb: np.ndarray) -> np.ndarray:
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    return (np.minimum(g, b) - r) >= CYAN_KEY_DIFF


def _ink_gray(rgb: np.ndarray) -> np.ndarray:
    """Grayscale with all cyan furniture keyed to white."""
    gray = np.asarray(
        Image.fromarray(rgb, "RGB").convert("L"), dtype=np.float32)
    gray[_cyan_mask(rgb)] = 255.0
    return gray


# ------------------------------------------------------------ marker sanity

def _marker_sanity(rgb: np.ndarray, markers, scale, name):
    """Check the 4 cyan fiducials sit within +-2 layout px of their layout
    positions. Returns max deviation in layout px, or None if no markers are
    visible (background-off export)."""
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    strong = (r < 130) & (g - r > 50) & (b - r > 50)
    if not strong.any():
        return None
    # search window must EXCEED the marker itself (36 layout px) so the blob
    # centroid is the true marker center, not the window center — otherwise a
    # shifted export would read as dev≈0
    half = 30 * scale
    devs = []
    for mx, my in markers:
        cx, cy = mx * scale, my * scale
        y0, y1 = max(0, cy - half), cy + half
        x0, x1 = max(0, cx - half), cx + half
        win = strong[y0:y1, x0:x1]
        if not win.any():
            raise SystemExit(
                f"{name}: cyan marker near layout ({mx},{my}) not found — "
                f"export shifted/cropped; refusing exact-coordinate crop")
        ys, xs = np.nonzero(win)
        devs.append(np.hypot(xs.mean() + x0 - cx, ys.mean() + y0 - cy) / scale)
    dev = max(devs)
    if dev > MARKER_TOL_LAYOUT_PX:
        raise SystemExit(
            f"{name}: marker deviation {dev:.2f}px exceeds the "
            f"{MARKER_TOL_LAYOUT_PX}px sanity bound — export geometry is off; "
            f"refusing exact-coordinate crop (no warp fallback by design)")
    return dev


# ------------------------------------------------------------- cell extract

def _extract_cell(gray: np.ndarray, cell: dict, scale: int):
    """Color-keyed, exact-coordinate version of Tool 2's extract_cell.
    Same guide-frame / dark-ink metric conventions, all coords x scale."""
    x0, y0, x1, y1 = (v * scale for v in cell["rect"])
    g = {k: v * scale for k, v in cell["guides"].items()}
    inset = split_scan.BORDER_INSET * scale
    cx0, cy0, cx1, cy1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    crop = gray[cy0:cy1, cx0:cx1]

    cand = crop < split_scan.INK_THRESH
    dark = crop < split_scan.DARK_INK_CAP

    pad = split_scan.GUIDE_FRAME_PAD * scale
    ft = max(0, int(round(g["ascender"] - cy0 - pad)))
    fb = min(crop.shape[0], int(round(g["descender"] - cy0 + pad)))

    dys, dxs = np.where(dark)
    in_frame = (dys >= ft) & (dys < fb)
    if int(in_frame.sum()) < BLANK_INK_PX_1X * scale * scale:
        return None, None
    fxs = dxs[in_frame]
    ink_l, ink_r = int(fxs.min()), int(fxs.max()) + 1
    m = split_scan.CROP_MARGIN * scale
    gx0 = max(0, ink_l - m)
    gx1 = min(crop.shape[1], ink_r + m)

    sub_gray = crop[ft:fb, gx0:gx1]
    sub_cand = cand[ft:fb, gx0:gx1]
    darkness = np.clip(
        (split_scan.INK_THRESH - sub_gray)
        / (split_scan.INK_THRESH - split_scan.INK_SOLID_FLOOR), 0, 1)
    alpha = (darkness * 255).astype(np.uint8)
    alpha[~sub_cand] = 0
    rgba = np.zeros((*sub_gray.shape, 4), dtype=np.uint8)
    rgba[..., 3] = alpha
    image = Image.fromarray(rgba, "RGBA")

    sub_dark = dark[ft:fb, gx0:gx1]
    diy, dix = np.where(sub_dark)
    ink_w = ink_r - ink_l
    side = round(split_scan.SIDE_BEARING_FRAC * (y1 - y0))
    metrics = {
        "baseline_y": int(round(g["baseline"] - cy0 - ft)),
        "advance_width": float(2 * side + ink_w),
        "left_bearing": float(side - (ink_l - gx0)),
        "right_bearing": float(side - (gx1 - ink_r)),
        "ink_bbox": [int(dix.min()), int(diy.min()),
                     int(dix.max()) + 1, int(diy.max()) + 1],
    }
    return image, metrics


def extract(inputs, layout, out_dir: Path, scale: int):
    pages_meta = sorted((p["index"], p) for p in layout["pages"])
    n_pages = len(pages_meta)
    per_char: dict[str, list] = {}
    pages = list(_load_pages(inputs, layout, scale))
    if len(pages) % n_pages != 0:
        raise SystemExit(f"{len(pages)} page(s) is not a multiple of the "
                         f"layout's {n_pages}")
    for pos, (name, rgb) in enumerate(pages):
        _, pmeta = pages_meta[pos % n_pages]
        dev = _marker_sanity(rgb, pmeta["markers"], scale, name)
        if dev is None:
            print(f"{name}: NO cyan markers (background-off export) — exact "
                  f"crop proceeds UNVERIFIED")
        else:
            print(f"{name}: marker sanity OK (max dev {dev:.2f}px <= "
                  f"{MARKER_TOL_LAYOUT_PX}px), no warp")
        gray = _ink_gray(rgb)
        blanks = 0
        for cell in pmeta["cells"]:
            image, metrics = _extract_cell(gray, cell, scale)
            if image is None:
                blanks += 1
                continue
            # math-template cells carry an explicit store key ("big:(",
            # "rule:long"); ordinary cells key on the character itself
            per_char.setdefault(cell.get("key", cell["char"]), []).append(
                (image, metrics))
        if blanks:
            print(f"{name}: {blanks} blank cell(s) skipped")

    out_dir.mkdir(parents=True, exist_ok=True)
    characters = {}
    frame_frac = (layout["guide_fractions"]["baseline"]
                  - layout["guide_fractions"]["ascender"])
    native = round(frame_frac * layout["cell_h"]) * scale
    for char, items in sorted(per_char.items()):
        folder = _folder_name_with_symbols(char)
        (out_dir / folder).mkdir(parents=True, exist_ok=True)
        entries = []
        for i, (image, metrics) in enumerate(items):
            rel = f"{folder}/v{i}.png"
            image.save(out_dir / rel)
            entries.append({"file": rel, **metrics})
        adv = float(np.mean([e["advance_width"] for e in entries]))
        characters[char] = {"folder": folder, "advance_width": adv,
                            "variants": entries}
    characters.setdefault(" ", {
        "folder": None,
        "advance_width": 0.30 * layout["cell_h"] * scale,
        "variants": []})
    manifest = {"version": 1, "native_size_px": native,
                "characters": characters}
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    n_var = sum(len(c["variants"]) for c in characters.values())
    print(f"ipad store: {len(per_char)} inked characters, {n_var} variants "
          f"-> {out_dir} (native_size_px={native})")


# ------------------------------------------------------------ inspect mode

def inspect(inputs, layout, out_dir: Path, scale: int):
    """Export-variant matrix: vector-vs-raster ink, per-stroke paths,
    background presence, 600-dpi same-cell crops."""
    import fitz
    out_dir.mkdir(parents=True, exist_ok=True)
    pw, _ = layout["page_px"]
    first_cell = layout["pages"][0]["cells"][0]["rect"]
    crops, report = [], []
    for src in map(Path, inputs):
        doc = fitz.open(src)
        page = doc[0]
        drawings = page.get_drawings()
        # dark near-neutral stroke/fill = pen ink; everything else (cyan) is
        # the vector template background
        dark_paths = sum(
            1 for d in drawings
            for col in [d.get("color") or d.get("fill") or (0, 0, 0)]
            if max(col) < 0.55 and abs(col[1] - col[0]) < 0.2)
        cyan_paths = len(drawings) - dark_paths
        images = page.get_images(full=True)
        inches = page.rect.width / 72.0
        img_dpis = []
        for im in images:
            xref = im[0]
            w = doc.extract_image(xref)["width"]
            img_dpis.append(round(w / inches))
        zoom = (pw * scale) / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        rgb = np.asarray(Image.frombytes(
            "RGB", (pix.width, pix.height), pix.samples))
        has_bg = bool(_cyan_mask(rgb).mean() > 0.0005)
        gray = np.asarray(
            Image.fromarray(rgb, "RGB").convert("L"), dtype=np.float32)
        has_ink = bool((gray < split_scan.DARK_INK_CAP).sum()
                       > 10 * scale * scale)
        x0, y0, x1, y1 = (v * scale for v in first_cell)
        crops.append((src.name, Image.fromarray(rgb[y0:y1, x0:x1])))
        report.append({
            "file": src.name,
            "vector_ink_paths": dark_paths,
            "vector_template_paths": cyan_paths,
            "raster_images": len(images),
            "raster_effective_dpi": img_dpis,
            "background_cyan": has_bg,
            "ink_present": has_ink,
        })
        doc.close()

    strip_h = max(c.height for _, c in crops) + 30
    strip = Image.new("RGB", (sum(c.width + 16 for _, c in crops), strip_h),
                      (255, 255, 255))
    from PIL import ImageDraw
    d = ImageDraw.Draw(strip)
    x = 8
    for name, c in crops:
        d.text((x, 2), name[:22], fill=(60, 60, 70))
        strip.paste(c, (x, 24))
        x += c.width + 16
    montage = out_dir / "matrix_cell_crops.png"
    strip.save(montage)

    print(f"\n=== export-variant matrix ({scale * 150} dpi checks) ===")
    for r in report:
        ink_kind = ("VECTOR" if r["vector_ink_paths"] > 0
                    else f"raster {r['raster_effective_dpi']}dpi"
                    if r["raster_images"] else "NO INK FOUND")
        print(f"  {r['file']}: ink={ink_kind} "
              f"(ink paths {r['vector_ink_paths']}, "
              f"template paths {r['vector_template_paths']}, "
              f"raster imgs {r['raster_images']} @ {r['raster_effective_dpi']}), "
              f"background={'ON' if r['background_cyan'] else 'off'}")
    print(f"  same-cell crops -> {montage}")
    (out_dir / "matrix_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print("\nRecommendation inputs: prefer a variant with VECTOR ink; "
          "background ON keeps the cyan markers for the ±2px sanity check "
          "(background off skips it); if Editable shows many ink paths "
          "(per-stroke) while Flattened merges them, extraction is unaffected "
          "— pick Flattened for robustness unless fidelity differs.")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--layout", type=Path, default=DEFAULT_LAYOUT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--scale", type=int, default=DEFAULT_SCALE,
                    help="render scale over the 150dpi layout (4 = 600 dpi)")
    ap.add_argument("--inspect", action="store_true",
                    help="run the export-variant matrix instead of extracting")
    args = ap.parse_args(argv)
    layout = json.loads(args.layout.read_text("utf-8"))
    if args.inspect:
        inspect(args.inputs, layout, args.out.parent / "matrix", args.scale)
    else:
        extract(args.inputs, layout, args.out, args.scale)


if __name__ == "__main__":
    main()
