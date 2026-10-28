"""Generate trivial background-PDF fixtures for the paper-background feature.

These are TEST FIXTURES only (created with Pillow, no extra dependency):
- lined_paper.pdf : A4-ish, off-white with faint blue horizontal rules
- offaspect.pdf   : a deliberately wide, non-page-aspect solid color, to
                    exercise cover/stretch/contain fit modes

Run: .venv/bin/python scripts/make_paper_fixtures.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def make_lined() -> Path:
    w, h = 1240, 1754  # matches the default A4 @ 150 dpi page raster
    img = Image.new("RGB", (w, h), (252, 251, 245))
    d = ImageDraw.Draw(img)
    for y in range(160, h - 100, 56):
        d.line([(90, y), (w - 90, y)], fill=(180, 200, 225), width=2)
    d.line([(150, 80), (150, h - 80)], fill=(225, 190, 190), width=2)  # margin rule
    path = SAMPLES / "lined_paper.pdf"
    img.save(path)
    return path


def make_offaspect() -> Path:
    # Wide aspect (2:1) vs the portrait page, with edge markers that make the
    # three fit modes uniquely identifiable:
    #   - RED bars on the far LEFT and RIGHT columns (full height)
    #   - BLUE bars on the TOP and BOTTOM rows (full width)
    # cover crops horizontally -> red edges gone, blue edges kept.
    # stretch fills exactly       -> both red and blue edges kept.
    # contain letterboxes top/bot -> red edges kept, blue edges gone.
    w, h, bar = 1600, 800, 30
    img = Image.new("RGB", (w, h), (245, 245, 245))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, bar, h], fill=(220, 30, 30))          # left  red
    d.rectangle([w - bar, 0, w, h], fill=(220, 30, 30))      # right red
    d.rectangle([0, 0, w, bar], fill=(30, 30, 220))          # top   blue
    d.rectangle([0, h - bar, w, h], fill=(30, 30, 220))      # bottom blue
    path = SAMPLES / "offaspect.pdf"
    img.save(path)
    return path


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    p1, p2 = make_lined(), make_offaspect()
    print(f"wrote {p1} and {p2}")


if __name__ == "__main__":
    main()
