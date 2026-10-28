"""Document Model: the neutral tree between the parser and the layout engine.

The layout engine consumes this model and emits placed glyphs; it must never
need to know what produced a node. Phase 2 adds math by introducing MathBlock
nodes here without changing the Layout/Variation/Renderer/Compositor contracts.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .mathrender import MathInk


@dataclass
class TextRun:
    """A run of plain text characters within a paragraph."""

    text: str


@dataclass
class MathBlock:
    """One Word equation (m:oMath) in its paragraph's run order.

    The parser fills omml_xml/display/index; the math stage (mathrender.py)
    fills latex and ink before layout. index is the equation's position among
    ALL equations of the document body, which is how it is paired with the
    LaTeX pandoc extracts in that same order.
    """

    omml_xml: str
    display: bool = False  # False = inline equation, True = display (own line)
    index: int = 0
    latex: str = ""
    ink: "MathInk | None" = None
    # Word wrote no space on that side ("kg/m" + "3" + ")"): the equation is
    # part of the neighbouring word, not a word of its own, so layout must
    # kern it in instead of opening a word gap.
    tight_left: bool = False
    tight_right: bool = False
    # Horizontal placement of a display equation, as Word justified it
    # ("left" / "center" / "right"); inline equations ignore it.
    align: str = "center"


@dataclass
class WordPageBreak:
    """Where Word's own layout last began a new page, inside a paragraph
    (w:lastRenderedPageBreak). A hint, not an instruction: layout follows it
    only when the style asks to mirror Word's pages."""


@dataclass
class Paragraph:
    """An ordered list of runs: TextRun and MathBlock, in document order
    (plus WordPageBreak hints where a Word page ended inside the paragraph)."""

    runs: list[TextRun | MathBlock | WordPageBreak] = field(default_factory=list)
    page_break_before: bool = False  # Word page break (w:br type=page /
    #                                  w:pageBreakBefore) precedes this one
    word_page_start: bool = False  # Word's last layout began a page here (hint)


@dataclass
class Document:
    """Ordered tree of blocks. Phase 1: paragraphs only."""

    paragraphs: list[Paragraph] = field(default_factory=list)
