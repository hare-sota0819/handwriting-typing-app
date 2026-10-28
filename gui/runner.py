"""Headless conversion core for the GUI: JobConfig in, PIL pages out.

No Qt in here — this module is what the checks exercise. The window code
(app.py) only builds a JobConfig, calls run_job on a worker thread, and shows
the returned pages.

Math modes reuse the spike chain. The python steps (parse_svg.py,
render_placement.py) run in-process via runpy with a patched argv instead of
subprocess-to-sys.executable, because inside a PyInstaller exe sys.executable
is the GUI itself, not a python interpreter. pandoc and node stay
subprocesses of bundled binaries (resources.py resolves them).
"""

import json
import runpy
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from . import resources

sys.path.insert(0, str(resources.SCRIPTS_DIR))
from render_docx_math import contact_sheet, extract_latex  # noqa: E402
from render_math_set import load_equations  # noqa: E402

from handwriting.cli import render_with_options, save_pages  # noqa: E402
from handwriting.compositor import PaperStyle  # noqa: E402
from handwriting.mathrender import MathTools, quiet_run  # noqa: E402

MODES = ("docx-text", "docx-math", "math-set")

# Chain state already prepared through parse_svg (pandoc/node/parse are
# deterministic per input file). Re-rolling the seed only re-runs the seeded
# placement render, which is what makes the 다시 뽑기 button fast.
_prepared: dict = {"key": None, "equations": None}


def detect_mode(path: Path) -> str:
    """Default mode for a dropped file. .docx also allows 'docx-math'."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return "docx-text"
    if suffix in (".txt", ".tex"):
        return "math-set"
    raise ValueError(f"unsupported file type: {path.name}")


@dataclass
class JobConfig:
    input: Path
    mode: str
    seed: int = 0
    store: Path | None = None  # None = resources.default_store()
    # docx-text options (mirror the CLI)
    style_path: Path | None = None
    paper_pdf: Path | None = None
    paper_fit: str = "cover"
    snap_lines: bool = False
    rule_spacing: float | None = None
    rule_offset: float | None = None
    rule_margin_x: float | None = None
    dpi: int = 400
    effects: bool = True
    line_height: float | None = None  # baseline-to-baseline, × letter size
    display_math_gap: float = 0.35    # air above/below display equations, × letter size
    base_size: float | None = None    # letter size in px at the 150-dpi scale
    # handwriting-rhythm knobs (style fields at the 150-dpi scale; 0 = off).
    # Defaults mirror HandwritingStyle's; the GUI always passes them through.
    word_drift: float = 6.0
    line_rise: float = 4.5
    line_step_jitter: float = 0.035
    margin_drift: float = 10.0
    word_tilt: float = 0.0
    word_pages: bool = False  # start a new page wherever Word's last layout did
    # math-mode options
    raw_pen: bool = False


def _run_py(script: Path, argv: list[str]) -> None:
    old_argv = sys.argv
    sys.argv = [str(script)] + argv
    try:
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv = old_argv


def _run_node(script: Path) -> None:
    node = resources.find_node()
    proc = quiet_run([str(node), str(script)], cwd=resources.ROOT,
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"MathJax step failed:\n{proc.stderr[-800:]}")


def _run_math_chain(cfg: JobConfig,
                    progress: Callable[[str], None]) -> list[Image.Image]:
    spike = resources.SPIKE_DIR
    out = spike / "out"
    out.mkdir(parents=True, exist_ok=True)

    key = (cfg.mode, str(cfg.input), cfg.input.stat().st_mtime)
    if _prepared["key"] == key:
        equations = _prepared["equations"]
    else:
        progress("extract")
        if cfg.mode == "docx-math":
            equations = extract_latex(cfg.input, pandoc=resources.find_pandoc())
        else:
            equations = load_equations(cfg.input)
        if not equations:
            raise RuntimeError("no equations found in the input")
        (out / "equations.json").write_text(
            json.dumps(equations, ensure_ascii=False, indent=1),
            encoding="utf-8")
        progress("mathjax")
        _run_node(spike / "tex2svg.js")
        progress("parse")
        _run_py(spike / "parse_svg.py", [])
        _prepared.update(key=key, equations=equations)

    progress("render")
    store = cfg.store or resources.default_store()
    argv = [f"--store={store}", f"--seed={cfg.seed}"]
    if cfg.raw_pen:
        argv.append("--raw-pen")
    _run_py(spike / "render_placement.py", argv)

    images = []
    for eq in equations:
        p = spike / "out" / "hand" / f"hand_{eq['id']}.png"
        if p.exists():
            images.append((eq["id"].replace("eq", "#"), Image.open(p)))
    if not images:
        raise RuntimeError("no equations rendered")
    progress("sheet")
    return contact_sheet(images)


def _math_tools() -> MathTools:
    """The bundled equation chain for equations inside a document.

    A missing tool is not an error here: a text-only document never needs
    it, and the chain itself reports the failure when it does run.
    """
    defaults = MathTools()
    try:
        pandoc = resources.find_pandoc()
    except resources.ToolMissingError:
        pandoc = defaults.pandoc
    try:
        node = resources.find_node()
    except resources.ToolMissingError:
        node = None
    return MathTools(spike_dir=resources.SPIKE_DIR, pandoc=pandoc, node=node)


def run_job(cfg: JobConfig,
            progress: Callable[[str], None] = lambda stage: None
            ) -> list[Image.Image]:
    """Convert cfg.input according to cfg; returns finished RGB pages."""
    if cfg.mode not in MODES:
        raise ValueError(f"unknown mode: {cfg.mode}")
    if not cfg.input.exists():
        raise FileNotFoundError(f"input not found: {cfg.input}")

    if cfg.mode == "docx-text":
        progress("render")
        overrides = {}
        if cfg.line_height is not None:
            overrides["line_height"] = cfg.line_height
        if cfg.base_size is not None:
            overrides["base_size_px"] = cfg.base_size
        overrides["word_drift_px"] = cfg.word_drift
        overrides["line_rise_px"] = cfg.line_rise
        overrides["line_step_jitter_frac"] = cfg.line_step_jitter
        overrides["margin_drift_px"] = cfg.margin_drift
        overrides["word_tilt_deg"] = cfg.word_tilt
        overrides["display_math_gap"] = cfg.display_math_gap
        overrides["word_pages"] = cfg.word_pages
        paper_style = None
        if cfg.paper_pdf is None:
            # GUI default background: plain white A4 (like a Word page), even
            # with scan effects on — effects act on the ink, never the paper.
            paper_style = PaperStyle(paper_rgb=(255, 255, 255), texture_amp=0)
            overrides["scanner_tone_amp"] = 0
        return render_with_options(
            cfg.input,
            style_path=cfg.style_path,
            seed=cfg.seed,
            store=cfg.store or resources.default_store(),
            paper_pdf=cfg.paper_pdf,
            paper_fit=cfg.paper_fit,
            snap_lines=cfg.snap_lines,
            rule_spacing=cfg.rule_spacing,
            rule_offset=cfg.rule_offset,
            rule_margin_x=cfg.rule_margin_x,
            dpi=cfg.dpi,
            effects=cfg.effects,
            style_overrides=overrides or None,
            paper_style=paper_style,
            math_tools=_math_tools(),
            math_raw_pen=cfg.raw_pen,
        )
    return _run_math_chain(cfg, progress)


def save(pages: list[Image.Image], out: Path) -> list[Path]:
    """Write pages as .pdf (combined) or .png (per page); returns paths."""
    return save_pages(pages, out)
