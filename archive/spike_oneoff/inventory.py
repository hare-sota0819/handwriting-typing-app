"""Symbol inventory + final proposed collection charset (STOP 0, rev 2).

Rev 2 incorporates the user's 2026-07-31 decisions:
  - ALIAS layer (general mechanism for the substitution table): codepoints
    that map onto an already-collected glyph instead of being collected.
    Greek capitals visually identical to Latin (Α=A .. Χ=X, 14), ο=o,
    ∘=° (one degree glyph, two codepoints), ≃=≈, ⋅=·.
  - Greek capitals collected: only the 10 with unique shapes (Γ Δ Θ Λ Ξ Π
    Σ Φ Ψ Ω).
  - Additions: ≡ ′ ∴ ∵ ∮ ∠ (recommended), ⟨ ⟩ ∈ (optional).

Sources scanned:
  1. every OMML equation in every .docx under spike/input/ (m:t text runs)
     — now includes 2 REAL lab reports (126 equations)
  2. codepoints MathJax emitted for the test equations (base_char)

Writes spike/inventory.md.

Run: .venv/bin/python spike/inventory.py
"""

import json
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

SPIKE = Path(__file__).resolve().parent
INPUT = SPIKE / "input"
PLACEMENTS = SPIKE / "out" / "placements"
CHARSET_FILE = SPIKE.parent / "template" / "charset_default.txt"

# ------------------------------------------------------------ user decisions

# alias -> glyph actually collected/existing (substitution-table layer)
ALIASES = {
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    "ο": "o",
    "∘": "°",   # one degree glyph, two codepoints (U+2218 comes from MathJax \circ)
    "≃": "≈",
    "⋅": "·",   # U+22C5 dot operator -> middle dot glyph
}

GREEK_CAPS_UNIQUE = "ΓΔΘΛΞΠΣΦΨΩ"
GREEK_LOWER_COLLECT = "αβγδεζηθικλμνξπρστυφχψω"  # ο excluded (aliased)
MATH_CORE = "∫∑∏√±∓×·÷≤≥≠≈∝→⇒∞∂∇ℏ°"
ADD_RECOMMENDED = "≡′∴∵∮∠"
ADD_OPTIONAL = "⟨⟩∈"

COLLECT = (GREEK_CAPS_UNIQUE + GREEK_LOWER_COLLECT + MATH_CORE
           + ADD_RECOMMENDED)

OPERATORS = set("+−-*/√±∓×·÷∫∮∑∏∂∇′")
RELATIONS = set("=<>≤≥≠≈≃∝→⇒≡∈")
DELIMS = set("()[]{}|⟨⟩")


def category(ch):
    o = ord(ch)
    if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF:
        return "hangul"
    if ch.isascii() and ch.isalpha():
        return "latin"
    if ch.isdigit():
        return "digit"
    if "GREEK" in unicodedata.name(ch, ""):
        return "greek"
    if ch in OPERATORS:
        return "operator"
    if ch in RELATIONS:
        return "relation"
    if ch in DELIMS:
        return "delimiter"
    return "other"


def existing_charset():
    chars = set()
    for line in CHARSET_FILE.read_text().splitlines():
        s = line.strip()
        if not s or (s.startswith("#") and s != "#"):
            continue
        chars.add(s)
    return chars


def scan_docx():
    counts = Counter()
    per_doc = {}
    for docx in sorted(INPUT.glob("*.docx")):
        xml = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8")
        n = 0
        for omath in re.findall(r"<m:oMath[ >].*?</m:oMath>", xml, flags=re.S):
            n += 1
            for t in re.findall(r"<m:t[^>]*>(.*?)</m:t>", omath, flags=re.S):
                for ch in t:
                    if not ch.isspace():
                        counts[ch] += 1
        per_doc[docx.name] = n
    return counts, per_doc


def scan_mathjax():
    chars = set()
    for f in sorted(PLACEMENTS.glob("*.json")):
        for el in json.loads(f.read_text())["elements"]:
            if el["kind"] != "rule":
                chars.add(el["base_char"])
    return chars


def main():
    doc_counts, per_doc = scan_docx()
    mj_chars = scan_mathjax()
    store = existing_charset()

    hangul = {c: n for c, n in doc_counts.items() if category(c) == "hangul"}
    covered = set(COLLECT) | set(ALIASES) | store
    seen_uncovered = {
        c: n for c, n in doc_counts.items()
        if c not in covered and category(c) != "hangul"
    }

    L = ["# Phase 2 symbol inventory (STOP 0, rev 2 — real documents + "
         "user charset decisions)", ""]
    L.append("## Documents scanned")
    L.append("")
    for name, n in per_doc.items():
        L.append(f"- `{name}`: {n} OMML equations")
    L.append("")

    L.append("## Inventory — every char seen in OMML input")
    L.append("")
    L.append("| codepoint | char | count | category |")
    L.append("|---|---|---|---|")
    for ch, n in sorted(doc_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        L.append(f"| U+{ord(ch):04X} | `{ch}` | {n} | {category(ch)} |")
    L.append("")

    L.append("## Alias layer (decided 2026-07-31 — general substitution-table "
             "mechanism)")
    L.append("")
    L.append("These codepoints are NOT collected; the substitution table maps "
             "them onto an existing/collected glyph:")
    L.append("")
    L.append("| alias | → glyph | note |")
    L.append("|---|---|---|")
    notes = {"∘": "MathJax emits U+2218 for ^\\circ; ° is what Word stores",
             "⋅": "U+22C5 dot operator, seen in real docs",
             "≃": "asymptotically-equal folds into ≈",
             "ο": "omicron = latin o in handwriting"}
    for a, g in ALIASES.items():
        L.append(f"| U+{ord(a):04X} `{a}` | `{g}` | "
                 f"{notes.get(a, 'visually identical in handwriting')} |")
    L.append("")

    L.append("## Final proposed collection charset")
    L.append("")
    groups = [
        ("Greek capitals (unique shapes only)", GREEK_CAPS_UNIQUE, "confirmed"),
        ("Greek lowercase (ο aliased away)", GREEK_LOWER_COLLECT, "confirmed"),
        ("Math core (standard physics/EE set)", MATH_CORE, "confirmed"),
        ("Additions (user 2026-07-31)", ADD_RECOMMENDED, "confirmed"),
        ("Optional (user to include/drop)", ADD_OPTIONAL, "OPTIONAL"),
    ]
    L.append("| group | chars | n | status |")
    L.append("|---|---|---|---|")
    for name, chars, status in groups:
        L.append(f"| {name} | {' '.join(chars)} | {len(chars)} | {status} |")
    total = sum(len(c) for _, c, s in groups if s == "confirmed")
    L.append("")
    L.append(f"**Total to collect: {total} confirmed** "
             f"(+{len(ADD_OPTIONAL)} optional). Seen-in-real-documents marks: "
             + " ".join(f"`{c}`" for c in COLLECT if c in doc_counts)
             + " — everything else is standard-set/MathJax-emitted only.")
    L.append("")

    L.append("## Real-document findings outside the charset")
    L.append("")
    if hangul:
        top = sorted(hangul.items(), key=lambda kv: -kv[1])
        L.append(f"- **HANGUL inside equations** ({sum(hangul.values())} chars, "
                 f"{len(hangul)} distinct: "
                 + " ".join(f"`{c}`×{n}" for c, n in top)
                 + ") — e.g. subscripts like I_측정 (measured), I_이론 "
                   "(theory). The handwriting store has NO hangul; needs a "
                   "user decision (open question).")
    if seen_uncovered:
        L.append("- Seen in documents, NOT in charset/aliases/store: "
                 + " ".join(f"`{c}`×{n} (U+{ord(c):04X})"
                            for c, n in sorted(seen_uncovered.items(),
                                               key=lambda kv: -kv[1])))
    L.append("")

    (SPIKE / "inventory.md").write_text("\n".join(L))
    print(f"docs: {sum(per_doc.values())} equations, "
          f"{len(doc_counts)} distinct chars ({len(hangul)} hangul); "
          f"collect {total} confirmed; uncovered non-hangul: "
          f"{sorted(seen_uncovered)}")


if __name__ == "__main__":
    main()
