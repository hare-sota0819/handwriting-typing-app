"""Checkpoint 2 verification: .docx parser → Document Model.

Feeds three sample .docx files (plain / multi-paragraph / one containing Word
equations), dumps the resulting Document Model, and asserts: structure is
right, whitespace is normalized, equations become MathBlock nodes in run
order (inline vs display) with their text kept out of the text runs, and
unsupported characters are kept + logged. Exit 0 = pass.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_samples
from handwriting.document_model import Document, MathBlock
from handwriting.parser import parse_docx

SAMPLES = make_samples.SAMPLES


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def dump(name: str, doc: Document) -> None:
    print(f"--- Document Model: {name} ({len(doc.paragraphs)} paragraphs) ---")
    for i, para in enumerate(doc.paragraphs):
        if not para.runs:
            print(f"  [{i}] (blank line)")
        else:
            for run in para.runs:
                if isinstance(run, MathBlock):
                    print(f"  [{i}] <math #{run.index} "
                          f"{'display' if run.display else 'inline'}>")
                else:
                    print(f"  [{i}] {run.text!r}")


def texts(doc: Document) -> list[str]:
    return ["".join(r.text for r in p.runs if not isinstance(r, MathBlock))
            for p in doc.paragraphs]


def main() -> int:
    failures: list[str] = []
    if not all((SAMPLES / f).exists() for f in ("plain.docx", "multi.docx", "equation.docx")):
        make_samples.main()

    capture = _Capture()
    logging.getLogger("handwriting.parser").addHandler(capture)

    # 1. plain single-paragraph doc
    plain = parse_docx(SAMPLES / "plain.docx")
    dump("plain.docx", plain)
    if texts(plain) != ["Hello handwriting world! This is sample 1, typed on 2026-07-12."]:
        failures.append(f"plain.docx: unexpected content {texts(plain)!r}")

    # 2. multi-paragraph doc: soft break splits, blank line kept, text normalized
    multi = parse_docx(SAMPLES / "multi.docx")
    dump("multi.docx", multi)
    expected_multi = [
        "First paragraph with numbers 123 and (parentheses).",
        "Second paragraph, first line.",
        "Second paragraph, after a soft line break.",
        "",
        'Word-style "smart quotes", an em-dash, a tab here, and café.',
    ]
    if texts(multi) != expected_multi:
        failures.append(f"multi.docx: expected {expected_multi!r}, got {texts(multi)!r}")
    if not any("unsupported characters" in m and "é" in m for m in capture.messages):
        failures.append("multi.docx: no unsupported-character warning for 'é'")

    # 3. doc with equations: MathBlocks in run order, equation text excluded
    equation = parse_docx(SAMPLES / "equation.docx")
    dump("equation.docx", equation)
    blocks = [(i, r) for i, p in enumerate(equation.paragraphs)
              for r in p.runs if isinstance(r, MathBlock)]
    if [b.index for _, b in blocks] != [0, 1]:
        failures.append(f"equation.docx: expected MathBlocks #0,#1 in order, "
                        f"got {[b.index for _, b in blocks]}")
    else:
        (pi, inline), (pd, display) = blocks
        para_inline = equation.paragraphs[pi].runs
        if inline.display or para_inline[0].text != "Inline equation here:" \
                or para_inline[-1] is not inline:
            failures.append("equation.docx: inline equation should follow its "
                            "text run in the same paragraph, inline")
        if not display.display or len(equation.paragraphs[pd].runs) != 1:
            failures.append("equation.docx: lone equation paragraph should be "
                            "one display MathBlock")
    joined = " ".join(texts(equation))
    if "E=mc" in joined or "sqrt" in joined:
        failures.append("equation.docx: equation content leaked into the Document Model")
    if "Text before the equation." not in texts(equation):
        failures.append("equation.docx: surrounding text missing")

    print()
    if failures:
        print(f"FAIL ({len(failures)} problems):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: checkpoint 2 checks all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
