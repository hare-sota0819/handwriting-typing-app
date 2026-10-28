# Project Prompts

User-provided project prompts, saved verbatim. Newest sections appended at the bottom.

## [2026-07-12] Initial prompt — Build Spec

# Document-to-Handwriting Converter — Build Spec

## How to use this document
This is the master plan. **Read the entire document before writing any code** so you understand the full architecture and where the project is heading, even though you will only implement Phase 1 now.

Then implement **Phase 1 only**, and within Phase 1 work **one checkpoint at a time**. At the end of each checkpoint: STOP, run its verification steps, report results to the user, and wait for explicit approval before continuing. Do NOT implement Phase 2 yet — it is described only so you build Phase 1 with the right extension points.

If anything is ambiguous or seems wrong, ask before implementing. Do not silently guess.

---

## What we are building (full vision)
A program that converts a typed document into an image (or multi-page PDF) that looks like it was genuinely handwritten by a specific person (the user), in their own handwriting style.

- **Input:** a Word document (`.docx`). The user types normally in Word; math is entered with Word's equation editor.
- **Output:** page image(s) rendering that document in the user's handwriting, including natural handwriting variation so it does not look like a repeated font.
- **Must eventually support STEM content:** mathematical formulas, superscripts/subscripts, fractions, integrals, Greek letters, and (less frequently) chemical formulas — because the user is an electrical/electronic engineering student.

The realism target: a human looking at the output should find it plausibly hand-written — same letter appearing multiple times should differ, baseline should drift naturally, spacing should be irregular in a *structured* (not purely random) way.

## Why the architecture is split this way
Handling math is really THREE problems bolted together:
1. **Parsing** — extracting text and (structured) equations from the `.docx`.
2. **Typesetting** — computing the 2D position/size of every character and math symbol (superscript placement, fraction bars, integral sizing, etc.).
3. **Handwriting rendering** — drawing each positioned glyph in the user's handwriting.

Word equations are stored as **OMML**, which is *structured* math (unlike PDF, where equations are usually flattened and would require OCR). This is exactly why the input is Word and not PDF: the equation structure survives, so we can convert OMML → LaTeX reliably and typeset it.

**Rendering method decision (locked): glyph-assembly**, not a generative neural model. Reason: math requires placing each symbol at an exact computed 2D coordinate. Glyph-assembly gives us that direct positional control; generative handwriting models only "flow text along a line" and cannot place a superscript or a fraction, and have never seen math symbols. So we assemble handwriting from per-character glyph images at computed positions.

---

## Phased plan

### PHASE 1 — Plain-text Word → handwriting (NO math yet)
Build the entire end-to-end pipeline for a `.docx` that contains only ordinary text (paragraphs, line breaks). This proves the whole spine works before math is layered on. This is what you implement now, checkpoint by checkpoint.

### PHASE 2 — Add math (described for context only; DO NOT build yet)
Layer equation support on top of the Phase 1 spine:
- Extract OMML equations from the `.docx`.
- Convert OMML → LaTeX.
- Use a math typesetting layer to compute the 2D layout of each equation (symbol positions/sizes).
- Render those positioned math symbols with handwriting glyphs (requires a glyph set extended with math symbols / Greek letters).
- Composite inline and display equations into the page flow from Phase 1.

**Phase 1 must be structured so Phase 2 slots in without rewrites** — see "Extension points" below.

---

## Architecture (Phase 1 scope, with Phase 2 seams)

```
.docx → Parser → Document Model → Layout Engine → Glyph Selector → Variation Engine → Renderer → Paper Compositor → Output (PNG/PDF)
```

**Document Model** is the key neutral interface: an ordered tree of blocks (paragraphs) containing runs of characters. In Phase 1 every element is a text run. Design it so a "math block" node type can be added in Phase 2 **without changing** the Layout/Variation/Renderer/Compositor contracts:
- The Layout Engine consumes the Document Model and emits an abstract list of **placed elements** (each: what to draw, x, y, scale, rotation). For text this is placed glyphs. In Phase 2, a math block will expand into placed glyphs too (positions computed by the math typesetter) — so the Renderer never needs to know whether a glyph came from text or math.
- Keep the Glyph Selector + Renderer as the **only** components that touch glyph images. These are also the components that will later gain math-symbol glyphs.

### Extension points to leave explicit (documented stubs, not implemented)
- `parse_equations()` hook in the parser (Phase 1: assert no equations / warn if found).
- A `MathBlock` node type reserved in the Document Model.
- Layout Engine dispatch that currently only handles text runs but has a clear place to add a math-block handler.

---

## Tech stack
- **Python 3** (target a currently-supported version, not 3.7).
- `.docx` parsing: **python-docx** (and inspect underlying XML where needed).
- Image rendering: **Pillow**; **NumPy** for math on arrays.
- Output: PNG per page, plus optional combined PDF (Pillow can do this).
- No GPU, no ML in this project. Everything is rule-based and CPU-only.
- Keep dependencies minimal; justify and get approval before adding beyond the above.

---

## Data format design

### Glyph store (same design that Phase 2 will extend)
- Multiple sample images per character (variants), transparent-background PNG, ink only.
- On-disk layout with a `manifest.json` mapping each logical character to its variant files + metadata:
  - `baseline_y`, `advance_width`, `left_bearing`, `right_bearing`, ink bounding box.
  - Punctuation stored under safe folder names mapped in the manifest (never literal punctuation as filenames).
- The user does NOT have scanned glyphs yet, so Phase 1 must be fully developable with **synthetic placeholder glyphs** generated from a normal font (with small per-variant perturbation). Real scanned glyphs drop into the same manifest later.

### HandwritingStyle config (dataclass)
All variation "knobs", so they can become per-mood presets later (the user writes in several moods — upright vs slanted, tall vs squat):
- `slant_deg` (mean) + `slant_jitter`
- `size_jitter`, `rotation_jitter_deg`, `vertical_jitter` (per glyph)
- `baseline_drift` (low-frequency wander across a line — NOT per-glyph noise)
- `letter_spacing` (mean+jitter), `word_spacing` (mean+jitter), `line_height`
- `variant_selection`: pick among a character's variants, avoiding immediate repeats
- Variation must be **structured randomness** driven by a smooth/low-frequency function for drift and slant, and must be **seedable** (fixed seed ⇒ identical output) for debugging/evaluation.

---

## PHASE 1 CHECKPOINTS

### Checkpoint 1 — Skeleton + glyph store + synthetic glyphs
- Project structure, dependency setup, README stub, git init.
- `manifest.json` schema + loader.
- Synthetic glyph generator: render a–z, A–Z, 0–9, common punctuation, space into placeholder variant PNGs (transparent, ink-only) with slight per-variant perturbation, and write a correct manifest.
- `HandwritingStyle` dataclass with sane defaults.
- Reserve (documented, unimplemented) the `MathBlock` node type and `parse_equations()` hook.

**STOP & verify:** manifest loads; every char has ≥3 variants; PNGs are transparent and open correctly; print a coverage report (char count, variants/char, missing chars). Wait for approval.

### Checkpoint 2 — .docx parser → Document Model
- Parse a plain-text `.docx` into the Document Model (paragraphs → runs → characters).
- Preserve paragraph breaks; normalize whitespace sanely.
- If the `.docx` contains equations (OMML), for Phase 1 just **detect and warn** ("N equations found; math support is Phase 2") — do not crash, do not attempt to render them.
- Unsupported characters: fallback or log, never crash.

**STOP & verify:** feed 2–3 sample `.docx` files (a plain paragraph doc; a multi-paragraph doc; a doc that DOES contain a Word equation, to confirm it warns rather than crashes). Dump the Document Model and confirm structure. Wait for approval.

### Checkpoint 3 — Layout engine
- Given Document Model + HandwritingStyle + page size/margins, compute placement of every glyph: line breaking to page width (no mid-word splits), letter/word spacing, line height, multi-page overflow, and smooth baseline drift.
- Emit the abstract **placed-glyph list** (char, variant id, x, y, rotation, scale) WITHOUT rendering pixels yet.

**STOP & verify:** for a multi-paragraph sample, dump the placed-glyph list and/or draw bounding boxes so the user can sanity-check wrapping, spacing, page breaks, and that baseline drift is smooth not jumpy. Wait for approval.

### Checkpoint 4 — Variation engine + renderer
- Variation engine: apply structured randomness (slant, jitters, drift, no-immediate-repeat variant selection) to produce final per-glyph transforms. Seedable.
- Renderer: composite chosen glyph images onto a transparent canvas at placed positions/rotations/scales. Ink-only output with alpha, per page.

**STOP & verify:**
- same sentence, 3 different seeds ⇒ visibly different but all plausible;
- same sentence, same seed ⇒ pixel-identical;
- visually: no bad overlaps, natural baseline, repeated letters show different variants. Wait for approval.

### Checkpoint 5 — Paper compositor + output + CLI
- Composite ink onto paper background (start simple: off-white; optional subtle texture and faint per-glyph ink-shade variation), as its own reusable stage.
- Output: PNG per page + optional combined PDF.
- CLI: `input.docx [--style style.json] [--seed N] --out path` → page image(s)/PDF.
- Update README: usage + data-format spec + how to add real scanned glyphs later + note that math is Phase 2.

**STOP & verify:** run end-to-end on a plain-text `.docx`; produce final page(s); show output for the handwriting sanity check; confirm CLI + README. **Phase 1 complete — wait for user sign-off before any Phase 2 work.**

---

## Rules for the whole build
- **One checkpoint at a time.** Always stop, verify, report, and wait for approval at each boundary.
- **Minimal, surgical changes** toward the current checkpoint only. No speculative features beyond this spec. Do not start Phase 2.
- Ask a clarifying question before implementing anything ambiguous.
- Keep the Document Model / Layout / Renderer contracts clean so Phase 2 math slots in without rewrites.
- Commit at each checkpoint with a clear message.
- If a checkpoint's verification fails, fix it before proposing to move on — never proceed on a broken stage.

## [2026-07-13] Feature — user-supplied PDF paper background

# Feature: user-supplied PDF paper background

## Context
Phase 1 is complete and signed off. This is a small, self-contained feature addition — NOT a new phase. Read `docs/PROMPT.md` and the current `handwriting/compositor.py` before starting so you extend the existing paper stage rather than rewriting it.

Do the whole feature, then STOP and run the verification steps and report results. It's small enough that it does not need internal checkpoints, but do not start any other work (no Phase 2, no glyph-import work) — just this.

## Goal
Let the user supply their own paper background as a **PDF file**. When a background PDF is provided, the compositor lays the rendered ink onto that PDF's page image(s) instead of the current procedurally-generated off-white paper. When no PDF is provided, behavior is unchanged (existing off-white textured paper).

This must touch **only the compositor stage** (and the CLI/pipeline wiring to pass the option through). Do NOT modify the renderer, layout, variation, parser, or glyph store. This is exactly the reusable-paper-stage seam Phase 1 established.

## Requirements

### 1. Rasterize the PDF
- Convert the background PDF's page(s) to images at the pipeline's page resolution (the same DPI the pages are rendered at — currently A4 @ 150 dpi; read the actual spec, don't hardcode).
- Use a PDF rasterizer available in this environment. **pymupdf (fitz)** is the recommended choice (it renders PDF pages to bitmaps directly and adds one dependency). If you prefer another approach, justify it and get approval first. Add the dependency to `requirements.txt`.
- Because installing a new dependency modifies the environment, STOP and ask the user to run the install command themselves (per the project's permission rules) rather than running it yourself.

### 2. Fit the background to the page
The background image and the page raster may differ in size/aspect. Provide a fit mode, defaulting to the safest choice:
- `cover` (default): scale to fill the page, center-crop overflow — guarantees full coverage, no empty margins.
- `stretch`: scale to exactly the page dimensions (may distort).
- `contain`: fit entirely with possible letterbox margins (fill margins with the average edge color or white).
Expose this as a compositor/style option with `cover` as default. Document the choice.

### 3. Multi-page handling
The output document may have more pages than the background PDF. Provide a policy, defaulting to the most useful:
- If the background PDF has 1 page: reuse it for every output page (default).
- If it has >= output pages: use page N of the background for output page N.
- If it has >1 but fewer than the output pages: reuse the last background page for the overflow (and log this).
Document the policy.

### 4. Wire through CLI + pipeline
- Add a CLI flag, e.g. `--paper background.pdf` (and optional `--paper-fit cover|stretch|contain`).
- Thread it through `pipeline.py` to the compositor. Keep the existing off-white path as the default when `--paper` is absent.

### 5. Ink legibility note (no code, just surface it)
In the README, note that a dark/low-contrast background PDF can hurt ink legibility, and that ink color is adjustable via `--style` (`ink_rgb`). Do not auto-adjust ink color.

## Verification (run, then STOP and report)
- With NO `--paper`: output is byte-identical to before (procedural off-white unchanged). Confirm this explicitly — it proves nothing else regressed.
- With a single-page `--paper test.pdf`: the ink is composited over that background; produce an output PNG and show it.
- With a multi-page document + single-page background: every output page shows the background.
- With `--paper-fit` set to each of cover/stretch/contain on a background whose aspect differs from the page: confirm each behaves as documented (dump/show the three results).
- Seed reproducibility still holds end-to-end with a paper PDF supplied.
- Update README (usage of `--paper` / `--paper-fit`, multi-page policy, fit modes, ink-legibility note) and `docs/STATUS.md`. Commit.

If you don't have a sample background PDF to test with, generate a couple of trivial ones (e.g. a lined-paper PDF and an off-aspect colored PDF) purely as test fixtures, and say so.

## Rules
- Only the compositor + CLI/pipeline wiring changes. If you find yourself editing the renderer or layout, stop — you're doing it wrong.
- Minimal, surgical changes. No speculative features.
- Ask before implementing anything ambiguous.
- Stop for the dependency install (user runs it).

## [2026-07-13] Feature — snap text baselines to ruled-paper lines

# Feature: snap text baselines to ruled-paper lines

## Context
Phase 1 is complete and the `--paper` PDF-background feature is done. The user's chosen paper is **ruled notebook paper** (horizontal rule lines + a vertical margin line, cream background, A4). Right now text is laid out on its own baseline grid and ignores the paper's rules, so glyphs float across the printed lines and look wrong.

This feature makes the text sit ON the paper's ruled lines. Read `docs/PROMPT.md`, the current `handwriting/layout.py`, and `handwriting/compositor.py` before starting.

Do the whole feature, then STOP, run the verification, and report. No internal checkpoints needed (it's focused), but do not start any other work (no Phase 2, no glyph import).

## Goal
When the user supplies a ruled-paper background and enables line-snapping, the layout engine places each text line so its baseline aligns with a printed rule on the paper — while preserving a *small* natural vertical wobble so it doesn't look mechanically perfect. When line-snapping is off (default, or non-ruled paper), behavior is unchanged.

## Design

### 1. Determine the rule positions (two sources; auto first, manual override)
Add a way to obtain the paper's horizontal rule spacing and offset:

- **Auto-detect (default when a `--paper` PDF is given and snapping is on):** rasterize the background PDF page (reuse the compositor's existing rasterization), then detect horizontal rule lines by scanning rows for long, roughly-horizontal darker-than-background runs. From detected rules, compute: `line_spacing_px` (median gap between consecutive rules) and `first_line_y_px` (y of the top rule). Detect the vertical margin line's x too if easily done, and expose it (optional; used for left indent), but rules are the priority.
- **Manual override:** CLI flags `--rule-spacing PX` and `--rule-offset PX` (and optional `--rule-margin-x PX`) that, if provided, bypass detection. This is the safety net when auto-detect is off on a given paper.

Detection must be **robust to a faint/low-contrast rule color** (this paper's rules are pale). If detection finds too few rules or an irregular spacing (high variance), do NOT silently guess — emit a clear warning and fall back to the un-snapped layout, telling the user to pass `--rule-spacing/--rule-offset` manually. Report what was detected (e.g. "detected 34 rules, spacing 38px, first at y=52px").

### 2. Snap baselines in the layout engine
- Add an optional `LineGrid(spacing_px, offset_px, margin_x_px|None)` input to the layout engine.
- When present: the layout places successive text lines on successive rules — i.e. each line's baseline y = `offset_px + k * spacing_px` for increasing k, instead of the current internal line-height stepping. The engine's own `line_height` is overridden by the rule spacing while snapping is active.
- Page breaks: when the rules run out at the bottom of the page, continue on the next page starting from the first rule again.
- **Font size sanity:** if the glyph size is too large for the rule spacing (text would collide across rules), warn and either scale glyphs down to fit the spacing or proceed — pick the least-surprising behavior and document it. Do not produce overlapping lines silently.

### 3. Preserve natural wobble (important — do not skip)
Snapping every baseline exactly onto a printed rule looks mechanical and *defeats the handwriting illusion*. Real handwriting on ruled paper sits near the line but wobbles slightly. So:
- Keep a small per-line vertical jitter around the rule (a fraction of the existing `baseline_drift`, e.g. a few px), driven by the existing seeded RNG so it stays reproducible.
- The smooth intra-line baseline drift can remain but should be **reduced in amplitude** while snapping (the rule now dominates the line's vertical position). Expose the wobble amount as a style knob with a sensible default; don't hardcode.

### 4. Wire through
- CLI flag `--snap-lines` (off by default) to enable snapping. When on and a `--paper` PDF is present, auto-detect runs. Manual `--rule-*` flags override detection and imply snapping.
- Thread a `LineGrid` (from detection or manual flags) into the layout engine via the pipeline. Keep the non-snapped path the default and unchanged.

## Verification (run, then STOP and report)
- **Regression:** with `--snap-lines` absent, output is byte-identical to before. Confirm explicitly.
- **Auto-detect on the user's paper:** run on the real ruled paper (`samples/배경_종이.pdf` — copy it into the repo if not there) with `--paper ... --snap-lines`. Report detected spacing/offset. Produce an output PNG and show it: text baselines should sit on the printed rules.
- **Manual override:** run with `--rule-spacing/--rule-offset` and confirm baselines move accordingly (dump/show).
- **Wobble preserved:** confirm baselines are near — but not all pixel-perfect identical distance from — the rules (i.e. wobble is present, reproducible under a fixed seed).
- **Font-too-big case:** run with an exaggerated large glyph size vs. spacing and confirm the documented behavior (warn + scale-down or whatever was chosen), no silent overlap.
- **Detection-failure fallback:** run snapping against a *non-ruled* background (e.g. the plain off-aspect fixture) and confirm it warns and falls back rather than snapping to garbage.
- Update README (`--snap-lines`, `--rule-*`, auto-detect behavior, wobble knob, fallback) and `docs/STATUS.md`. Commit.

## Rules
- Layout engine + compositor detection helper + CLI/pipeline wiring only. Renderer, parser, variation core, glyph store stay untouched (variation may gain the wobble knob read, nothing more).
- Minimal, surgical. No speculative features.
- Ask before implementing anything ambiguous.
- If auto-detection reliability is unclear on this paper, prefer warning + manual fallback over guessing.

## [2026-07-13] Feature — real handwriting import via grid template

# Feature: real handwriting import via grid template

## Context
Phase 1 (glyph-assembly pipeline) is done, plus `--paper` PDF backgrounds and ruled-line snapping. Everything currently runs on **synthetic placeholder glyphs** (rendered from a font). This feature replaces them with the **user's real handwriting**, captured through a printed grid template.

Read `docs/PROMPT.md`, `handwriting/glyphstore.py` (the store layout + manifest schema you must match), and `handwriting/synthglyphs.py` (the reference for which characters exist and what metrics each glyph needs) before starting.

The user's handwriting is **print-style, consistently right-slanted**. Keep that in mind for cell sizing (slanted letters lean out of a tight box) and for NOT trying to de-slant glyphs — preserve the natural slant.

This is two tools. Build them in order, STOP at the checkpoint between them, and STOP again at the end. Do not start unrelated work (no Phase 2).

---

## Tool 1 — Grid template generator (PDF)
A script that produces a printable A4 PDF grid the user fills in by hand.

Requirements:
- **Cells:** one labeled cell per glyph sample. Cover every character the store needs (read the character set from the existing store/synthglyphs: a–z, A–Z, 0–9, the same punctuation set). Give each character **N cells** (default N=5) so we capture natural variation. Group a character's N cells together (e.g. a row or block per character).
- **Labels:** print the target character faintly (light gray) next to/above each cell so the user knows what to write, positioned so it does NOT sit inside the writing area (it must not get scanned as ink). The user writes the glyph *inside* the cell box.
- **Cell size:** generous enough that a right-slanted print letter fits without touching the cell borders. Make cell size a parameter.
- **Registration markers:** print solid black fiducial squares at (at least) the 4 corners of the grid area, at known positions, so Tool 2 can detect them and correct scan skew/scale/translation. Document their exact positions.
- **Deterministic layout:** the exact pixel/point geometry of every cell (which character, which cell index, its rectangle relative to the markers) must be recorded to a **sidecar JSON** (e.g. `template_layout.json`) written alongside the PDF. Tool 2 reads this instead of re-guessing the grid. This is the key to reliable auto-splitting.
- Multiple pages are fine if one A4 can't hold all cells; markers + layout JSON must cover every page.

**STOP after Tool 1. Verify & report:**
- Generate the PDF + layout JSON. Render the PDF to PNG and show it so the user can eyeball that cells, labels, and corner markers look right and printable.
- Confirm the layout JSON lists every character with N cell rectangles and that marker positions are recorded.
- Report the character coverage (chars × N = total cells, page count).
Wait for user approval before Tool 2.

---

## Tool 2 — Scan splitter → glyph store
A script that takes the **filled, scanned** template (image or PDF, one or more pages) plus `template_layout.json`, and produces a real-handwriting glyph store in the **same on-disk layout + manifest schema** the pipeline already uses.

Requirements:
- **Input:** scanned page image(s) (png/jpg) or a scanned PDF, plus the layout JSON. Assume the scan is skewed/scaled/shifted relative to the template.
- **Registration:** detect the 4 corner markers, compute the transform (affine/perspective) that maps template coordinates → scan coordinates, and use it to locate each cell precisely. If markers can't be found reliably, STOP with a clear error telling the user to rescan flatter/higher-contrast — do NOT fall back to blind grid guessing.
- **Per cell:** crop the cell, remove the printed cell border and the faint label (they're at known positions / distinguishable by color-lightness), binarize/extract just the ink as a transparent-background RGBA image (ink only, alpha = coverage), trim to the ink bounding box. **Do not de-slant** — keep the natural slant.
- **Empty-cell handling:** if a cell has (almost) no ink, skip it (the user may not have filled every cell). A character with ≥1 filled cell is imported with however many variants it has; a character with 0 filled cells is left to fall back (see partial import).
- **Metrics:** for each extracted glyph, compute the same manifest fields the synthetic store uses (`baseline_y`, `advance_width`, `left_bearing`, `right_bearing`, `ink_bbox`, and the store-wide `native_size_px`). Baseline estimation for print glyphs: infer from the ink bbox bottom for non-descenders; document the heuristic and make it overridable. This directly reuses the schema in `glyphstore.py`.
- **Partial import:** support merging into / producing a store where characters with no captured samples keep the synthetic placeholder, so the user can fill the template incrementally over several passes. Make it explicit which chars are real vs still synthetic (print a report).
- **Output:** a new glyph store directory (don't overwrite the synthetic one) that the pipeline can point at, plus a coverage report: chars imported, variants each, chars still synthetic.

**STOP after Tool 2. Verify & report:**
- Since the user hasn't filled a template yet, verify with a **simulated fill**: take the synthetic glyphs, lay them into the template cells to fabricate a "fake scan" (optionally with a small rotation/scale to exercise registration), then run Tool 2 on that and confirm it round-trips into a valid store (markers found, cells split, manifest valid, metrics sane, partial-import report correct). Say clearly that this is a simulated scan.
- Render a sample `.docx` using the imported store to confirm the pipeline reads it with zero code changes (proves the schema matched).
- Report coverage and show a rendered sample.
Wait for user sign-off.

---

## Rules
- Match the EXISTING store layout + manifest schema exactly (see `glyphstore.py`); the pipeline must read the new store with **no code changes**. If you're tempted to change the schema, stop and ask.
- Two independent scripts (generator, splitter); don't touch renderer/layout/variation/parser.
- Minimal, surgical. Ask before implementing anything ambiguous.
- Preserve the user's natural slant; never de-slant.
- Never blind-guess the grid — registration markers + layout JSON are mandatory; fail loudly if markers aren't found.
- Commit at each STOP.

## [2026-07-29] Stage 2 go-ahead + decisions confirmed (reviewer)

Reviewer confirms all three decisions — record them in STATUS/SOLVED now:

STOP A: approved.
Dark residue (~19% surviving the global threshold): accepted as-is, closed. No shape-aware filter. Revisit only if the STOP B comparison shows it as a distinct artifact.
Stage 2 ink-tone target = existing 1200 DPI template scans (scans/스캔본_*.pdf). Not blocked on any example PDF.
Also closed: a v9 / e v1/v9 bleed — measured 1px, subpixel at render scale, no action.

Before starting Stage 2, one completeness check the handoff missed: report git status (working tree clean?), git stash list, and git branch -a — confirm no uncommitted or off-branch work exists. If anything shows up, stop and report; if clean, proceed.

Then start Stage 2 per the scanned-look brief: (1) measure the target ink histogram from the 1200 DPI scans and report it, (2) global tone match, (3) per-glyph density jitter, (4) intra-glyph low-frequency pressure approximation, (5) edge softening/bleed matched to measured scan edge gradients, (6) minimal page-level scanner tone (the paper PDF is already a real scan — do not double-texture). Every knob defaults to the weakest setting visible in a 4× A/B. All seeded, all off under --no-effects (byte-identical golden). STOP B deliverables: 3-way comparison (GT photo / clean / effects), 4× A/B pairs for two words + one punctuation/symbol cluster, ink histograms (target vs clean vs effects), honest remaining-gap list. Halt at STOP B for review.

## [2026-07-30] Phase 2 (Equations) — STOP 0: Toolchain Spike + Symbol Inventory

# Phase 2 (Equations) — STOP 0: Toolchain Spike + Symbol Inventory

## Context

Phase 1 is signed off (pending only the asymmetric-jitter histogram fix, which may land independently). Phase 2 adds equation support: Word documents contain math as OMML; the goal is rendering those equations in the user's handwriting with correct 2D typesetting (fractions, integrals with limits, sub/superscripts, radicals).

**Architecture decision (fixed):** we do NOT write a typesetting engine. We steal coordinates from an existing one:

```
.docx OMML → LaTeX (existing converter) → MathJax SVG (tex2svg) → parse SVG → symbol placement list → glyph substitution (later phase)
```

This STOP is a **feasibility spike + inventory extraction only**. No rendering integration, no layout work, no collection, no changes to the existing pipeline. Throwaway-quality code is acceptable in `spike/` — but the findings and the JSON schema are deliverables.

## Goal

Prove (or disprove, with specifics) that we can go from real OMML in the user's real documents to a clean per-symbol placement list. This is the single highest-risk assumption in the Phase 2 design; everything else waits on it.

## Tasks

### 1. OMML → LaTeX

- Extract OMML from real .docx files containing Word-native equations. If the repo has none, first generate a test .docx via python-docx is NOT sufficient (it can't create OMML easily) — instead ask the user to drop 1–2 real course documents into `spike/input/`, OR construct a minimal .docx with equations by unzipping/editing document.xml from a template. Prefer real documents; note in the report which path was taken.
- Convert OMML → LaTeX with an existing tool (candidates: pandoc, `dwml`, `omml2latex`-family libraries). Try pandoc first (already scriptable). Record: tool chosen, failure cases, LaTeX output for each test equation.

### 2. LaTeX → per-symbol coordinates

- Run MathJax (node, `tex2svg`) on the LaTeX. Parse the SVG output: MathJax emits each symbol as a `<use>`/`<path>` reference with a transform chain, and rules (fraction bars, radical bars) as `<rect>`.
- Resolve the transform chains to absolute coordinates. Produce, per equation, a JSON placement list:

```json
{
  "equation": "T = 2\\pi\\sqrt{I/(Mgd)}",
  "em_height": <float>,
  "elements": [
    {"kind": "symbol", "codepoint": "U+0054", "char": "T", "x": .., "y": .., "scale": ..},
    {"kind": "rule", "x": .., "y": .., "w": .., "h": .., "role": "frac_bar|sqrt_bar|unknown"},
    {"kind": "stretchy", "char": "(", "x": .., "y": .., "h": ..}
  ]
}
```

  (Adjust schema as reality dictates — the schema you land on IS a deliverable; document every field.)
- **Verification (mandatory, pixel-level):** for each test equation, render a debug overlay — draw each element's bounding box + codepoint label at its computed position, and visually compare against MathJax's own rasterized SVG side by side. Save to `spike/debug/`. Coordinates are correct when every box lands on its symbol.

### 3. Test equations (minimum set)

Use these five from the user's actual prelab domain, plus any real equations found in Task 1 documents:

1. `T = 2\pi\sqrt{\dfrac{I}{Mgd}}`  (nested fraction inside radical)
2. `\alpha_z = \dfrac{d^2\theta}{dt^2}`  (Greek, subscript, second derivative)
3. `k = \dfrac{4\pi^2 I}{T^2}`  (superscripts in fraction)
4. `I = \dfrac{1}{12}ML^2 + Md^2`  (inline-size fraction + terms)
5. `\omega = \sqrt{\dfrac{mgd}{I}}` and inline `\theta \le 5^\circ`  (radical + degree symbol)

Report which constructs work cleanly and which don't (known suspects: stretchy delimiters, radical hook vs bar decomposition, large operators like `\int` with limits, accent placement).

### 4. Symbol inventory for the collection charset

- Scan ALL OMML equations found in the user's documents in `spike/input/` and enumerate every distinct character/symbol that appears, with frequency counts.
- Output `spike/inventory.md`: table of codepoint, char, count, category (latin/digit/greek/operator/relation/delimiter/other).
- Then produce a **proposed collection charset** = (inventory) ∪ (standard physics/EE set: full Greek alphabet upper+lower, `∫ ∑ ∏ √ ± ∓ × · ÷ ≤ ≥ ≠ ≈ ∝ → ⇒ ∞ ∂ ∇ ℏ °` and anything else MathJax emitted for the test equations). Mark each entry: seen-in-documents / standard-set-only. The user will confirm the final charset — do not generate a template yet.

## Constraints

- Everything under `spike/` — do not touch `handwriting/`, `glyphs/`, `scripts/`, existing configs, or goldens.
- Node/npm usage is fine (MathJax); record exact versions for reproducibility.
- If a chosen tool fails on real OMML, try the next candidate and document the failure — a converter comparison table is more valuable than a silent workaround.

## STOP 0 report

1. Toolchain verdict: OMML→LaTeX tool chosen + failure cases; MathJax version; overall GO / NO-GO on the coordinate-stealing architecture, with evidence.
2. `spike/debug/` overlay images for all test equations (side-by-side with MathJax's own render).
3. Final JSON schema with field documentation + one full example.
4. `spike/inventory.md` + proposed collection charset with seen/standard markings.
5. Known limitations list (constructs that will need special handling in the substitution phase: stretchy delimiters, radical geometry, integral limits, etc.) — ranked by how common they are in the user's actual documents.
6. Open questions for the user, if any.

Git commit: `phase2: STOP 0 spike — <GO|NO-GO> <summary>`. Halt after the report; the user confirms the charset and the next STOP (geometry validation with existing glyphs) before any further work.

## [2026-07-31] STOP 0 charset decisions (user) + real documents provided

User dropped 2 real lab-report .docx into spike/input/ and decided:

2. 70자 목록 — 두 방향으로 수정 제안합니다.

줄이는 쪽: 그리스 대문자 절반은 수집할 필요가 없습니다. 손글씨에서 라틴 대문자와 시각적으로 동일한 게 14자나 됩니다: Α=A, Β=B, Ε=E, Ζ=Z, Η=H, Ι=I, Κ=K, Μ=M, Ν=N, Ο=O, Ρ=P, Τ=T, Υ=Y, Χ=X. 손으로 쓰면 구분 자체가 안 되는 글자들이라, °/∘와 같은 별칭(alias) 처리가 맞습니다 — 기존 라틴 글리프에 매핑. 실제 수집은 형태가 고유한 Γ Δ Θ Λ Ξ Π Σ Φ Ψ Ω 10자만. 소문자도 ο(오미크론)=o는 별칭으로. 나머지 소문자(ι κ υ ν 등)는 라틴과 미묘하게 달라 수집 유지. 이걸로 70 → 약 55자.

늘리는 쪽: 사토 님 실제 문서에 이미 등장하는 기호가 목록에 빠져 있습니다. 사토 님 프리랩에 ≡가 있고("T ≡ (∂U/∂S)"), 목표 스타일인 열역학 노트에는 ∴가 보입니다. 전기전자 전공이면 ∮(폐곡선 적분, 전자기학 필수), ∠(페이저 각), ′(프라임 — 도함수 표기, 매우 빈번)도 사실상 확정 수요입니다. 추가 권고: ≡ ′ ∴ ∵ ∮ ∠, 선택: ⟨ ⟩ ∈. ≃는 ≈에, ⋅(U+22C5)는 ·에 별칭. 실제 문서 재실행 결과와 합쳐서 확정하면 됩니다.

3. °/∘ 별칭 — 동의. 한 글리프 수집, 두 코드포인트 매핑. 위의 그리스 대문자 별칭과 같은 메커니즘이니 substitution 테이블에 별칭 계층을 일반 기능으로 넣는 게 좋겠습니다.

## [2026-07-31] Decision update: English-only + charset FINAL 63 + proceed to geometry validation

Decision update, replacing the previous Korean-subscript instruction: the real use case is English documents only — the two Korean .docx files were provided solely as inventory-validation samples because no English ones were on hand. Therefore: (1) NO Korean collection; Korean characters follow the general fallback (warn + blank) like any unsupported char. (2) Collection charset is FINAL at 63 symbols: the confirmed 60 + ⟨ ⟩ ∈. (3) ⋯ procedural from ·, aliases as designed — all unchanged. (4) The pandoc/coordinate validation from the Korean docs remains valid (the 86 equations' math structure is language-independent); when the user adds a real English .docx later, re-run the inventory as a gap check only — do not block on it. Proceed now to the geometry-validation STOP: substitute existing glyphs/real latin/digit glyphs into placement lists at computed (x, y, scale), render, and report with the eq1/eq7 spike overlays attached.

## [2026-07-31] STOP 1 approved + iPad collection pilot

STOP 1 formally approved — all 8 geometry images verified by the reviewer. Two notes for the substitution module design (no action now, just reserve the hooks): (1) math symbol spacing will eventually need a compression factor + small jitter knob (MathJax metrics read wider than the user's target note style); (2) the old store's = renders as two blunt blobs at equation sizes — no fix needed, the new-style collection will replace it.

Now execute the iPad collection pilot brief (PROMPT_ipad_pilot.md): build scripts/make_template_ipad.py, generate the pilot template PDF (10 chars × 2 variants: a e g f z t . ( ∂ θ), and build Tool 2b (scripts/split_ipad.py) so it's ready the moment the user hands back the GoodNotes exports. Deliver the template PDF to the user first — Tool 2b can be built while waiting for the written files.

NOTE (assistant): PROMPT_ipad_pilot.md was NOT found anywhere in the repo or filesystem — the brief was never delivered. Executed from the instruction above alone, with these documented assumptions: identical geometry to the print template (A4@150dpi, cell 84x132, same guides/markers/layout-JSON schema) for maximum Tool 2 reuse; GoodNotes workflow = import PDF -> write -> export PDF with background; pilot store NOT committed (out/). If the brief surfaces later, reconcile against it.

## [2026-07-31] iPad pilot reconciliation — 3 divergences from the brief

The pilot brief file is attached now — diff your implementation against it and reconcile. Three known divergences to fix before the user writes anything: (1) Regenerate the template with guides/labels/markers in a distinct non-black color (light cyan) per the brief — nothing black in the template — and switch Tool 2b extraction to color-key removal accordingly; brightness-band deletion near the baseline remains forbidden. (2) Exact-coordinate cropping with markers as a ±2px sanity check only, not affine registration. (3) The user will export the SAME written page in all available combinations of {Editable, Flattened} × {Include Page Background on/off}; Tool 2b must run the export-variant matrix from the brief: confirm vector ink at 600 dpi per variant, inspect whether Editable preserves per-stroke paths (finding only), and recommend ONE canonical export recipe for full collection. Re-deliver the corrected template PDF, then wait for the user's files.

NOTE (assistant): PROMPT_ipad_pilot.md was searched for again (repo, home, /mnt Windows drives) and is STILL not present on this machine — "attached" did not deliver a file. The three enumerated divergences were implemented from this instruction directly; full-brief reconciliation remains pending if the file ever lands.

## [2026-08-03] Style reference + two output looks (iPad-like and paper-like)

내가 지금 예시로 넣어둔 Thermodynamics_and_Thermostatistics_Lecture_Notes 처럼 쓸 수 있으면 됨. 그리고 너무 두꺼우면 볼펜이나 만년필로 쓴게 아니라 아이패드로 쓴 것 처럼 되니까 그건 주의할 필요가 있음. 너도 계획서 보면 알겠지만 결국 아이패드로 쓴 것 같은 버전과 종이에 쓴 것 같은 버전을 모두 만들어야 하는데 그 둘을 다 만족할 수 있어?

아 야 시발 실제 펜으로 쓴거 다시 보내줄게 그거가지고 비교하니까 그런거구나

NOTE (assistant): the "two versions (iPad-like / paper-like)" requirement is NOT
present anywhere in the earlier sections of this document — searched in full.
What exists is the --paper background feature, the scanned-look effects stages,
and the --no-effects clean path. Recording it here as a NEW requirement as of
this date. Also recorded: the stroke-weight target is the lecture-notes
reference, and over-thick strokes are explicitly unwanted (they read as tablet
ink rather than ballpoint/fountain pen). The real-pen comparison is being
re-supplied by the user because samples/ground_truth.png.jpg is a low-resolution
photo (2 px stroke on a 9 px x-height) and is too coarse to calibrate against.

## [2026-08-03] Weight decision — keep the pilot stroke weight as written

지금 정도가좋은데?내 육안으로 보면 두께는 펜으로 쓴거랑 비슷함

DECISION: the iPad pilot's as-written stroke weight (ratio 0.16) is FINAL for
the collection. Do not raise the GoodNotes pen; do not dilate the store. The
0.22 target derived from the lecture notes is a different person's hand and is
NOT the weight goal — the user's own ballpoint is the goal, and it reads
thinner. Thickening remains available later as a render/extraction-time
operation if a full page ever reads faint.

## [2026-08-11] GUI shell — desktop app + distributable exe

야 우리 이제 그거 만들어야 해. 껍데기. 매번 내가 어디에 파일 넣었으니까 만들어 줘 할 수 없잖아? exe프로그램 같은거 만들어서 내가 드래그나 뭐 어떻게든 파일 집어넣으면 내가 옵션 선택하고 변환하기 같은거 누르면 딸깍 하고 나오는거지

(follow-ups in the same conversation)
- 배포도 할거야. 그리고 ㅅㅂ 매번 브라우저 키기 싫어
- inputs: .docx AND math-list text file ("둘 다")
- options: expose everything adjustable ("조정할 수 있는걸 다 띄워주는게 좋지 않을까")
- preview + re-roll in app, save when satisfied (option A)
- approach: PySide6 desktop app + PyInstaller Windows exe (option 1 approved)
- "한번 끝까지 만들어와 봐 결과물 써보고 판단할게" — build end-to-end without
  intermediate review gates; the user judges the finished program.

Clarifies scope: this is a SHELL around the existing entry points (text docx
render, docx equation contact sheet, math-set contact sheet). It does not add
new rendering capability; the integrated text+math page remains Phase 2 work.

## [2026-08-16] Document conversion must include equations + stretched-bracket weight bug

User's message (verbatim, with a screenshot of two rendered equations
`I(θ; X | T(X)) = E[log ...]` whose tall `[ ]` had uneven stroke weight):

> 야 씨발 비상. 왜 문서 변환기 수식은 변환을 못하냐? 워드를 그대로 갖고와야
> 하는데 왜 씨발 수식을 변환을 못하는거야???????????????????? 그리고 수식
> 변환기 써 봤는데 지금 이미지에서 문제점 보이지? 대괄호같은거 위로 쳐늘릴
> 때 시발 획 두꺼워지거나 얇아지거나 그 버그좀 어떻게 해결 좀 해봐. 다른
> 문자도 그럴 것 같은데.. 시발. 아무튼 시발 그냥 변환해도 수식 변환하도록 해
> 줘. 왜 못하는거야 이걸.. 워드 파일을 정말 그대로 손글씨로 바꿔야 된다니까

Confirmed plan (user: "맞아, 진행해"): (1) fix the stretched-delimiter
weight bug (stretch only the straight run, for all delimiters, not just √);
(2) wire equations into the document pipeline so plain docx conversion
renders text AND equations on the same page (inline in the line, display
centred on its own line, Word-like); (3) verify; (4) rebuild the exe.
Supersedes the 2026-08-11 note "integrated text+math page remains Phase 2".

## [2026-08-16] Millikan render review — grey ⋯ dash, display-equation spacing

> 지금 (2) 같은거 왼쪽에 있는 - 작대기가 회색으로 없다는 표시가 뜨는데 이거
> 수정 필요해보임. 그리고 지금 특히나 (8)보면 글하고 겹쳐있잖아? 위아래
> 변수를 빼더라도 저건 너무 줄글하고 붙어있는 느낌이야. 그래서 애초에 저렇게
> 따로 떨어져 있는 수식의 경우(인라인 말고) 위아래 간격을 더 벌리는게
> 나아보여. 이거는 기본으로 해야하는거니까 수정 좀 해줘.

Follow-up answer to the plan: "다른 고급 옵션들처럼 수식과 다른 문단 간 간격
조절도 기본값은 너가 말한대로 하고 수동으로 조절 가능하게 넣어주라"
(default 0.35 × letter size, plus a GUI advanced-option knob).

## [2026-08-18] MAS557 HW3 변환 결과 리뷰 (Downloads의 docx + 손글씨 PDF)
> C:\Users\lunas\Downloads 경로에 지금 스샷 보낸거 2개 했거든? 변환한거야. 근데 문제가 좀 많아. 너가 한번 보고 어떤 문제가 있는지 봐봐

(스샷: ∏ 렌더, `)^{α_j}.` 의 마침표, "MAS55" 헤더, 이중 ∑ 식)
> 이 간첩새끼 퀄리티 이상함. 그리고 오른쪽 끝에 보면 마침표 같은게 있는데 저게 왜 저기 있는거임? 그리고 5는 왤케 아래로 내려감?  아까도 말했지만 이런 대형 연산자들 왜 자꾸 깎는지 모르겠군. 이거도 추가해서 너가 말한 것까지 싹 다 수정해

## [2026-09-21] 실험1 예비레포트 — 페이지 아랫부분을 안 쓰고 넘어감 / 워드 페이지 그대로 옮기기

> 야 이거 근데 왜 아랫부분은 다 사용 안하고 남기고 넘어가는거임?
> C:\Users\lunas\Desktop\Univ\2026IS2\공물실(2)\실험\예비레포트 에 있는 실험1 예비레포트, 2026101227, 최찬호 파일을 보면 알겠지만(내가 일부러 칸 남겨둔 부분 말고) 그냥 밑에 부분을 보면 내가 보내준 이미지처럼 다 안쓰잖아? 그건 어떻게 처리할 수 없음?

Answer to "use the last printed rule, or leave one empty?": "다 써"
(write down to the last printed rule).

Follow-up, sent while that fix was being written:

> 사실 그냥 워드 페이지를 그대로 옮기면 되지 않나? 라는 생각이 있긴 해. 내가 변환기 좀 써 보니까 이게 워드 페이지를 그대로 옮기는게 안되더라고.
> 이미지처럼 예를 들어보면, 워드에 저렇게 되어 있으면 손글씨도 딱 저 페이지에 나와있는 내용이 한 페이지 안에 들어가면 좋겠거든? 왜냐면 내가 일부러 줄바꿈하거나 다음 페이지로 넘겨서 작성한 경우가 있는데 그러면 다시 손글씨 변환할 때 내가 레이아웃을 맟춰줘야 하더라고. 근데 이게 내가 탬플릿을 써서 그런건지는 잘 모르겠지만 그런 부분도 좀 알아서 되면 좋겟음

(스샷: 워드 1쪽 — Learning Objectives부터 식 (7)까지)

Then: "다시 시작해봐". Direction NOT yet decided: the two requests pull
against each other (mirrored Word pages end with empty rules by design), so
the user was asked to choose. See docs/STATUS.md.

Answer to that choice:

> 일단 다 만들고 나서 내가 실사용하면서 피드백 주는게 더 나아보임

So both were built: write ruled paper down to the last printed rule, and
mirror Word's pages as a GUI option (on by default). Feedback comes after
real use.

## [2026-09-21] 실사용 피드백 (실험2 예비레포트) — ∮ 모양, 큰 빈 공간

> 씨발 선적분 왜저럼? 글고 저거 문제가 있는 것 같은게 저렇게 너무 공간이 띄어지는 경우가 발생하네. 이런 경우는 어케해야하지?

(스샷 1: `Φ_E = ∮E⊥dA = ∮E·dA = Q_encl/ε0 … (2)` — ∮의 원이 아래로 내려가 있음.
스샷 2: Procedure (10)번과 "Graph Capacitance C versus…" 뒤로 페이지 절반이
비고 다음 장이 (11)번으로 시작)

Asked how to handle the empty space, the user chose "채우기 우선": pages fill
to the bottom, only Ctrl+Enter page breaks open a new page, a caption plus
its run of blank lines (figure space) is never split across pages, and the
"워드 페이지 그대로" checkbox stays but defaults to OFF. This CHANGES the
default set earlier today (it was ON). The ∮ fix was approved in the same
answer.

After the rebuild the user converted again and the pages were still
half-empty (the old ON default had been saved into their settings):

> C:\Users\lunas\Desktop\Univ\2026IS2\공물실(2)\실험\예비레포트
> 여기에 실험2 예비레포트, 2026101227, 최찬호_손글씨 로 해놨거든? 봐봐

> 빈공간은 원본 워드 문서랑 비교해가면서 어떻게 고치는게 좋을지 너가 생각해보고, 그걸 반영해서 EXE까지 다시 만들어볼래? 만들면 내가 써볼개

The decision was delegated. Outcome: fill-first stays (their Word files show
figure space and natural page ends, never Enter-padding), the stale saved
setting is ignored, and mirror mode's missed in-equation marker is fixed.

## [2026-09-30] 16장 연습문제 — 문단 중간 빈 줄, 쪽 끝으로 밀린 "easily." / 적응형 레이아웃

(스샷 1: 손글씨 16.136 (a) — 한 문단인데 첫 줄과 둘째 줄 사이에 빈 줄.
스샷 2: 같은 부분의 워드 원본 — 줄바꿈 없음.
스샷 3: (b) — "…so H⁺ is lost more" 가 쪽 마지막 줄, "easily." 한 단어만
다음 쪽 첫 줄.)

> 씨발
> 이거 원본은 줄바꿈이 없는데 왜이러지??
> 설마 그 전에 했던 페이지 다 채우는 그거때문에 그런가?
>
> 글고 좀 이 손글씨쌀먹 앱을 적응형으로 만들 필요가 있어보여. 지금 보면 만약에 사람이 썼다고 한다면 저 easily를 전에 문장에 그냥 이어서 썼겠지, 근데 지금 보면 그냥 다음 페이지로 넘겨버렸잖아. 그런건 사람이면 당연히 안하는 거니까 그런거도 해야겠지

Adds scope: the layout must not do what a person copying by hand would
obviously not do (the user's word: "적응형"). Nothing earlier is cancelled.

## [2026-09-30] 창 크기가 더 안 줄어듦

(스샷: 손글씨쌀먹 창이 화면 왼쪽 약 2/3를 차지, 오른쪽은 Windows 창 스냅
선택 화면.)

> 아 글고 보면 알겠지만 이새끼 사이즈가 더 안줄어드니까 그거도 수정해라

Adds scope: the GUI window must be able to shrink (e.g. snap to half the
screen).
