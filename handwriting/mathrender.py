"""Equations for the document pipeline: LaTeX in, handwritten ink images out.

Wraps the equation chain that lives in spike/ (pandoc → MathJax SVG →
placement → glyph substitution) so a .docx with equations renders them on the
same page as its text. Each MathBlock the parser produced gets a MathInk: an
ink-only RGBA image drawn at the chain's fixed pixels-per-em, plus where its
baseline sits and the cap height it was drawn at, which is all layout needs
to seat and scale it against the body letters.

The chain is file-based and runs in its own working directory
(HW_MATH_OUT), so it never touches spike/out that the equation-sheet mode
of the GUI caches between re-rolls.
"""

import hashlib
import json
import logging
import os
import shutil
import re
import runpy
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .document_model import Document, MathBlock
from .glyphstore import GlyphStore

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

# pandoc writes inline math as \( .. \) and display math as \[ .. \]
_MATH_RE = re.compile(r"\\\((.+?)\\\)|\\\[(.+?)\\\]", re.S)

# The chain draws its ink in this colour on white; the conversion to alpha
# maps that luminance to fully opaque.
_INK_LUMA = 40.0


def quiet_run(cmd, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run that never flashes a console window.

    From the windowed exe every child process (pandoc, node) opened its own
    console for a moment on Windows — one per equation-chain step, on every
    conversion. CREATE_NO_WINDOW keeps them hidden; elsewhere it is a plain run.
    """
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.run(cmd, **kwargs)


def _default_pandoc() -> Path:
    """The pinned pandoc under spike/tools when present (dev checkout, exe
    bundle), else whatever `pandoc` is on PATH."""
    bundled = ROOT / "spike" / "tools" / "pandoc-3.5" / "bin" / "pandoc"
    if bundled.exists():
        return bundled
    found = shutil.which("pandoc")
    return Path(found) if found else bundled


@dataclass(frozen=True)
class MathTools:
    """Where the chain's pieces are; defaults are the repo checkout layout.

    The GUI passes bundle-resolved paths (gui/resources.py) so the frozen exe
    finds them too.
    """

    spike_dir: Path = ROOT / "spike"
    pandoc: Path = field(default_factory=lambda: _default_pandoc())
    node: Path | None = None  # None = "node" from PATH
    work_dir: Path | None = None  # None = spike_dir / "out_doc"


@dataclass
class MathInk:
    """One rendered equation: ink-only alpha image at the chain's scale."""

    image: Image.Image  # RGBA, transparent ground, ink alpha
    baseline_y: float  # baseline row inside `image`
    cap_px: float  # cap height the image was drawn at (px)
    store_cap_ink: float  # the store's cap ink height in native px
    ends_subscript: bool = False  # its rightmost ink is a subscript
    _bounds: "tuple[float, float] | None" = field(
        default=None, repr=False, compare=False)

    @property
    def ink_bounds(self) -> tuple[float, float]:
        """(left, right) x of the drawn ink inside `image`.

        The chain crops each equation with a few px of clear ground around it
        (render_placement.CROP_PAD), so an equation kerned against a letter
        has to be measured by its ink, not by the image edge.
        """
        if self._bounds is None:
            bbox = self.image.getchannel("A").getbbox()
            self._bounds = ((0.0, float(self.image.width)) if bbox is None
                            else (float(bbox[0]), float(bbox[2])))
        return self._bounds

    @property
    def ascent(self) -> float:
        return self.baseline_y

    @property
    def descent(self) -> float:
        return self.image.height - self.baseline_y


# Word's x′ reaches pandoc as `x\prime`: a full-size PRIME symbol on the
# baseline, which MathJax typesets as a big slash after the letter ("x/").
# TeX's own notation `x'` is the raised superscript prime a hand writes.
_PRIME_RE = re.compile(r"\\prime\b")


def fix_latex(latex: str) -> str:
    """Normalise pandoc's LaTeX for MathJax (see _PRIME_RE)."""
    return _PRIME_RE.sub("'", latex)


def extract_latex(docx_path: Path, pandoc: Path) -> list[dict]:
    """Every equation in document order, as MathJax-ready LaTeX."""
    tex = quiet_run(
        [str(pandoc), str(docx_path), "-t", "latex"],
        capture_output=True, text=True, encoding="utf-8", check=True).stdout
    out = []
    for i, m in enumerate(_MATH_RE.finditer(tex)):
        inline, display = m.groups()
        latex = fix_latex(" ".join((inline or display).split()))
        out.append({"id": f"eq{i:03d}", "latex": latex,
                    "display": display is not None})
    return out


def _run_py(script: Path, argv: list[str]) -> None:
    # In-process (runpy) rather than a python subprocess: inside a frozen
    # exe sys.executable is the app itself, not an interpreter.
    old_argv = sys.argv
    sys.argv = [str(script)] + argv
    try:
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = old_argv


def _run_node(node: Path | None, script: Path, cwd: Path) -> None:
    proc = quiet_run([str(node or "node"), str(script)], cwd=cwd,
                     capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"MathJax step failed:\n{proc.stderr[-800:]}")


def _to_ink_alpha(img: Image.Image) -> Image.Image:
    """Chain output (dark ink on white) → transparent RGBA with ink alpha."""
    luma = np.asarray(img.convert("L"), dtype=np.float32)
    alpha = np.clip((255.0 - luma) / (255.0 - _INK_LUMA), 0.0, 1.0) * 255.0
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.putalpha(Image.fromarray(alpha.astype("uint8")))
    return out


_CHAIN_FILES = ("tex2svg.js", "parse_svg.py", "render_placement.py")


def _chain_fingerprint(tools: MathTools, store_root: Path) -> str:
    """Hash of the chain code + the store manifest: any change to either
    invalidates cached renders (a cache never serves stale drawings)."""
    h = hashlib.sha1()
    for name in _CHAIN_FILES:
        f = tools.spike_dir / name
        if f.exists():
            h.update(f.read_bytes())
    manifest = Path(store_root) / "manifest.json"
    if manifest.exists():
        st = manifest.stat()
        h.update(f"{manifest.resolve()}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()


def _cache_key(eq: dict, seed: int, raw_pen: bool, fingerprint: str) -> str:
    h = hashlib.sha1()
    h.update(f"{fingerprint}|{seed}|{raw_pen}|{eq.get('display', False)}|"
             f"{eq['latex']}".encode("utf-8"))
    return h.hexdigest()


def _load_ink(png: Path, meta_path: Path, eq_id: str,
              ink_alpha: bool = False) -> MathInk | None:
    """ink_alpha: the PNG is already ink-only RGBA (a cache file), no
    white-to-alpha conversion needed."""
    if not png.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    with Image.open(png) as im:
        if ink_alpha:  # cache file: the alpha channel alone, mode L
            image = Image.new("RGBA", im.size, (0, 0, 0, 0))
            image.putalpha(im.convert("L"))
        else:
            image = _to_ink_alpha(im)
    if meta.get("missing"):
        logger.warning("equation %s: no handwriting for %s (placeholder drawn)",
                       eq_id, " ".join(meta["missing"]))
    return MathInk(
        image=image, baseline_y=float(meta["baseline_y"]),
        cap_px=float(meta["cap_px"]),
        store_cap_ink=float(meta["store_cap_ink"]),
        ends_subscript=bool(meta.get("ends_subscript")))


def run_chain(equations: list[dict], store_root: Path, seed: int,
              tools: MathTools = MathTools(),
              raw_pen: bool = False) -> dict[str, MathInk]:
    """Render `equations` ([{id, latex, display}]) through the chain.

    Returns MathInk by equation id. Equations the chain could not draw at all
    are absent from the result (the caller decides what to do about them).

    Renders are cached per equation (work/cache/<key>.png+json, keyed by
    LaTeX, display flag, seed, raw_pen and a fingerprint of the chain code +
    store): re-converting a document — the GUI user's edit/tweak loop — only
    runs pandoc, not MathJax/placement, for equations already drawn. Each
    equation draws from its own RNG (seed + LaTeX), so a cached render is
    identical to a fresh one.
    """
    if not equations:
        return {}
    work = tools.work_dir or (tools.spike_dir / "out_doc")
    work.mkdir(parents=True, exist_ok=True)
    cache = work / "cache"
    cache.mkdir(exist_ok=True)
    fp = _chain_fingerprint(tools, Path(store_root))
    keys = {eq["id"]: _cache_key(eq, seed, raw_pen, fp) for eq in equations}

    inks: dict[str, MathInk] = {}
    todo = []
    for eq in equations:
        k = keys[eq["id"]]
        ink = _load_ink(cache / f"{k}.png", cache / f"{k}.json", eq["id"],
                        ink_alpha=True)
        if ink is None:
            todo.append(eq)
        else:
            inks[eq["id"]] = ink
    if inks:
        logger.info("equations: %d cached, %d to render", len(inks), len(todo))
    if not todo:
        return inks

    (work / "equations.json").write_text(
        json.dumps(todo, ensure_ascii=False, indent=1), encoding="utf-8")
    old_env = os.environ.get("HW_MATH_OUT")
    os.environ["HW_MATH_OUT"] = str(work)
    try:
        _run_node(tools.node, tools.spike_dir / "tex2svg.js", tools.spike_dir)
        _run_py(tools.spike_dir / "parse_svg.py", [])
        argv = [f"--store={store_root}", f"--seed={seed}"]
        if raw_pen:
            argv.append("--raw-pen")
        _run_py(tools.spike_dir / "render_placement.py", argv)
    finally:
        if old_env is None:
            os.environ.pop("HW_MATH_OUT", None)
        else:
            os.environ["HW_MATH_OUT"] = old_env

    for eq in todo:
        png = work / "hand" / f"hand_{eq['id']}.png"
        meta_path = work / "hand" / f"hand_{eq['id']}.json"
        ink = _load_ink(png, meta_path, eq["id"])
        if ink is None:
            logger.warning("equation %s was not rendered", eq["id"])
            continue
        inks[eq["id"]] = ink
        k = keys[eq["id"]]
        try:
            # cached as ink-only RGBA so a cache hit skips the conversion
            ink.image.getchannel("A").save(cache / f"{k}.png", compress_level=1)
            shutil.copyfile(meta_path, cache / f"{k}.json")
        except OSError as e:  # a read-only install: just do not cache
            logger.debug("equation cache write failed: %s", e)
    return inks


def render_document_math(document: Document, docx_path: Path,
                         store_root: Path, seed: int,
                         tools: MathTools = MathTools(),
                         raw_pen: bool = False) -> None:
    """Fill every MathBlock in `document` with its LaTeX and rendered ink.

    LaTeX comes from ONE pandoc pass over the whole .docx, paired with the
    parser's blocks by document order (both walk the body in order). A count
    mismatch would silently pair the wrong equation with the wrong slot, so
    the pairing is refused and the blocks are left unrendered (warned).
    """
    blocks = [r for p in document.paragraphs for r in p.runs
              if isinstance(r, MathBlock)]
    if not blocks:
        return
    equations = extract_latex(docx_path, tools.pandoc)
    n_doc = max(b.index for b in blocks) + 1
    if len(equations) != n_doc:
        logger.warning(
            "equation count mismatch: parser saw %d, pandoc gave %d; "
            "equations left unrendered", n_doc, len(equations))
        return
    for b in blocks:
        b.latex = equations[b.index]["latex"]
        # The chain typesets by the block's own kind (Word's inline vs display),
        # not pandoc's guess: an inline equation must not get display-size
        # operators and stretched fractions on a text line.
        equations[b.index]["display"] = b.display
    inks = run_chain(equations, store_root, seed, tools, raw_pen=raw_pen)
    for b in blocks:
        b.ink = inks.get(equations[b.index]["id"])


def measure_cap_ink(store: GlyphStore) -> float:
    """Median cap-letter ink height above baseline, native px (chain's rule)."""
    hs = []
    for ch in "THELFB":
        if ch not in store:
            continue
        for v in store.entry(ch).variants:
            hs.append(v.baseline_y - v.ink_bbox[1])
    hs.sort()
    return float(hs[len(hs) // 2]) if hs else float(store.native_size_px) * 0.68
