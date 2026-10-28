# Phase 2 — STOP 0 report: toolchain spike + symbol inventory

Date: 2026-07-30. Everything in this spike lives under `spike/` (scripts,
inputs, outputs); nothing in the existing pipeline was touched.

## 1. Toolchain verdict: **GO**

The coordinate-stealing architecture works end-to-end on structured OMML:

```
.docx OMML --pandoc--> LaTeX --MathJax tex2svg--> SVG --parse_svg.py--> placement JSON
```

| stage | tool | version | result |
|---|---|---|---|
| OMML → LaTeX | pandoc (static binary, `spike/tools/`, not committed) | 3.5 | 8/8 structured equations converted perfectly |
| LaTeX → SVG | mathjax-full (npm, `spike/node_modules/`) | 3.2.1 | 8/8 rendered; `fontCache:'local'`, direct liteAdaptor API (`tex2svg.js`) |
| SVG → coordinates | `parse_svg.py` (stdlib only) | — | all transform chains resolved; verified pixel-level (below) |
| runtime | node | v24.18.0 (npm 11.16.0) | — |

**Input documents:** the repo contained NO .docx with structured OMML
(`samples/equation.docx` holds only flat text runs), and no real course
documents were provided. Path taken: **constructed** a test document
(`spike/make_test_docx.py` → `spike/input/test_equations.docx`) with
hand-authored OMML using the same element tree Word emits (`m:f`, `m:rad`,
`m:sSub`/`m:sSup`, `m:d`, `m:nary`) for the 5 required prelab equations plus
2 extra probing known suspects. Real documents remain wanted (open question #1).

**pandoc results (spike/out/pandoc_output.tex):** all 8 equations converted
cleanly, including symbol mapping done for us: `π→\pi`, `α→\alpha`, `≤→\leq`,
`°→{^\circ}`, `∫→\int`, `φ→\varphi`, and even `max→\max`. No failure cases on
structured OMML, so the other converter candidates (dwml, omml2latex) were not
needed — no comparison table required.

**pandoc failure case (known, matters):** *linear-format* OMML — equations
typed as a flat text run and never converted to Word's "Professional" layout —
degrades: `E=mc^2` stored flat becomes `E = mc\hat{}2` (literal `^` → `\hat{}`
garbage). Word GUI equations in Professional format (the normal case) are
structured and fine. The Phase 2 pipeline should detect flat-run-only oMath
and either pass it through as plain text or warn.

## 2. Pixel-level verification (archive/spike_debug_evidence/)

For each equation: left = MathJax's own render, right = the same SVG at 35%
opacity with boxes/labels drawn at OUR computed absolute coordinates (drawn in
root viewBox space — i.e. AFTER resolving the full transform chain, including
the root `scale(1,-1)` y-flip). Red = symbol ink bbox, blue = stretchy glyph,
green = rule, orange crosshair = glyph pen origin.

All 8 pass — every box lands exactly on its symbol:

- `eq1_pendulum.png` — nested fraction inside radical; surd = stretchy S4 glyph (h=3.0 em) + separate overline rect (`sqrt_bar`)
- `eq2_alpha.png` — Greek, subscript, d²θ/dt²; script-size digits at scale 0.707
- `eq3_k.png` — superscripts inside fraction
- `eq4_inertia.png` — inline fraction + terms; `+` and `=` boxed correctly
- `eq5a_omega.png` — radical + fraction
- `eq5b_smallangle.png` — inline (display=false) θ ≤ 5°; `\circ` emitted as U+2218 at scale 0.707
- `eq6_stretchy.png` — θ₀ = θ_max cos(ωt + φ); parens at this height are ordinary font-N glyphs (no stretching needed)
- `eq7_integral.png` — ∫ with limits: single font-LO glyph, limits placed at scale 0.707 (T at y=−1.088, 0 at y=+0.896)

Regenerate: `make_test_docx.py` → pandoc → `tex2svg.js` → `parse_svg.py` →
`make_overlays.py` → screenshot `spike/out/overlay/*.html` (needs a local http
server; `file://` is blocked in playwright-cli).

## 3. Placement JSON schema (deliverable)

One file per equation: `spike/out/placements/<id>.json` (gitignored,
regenerable; full example embedded below).

**Coordinate convention:** units = em (MathJax viewBox units / 1000); x grows
right, y grows DOWN; **y = 0 is the equation's main baseline**. This matches
the renderer's y-down world and the glyph store's baseline anchoring.

Top level:

| field | meaning |
|---|---|
| `id` | equation id |
| `latex` | the LaTeX input MathJax rendered |
| `em_height` | total height of the equation box (em) |
| `ascent` | height above the main baseline (em) |
| `descent` | depth below the main baseline (em) |
| `width` | total width (em) |
| `elements` | placement list, document order |

`elements[]`, `kind: "symbol"` (a glyph to substitute) and `kind: "stretchy"`
(same fields; glyph came from a size-variant font S1–S4, i.e. a stretched/large
form — the substitution phase must scale/synthesize it rather than use a
1:1 handwritten glyph):

| field | meaning |
|---|---|
| `codepoint` | `U+XXXX` of the char MathJax placed |
| `char` | that char (may be a math-alphanumeric variant, e.g. 𝑇 U+1D447) |
| `base_char` | plain char after stripping the math-font mapping (`T`) — the key to look up in the handwriting store |
| `font` | MathJax font: `N` upright, `I` italic, `B` bold, `S1`–`S4` size variants, `LO` large operators |
| `x`, `y` | glyph ORIGIN = pen position on its own baseline (em) |
| `scale` | resolved scale factor (1.0 full size, 0.707 script size, 0.5 scriptscript) |
| `bbox` | `{x, y, w, h}` transformed ink bounding box; `y` = top edge (em) |
| `mml` | enclosing MathML node type (`mi`/`mo`/`mn`…), kept for debugging |

`elements[]`, `kind: "rule"` (a bar to DRAW, not substitute):

| field | meaning |
|---|---|
| `x`, `y`, `w`, `h` | absolute rect (em), `y` = top edge |
| `role` | `frac_bar` / `sqrt_bar` / `underline` / `overline` / `unknown` — from the nearest `data-mml-node` ancestor |

Invisible operators (U+2061 function-application, U+2062 invisible-times, …)
have empty paths and are filtered out during parsing.

Full example (eq1, `T = 2\pi\sqrt{\frac{I}{Mgd}}`, abridged only in that
repeated symbol entries follow the identical shape):

```json
{
 "id": "eq1_pendulum",
 "latex": "T = 2\\pi\\sqrt{\\frac{I}{Mgd}}",
 "em_height": 3.06, "ascent": 1.9093, "descent": 1.1507, "width": 6.6156,
 "elements": [
  {"kind": "symbol", "codepoint": "U+1D447", "char": "𝑇", "base_char": "T",
   "font": "I", "x": 0.0, "y": 0.0, "scale": 1.0, "mml": "mi",
   "bbox": {"x": 0.021, "y": -0.677, "w": 0.683, "h": 0.677}},
  {"kind": "symbol", "codepoint": "U+003D", "char": "=", "base_char": "=",
   "font": "N", "x": 0.9818, "y": 0.0, "scale": 1.0, "mml": "mo",
   "bbox": {"x": 1.0378, "y": -0.367, "w": 0.666, "h": 0.234}},
  {"kind": "symbol", "codepoint": "U+1D43C", "char": "𝐼", "base_char": "I",
   "font": "I", "x": 5.1196, "y": -0.676, "scale": 1.0, "mml": "mi",
   "bbox": {"x": 5.1456, "y": -1.359, "w": 0.478, "h": 0.683}},
  {"kind": "rule", "x": 4.2476, "y": -0.28, "w": 2.248, "h": 0.06,
   "role": "frac_bar"},
  {"kind": "stretchy", "codepoint": "U+221A", "char": "√", "base_char": "√",
   "font": "S4", "x": 3.1076, "y": -0.0993, "scale": 1.0, "mml": "mo",
   "bbox": {"x": 3.2186, "y": -1.8493, "w": 0.909, "h": 3.0}},
  {"kind": "rule", "x": 4.1276, "y": -1.8493, "w": 2.488, "h": 0.06,
   "role": "sqrt_bar"}
 ]
}
```

(The fraction numerator sits at y=−0.676, denominator at +0.686, the surd
spans the full 3 em — exactly what the overlay images confirm visually.)

## 4. Symbol inventory + proposed collection charset

See `spike/inventory.md`. Headline: 31 distinct chars in the (constructed)
input document, 95 proposed collection entries, of which **70 are NOT in the
existing 87-char store**: the full Greek alphabet (48) plus
`± · × ÷ ∂ ∇ ∏ ∑ ∓ √ ∫ → ⇒ ∝ ≈ ≠ ≤ ≥ ° ℏ ∘ ∞` (22).
Latin letters, digits, `+ = ( ) / < >` etc. are already collected.
CAVEAT: frequencies are from the 8 test equations, not real course documents.

## 5. Known limitations (ranked by expected frequency in prelab docs)

1. **° vs ∘ mapping** (very common): the ° typed in Word survives OMML→LaTeX
   as `^\circ`, but MathJax emits U+2218 RING OPERATOR, not U+00B0. The
   substitution table must map U+2218 (superscript position) onto the user's
   handwritten ° — or we collect one glyph and alias both codepoints.
2. **Radical geometry** (very common): MathJax decomposes √ into a size-variant
   hook glyph (S1–S4 by height) + a separate overline `rect`. A handwritten √
   is one stroke; substitution must scale the hook vertically to `bbox.h` and
   draw/join the bar to `sqrt_bar` — needs its own design at the next STOP.
3. **Stretchy delimiters** (common): small parens are ordinary glyphs (verified
   eq6), tall ones become S1–S4 variants — scalable the same way as the radical
   hook. NOT yet exercised: MathJax's multi-part assemblies (very tall
   delimiters built from top/mid/bottom segments); none appeared at these
   sizes. Handle when seen.
4. **Script-size glyphs** (very common, already working): sub/superscripts
   arrive at scale 0.707 (0.5 for second order). The renderer just scales the
   handwritten glyph — same mechanism as today's size jitter.
5. **Function names / upright vs italic** (common): `cos`, `max` emit upright
   (font N) letters, variables emit italic (font I); `base_char` collapses
   both onto the same handwriting glyph. Acceptable — a hand doesn't have two
   letterforms — but recorded in case the user wants distinct treatment.
6. **Integral limits** (moderate): ∫ is a single LO glyph with limits at
   ±1 em / scale 0.707 (verified eq7). Display-style `\int` with limits ABOVE/
   BELOW (`\limits`) not tested; same placement machinery should cover it.
7. **Linear-format (flat) OMML** (rare in properly-authored docs): degrades in
   pandoc (see §1). Needs detection: an oMath whose tree is only `m:r` runs.
8. **Accents** (`\hat`, `\vec`, `\dot`) and **matrices/multi-line**: not in the
   test set, untested. Accents place a combining glyph over a base — likely
   fine, verify at next STOP if the user's documents use them.

## 6. Open questions for the user

1. **Real course documents**: please drop 1–2 real .docx files (with Word
   equations) into `spike/input/` — the inventory frequencies and limitation
   ranking should be re-run against real material before the charset is final.
2. **Charset confirmation**: is the 70-symbol collection list (inventory.md)
   right for your courses? Anything to add (e.g. `≡ ⋅ ‖ ⟨ ⟩ ∈ ∀`) or drop
   (uppercase Greek you'll never write)?
3. **∘/° policy**: collect one degree glyph and alias U+2218/U+00B0 to it? (Recommended.)

## Next STOP (after user confirmation)

Geometry validation with existing glyphs: substitute latin/digit symbols from
`glyphs/real` into a placement list at the computed (x, y, scale) and check the
result reads as a correct equation — before any new symbol collection.

---

## Rev 2 (2026-07-31) — real documents + user charset decisions

Two REAL lab reports (실험6/실험9 결과 보고서, 86 OMML equations) were dropped
into `spike/input/` (gitignored: 155 MB + personal info in filenames; the
constructed test docx stays committed). All rev-2 numbers come from
re-running `inventory.py`.

**Toolchain re-verdict on real OMML: GO holds.** pandoc 3.5 converted all 86
real equations with zero errors — fractions, radicals, `\left(...\right)`
stretchy delimiters, |absolute-value| bars, sub/superscripts, `\cdots`, `%`,
`×`, `⋅`, thin spaces, scientific notation all clean. No converter fallback
needed.

**Charset decisions applied (user, 2026-07-31; recorded in PROMPT.md):**
- ALIAS layer added as a general substitution-table mechanism: 14 Greek
  capitals visually identical to Latin (Α=A … Χ=X), ο=o, ∘=° (one degree
  glyph, both codepoints), ≃=≈, ⋅=· — see inventory.md alias table.
- Greek capitals collected: only the 10 unique shapes (Γ Δ Θ Λ Ξ Π Σ Φ Ψ Ω).
- Additions confirmed: ≡ ′ ∴ ∵ ∮ ∠; optional pending: ⟨ ⟩ ∈.
- **Final: 60 confirmed collection glyphs (+3 optional).**
- Symbols actually seen in the real reports: α θ λ μ π τ φ ω × ≤ ° — all
  inside the confirmed set.

**New real-document findings:**
1. **Hangul inside equations** — subscripts like `I_측정`, `I_측정 평균`,
   `I_이론` (6 distinct syllables, 30 occurrences). The store has no hangul
   and hangul is outside the math charset. → open question below.
2. `⋯` (U+22EF, midline ellipsis, 1×) — recommend NOT collecting: synthesize
   in the substitution phase as three `·`/`.` glyphs in a row.

**Open questions (rev 2):**
1. Hangul in equation subscripts — options: (a) render those subscripts with a
   future hangul store (big collection effort, out of Phase 2 scope), (b) keep
   them as unsupported-with-warning like today's missing chars (spaced-over),
   (c) transliterate/skip. Recommendation: (b) for Phase 2, decide a hangul
   phase separately.
2. Optional ⟨ ⟩ ∈ — include in the collection template or drop?

---

## Rev 3 (2026-07-31) — STOP 1: geometry validation with real glyphs

Decisions applied first (PROMPT.md [2026-07-31] #2): English-only use case —
hangul follows the general unsupported-char fallback (warn + blank), NO
Korean collection; **collection charset FINAL at 63** (60 confirmed + ⟨ ⟩ ∈);
future English .docx = gap-check only, non-blocking.

**Method** (`render_placement.py`): for each placement element, paste a real
`glyphs/real` variant — baseline row on the element's pen y, ink centered in
MathJax's ink bbox, scaled per element `scale`; symbols in the 63-to-collect
set become gray labeled placeholder boxes at their exact bbox; rules are drawn
as ink bars. 120 px/em, seeded variant choice. Evidence: `archive/spike_debug_evidence/
geom_<id>.png` (MathJax reference vs substitution, pixel-matched width) for
all 8 equations.

**VERDICT: geometry validation PASSES.** The stolen coordinates place real
handwriting into correct 2D structure: fraction num/den stack on the bar,
superscript ² lands high-right at 0.707 scale, integral limits sit at the
LO-glyph's corners, baselines align. `geom_eq4_inertia.png` is the money
shot — `I = 1/12 ML² + Md²` renders FULLY in the user's hand (zero
placeholders) and reads exactly like the reference.

**Finding (size anchor — the one real bug found):** the first render came out
~32% small. Cause: scaling by the store's nominal frame (`native_size_px` =
74 = guide-frame cap height) — but the user's real ink only reaches ~50.5 px
(caps) / 24 px (x-height) inside that frame. Fix: anchor on MEASURED ink
metrics. A/B (`geom_anchor_ab_eq1.png`): cap-anchored (50.5 px → 0.68 em,
RECOMMENDED — matches TeX optically) vs x-height-anchored (24 px → 0.442 em —
caps/ascenders oversized, overflow the fraction lanes). The substitution
phase must use measured-ink anchoring, not the frame.

**Notes for the substitution phase:** (a) faint dotted baseline residue from
the store shows under some glyphs (known, accepted at Phase 1); (b) the hand
is narrower than TeX italics, so words sit airy inside MathJax's boxes —
coordinates are used as-is by design; revisit only if full pages read badly;
(c) ∫ √ and Greek render as placeholders until the 63 symbols are collected —
their boxes land correctly, so collection is the only missing piece.
