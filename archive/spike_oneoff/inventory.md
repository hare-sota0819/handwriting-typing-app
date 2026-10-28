# Phase 2 symbol inventory (STOP 0, rev 2 — real documents + user charset decisions)

## Documents scanned

- `test_equations.docx`: 8 OMML equations
- `실험6 결과 보고서_2026101227 최찬호.docx`: 41 OMML equations
- `실험9 결과 보고서_2026101227 최찬호.docx`: 45 OMML equations

## Inventory — every char seen in OMML input

| codepoint | char | count | category |
|---|---|---|---|
| U+0032 | `2` | 77 | digit |
| U+002E | `.` | 62 | other |
| U+0033 | `3` | 55 | digit |
| U+0034 | `4` | 54 | digit |
| U+0030 | `0` | 53 | digit |
| U+0031 | `1` | 53 | digit |
| U+003D | `=` | 50 | relation |
| U+006D | `m` | 45 | latin |
| U+0049 | `I` | 28 | latin |
| U+002D | `-` | 26 | operator |
| U+00D7 | `×` | 23 | operator |
| U+0036 | `6` | 22 | digit |
| U+0063 | `c` | 21 | latin |
| U+004C | `L` | 20 | latin |
| U+0066 | `f` | 16 | latin |
| U+0035 | `5` | 15 | digit |
| U+006E | `n` | 15 | latin |
| U+0037 | `7` | 14 | digit |
| U+0038 | `8` | 14 | digit |
| U+0067 | `g` | 14 | latin |
| U+002F | `/` | 13 | operator |
| U+0073 | `s` | 13 | latin |
| U+002C | `,` | 12 | other |
| U+0072 | `r` | 12 | latin |
| U+0061 | `a` | 11 | latin |
| U+03C9 | `ω` | 11 | greek |
| U+0064 | `d` | 10 | latin |
| U+0069 | `i` | 9 | latin |
| U+03BB | `λ` | 9 | greek |
| U+006B | `k` | 8 | latin |
| U+C815 | `정` | 8 | hangul |
| U+CE21 | `측` | 8 | hangul |
| U+0046 | `F` | 7 | latin |
| U+0039 | `9` | 6 | digit |
| U+03BC | `μ` | 6 | greek |
| U+0028 | `(` | 5 | delimiter |
| U+0029 | `)` | 5 | delimiter |
| U+002B | `+` | 5 | operator |
| U+004D | `M` | 5 | latin |
| U+0052 | `R` | 5 | latin |
| U+0074 | `t` | 5 | latin |
| U+0076 | `v` | 5 | latin |
| U+22C5 | `⋅` | 5 | other |
| U+0041 | `A` | 4 | latin |
| U+0054 | `T` | 4 | latin |
| U+0065 | `e` | 4 | latin |
| U+03B8 | `θ` | 4 | greek |
| U+ADE0 | `균` | 4 | hangul |
| U+D3C9 | `평` | 4 | hangul |
| U+0025 | `%` | 3 | other |
| U+006F | `o` | 3 | latin |
| U+B860 | `론` | 3 | hangul |
| U+C774 | `이` | 3 | hangul |
| U+0058 | `X` | 2 | latin |
| U+0075 | `u` | 2 | latin |
| U+007A | `z` | 2 | latin |
| U+03C0 | `π` | 2 | greek |
| U+0042 | `B` | 1 | latin |
| U+0045 | `E` | 1 | latin |
| U+0048 | `H` | 1 | latin |
| U+004E | `N` | 1 | latin |
| U+0078 | `x` | 1 | latin |
| U+00B0 | `°` | 1 | other |
| U+03B1 | `α` | 1 | greek |
| U+03C4 | `τ` | 1 | greek |
| U+03C6 | `φ` | 1 | greek |
| U+2264 | `≤` | 1 | relation |
| U+22EF | `⋯` | 1 | other |

## Alias layer (decided 2026-07-31 — general substitution-table mechanism)

These codepoints are NOT collected; the substitution table maps them onto an existing/collected glyph:

| alias | → glyph | note |
|---|---|---|
| U+0391 `Α` | `A` | visually identical in handwriting |
| U+0392 `Β` | `B` | visually identical in handwriting |
| U+0395 `Ε` | `E` | visually identical in handwriting |
| U+0396 `Ζ` | `Z` | visually identical in handwriting |
| U+0397 `Η` | `H` | visually identical in handwriting |
| U+0399 `Ι` | `I` | visually identical in handwriting |
| U+039A `Κ` | `K` | visually identical in handwriting |
| U+039C `Μ` | `M` | visually identical in handwriting |
| U+039D `Ν` | `N` | visually identical in handwriting |
| U+039F `Ο` | `O` | visually identical in handwriting |
| U+03A1 `Ρ` | `P` | visually identical in handwriting |
| U+03A4 `Τ` | `T` | visually identical in handwriting |
| U+03A5 `Υ` | `Y` | visually identical in handwriting |
| U+03A7 `Χ` | `X` | visually identical in handwriting |
| U+03BF `ο` | `o` | omicron = latin o in handwriting |
| U+2218 `∘` | `°` | MathJax emits U+2218 for ^\circ; ° is what Word stores |
| U+2243 `≃` | `≈` | asymptotically-equal folds into ≈ |
| U+22C5 `⋅` | `·` | U+22C5 dot operator, seen in real docs |

## Final proposed collection charset

| group | chars | n | status |
|---|---|---|---|
| Greek capitals (unique shapes only) | Γ Δ Θ Λ Ξ Π Σ Φ Ψ Ω | 10 | confirmed |
| Greek lowercase (ο aliased away) | α β γ δ ε ζ η θ ι κ λ μ ν ξ π ρ σ τ υ φ χ ψ ω | 23 | confirmed |
| Math core (standard physics/EE set) | ∫ ∑ ∏ √ ± ∓ × · ÷ ≤ ≥ ≠ ≈ ∝ → ⇒ ∞ ∂ ∇ ℏ ° | 21 | confirmed |
| Additions (user 2026-07-31) | ≡ ′ ∴ ∵ ∮ ∠ | 6 | confirmed |
| Optional (user to include/drop) | ⟨ ⟩ ∈ | 3 | OPTIONAL |

**Total to collect: 60 confirmed** (+3 optional). Seen-in-real-documents marks: `α` `θ` `λ` `μ` `π` `τ` `φ` `ω` `×` `≤` `°` — everything else is standard-set/MathJax-emitted only.

## Real-document findings outside the charset

- **HANGUL inside equations** (30 chars, 6 distinct: `측`×8 `정`×8 `평`×4 `균`×4 `이`×3 `론`×3) — e.g. subscripts like I_측정 (measured), I_이론 (theory). The handwriting store has NO hangul; needs a user decision (open question).
- Seen in documents, NOT in charset/aliases/store: `⋯`×1 (U+22EF)
