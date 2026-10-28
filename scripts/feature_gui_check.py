"""Feature verification: GUI shell (gui/ package) around the pipelines.

Checks:
- Mode autodetection: .docx -> docx-text, .txt/.tex -> math-set, else rejects.
- Headless runner, docx-text: run_job returns pages; same seed reproduces,
  different seed differs; save() writes PNG and combined PDF.
- Headless runner, math-set: full chain (node+parse+render) yields the
  contact sheet; a re-roll with a new seed reuses the prepared chain (no
  extract/mathjax/parse stages) and still renders.
- Window (offscreen): drop wiring sets file/mode, widget state maps into
  JobConfig correctly (auto spin boxes -> None), a real conversion through
  the worker thread lands in the preview and enables re-roll/save.
Exit 0 = pass.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from gui import resources, runner  # noqa: E402
from gui.runner import JobConfig, detect_mode  # noqa: E402

SCRATCH = ROOT / "out" / "gui_check"
# Never let a check write the real user's settings file.
os.environ["HW_SETTINGS_DIR"] = str(SCRATCH / "settings")


def check_detect_mode() -> None:
    assert detect_mode(Path("a.docx")) == "docx-text"
    assert detect_mode(Path("a.DOCX")) == "docx-text"
    assert detect_mode(Path("eqs.txt")) == "math-set"
    assert detect_mode(Path("eqs.tex")) == "math-set"
    try:
        detect_mode(Path("a.pdf"))
    except ValueError:
        pass
    else:
        raise AssertionError("detect_mode accepted a .pdf")
    print("mode autodetect: OK")


def check_text_mode() -> None:
    cfg = JobConfig(input=ROOT / "samples" / "plain.docx",
                    mode="docx-text", seed=5, dpi=150)
    pages = run_and_report(cfg)
    again = run_and_report(cfg)
    assert list(pages[0].tobytes()) == list(again[0].tobytes()), \
        "same seed must reproduce identical pages"
    other = run_and_report(JobConfig(input=cfg.input, mode="docx-text",
                                     seed=6, dpi=150))
    assert pages[0].tobytes() != other[0].tobytes(), \
        "different seed must change the page"

    # GUI background is plain white A4 even with effects on (default cfg)
    corner = pages[0].getpixel((5, 5))
    assert corner == (255, 255, 255), \
        f"GUI background must be plain white, got {corner}"

    png = runner.save(pages, SCRATCH / "text.png")
    pdf = runner.save(pages, SCRATCH / "text.pdf")
    assert png[0].exists() and png[0].suffix == ".png"
    assert pdf[0].exists() and pdf[0].suffix == ".pdf"

    # line-height needs a multi-line sample: plain.docx is one line in this store
    multi = ROOT / "samples" / "multi.docx"
    base = run_and_report(JobConfig(input=multi, mode="docx-text",
                                    seed=5, dpi=150))
    tight = run_and_report(JobConfig(input=multi, mode="docx-text",
                                     seed=5, dpi=150, line_height=1.2))
    assert tight[0].tobytes() != base[0].tobytes(), \
        "line_height override must change the layout"
    print(f"docx-text: OK ({len(pages)} page(s), seed reproducible, "
          "png+pdf written, line-height override effective)")


def check_math_mode() -> None:
    eqfile = ROOT / "samples" / "eqs_sqrt_test.txt"
    stages: list[str] = []
    pages = runner.run_job(JobConfig(input=eqfile, mode="math-set", seed=1),
                           progress=stages.append)
    assert pages, "math-set produced no pages"
    assert "mathjax" in stages and "render" in stages

    stages.clear()
    reroll = runner.run_job(JobConfig(input=eqfile, mode="math-set", seed=2),
                            progress=stages.append)
    assert reroll, "re-roll produced no pages"
    assert "extract" not in stages and "mathjax" not in stages, \
        f"re-roll must skip the prepared chain, ran: {stages}"
    print(f"math-set: OK ({len(pages)} sheet page(s), re-roll skipped "
          "extract/mathjax)")


def run_and_report(cfg: JobConfig):
    pages = runner.run_job(cfg)
    assert pages and pages[0].mode == "RGB"
    return pages


def check_settings_file() -> None:
    """The settings module: where it lives, that it round-trips, and the
    order the save dialog picks a folder in."""
    import json

    from gui.settings import Settings, default_path, resolve_save_dir

    # the file lives OUTSIDE the app folder, so replacing dist/ on a rebuild
    # does not wipe it
    assert default_path() == SCRATCH / "settings" / "settings.json"
    # without the override it lands in the per-user config dir — never inside
    # the app folder, which a rebuild replaces wholesale
    override = os.environ.pop("HW_SETTINGS_DIR")
    try:
        real = default_path()
    finally:
        os.environ["HW_SETTINGS_DIR"] = override
    assert real.parent.name == "handwriting-converter"
    assert ROOT not in real.parents and resources.ROOT not in real.parents

    path = SCRATCH / "settings" / "roundtrip.json"
    path.unlink(missing_ok=True)
    s = Settings(path)
    assert s.options == {} and s.presets == {}
    s.options = {"dpi": 300, "effects": True}
    s.last_save_dir = str(SCRATCH)
    s.put_preset("숙제", {"dpi": 150})
    s.save()
    again = Settings(path)
    assert again.options == {"dpi": 300, "effects": True}
    assert again.last_save_dir == str(SCRATCH)
    assert again.presets == {"숙제": {"dpi": 150}}
    again.drop_preset("숙제")
    again.save()
    assert Settings(path).presets == {}
    # non-ASCII names survive the file
    assert "숙제" in json.dumps({"숙제": 1}, ensure_ascii=False)

    # a corrupt or missing file must not crash the app — it starts fresh
    path.write_text("{ not json", encoding="utf-8")
    assert Settings(path).options == {}

    # save dialog folder: configured -> last used -> the input file's folder
    here, missing = SCRATCH, SCRATCH / "does-not-exist"
    doc = ROOT / "samples" / "plain.docx"
    assert resolve_save_dir(str(here), None, None) == here
    assert resolve_save_dir(str(missing), str(here), doc) == here
    assert resolve_save_dir(None, str(here), doc) == here
    assert resolve_save_dir(None, str(missing), doc) == doc.parent
    assert resolve_save_dir(None, None, doc) == doc.parent
    assert resolve_save_dir(None, None, None) is None
    print("settings file: OK — path outside the app, round-trip, corrupt file "
          "survived, folder order configured>last>input")


def check_window() -> None:
    from PySide6.QtWidgets import QApplication

    from gui.app import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()

    win.set_input(ROOT / "samples" / "plain.docx")
    assert win.current_mode() == "docx-text"
    win.mode_math.setChecked(True)
    assert win.current_mode() == "docx-math"
    win.set_input(ROOT / "samples" / "eqs_sqrt_test.txt")
    assert win.current_mode() == "math-set"
    assert not win.mode_text.isEnabled()

    win.seed.setValue(42)
    win.dpi.setValue(300)
    win.snap.setChecked(True)
    win.rule_spacing.setValue(55.5)
    cfg = win.build_config()
    assert cfg.seed == 42 and cfg.dpi == 300 and cfg.snap_lines
    assert cfg.rule_spacing == 55.5 and cfg.rule_offset is None
    assert cfg.style_path is None
    # 손글씨 드롭다운 lists every store under glyphs/ (user stores first, then
    # demo); the default pick IS the registry default; 고급 옵션의 직접 지정
    # 폴더가 이긴다
    stores = resources.list_stores()
    assert stores and cfg.store == stores[0] == resources.default_store()
    assert [win.hand_store.itemText(i) for i in range(win.hand_store.count())] \
        == [p.name for p in stores]
    win.hand_store.setCurrentIndex(len(stores) - 1)
    assert win.build_config().store == stores[-1]
    win.store_pick.edit.setText(str(ROOT / "glyphs" / "demo"))
    assert win.build_config().store == ROOT / "glyphs" / "demo"
    win.store_pick.edit.clear()
    win.hand_store.setCurrentIndex(0)
    assert win.build_config().store == stores[0]
    # line spacing defaults to 0.6 in the GUI (user pick 2026-08-18); spinning
    # down to 0 ("자동") falls back to the style default
    assert cfg.line_height == 0.6 and cfg.base_size is None
    assert cfg.display_math_gap == 0.35
    # handwriting-rhythm defaults = the values the user set by hand every
    # run (2026-08-18: 2.0 / 1.5 / 10 / 0, jitter 2%); scan effects OFF
    assert (cfg.word_drift, cfg.line_rise, cfg.margin_drift, cfg.word_tilt) \
        == (2.0, 1.5, 10.0, 0.0)
    assert abs(cfg.line_step_jitter - 0.02) < 1e-9
    assert not cfg.effects
    win.line_height.setValue(0.0)
    assert win.build_config().line_height is None
    win.line_height.setValue(1.4)
    win.base_size.setValue(80.0)
    cfg = win.build_config()
    assert cfg.line_height == 1.4 and cfg.base_size == 80.0

    # 고급 옵션 기본값으로 되돌리기 restores every shipped default
    win.effects.setChecked(True)
    win.margin_drift.setValue(0.0)
    win.math_gap.setValue(1.0)
    assert win.build_config().display_math_gap == 1.0
    win.reset_advanced()
    cfg = win.build_config()
    assert cfg.line_height == 0.6 and cfg.base_size is None
    assert cfg.display_math_gap == 0.35
    assert cfg.dpi == 400 and not cfg.effects and not cfg.snap_lines
    assert cfg.word_drift == 2.0 and cfg.line_rise == 1.5 and cfg.margin_drift == 10.0
    assert cfg.rule_spacing is None and cfg.style_path is None

    win.set_input(ROOT / "samples" / "plain.docx")
    win.dpi.setValue(150)
    done: list = []
    on_done = win._on_done
    win._on_done = lambda pages: (on_done(pages), done.append(pages),
                                  app.quit())
    win._on_failed = lambda msg: (print("convert failed:", msg), app.quit())
    win.convert()
    app.exec()
    assert done, "worker conversion did not complete"
    assert win.preview.pixmap() and not win.preview.pixmap().isNull()
    assert win.save_btn.isEnabled() and win.reroll_btn.isEnabled()

    # zoomable preview: pixmap is the FULL page raster; 100% -> scale 1.0,
    # zoom steps clamp; fit mode restores on demand
    page = win.pages[0]
    pix = win.preview.pixmap()
    assert (pix.width(), pix.height()) == page.size, \
        f"preview pixmap {pix.width()}x{pix.height()} != page {page.size}"
    win.preview.zoom_actual()
    assert abs(win.preview.transform().m11() - 1.0) < 1e-6
    win.preview.zoom_by(1.25)
    assert abs(win.preview.transform().m11() - 1.25) < 1e-6
    for _ in range(20):
        win.preview.zoom_by(1.25)
    assert win.preview.transform().m11() <= win.preview.MAX_ZOOM + 1e-6
    win.preview.zoom_fit()
    assert win.preview._fit
    # The window narrows to half a screen (user report 2026-09-30: it stopped
    # at 980 px); with room the options column keeps its full width.
    from gui.app import PANEL_W
    assert win.minimumSizeHint().width() <= 700, win.minimumSizeHint()
    win.resize(1100, 760)
    app.processEvents()
    panel = win.centralWidget().layout().itemAt(0).widget()
    assert panel.width() == PANEL_W, panel.width()
    win.resize(640, 760)
    app.processEvents()
    assert win.width() <= 700, win.width()
    print("window (offscreen): OK — worker convert landed in preview; "
          "zoom 100%/step/clamp/fit OK; narrows to "
          f"{win.minimumSizeHint().width()} px, options column {PANEL_W} px when wide")


def check_settings_window() -> None:
    """고급 옵션 survive closing the window, presets name a set of them, and
    the save dialog opens where the user expects."""
    from PySide6.QtWidgets import QApplication, QFileDialog

    from gui import app as app_mod
    from gui.app import ADVANCED_DEFAULTS, MainWindow
    from gui.settings import default_path

    app = QApplication.instance() or QApplication([])
    default_path().unlink(missing_ok=True)

    win = MainWindow()
    assert win.collect_advanced() == ADVANCED_DEFAULTS, \
        "a fresh install must start on the shipped defaults"
    win.dpi.setValue(220)
    win.effects.setChecked(True)
    win.margin_drift.setValue(3.5)
    win.paper_fit.setCurrentText("contain")
    win.line_height.setValue(1.4)
    win.seed.setValue(777)
    win.save_dir_pick.edit.setText(str(SCRATCH))
    changed = win.collect_advanced()
    win.close()

    win = MainWindow()
    assert win.collect_advanced() == changed, "고급 옵션 were not remembered"
    assert win.dpi.value() == 220 and win.effects.isChecked()
    assert win.paper_fit.currentText() == "contain"
    assert win.save_dir_pick.path() == SCRATCH
    # the seed is deliberately NOT remembered: 다시 뽑기 bumps it every run
    assert win.seed.value() == 0

    # 기본값으로 되돌리기 resets the rendering knobs and leaves the save
    # folder alone — that is a preference, not a style knob
    win.reset_advanced()
    assert win.collect_advanced() == ADVANCED_DEFAULTS
    assert win.save_dir_pick.path() == SCRATCH

    # presets: name the current 고급 옵션, come back to them later
    win.dpi.setValue(150)
    win.word_tilt.setValue(1.5)
    homework = win.collect_advanced()
    win.save_preset("숙제")
    win.reset_advanced()
    assert win.collect_advanced() == ADVANCED_DEFAULTS
    win.apply_preset("숙제")
    assert win.collect_advanced() == homework
    assert win.preset_names() == ["숙제"]
    win.close()
    win = MainWindow()
    assert win.preset_names() == ["숙제"], "presets did not outlive the window"
    win.delete_preset("숙제")
    assert win.preset_names() == []

    # A build whose default was ON once saved word_pages=true that nobody had
    # chosen. The option is remembered under another name now, so that stale
    # value must not switch Word-page mirroring back on (user report
    # 2026-09-21: half-empty pages kept coming after the default went OFF).
    import json
    win.close()
    stale = json.loads(default_path().read_text(encoding="utf-8"))
    stale["options"]["word_pages"] = True
    default_path().write_text(json.dumps(stale), encoding="utf-8")
    win = MainWindow()
    assert not win.word_pages.isChecked(), \
        "a stale word_pages=true switched Word-page mirroring on"
    win.word_pages.setChecked(True)
    win.close()
    win = MainWindow()
    assert win.word_pages.isChecked(), "choosing Word-page mirroring was not remembered"
    win.reset_advanced()

    # save(): the dialog opens in the resolved folder, and a successful save
    # records where it went
    win.reset_advanced()
    win.save_dir_pick.edit.clear()
    win.set_input(ROOT / "samples" / "plain.docx")
    win.pages = [Image.new("RGB", (60, 80), "white")]
    opened: list[str] = []
    target = SCRATCH / "saved"
    target.mkdir(parents=True, exist_ok=True)

    def fake_dialog(parent, title, start, name_filter):
        opened.append(start)
        return str(target / "out.pdf"), "PDF (*.pdf)"

    real = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(fake_dialog)
    try:
        app_mod._reveal_in_file_browser = lambda path: None
        win.save()
        assert Path(opened[-1]).parent == (ROOT / "samples"), \
            f"no configured or last folder yet, so the input's: {opened[-1]}"
        assert (target / "out.pdf").exists()
        win.save()
        assert Path(opened[-1]).parent == target, \
            f"second save should offer the last used folder: {opened[-1]}"
        win.save_dir_pick.edit.setText(str(SCRATCH))
        win.save()
        assert Path(opened[-1]).parent == SCRATCH, \
            f"a configured folder wins over the last used one: {opened[-1]}"
    finally:
        QFileDialog.getSaveFileName = real

    # 파일 선택: the same fault, on the way in. An empty start path sends Qt to
    # the process's working directory — the app folder for a double-clicked exe.
    win.open_dir_pick.edit.clear()
    started: list[str] = []

    def fake_open(parent, title, start, name_filter):
        started.append(start)
        return "", ""

    real_open = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(fake_open)
    try:
        win.drop.mousePressEvent(None)
        assert Path(started[-1]) == (ROOT / "samples"), \
            f"the folder the last input came from: {started[-1]}"
        win.open_dir_pick.edit.setText(str(SCRATCH))
        win.drop.mousePressEvent(None)
        assert Path(started[-1]) == SCRATCH, \
            f"a configured folder wins over the last used one: {started[-1]}"
    finally:
        QFileDialog.getOpenFileName = real_open
    win.close()

    win = MainWindow()
    assert win.open_dir_pick.path() == SCRATCH, \
        "기본 불러오기 폴더 was not remembered"
    win.close()
    default_path().unlink(missing_ok=True)
    print("settings in the window: OK — 고급 옵션 remembered, seed not, reset "
          "spares the save folder, presets round-trip, open/save dialog "
          "folder order")


def main() -> int:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    # Every run starts from a fresh install: the window checks assert the
    # SHIPPED defaults, and a settings file left by a previous run would feed
    # them the previous run's values instead.
    from gui.settings import default_path
    default_path().unlink(missing_ok=True)
    check_detect_mode()
    check_text_mode()
    check_math_mode()
    check_settings_file()
    check_window()
    check_settings_window()
    print("feature_gui_check: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
