"""Locate bundled data and external tools, in dev checkout and frozen exe alike.

In the dev checkout everything sits in the repo layout. In a PyInstaller
bundle the same layout is reproduced under the bundle root (onedir: next to
the exe in _internal; onefile: the _MEIPASS unpack dir), plus a tools/ dir
holding pandoc and node fetched by the build script.
"""

import shutil
import sys
from pathlib import Path


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
    return Path(__file__).resolve().parent.parent


ROOT = bundle_root()
SPIKE_DIR = ROOT / "spike"
SCRIPTS_DIR = ROOT / "scripts"
GLYPHS_DIR = ROOT / "glyphs"


def _app_name() -> str:
    """Product name. packaging/app_name.local.txt (gitignored, optional)
    overrides it for a private build — the public build has none."""
    override = ROOT / "packaging" / "app_name.local.txt"
    if override.is_file():
        name = override.read_text(encoding="utf-8").strip()
        if name:
            return name
    return "Handwriting Converter"


APP_NAME = _app_name()


def list_stores() -> list[Path]:
    """Glyph stores bundled/installed under glyphs/, user stores first."""
    from handwriting.stores import list_stores as _list
    return _list(GLYPHS_DIR)


def default_store() -> Path:
    from handwriting.stores import default_store as _default
    return _default(GLYPHS_DIR)


class ToolMissingError(RuntimeError):
    """A required external tool (pandoc / node) could not be found."""

    def __init__(self, tool: str, looked_in: list[Path]):
        self.tool = tool
        super().__init__(
            f"{tool} not found (looked in: "
            f"{', '.join(str(p) for p in looked_in)}, and PATH)")


def _find(tool: str, bundled: list[Path]) -> Path:
    for p in bundled:
        if p.exists():
            return p
    on_path = shutil.which(tool)
    if on_path:
        return Path(on_path)
    raise ToolMissingError(tool, bundled)


def find_pandoc() -> Path:
    exe = "pandoc.exe" if sys.platform == "win32" else "pandoc"
    return _find("pandoc", [
        ROOT / "tools" / "pandoc" / exe,
        SPIKE_DIR / "tools" / "pandoc-3.5" / "bin" / "pandoc",
    ])


def find_node() -> Path:
    exe = "node.exe" if sys.platform == "win32" else "node"
    return _find("node", [ROOT / "tools" / "node" / exe])
