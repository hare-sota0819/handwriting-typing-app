# PyInstaller spec for the handwriting converter GUI (onedir).
#
# Reproduces the repo layout inside the bundle so gui/resources.py finds
# everything at the same relative paths: glyphs/<store>, spike/ (js + py +
# node_modules), scripts/ (imported helpers), tools/ (pandoc/node, fetched by
# build_windows.bat; absent on the Linux validation build, where system
# node/pandoc on PATH are used instead).

from pathlib import Path

ROOT = Path(SPECPATH).parent

# Every glyph store present under glyphs/ ships (your imported handwriting
# and/or the demo store), except the Phase 1 synthetic set.
_stores = [p for p in sorted((ROOT / "glyphs").glob("*/manifest.json"))
           if p.parent.name != "synthetic"]
if not any(p.parent.name == "demo" for p in _stores):
    import subprocess, sys as _sys
    subprocess.run([_sys.executable, "-m", "handwriting.demostore"], cwd=ROOT, check=True)
    _stores = [p for p in sorted((ROOT / "glyphs").glob("*/manifest.json"))
               if p.parent.name != "synthetic"]

# Optional private product name (packaging/app_name.local.txt, gitignored).
_name_file = ROOT / "packaging" / "app_name.local.txt"
APP_EXE = (_name_file.read_text(encoding="utf-8").strip()
           if _name_file.is_file() else "") or "HandwritingConverter"

datas = [
    (str(ROOT / "handwriting" / "data"), "handwriting/data"),
    (str(ROOT / "template" / "charset_default.txt"), "template"),
    (str(ROOT / "template" / "charset_math.txt"), "template"),
    (str(ROOT / "spike" / "tex2svg.js"), "spike"),
    (str(ROOT / "spike" / "parse_svg.py"), "spike"),
    (str(ROOT / "spike" / "render_placement.py"), "spike"),
    (str(ROOT / "spike" / "node_modules"), "spike/node_modules"),
    (str(ROOT / "scripts" / "render_docx_math.py"), "scripts"),
    (str(ROOT / "scripts" / "render_math_set.py"), "scripts"),
    (str(ROOT / "packaging" / "app_icon.png"), "packaging"),
]
# Optional private icon (packaging/app_icon.local.*, gitignored): made from
# your own handwriting by `scripts/make_app_icon.py --local`.
_local_png = ROOT / "packaging" / "app_icon.local.png"
_local_ico = ROOT / "packaging" / "app_icon.local.ico"
if _local_png.is_file():
    datas.append((str(_local_png), "packaging"))
APP_ICON = _local_ico if _local_ico.is_file() else ROOT / "packaging" / "app_icon.ico"
datas += [(str(p.parent), f"glyphs/{p.parent.name}") for p in _stores]
if _name_file.is_file():
    datas.append((str(_name_file), "packaging"))
if (ROOT / "tools").exists():
    datas.append((str(ROOT / "tools"), "tools"))

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["docx"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name=APP_EXE,
    console=False,
    icon=str(APP_ICON),
)

# The exe (user-visible program name) may be non-ASCII, but the app FOLDER
# stays ASCII on purpose: bundled node v22.12 dies silently (V8 fatal, exit 5)
# when the script path it is given contains non-ASCII characters, which
# would break the math chain for every path under _internal.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="HandwritingConverter",
)
