"""Build spike/input/test_equations.docx with REAL Word OMML structures.

The repo had no .docx with structured OMML (samples/equation.docx holds only
flat <m:r> text runs), so this constructs one by writing document.xml by hand
— fractions (m:f), radicals (m:rad), sub/superscripts (m:sSub/m:sSup),
delimiters (m:d) and an n-ary integral (m:nary), i.e. the same element tree
Word itself emits. Throwaway spike tool.

Run: .venv/bin/python spike/make_test_docx.py
"""

import shutil
import zipfile
from pathlib import Path

SPIKE = Path(__file__).resolve().parent
TEMPLATE = SPIKE.parent / "samples" / "equation.docx"
OUT = SPIKE / "input" / "test_equations.docx"


def r(t: str) -> str:
    """A math run."""
    return f"<m:r><m:t>{t}</m:t></m:r>"


def frac(num: str, den: str) -> str:
    return f"<m:f><m:num>{num}</m:num><m:den>{den}</m:den></m:f>"


def sqrt(e: str) -> str:
    return (
        '<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr>'
        f"<m:deg/><m:e>{e}</m:e></m:rad>"
    )


def sup(base: str, s: str) -> str:
    return f"<m:sSup><m:e>{base}</m:e><m:sup>{s}</m:sup></m:sSup>"


def sub(base: str, s: str) -> str:
    return f"<m:sSub><m:e>{base}</m:e><m:sub>{s}</m:sub></m:sSub>"


def paren(e: str) -> str:
    return f"<m:d><m:e>{e}</m:e></m:d>"


def integral(lo: str, hi: str, e: str) -> str:
    return (
        '<m:nary><m:naryPr><m:chr m:val="∫"/><m:limLoc m:val="subSup"/>'
        "</m:naryPr>"
        f"<m:sub>{lo}</m:sub><m:sup>{hi}</m:sup><m:e>{e}</m:e></m:nary>"
    )


# The five required test equations + two extra probing known suspects
# (stretchy parens, integral with limits).
EQUATIONS = [
    # 1. T = 2π√(I/(Mgd))  — nested fraction inside radical
    r("T=2π") + sqrt(frac(r("I"), r("Mgd"))),
    # 2. α_z = d²θ/dt²  — Greek, subscript, second derivative
    sub(r("α"), r("z")) + r("=")
    + frac(sup(r("d"), r("2")) + r("θ"), r("d") + sup(r("t"), r("2"))),
    # 3. k = 4π²I/T²  — superscripts in fraction
    r("k=") + frac(r("4") + sup(r("π"), r("2")) + r("I"), sup(r("T"), r("2"))),
    # 4. I = (1/12)ML² + Md²  — inline-size fraction + terms
    r("I=") + frac(r("1"), r("12")) + r("M") + sup(r("L"), r("2"))
    + r("+M") + sup(r("d"), r("2")),
    # 5a. ω = √(mgd/I)
    r("ω=") + sqrt(frac(r("mgd"), r("I"))),
    # 5b. θ ≤ 5°  (inline; relation + degree symbol)
    r("θ≤5°"),
    # 6. extra: stretchy delimiters  θ(t) = θ₀ cos(ωt)
    sub(r("θ"), r("0")) + r("=") + sub(r("θ"), r("max"))
    + r("cos") + paren(r("ωt+φ")),
    # 7. extra: integral with limits  E = ∫₀^T τ ω dt
    r("E=") + integral(r("0"), r("T"), r("τω") + r("dt")),
]

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
M_NS = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'


def text_p(t: str) -> str:
    return f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>"


def math_p(omml: str) -> str:
    return f"<w:p><m:oMathPara><m:oMath>{omml}</m:oMath></m:oMathPara></w:p>"


def main() -> None:
    body = [text_p("Prelab test equations follow.")]
    for i, eq in enumerate(EQUATIONS, 1):
        body.append(text_p(f"Equation {i}:"))
        body.append(math_p(eq))
    body.append(text_p("End of test document."))
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {W_NS} {M_NS}><w:body>"
        + "".join(body)
        + "</w:body></w:document>"
    )
    OUT.parent.mkdir(exist_ok=True)
    shutil.copy(TEMPLATE, OUT)
    # rewrite word/document.xml inside the copied docx
    tmp = OUT.with_suffix(".tmp.docx")
    with zipfile.ZipFile(OUT) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = doc.encode("utf-8")
            zout.writestr(item, data)
    tmp.replace(OUT)
    print(f"wrote {OUT} with {len(EQUATIONS)} equations")


if __name__ == "__main__":
    main()
