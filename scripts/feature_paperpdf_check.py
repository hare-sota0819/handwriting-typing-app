"""Feature verification: user-supplied PDF paper background.

Checks:
- NO --paper: procedural output is byte-identical to the pre-feature baseline
  (regression proof that nothing else changed).
- single-page --paper: ink is composited over the background (output differs
  from procedural, and matches the background's tone away from ink).
- multi-page document + single-page background: every page shows the background.
- fit cover/stretch/contain on an off-aspect background behave as documented
  (cover/stretch fill the page edge-to-edge; contain letterboxes).
- seed reproducibility holds end-to-end with a paper PDF.
Writes viewable outputs to out/. Exit 0 = pass.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from PIL import Image

import make_paper_fixtures
import make_samples
from handwriting.compositor import PaperStyle
from handwriting.document_model import Document, Paragraph, TextRun
from handwriting.pipeline import render_document


# These goldens were baselined on the Phase 1 synthetic store; the pipeline's
# default store is now whatever glyphs/ holds, so pin it here.
from handwriting.synthglyphs import DEFAULT_STORE as _SYNTH  # noqa: E402
_render_document = render_document


def render_document(*args, **kwargs):  # noqa: E302
    kwargs.setdefault("store_root", _SYNTH)
    return _render_document(*args, **kwargs)
from handwriting.style import HandwritingStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"

# Baseline hashes of the procedural (no-paper) output at seed=4. Two goldens:
# CLEAN (effects=False) anchors the plain render path; EFFECTS (default style)
# adds the scanned-look chain (stage 0 residue threshold + stage 2 ink
# density/pressure value jitter and scanner tone; the stage-0/1-only output is
# pinned by feature_effects2_check). This check still proves --paper doesn't
# perturb the base output.
# RE-BASELINED 2026-08-05 for the user-approved default look (bigger at
# base_size_px 64, every wobble source zeroed, intra-word gap 0.24 -> 0.12).
# The old hashes pinned the pre-approval style; this is a deliberate change of
# the default, not a relaxation — the check still refuses any later drift.
# RE-BASELINED 2026-08-07: glyphs are now seated by their own ink at the depth
# a reference font gives each character (handwriting/metrics.py), instead of by
# the printed guide recorded at capture time. Digits and colons in this hand were
# written clear of that guide and floated above the line. Deliberate change of
# rendering, not a relaxation; the check still refuses any later drift.
# RE-BASELINED 2026-08-13 (Millikan-render review, user-reported): descenders
# (g/j/p/q/y) are seated by their captured baseline again (their tails run
# deeper than the reference font's — font-depth seating lifted them off the
# line), trailing punctuation/brackets/hyphen get real air, and word_gap_frac
# tightened 1.5 -> 1.2. Deliberate change, not a relaxation.
# RE-BASELINED 2026-08-13 (2): handwriting rhythm defaults chosen by the
# user per-knob (word_drift 6, line_rise 4.5, step jitter 3.5%, margin
# drift 10; word tilt dropped) + the word-walk RNG replaced the sinusoid.
# Deliberate change of the default look, not a relaxation.
# RE-BASELINED 2026-08-14 (multi only): bracket-vs-alnum pair gap raised
# 1.2 -> 2.0 ("(1)"/"(5)" still read cramped to the user). plain has no
# brackets, so its hashes are unchanged. Deliberate, not a relaxation.
# RE-BASELINED 2026-09-16 (clean only): the per-glyph ink fade now belongs to
# the scanned look alone — on a clean page it left random letters grey next to
# solid equations (user report). EFFECTS hashes are unchanged. Deliberate.
CLEAN_BASELINE = {
    "plain": (1, "b2163f8af78390d743475343847bee35668670a9c145442c2540cd4ccfffad43"),
    "multi": (1, "791c173f357766887dece27539ab498bb6820c58aaeb01771e0f8a742c6fe305"),
}
EFFECTS_BASELINE = {
    "plain": (1, "0b45cf1d18ba63220795782b7a0f79612c719cb6abd0472fee53da8f14075ebc"),
    "multi": (1, "8aa52f117bf22dd716d47dee6bff2ab2a686bb37bc3d5abff5a6c17ad4e18c43"),
}


def digest(pages) -> str:
    return hashlib.sha256(b"".join(p.tobytes() for p in pages)).hexdigest()


def long_doc(n=40) -> Document:
    words = ("alpha beta gamma delta epsilon zeta eta theta iota kappa "
             "lambda mu nu xi omicron pi rho sigma tau upsilon").split()
    paras = [
        Paragraph(runs=[TextRun(text=" ".join(words) + " " + " ".join(words) + ".")])
        for _ in range(n)
    ]
    return Document(paragraphs=paras)


def main() -> int:
    failures: list[str] = []
    OUT.mkdir(exist_ok=True)
    if not (make_samples.SAMPLES / "plain.docx").exists():
        make_samples.main()
    lined = make_paper_fixtures.SAMPLES / "lined_paper.pdf"
    offaspect = make_paper_fixtures.SAMPLES / "offaspect.pdf"
    # Only (re)generate if missing, so verify.sh doesn't churn the committed
    # fixtures via PDF creation-timestamp changes on every run.
    if not (lined.exists() and offaspect.exists()):
        make_paper_fixtures.main()

    # 1. no-paper regression: byte-identical to baselines, both render paths
    for label, baseline, style in (
        ("clean", CLEAN_BASELINE, HandwritingStyle(effects=False)),
        ("effects", EFFECTS_BASELINE, HandwritingStyle()),
    ):
        for name, (n_ref, h_ref) in baseline.items():
            pages = render_document(f"samples/{name}.docx", seed=4, style=style)
            if len(pages) != n_ref or digest(pages) != h_ref:
                failures.append(
                    f"no-paper {label} output for {name} changed vs baseline "
                    f"({len(pages)} pages, {digest(pages)[:12]}...)"
                )

    # 2. single-page background: differs from procedural, tone matches paper
    plain = "samples/plain.docx"
    proc = render_document(plain, seed=1)
    lined_paper = PaperStyle(background_pdf=lined, fit="cover")
    onpaper = render_document(plain, seed=1, paper=lined_paper)
    if digest(proc) == digest(onpaper):
        failures.append("--paper output identical to procedural (background ignored)")
    # The lined paper's blue rules must show through in a text-free bottom strip;
    # the procedural off-white paper has no bluish pixels there.
    on_strip = np.asarray(onpaper[0])[-300:, :, :].astype(int)
    proc_strip = np.asarray(proc[0])[-300:, :, :].astype(int)
    on_blue = int(np.sum((on_strip[:, :, 2] - on_strip[:, :, 0]) > 15))
    proc_blue = int(np.sum((proc_strip[:, :, 2] - proc_strip[:, :, 0]) > 15))
    if on_blue < 1000:
        failures.append(f"lined-paper rules not visible under output ({on_blue} blue px)")
    if proc_blue != 0:
        failures.append(f"procedural paper unexpectedly has blue px ({proc_blue})")
    onpaper[0].save(OUT / "paper_lined.png")

    # 3. multi-page document + single-page background: every page shows it
    long_pages = _render_doc(long_doc(), seed=1, paper=lined_paper)
    if len(long_pages) < 2:
        failures.append(f"long doc did not paginate ({len(long_pages)} page)")
    for i, pg in enumerate(long_pages):
        corner = np.asarray(pg)[20:60, 20:60, :].mean(axis=(0, 1))
        if corner[2] < 200:
            failures.append(f"page {i} corner lacks background tone: {corner}")
            break
    for i, pg in enumerate(long_pages[:2]):
        pg.save(OUT / f"paper_multipage_p{i+1}.png")

    # 4. fit modes on an off-aspect background with edge markers.
    # Detect the red LEFT/RIGHT bars and blue TOP/BOTTOM bars at the page edges.
    # Expected (red-at-side, blue-at-top): cover=(no,yes) stretch=(yes,yes)
    # contain=(yes,no) — a unique signature per mode.
    # Detect only the *saturated* bars (r-b>150 / b-r>150); the contain
    # letterbox fill is the average edge color (a desaturated mix) and must
    # NOT register as a bar.
    def red_at_sides(arr) -> bool:
        band = np.concatenate([arr[:, :12, :], arr[:, -12:, :]], axis=1).astype(int)
        return bool(np.mean((band[:, :, 0] - band[:, :, 2]) > 150) > 0.05)

    def blue_at_topbottom(arr) -> bool:
        band = np.concatenate([arr[:12, :, :], arr[-12:, :, :]], axis=0).astype(int)
        return bool(np.mean((band[:, :, 2] - band[:, :, 0]) > 150) > 0.05)

    expected = {  # (red_at_sides, blue_at_topbottom)
        "cover": (False, True),
        "stretch": (True, True),
        "contain": (True, False),
    }
    fit_digests = {}
    for mode in ("cover", "stretch", "contain"):
        ps = PaperStyle(background_pdf=offaspect, fit=mode)
        img = render_document(plain, seed=1, paper=ps)[0]
        img.save(OUT / f"paper_fit_{mode}.png")
        fit_digests[mode] = digest([img])
        arr = np.asarray(img)
        got = (red_at_sides(arr), blue_at_topbottom(arr))
        if got != expected[mode]:
            failures.append(
                f"fit={mode}: edge markers {got} != documented {expected[mode]} "
                f"(red@sides, blue@top/bottom)"
            )
    if len(set(fit_digests.values())) != 3:
        failures.append(f"fit modes did not all differ: {fit_digests}")

    # 5. seed reproducibility with a paper PDF
    a = render_document(plain, seed=9, paper=lined_paper)
    b = render_document(plain, seed=9, paper=lined_paper)
    c = render_document(plain, seed=10, paper=lined_paper)
    if digest(a) != digest(b):
        failures.append("same seed + paper PDF not reproducible")
    if digest(a) == digest(c):
        failures.append("different seeds + paper PDF produced identical output")

    print("outputs in:", OUT)
    print()
    if failures:
        print(f"FAIL ({len(failures)} problems):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: paper-background feature checks all green")
    return 0


def _render_doc(document, seed, paper):
    """Render an in-memory Document (bypassing the parser) through the rest of
    the pipeline, so pagination can be forced without authoring a huge .docx."""
    from handwriting.compositor import compose_pages
    from handwriting.glyphstore import GlyphStore
    from handwriting.layout import PageSpec, layout_document
    from handwriting.renderer import render_pages
    from handwriting.style import HandwritingStyle
    from handwriting.synthglyphs import DEFAULT_STORE
    from handwriting.variation import apply_variation

    store = GlyphStore(DEFAULT_STORE)
    style = HandwritingStyle()
    counts = {c: len(store.entry(c).variants) for c in store.characters}
    pages = layout_document(document, store, style, PageSpec(), seed=seed)
    pages = apply_variation(pages, counts, style, seed=seed)
    ink = render_pages(pages, store, style)
    return compose_pages(ink, paper, seed=seed)


if __name__ == "__main__":
    sys.exit(main())
