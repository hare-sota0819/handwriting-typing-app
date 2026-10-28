# Bugs (Unresolved)

<!--
Unresolved bugs and debugging dead ends. Managed by the debug-log skill.
When a bug is resolved, move its entry to SOLVED.md.

Entry format:

## [YYYY-MM-DD] One-line summary
- **Symptom**: What went wrong and how it manifested
- **Repro conditions**: When / under what circumstances it occurs
- **Attempts**: Numbered list of what was tried, INCLUDING failed approaches
- **Root cause**: unknown / unresolved
- **Fix**: unknown / unresolved
- **Prevention**: (leave empty until resolved)
-->

## [2026-09-20] `⇐` has no handwriting, so `\Leftarrow` draws a grey box
- **Symptom**: `⟸` aliases to `⇐`, and `⇐` is in no charset file, so both
  codepoints resolve to nothing and the renderer draws a placeholder box.
  Found by the new alias check while fixing the `ϵ` boxes, not by a user
  report — no document has hit it yet.
- **Repro conditions**: any equation with `\Leftarrow` / `\Longleftarrow`.
  Its partner `⇒` was collected; this one was simply missed.
- **Attempts**: 1. aliasing to `←` was offered and the user declined —
  they will write the glyph themselves. 2. `scripts/make_template_arrows.py`
  generates the one-page collection sheet (`template/arrows/`, 10 cells).
- **Root cause**: `⇐` was never added to `template/charset_math.txt`.
- **Fix**: pending the user's written sheet. Then:
  `split_ipad.py <export.pdf> --layout template/arrows/template_layout.json
  --out glyphs/ipad_arrows`, merge into the store, and drop `⇐` from
  `PENDING_GLYPHS` in `scripts/feature_docmath_check.py`.
- **Prevention**: `check_aliases` fails on any alias target that resolves to
  nothing unless it is listed in `PENDING_GLYPHS`, and every pending target
  must have a collection sheet waiting for it.
