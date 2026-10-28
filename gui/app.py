"""PySide6 window for the handwriting converter. UI strings are Korean.

Thin by design: builds a JobConfig from the widgets, runs gui.runner.run_job
on a worker thread, shows the returned pages. All conversion logic lives in
runner.py.
"""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QGraphicsScene, QGraphicsView, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from . import resources, runner
from .settings import Settings, resolve_open_dir, resolve_save_dir

# Every 고급 옵션 and the value it ships with. ONE table: the reset button,
# the remembered settings and the presets all read and write through it, so a
# knob can never be added to one and forgotten in the others.
ADVANCED_DEFAULTS = {
    "style_path": "",
    "line_height": 0.6,      # GUI default (user 2026-08-18); 0 = style default (1.8)
    "base_size": 0.0,        # 기본 (64)
    "math_gap": 0.35,
    # 손글씨 리듬 (0 = 끔): the values the user set by hand every run (2026-08-18)
    "word_drift": 2.0,
    "line_rise": 1.5,
    "step_jitter": 2.0,
    "margin_drift": 10.0,
    "word_tilt": 0.0,
    "paper_pdf": "",
    "paper_fit": "cover",
    "snap": False,
    "rule_spacing": 0.0,     # 자동
    "rule_offset": 0.0,
    "rule_margin": 0.0,
    # Follow Word's own pages; off = fill every page (user 2026-09-21, after
    # trying it on). Saved as "mirror_word_pages", not "word_pages": a build
    # whose default was ON wrote word_pages=true into settings nobody had
    # chosen, and under the old name that stale value would keep it on.
    "mirror_word_pages": False,
    "dpi": 400,
    "effects": False,        # off by default (user 2026-08-18)
    "raw_pen": False,
    "store": "",
}

STAGE_TEXT = {
    "extract": "수식 추출 중…",
    "mathjax": "수식 조판 중…",
    "parse": "구조 분석 중…",
    "render": "손글씨 렌더 중…",
    "sheet": "시트 조립 중…",
}


class ConvertWorker(QThread):
    done = Signal(list)
    failed = Signal(str)
    stage = Signal(str)

    def __init__(self, cfg: runner.JobConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg

    def run(self):
        try:
            pages = runner.run_job(self.cfg, progress=self.stage.emit)
        except resources.ToolMissingError as e:
            self.failed.emit(
                f"필요한 변환 도구({e.tool})를 찾지 못했어요. "
                "프로그램 폴더가 온전한지 확인해 주세요.")
        except Exception as e:  # surfaced to a dialog, never a silent crash
            self.failed.emit(str(e))
        else:
            self.done.emit(pages)


class DropZone(QLabel):
    """Dashed drop target; also opens a file dialog on click.

    Turns into a green "file selected" card once set_file() is called so the
    selection is visible in the zone itself, not just in a side label.
    """

    file_dropped = Signal(Path)

    # Set by MainWindow; returns the folder the dialog should open in. Asked
    # at click time rather than stored, so a folder the user has just typed
    # into 기본 불러오기 폴더 takes effect without any wiring to keep in sync.
    start_dir = staticmethod(lambda: "")

    PROMPT = ("여기에 파일을 끌어다 놓거나\n클릭해서 선택하세요\n\n"
              "(.docx 문서 / .txt 수식 목록)")
    IDLE_STYLE = ("QLabel { border: 2px dashed #999; border-radius: 8px; "
                  "color: #555; padding: 8px; }")
    SELECTED_STYLE = ("QLabel { border: 2px solid #2e7d32; border-radius: 8px; "
                      "color: #1b5e20; background: #e8f5e9; padding: 8px; "
                      "font-weight: bold; }")

    def __init__(self):
        super().__init__(self.PROMPT)
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setStyleSheet(self.IDLE_STYLE)

    def set_file(self, path: Path):
        self.setText(f"✔ {path.name}\n\n다른 파일을 끌어다 놓거나\n클릭해서 바꿀 수 있어요")
        self.setStyleSheet(self.SELECTED_STYLE)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.file_dropped.emit(Path(urls[0].toLocalFile()))

    def mousePressEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(
            self, "파일 선택", self.start_dir(),
            "지원 파일 (*.docx *.txt *.tex);;모든 파일 (*)")
        if path:
            self.file_dropped.emit(Path(path))


class FilePicker(QWidget):
    """Line edit + 찾아보기 button; empty text means 'not set'."""

    def __init__(self, dialog_title: str, name_filter: str, directory=False):
        super().__init__()
        self.dialog_title = dialog_title
        self.name_filter = name_filter
        self.directory = directory
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("(선택 안 함)")
        btn = QPushButton("찾아보기…")
        btn.clicked.connect(self._browse)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit)
        lay.addWidget(btn)

    def _browse(self):
        if self.directory:
            path = QFileDialog.getExistingDirectory(self, self.dialog_title)
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, self.dialog_title, "", self.name_filter)
        if path:
            self.edit.setText(path)

    def path(self) -> Path | None:
        text = self.edit.text().strip()
        return Path(text) if text else None


class NoWheelSpin(QSpinBox):
    """Spin box that never reacts to the mouse wheel.

    The options live in a scroll area; a wheel that edits whatever control
    happens to be under the cursor makes scrolling the panel impossible.
    The wheel is ignored (so it scrolls the panel); values change by typing
    or the arrow buttons.
    """

    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpin(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelCombo(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


def _auto_spin(maximum: float, step: float = 1.0,
               auto_text: str = "자동") -> QDoubleSpinBox:
    """Spin box whose minimum position shows auto_text and means None."""
    box = NoWheelDoubleSpin()
    box.setRange(0.0, maximum)
    box.setSingleStep(step)
    box.setSpecialValueText(auto_text)
    box.setValue(0.0)
    return box


def _auto_value(box: QDoubleSpinBox) -> float | None:
    return None if box.value() == 0.0 else box.value()


class PreviewView(QGraphicsView):
    """Zoomable page preview at the full render resolution.

    Ctrl+wheel zooms (anchored at the cursor), dragging pans, double-click
    toggles fit <-> 100%, and the buttons below the preview drive the same
    actions. The full-DPI page raster lives in the scene, so zooming only
    repaints the visible region — nothing is re-rendered or re-scaled.
    """

    zoom_changed = Signal(float)
    MAX_ZOOM = 4.0
    MIN_ZOOM = 0.02

    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = self._scene.addPixmap(QPixmap())
        self._placeholder = self._scene.addText("변환 결과가 여기에 표시됩니다")
        self._fit = True
        self.setRenderHints(self.renderHints() | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)

    def pixmap(self) -> QPixmap:
        """Current page pixmap (duck-typed like QLabel for the checks)."""
        return self._item.pixmap()

    def set_page(self, image) -> None:
        """Show a PIL RGB page. Keeps the zoom unless in fit mode."""
        if self._placeholder is not None:
            self._scene.removeItem(self._placeholder)
            self._placeholder = None
        qimg = QImage(image.tobytes(), image.width, image.height,
                      image.width * 3, QImage.Format_RGB888)
        self._item.setPixmap(QPixmap.fromImage(qimg.copy()))
        self._scene.setSceneRect(self._item.boundingRect())
        if self._fit:
            self._refit()
        else:
            self._emit_zoom()

    def _refit(self) -> None:
        if not self._item.pixmap().isNull():
            self.fitInView(self._item, Qt.KeepAspectRatio)
        self._emit_zoom()

    def _emit_zoom(self) -> None:
        self.zoom_changed.emit(self.transform().m11())

    def zoom_fit(self) -> None:
        self._fit = True
        self._refit()

    def zoom_actual(self) -> None:  # 100%: one page pixel = one screen pixel
        if self._item.pixmap().isNull():
            return
        self._fit = False
        self.resetTransform()
        self._emit_zoom()

    def zoom_by(self, factor: float) -> None:
        if self._item.pixmap().isNull():
            return
        cur = self.transform().m11()
        target = max(self.MIN_ZOOM, min(self.MAX_ZOOM, cur * factor))
        self._fit = False
        self.scale(target / cur, target / cur)
        self._emit_zoom()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_by(1.25 if event.angleDelta().y() > 0 else 0.8)
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._item.pixmap().isNull():
            return
        if self._fit:
            self.zoom_actual()
        else:
            self.zoom_fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit:
            self._refit()


def _reveal_in_file_browser(path: Path) -> None:
    """Open the OS file browser with the saved file selected."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


# The options column is this wide when the window has room, and narrows down
# to PANEL_MIN_W (its contents then scroll sideways) so the whole window can
# be snapped to half a screen (user report 2026-09-30: it would not shrink).
PANEL_W = 490
PANEL_MIN_W = 230


class SidePanel(QWidget):
    """The left column; asks for PANEL_W, gives way down to PANEL_MIN_W."""

    def sizeHint(self) -> QSize:
        return QSize(PANEL_W, super().sizeHint().height())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(resources.APP_NAME)
        icon_path = resources.ROOT / "packaging" / "app_icon.local.png"
        if not icon_path.exists():
            icon_path = resources.ROOT / "packaging" / "app_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1100, 760)
        self.input_path: Path | None = None
        self.pages = []
        self.page_index = 0
        self.worker = None

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)

        # ----- left column: input + options (scrollable) + actions (pinned).
        # At most PANEL_W wide, and the options live in their own scroll area:
        # expanding 고급 옵션 must never resize the window (it used to grow
        # past the screen so nothing below was clickable) nor squeeze the
        # controls together when maximized — overflow scrolls instead, and
        # sideways too when the window is made narrow. The action buttons
        # sit BELOW the scroll area, always visible.
        left_panel = SidePanel()
        left_panel.setMinimumWidth(PANEL_MIN_W)
        left_panel.setMaximumWidth(PANEL_W)
        panel_lay = QVBoxLayout(left_panel)
        panel_lay.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(left_panel, 0)

        left_body = QWidget()
        left = QVBoxLayout(left_body)
        left.setContentsMargins(0, 0, 8, 0)
        left_scroll = QScrollArea()
        left_scroll.setWidget(left_body)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        panel_lay.addWidget(left_scroll, 1)

        self.drop = DropZone()
        self.drop.start_dir = self.open_dir
        self.drop.file_dropped.connect(self.set_input)
        left.addWidget(self.drop)

        mode_box = QGroupBox("변환 종류")
        self.mode_text = QRadioButton("문서 손글씨 (본문 + 수식 → 손글씨 페이지)")
        self.mode_math = QRadioButton("수식 시트 (수식만 뽑아 번호 매긴 PDF)")
        self.mode_text.setChecked(True)
        mlay = QVBoxLayout(mode_box)
        mlay.addWidget(self.mode_text)
        mlay.addWidget(self.mode_math)
        left.addWidget(mode_box)

        hand_box = QGroupBox("손글씨 (글리프 저장소)")
        self.hand_store = NoWheelCombo()
        self.hand_stores = resources.list_stores()
        for p in self.hand_stores:
            self.hand_store.addItem(p.name)
        if not self.hand_stores:
            self.hand_store.addItem("(demo — 처음 변환 때 생성)")
        hlay = QVBoxLayout(hand_box)
        hlay.addWidget(self.hand_store)
        hint = QLabel("glyphs/ 아래 폴더 = 손글씨 한 벌. 내 글씨 만들기: README 'Your own handwriting'")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        hlay.addWidget(hint)
        left.addWidget(hand_box)

        basic = QGroupBox("기본 옵션")
        blay = QVBoxLayout(basic)
        seed_row = QHBoxLayout()
        seed_row.addWidget(QLabel("시드 (같은 숫자 = 같은 글씨)"))
        self.seed = NoWheelSpin()
        self.seed.setRange(0, 999999)
        seed_row.addWidget(self.seed)
        blay.addLayout(seed_row)
        left.addWidget(basic)

        adv = QGroupBox("고급 옵션")
        adv.setCheckable(True)
        adv.setChecked(False)
        alay = QVBoxLayout(adv)
        self.adv_body = QWidget()
        alay.addWidget(self.adv_body)
        self.adv_body.setVisible(False)
        adv.toggled.connect(self.adv_body.setVisible)
        ab = QVBoxLayout(self.adv_body)
        ab.setContentsMargins(0, 0, 0, 0)

        def row(label: str, widget: QWidget) -> QWidget:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(QLabel(label))
            h.addWidget(widget, 1)
            return w

        self.style_pick = FilePicker("글씨 스타일 JSON", "JSON (*.json)")
        ab.addWidget(row("글씨 스타일", self.style_pick))
        self.line_height = _auto_spin(4.0, 0.1, auto_text="자동 (1.8)")
        ab.addWidget(row("줄 간격 (글자 크기의 배수)", self.line_height))
        self.base_size = _auto_spin(200.0, 2.0, auto_text="기본 (64)")
        ab.addWidget(row("글자 크기(px)", self.base_size))
        self.math_gap = NoWheelDoubleSpin()
        self.math_gap.setRange(0.0, 3.0)
        self.math_gap.setSingleStep(0.05)
        ab.addWidget(row("수식 문단 간격 (글자 크기의 배수)", self.math_gap))

        def knob(maximum: float, step: float) -> QDoubleSpinBox:
            box = NoWheelDoubleSpin()
            box.setRange(0.0, maximum)
            box.setSingleStep(step)
            return box

        # 손글씨 리듬 (0 = 끔); 기본값은 ADVANCED_DEFAULTS
        self.word_drift = knob(30.0, 0.5)
        ab.addWidget(row("단어 높낮이(px)", self.word_drift))
        self.line_rise = knob(30.0, 0.5)
        ab.addWidget(row("줄 우상향(px)", self.line_rise))
        self.step_jitter = knob(20.0, 0.5)
        ab.addWidget(row("줄간격 편차(%)", self.step_jitter))
        self.margin_drift = knob(40.0, 1.0)
        ab.addWidget(row("여백 흐름(px)", self.margin_drift))
        self.word_tilt = knob(5.0, 0.1)
        ab.addWidget(row("단어 기울기(°)", self.word_tilt))
        self.paper_pick = FilePicker("배경 종이 PDF", "PDF (*.pdf)")
        ab.addWidget(row("배경 종이 PDF", self.paper_pick))
        self.paper_fit = NoWheelCombo()
        self.paper_fit.addItems(["cover", "stretch", "contain"])
        ab.addWidget(row("종이 맞춤", self.paper_fit))
        self.snap = QCheckBox("종이 줄에 맞춰 쓰기 (배경 PDF의 괘선 자동 인식)")
        ab.addWidget(self.snap)
        self.rule_spacing = _auto_spin(2000.0)
        ab.addWidget(row("괘선 간격(px)", self.rule_spacing))
        self.rule_offset = _auto_spin(4000.0)
        ab.addWidget(row("첫 줄 위치(px)", self.rule_offset))
        self.rule_margin = _auto_spin(4000.0)
        ab.addWidget(row("왼쪽 여백선(px)", self.rule_margin))
        self.word_pages = QCheckBox("워드 페이지 그대로 옮기기 (쪽수는 워드와 같아지지만 페이지 아래가 빔)")
        ab.addWidget(self.word_pages)
        self.dpi = NoWheelSpin()
        self.dpi.setRange(150, 600)
        ab.addWidget(row("해상도(DPI)", self.dpi))
        self.effects = QCheckBox("스캔 느낌 효과 켜기")
        ab.addWidget(self.effects)
        self.raw_pen = QCheckBox("수식 획 굵기 원본 유지")
        ab.addWidget(self.raw_pen)
        self.store_pick = FilePicker("글리프 저장소 폴더", "", directory=True)
        ab.addWidget(row("글씨 데이터", self.store_pick))
        reset_btn = QPushButton("고급 옵션 기본값으로 되돌리기")
        reset_btn.clicked.connect(self.reset_advanced)
        ab.addWidget(reset_btn)

        # A preference, not a style knob: 되돌리기 leaves it alone and it is
        # not part of a preset.
        self.open_dir_pick = FilePicker("기본 불러오기 폴더", "", directory=True)
        self.open_dir_pick.edit.setPlaceholderText(
            "(자동 — 마지막에 파일을 연 폴더, 없으면 홈 폴더)")
        ab.addWidget(row("기본 불러오기 폴더", self.open_dir_pick))
        self.save_dir_pick = FilePicker("기본 저장 폴더", "", directory=True)
        self.save_dir_pick.edit.setPlaceholderText(
            "(자동 — 마지막에 저장한 폴더, 없으면 원본 파일 폴더)")
        ab.addWidget(row("기본 저장 폴더", self.save_dir_pick))

        presets = QWidget()
        prow = QHBoxLayout(presets)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.addWidget(QLabel("설정 모음"))
        self.preset_box = NoWheelCombo()
        self.preset_box.activated.connect(self._preset_chosen)
        prow.addWidget(self.preset_box, 1)
        preset_save = QPushButton("저장")
        preset_save.clicked.connect(self._preset_save_clicked)
        preset_del = QPushButton("삭제")
        preset_del.clicked.connect(self._preset_delete_clicked)
        prow.addWidget(preset_save)
        prow.addWidget(preset_del)
        ab.addWidget(presets)
        left.addWidget(adv)

        left.addStretch(1)  # keep the option groups top-aligned when tall

        # actions pinned below the scroll area — always reachable
        self.convert_btn = QPushButton("변환하기")
        self.convert_btn.clicked.connect(self.convert)
        self.reroll_btn = QPushButton("다시 뽑기 (글씨 다르게)")
        self.reroll_btn.clicked.connect(self.reroll)
        self.save_btn = QPushButton("저장…")
        self.save_btn.clicked.connect(self.save)
        for b in (self.convert_btn, self.reroll_btn, self.save_btn):
            panel_lay.addWidget(b)
        self.reroll_btn.setEnabled(False)
        self.save_btn.setEnabled(False)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        panel_lay.addWidget(self.progress)
        self.status = QLabel("")
        panel_lay.addWidget(self.status)

        # ----- right column: preview
        right = QVBoxLayout()
        outer.addLayout(right, 1)
        self.preview = PreviewView()
        right.addWidget(self.preview, 1)
        nav = QHBoxLayout()
        self.prev_btn = QPushButton("◀ 이전 장")
        self.next_btn = QPushButton("다음 장 ▶")
        self.page_label = QLabel("")
        self.prev_btn.clicked.connect(lambda: self.show_page(self.page_index - 1))
        self.next_btn.clicked.connect(lambda: self.show_page(self.page_index + 1))
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.page_label, 1)
        # zoom controls (Ctrl+휠로도 확대/축소, 더블클릭 = 맞춤/100% 토글)
        self.zoom_out_btn = QPushButton("－")
        self.zoom_in_btn = QPushButton("＋")
        self.fit_btn = QPushButton("맞춤")
        self.full_btn = QPushButton("100%")
        self.zoom_label = QLabel("")
        for b in (self.zoom_out_btn, self.zoom_in_btn, self.fit_btn, self.full_btn):
            b.setMaximumWidth(56)
        # as narrow as each label allows (the style's default minimum is far
        # wider), so a half-screen window still fits the whole row
        for b in (self.prev_btn, self.next_btn, self.zoom_out_btn,
                  self.zoom_in_btn, self.fit_btn, self.full_btn):
            b.setMinimumWidth(min(b.maximumWidth(),
                                  b.fontMetrics().horizontalAdvance(b.text()) + 18))
        self.zoom_out_btn.clicked.connect(lambda: self.preview.zoom_by(0.8))
        self.zoom_in_btn.clicked.connect(lambda: self.preview.zoom_by(1.25))
        self.fit_btn.clicked.connect(self.preview.zoom_fit)
        self.full_btn.clicked.connect(self.preview.zoom_actual)
        self.preview.zoom_changed.connect(
            lambda z: self.zoom_label.setText(f"{z * 100:.0f}%"))
        nav.addWidget(self.zoom_out_btn)
        nav.addWidget(self.zoom_label)
        nav.addWidget(self.zoom_in_btn)
        nav.addWidget(self.fit_btn)
        nav.addWidget(self.full_btn)
        nav.addWidget(self.next_btn)
        self.page_label.setAlignment(Qt.AlignCenter)
        right.addLayout(nav)
        self._update_nav()

        # Whatever the user was last using, or the shipped defaults on a fresh
        # install. Last: every widget must exist before it is filled in.
        self.settings = Settings()
        self.apply_advanced(self.settings.options)
        self.open_dir_pick.edit.setText(self.settings.open_dir or "")
        self.save_dir_pick.edit.setText(self.settings.save_dir or "")
        self._refresh_presets()

    # ----- input handling
    def open_dir(self) -> str:
        """Folder the 파일 선택 dialog starts in. Handed to the drop zone as a
        callable, so a folder just typed into 기본 불러오기 폴더 applies at
        once, with no second copy of the value to keep in sync."""
        folder = resolve_open_dir(self.open_dir_pick.edit.text().strip(),
                                  self.settings.last_open_dir)
        return str(folder) if folder is not None else ""

    def set_input(self, path: Path):
        try:
            mode = runner.detect_mode(path)
        except ValueError:
            QMessageBox.warning(
                self, "지원하지 않는 파일",
                f"{path.name} — .docx 문서나 .txt 수식 목록만 넣을 수 있어요.")
            return
        self.input_path = path
        # Dropped files count too: wherever the document came from is where
        # the next one is likely to be.
        if path.parent.is_dir():
            self.settings.last_open_dir = str(path.parent)
            self.settings.save()
        self.drop.set_file(path)
        is_docx = mode == "docx-text"
        self.mode_text.setEnabled(is_docx)
        self.mode_math.setEnabled(True)
        if is_docx:
            self.mode_text.setChecked(True)
        else:
            self.mode_math.setChecked(True)
            self.mode_text.setEnabled(False)
        self.status.setText("")

    # ----- 고급 옵션 as data: remembered between runs, named as presets
    def _advanced_widgets(self) -> dict:
        return {
            "style_path": self.style_pick.edit,
            "line_height": self.line_height,
            "base_size": self.base_size,
            "math_gap": self.math_gap,
            "word_drift": self.word_drift,
            "line_rise": self.line_rise,
            "step_jitter": self.step_jitter,
            "margin_drift": self.margin_drift,
            "word_tilt": self.word_tilt,
            "paper_pdf": self.paper_pick.edit,
            "paper_fit": self.paper_fit,
            "snap": self.snap,
            "rule_spacing": self.rule_spacing,
            "rule_offset": self.rule_offset,
            "rule_margin": self.rule_margin,
            "mirror_word_pages": self.word_pages,
            "dpi": self.dpi,
            "effects": self.effects,
            "raw_pen": self.raw_pen,
            "store": self.store_pick.edit,
        }

    def _set_one(self, key: str, value) -> None:
        w = self._advanced_widgets()[key]
        if isinstance(w, QLineEdit):
            w.setText(str(value))
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, QComboBox):
            w.setCurrentText(str(value))
        else:
            w.setValue(value)

    def collect_advanced(self) -> dict:
        """Every 고급 옵션 as plain JSON-able values."""
        out = {}
        for key, w in self._advanced_widgets().items():
            if isinstance(w, QLineEdit):
                out[key] = w.text().strip()
            elif isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QComboBox):
                out[key] = w.currentText()
            else:
                out[key] = w.value()
        return out

    def apply_advanced(self, values: dict) -> None:
        """Put `values` into the controls. A key that is missing, of the wrong
        type or out of range falls back to its default — a settings file from
        an older version, or edited by hand, must not break the window."""
        for key, default in ADVANCED_DEFAULTS.items():
            value = values.get(key, default)
            try:
                if isinstance(default, bool):
                    value = bool(value)
                elif isinstance(default, (int, float)) and not isinstance(value, bool):
                    value = type(default)(value)
                elif isinstance(default, str):
                    value = str(value)
                else:
                    raise TypeError(default)
                w = self._advanced_widgets()[key]
                if isinstance(w, QComboBox) and w.findText(value) < 0:
                    raise ValueError(value)
                self._set_one(key, value)
            except (TypeError, ValueError):
                self._set_one(key, default)

    def reset_advanced(self) -> None:
        """Put every 고급 옵션 control back to its shipped default. The 기본
        저장 폴더 is a preference, not a style knob, so it is left alone."""
        self.apply_advanced(ADVANCED_DEFAULTS)

    # ----- presets
    def preset_names(self) -> list[str]:
        return sorted(self.settings.presets)

    def save_preset(self, name: str) -> None:
        self.settings.put_preset(name, self.collect_advanced())
        self.settings.save()
        self._refresh_presets(select=name)

    def apply_preset(self, name: str) -> None:
        values = self.settings.presets.get(name)
        if values is not None:
            self.apply_advanced(values)

    def delete_preset(self, name: str) -> None:
        self.settings.drop_preset(name)
        self.settings.save()
        self._refresh_presets()

    def _refresh_presets(self, select: str | None = None) -> None:
        names = self.preset_names()
        self.preset_box.clear()
        self.preset_box.addItem("(설정 모음 고르기…)")
        self.preset_box.addItems(names)
        if select in names:
            self.preset_box.setCurrentIndex(names.index(select) + 1)

    def _preset_chosen(self, index: int) -> None:
        if index > 0:
            self.apply_preset(self.preset_box.itemText(index))

    def _preset_save_clicked(self) -> None:
        current = (self.preset_box.currentText()
                   if self.preset_box.currentIndex() > 0 else "")
        name, ok = QInputDialog.getText(self, "설정 모음 저장", "이름", text=current)
        name = name.strip() if ok else ""
        if not name:
            return
        if name in self.preset_names() and QMessageBox.question(
                self, "덮어쓰기", f"'{name}'을(를) 덮어쓸까요?") != QMessageBox.Yes:
            return
        self.save_preset(name)

    def _preset_delete_clicked(self) -> None:
        index = self.preset_box.currentIndex()
        if index > 0:
            self.delete_preset(self.preset_box.itemText(index))

    # ----- persistence
    def closeEvent(self, event):
        self.settings.options = self.collect_advanced()
        self.settings.open_dir = self.open_dir_pick.edit.text().strip()
        self.settings.save_dir = self.save_dir_pick.edit.text().strip()
        self.settings.save()
        super().closeEvent(event)

    def current_mode(self) -> str:
        if self.input_path.suffix.lower() == ".docx":
            return "docx-text" if self.mode_text.isChecked() else "docx-math"
        return "math-set"

    def build_config(self) -> runner.JobConfig:
        # 고급 옵션의 직접 지정 폴더가 우선, 아니면 손글씨 드롭다운
        store = self.store_pick.path()
        if store is None and self.hand_stores:
            store = self.hand_stores[self.hand_store.currentIndex()]
        return runner.JobConfig(
            input=self.input_path,
            mode=self.current_mode(),
            seed=self.seed.value(),
            store=store,
            style_path=self.style_pick.path(),
            paper_pdf=self.paper_pick.path(),
            paper_fit=self.paper_fit.currentText(),
            snap_lines=self.snap.isChecked(),
            rule_spacing=_auto_value(self.rule_spacing),
            rule_offset=_auto_value(self.rule_offset),
            rule_margin_x=_auto_value(self.rule_margin),
            dpi=self.dpi.value(),
            effects=self.effects.isChecked(),
            line_height=_auto_value(self.line_height),
            base_size=_auto_value(self.base_size),
            display_math_gap=self.math_gap.value(),
            word_drift=self.word_drift.value(),
            line_rise=self.line_rise.value(),
            line_step_jitter=self.step_jitter.value() / 100.0,
            margin_drift=self.margin_drift.value(),
            word_tilt=self.word_tilt.value(),
            word_pages=self.word_pages.isChecked(),
            raw_pen=self.raw_pen.isChecked(),
        )

    # ----- actions
    def convert(self):
        if not self.input_path:
            QMessageBox.information(self, "파일 없음", "먼저 파일을 넣어 주세요.")
            return
        self._set_busy(True)
        self.worker = ConvertWorker(self.build_config())
        self.worker.stage.connect(
            lambda s: self.status.setText(STAGE_TEXT.get(s, s)))
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def reroll(self):
        self.seed.setValue(self.seed.value() + 1)
        self.convert()

    def save(self):
        if not self.pages:
            return
        suggested = str(self.input_path.with_suffix("").name) + "_손글씨"
        # Qt resolves a bare file name against the PROCESS's working directory,
        # which for the frozen exe is the app folder — the user asked not to be
        # dropped there. Always hand it a folder.
        folder = resolve_save_dir(self.save_dir_pick.edit.text().strip(),
                                  self.settings.last_save_dir, self.input_path)
        if folder is not None:
            suggested = str(folder / suggested)
        path, chosen = QFileDialog.getSaveFileName(
            self, "저장", suggested, "PDF (*.pdf);;PNG (*.png)")
        if not path:
            return
        out = Path(path)
        if not out.suffix:
            out = out.with_suffix(".pdf" if "pdf" in chosen.lower() else ".png")
        try:
            written = runner.save(self.pages, out)
        except Exception as e:
            QMessageBox.critical(self, "저장 실패", str(e))
            return
        self.settings.last_save_dir = str(written[0].parent)
        self.settings.save()
        self.status.setText(f"저장 완료: {written[0].parent}")
        _reveal_in_file_browser(written[0])

    # ----- worker results
    def _on_done(self, pages):
        self._set_busy(False)
        self.pages = pages
        self.status.setText(f"완료 — {len(pages)}장")
        self.reroll_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.preview.zoom_fit()  # a fresh result starts fitted to the window
        self.show_page(0)

    def _on_failed(self, message: str):
        self._set_busy(False)
        self.status.setText("실패")
        QMessageBox.critical(self, "변환 실패", message)

    def _set_busy(self, busy: bool):
        self.progress.setVisible(busy)
        for b in (self.convert_btn, self.reroll_btn, self.save_btn):
            b.setEnabled(not busy)
        if busy:
            self.status.setText("준비 중…")
        elif not self.pages:
            self.reroll_btn.setEnabled(False)
            self.save_btn.setEnabled(False)

    # ----- preview
    def show_page(self, index: int):
        if not self.pages:
            return
        self.page_index = max(0, min(index, len(self.pages) - 1))
        # full resolution goes into the view; zooming is repaint-only
        self.preview.set_page(self.pages[self.page_index])
        self._update_nav()

    def _update_nav(self):
        n = len(self.pages)
        self.page_label.setText(f"{self.page_index + 1} / {n}" if n else "-")
        self.prev_btn.setEnabled(n > 1 and self.page_index > 0)
        self.next_btn.setEnabled(n > 1 and self.page_index < n - 1)

def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
