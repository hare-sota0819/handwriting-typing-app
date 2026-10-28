"""Where each character SITS, taken from a reference font.

The store records, per cell, the printed guide line the writer was aiming at —
not where their ink landed. Digits and colons in this hand were written well
clear of that guide, so anchoring on it floats them above the line in the output
(the user: "숫자들이 ㅈㄴ 떠있어. 줄에 안맞고").

A typeface already answers the question "how far below the baseline does this
character's ink reach, and how tall is it" for every character, consistently.
Those two numbers per character are read here from a plain reference font and
expressed in x-heights, so they carry over to any glyph size. The renderer then
seats our ink where the font would have put its own.

The same numbers drive the collection template's size guide, so what the user
writes against and what the renderer expects cannot drift apart.
"""

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# The bundled copy comes first: metrics must be identical on every platform
# (same seed = same page), so never fall back to a system font that merely
# looks similar. System paths remain as a safety net for stripped checkouts.
FONT_CANDIDATES = (
    str(Path(__file__).parent / "data" / "DejaVuSans.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)
_PX = 200          # rendering size for measurement; large enough to be stable


@lru_cache(maxsize=1)
def _font():
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, _PX)
    raise RuntimeError("no reference font found for metrics")


@lru_cache(maxsize=4096)
def _ink_box(ch: str):
    """(top, bottom) of the character's ink relative to the baseline, in px."""
    font = _font()
    pad = _PX
    img = Image.new("L", (_PX * 3, _PX * 3), 255)
    ImageDraw.Draw(img).text((pad, pad), ch, font=font, fill=0)
    box = img.point(lambda v: 255 if v < 200 else 0).getbbox()
    if box is None:
        return None
    ascent, _ = font.getmetrics()
    baseline = pad + ascent
    return box[1] - baseline, box[3] - baseline


@lru_cache(maxsize=1)
def _x_height_px() -> float:
    box = _ink_box("x")
    return float(box[0] * -1) if box else float(_PX) * 0.5


def depth_in_x_heights(ch: str) -> float | None:
    """How far the character's ink falls BELOW the baseline, in x-heights.

    Negative for characters whose ink stops short of the line (an apostrophe),
    positive for descenders. None when the font has no glyph to measure.
    """
    box = _ink_box(ch)
    if box is None:
        return None
    return box[1] / _x_height_px()


def height_in_x_heights(ch: str) -> float | None:
    """Total ink height of the character, in x-heights."""
    box = _ink_box(ch)
    if box is None:
        return None
    return (box[1] - box[0]) / _x_height_px()
