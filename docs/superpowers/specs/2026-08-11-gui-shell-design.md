# GUI Shell — desktop app + distributable Windows exe (design)

Approved 2026-08-11 ("1번으로 가자" / "한번 끝까지 만들어와 봐").

## Goal

A double-clickable desktop program (no browser) that wraps the existing
rendering entry points: drop a file in, tweak options, click convert, see a
preview, re-roll until happy, save. Distributable to other Windows machines as
an exe; the recipient needs nothing else installed.

## What it wraps (no new rendering capability)

| Input | Mode | Existing entry point |
|---|---|---|
| `.docx` | Body text → handwriting pages | `handwriting` pipeline (cli.py path) |
| `.docx` | Equations → labelled contact-sheet PDF | `scripts/render_docx_math.py` chain |
| `.txt` | LaTeX list → labelled contact-sheet PDF | `scripts/render_math_set.py` chain |

`.docx` defaults to body-text mode with a toggle for the equation sheet.
`.txt` is always the math-set mode. The integrated text+math page is Phase 2
work and out of scope here.

## UI (PySide6, Korean strings, single window)

- Left: drop zone (drag & drop or click-to-browse), detected mode shown.
- Right: preview panel — rendered pages, prev/next page buttons.
- Bottom: options.
  - Basic: output format (PNG/PDF), seed.
  - Advanced (collapsible): style JSON, paper background PDF + fit mode,
    snap-lines, rule spacing/offset/margin-x, DPI, effects on/off, glyph
    store dir, raw-pen (math modes).
  - Options not applicable to the detected mode are disabled.
- Buttons: 변환 (convert), 다시 뽑기 (re-roll = seed change + reconvert),
  저장 (save via file dialog).
- Conversion runs on a QThread; UI stays responsive; progress indicator.
- Errors surface as a one-line message dialog, never a silent crash.

## Architecture

- `gui/runner.py` — headless core, no Qt: `JobConfig` dataclass, mode
  autodetection, tool resolution, `run_job() -> pages`, `save()`.
  This is the tested unit.
- `gui/app.py` — window, widgets, worker thread. Thin.
- `gui/resources.py` — resolves bundled assets & tools in dev (repo layout)
  vs frozen (PyInstaller `sys._MEIPASS`): glyph store, spike dir, pandoc, node.
- Existing pipeline code is called, not modified, except two surgical seams:
  - `handwriting/cli.py`: extract the option→render core into a callable
    function so the GUI does not re-implement dpi/grid/style setup.
  - `spike/render_placement.py`: accept `--seed=N` (default 7 unchanged) so
    re-roll works for math modes too.
- Math chain steps that are python scripts run in-process via `runpy` with a
  patched argv (subprocess-to-`sys.executable` breaks inside a PyInstaller
  exe); pandoc and node run as bundled subprocess binaries.

## Packaging / distribution

- `build_windows.bat` + PyInstaller spec, run on Windows: produces a
  self-contained app folder (zip and share). Bundles python runtime, PySide6,
  pipeline code, `glyphs/ipad`, spike chain (`tex2svg.js`, `node_modules`),
  and fetches pinned official pandoc.exe + portable node.exe on first build.
- Dev/test stays on WSL; the spec's bundle logic is validated on Linux with a
  onedir build + offscreen smoke run.

## Verification

`scripts/feature_gui_check.py` in verify.sh: mode autodetect, option→config
mapping, end-to-end `run_job` on a sample docx and a small math set,
offscreen window smoke test (`QT_QPA_PLATFORM=offscreen`).
