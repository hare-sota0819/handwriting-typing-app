"""Which glyph store to draw with.

The pipeline is handwriting-agnostic: every store under `glyphs/` that has a
manifest is a candidate — your own imported handwriting, the bundled demo
store (font-rendered, generated on first use), or the Phase 1 synthetic set.
Precedence: `HW_STORE` env var → the first user store (anything that is not
`demo`/`synthetic`, alphabetical) → `demo` → `synthetic`.
"""

import os
from pathlib import Path

from .glyphstore import MANIFEST_NAME

ROOT = Path(__file__).resolve().parents[1]
GLYPHS_DIR = ROOT / "glyphs"
DEMO_NAME = "demo"
SYNTHETIC_NAME = "synthetic"
_BUILTIN = (DEMO_NAME, SYNTHETIC_NAME)


def is_store(path: Path) -> bool:
    return (Path(path) / MANIFEST_NAME).is_file()


def list_stores(glyphs_dir: Path = GLYPHS_DIR) -> list[Path]:
    """Every store directory, user stores first (alphabetical), then demo,
    then synthetic."""
    if not glyphs_dir.is_dir():
        return []
    found = [p for p in sorted(glyphs_dir.iterdir()) if p.is_dir() and is_store(p)]
    user = [p for p in found if p.name not in _BUILTIN]
    builtin = [p for name in _BUILTIN for p in found if p.name == name]
    return user + builtin


def default_store(glyphs_dir: Path = GLYPHS_DIR) -> Path:
    """The store to use when none is chosen. Generates the demo store on
    first use when nothing else exists (a fresh checkout has no glyphs)."""
    env = os.environ.get("HW_STORE")
    if env:
        return Path(env)
    stores = list_stores(glyphs_dir)
    if stores:
        return stores[0]
    from .demostore import generate
    return generate(glyphs_dir / DEMO_NAME)
