"""PyInstaller entry point for the handwriting converter GUI.

--selfcheck runs headless (offscreen Qt) inside the frozen bundle and
exercises what packaging can break: resource resolution, the text pipeline
end-to-end on a generated one-line docx, the math chain when node is
resolvable, and window construction. Exit 0 = bundle sane.

The exe is windowed (no console), so an escaping exception would pop the
PyInstaller error dialog on the user's screen. Selfcheck therefore never
raises: everything goes to selfcheck.log next to the exe, plus stdout when
one exists (Linux validation runs).
"""

import os
import sys
import tempfile
import traceback
from pathlib import Path

# Korean Windows defaults to cp949; chain scripts print math unicode. Never
# let a progress print be the thing that kills a render.
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _selfcheck_body(note) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from gui import resources, runner

    store = resources.default_store()
    assert store.exists(), f"glyph store missing: {store}"
    assert (resources.SPIKE_DIR / "tex2svg.js").exists(), "spike chain missing"

    with tempfile.TemporaryDirectory() as td:
        import docx
        doc = docx.Document()
        doc.add_paragraph("Selfcheck page one two three.")
        sample = Path(td) / "selfcheck.docx"
        doc.save(sample)
        pages = runner.run_job(runner.JobConfig(
            input=sample, mode="docx-text", dpi=150))
        assert pages and pages[0].mode == "RGB", "text pipeline failed"
        note(f"selfcheck: text pipeline OK ({pages[0].size})")

        try:
            resources.find_node()
        except resources.ToolMissingError:
            note("selfcheck: node not bundled/found — math chain SKIPPED")
        else:
            eqs = Path(td) / "eqs.txt"
            eqs.write_text("x^2 + 1\n")
            sheets = runner.run_job(runner.JobConfig(
                input=eqs, mode="math-set"))
            assert sheets, "math chain failed"
            note("selfcheck: math chain OK")

            # equations INSIDE a document (text + OMML on one page)
            from docx.oxml import parse_xml
            omml = ('<m:oMath xmlns:m="http://schemas.openxmlformats.org/'
                    'officeDocument/2006/math"><m:f><m:num><m:r><m:t>a</m:t>'
                    '</m:r></m:num><m:den><m:r><m:t>b</m:t></m:r></m:den>'
                    '</m:f></m:oMath>')
            doc = docx.Document()
            para = doc.add_paragraph("Fraction ")
            para._p.append(parse_xml(omml))
            para.add_run(" inline.")
            mixed = Path(td) / "selfcheck_math.docx"
            doc.save(mixed)
            pages = runner.run_job(runner.JobConfig(
                input=mixed, mode="docx-text", dpi=150))
            assert pages, "document maths failed"
            note("selfcheck: document maths OK")

    from PySide6.QtWidgets import QApplication

    from gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    assert win.isVisible()
    note("selfcheck: window OK")
    note("selfcheck: PASS")


def selfcheck() -> int:
    log_path = Path(sys.executable).resolve().parent / "selfcheck.log"
    with open(log_path, "w", encoding="utf-8") as log:
        def note(msg: str) -> None:
            print(msg, file=log, flush=True)
            if sys.stdout:
                print(msg, flush=True)
        try:
            _selfcheck_body(note)
        except Exception:
            note("selfcheck: FAIL")
            traceback.print_exc(file=log)
            if sys.stderr:
                traceback.print_exc()
            return 1
    return 0


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        sys.exit(selfcheck())
    from gui.app import main
    sys.exit(main())
