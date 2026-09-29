"""Low-level X12 tokenizing: delimiters, segments, elements, composites.

X12 is positional and delimiter-driven; the delimiters are declared in the ISA header and
must be read from the file rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

ISA_LENGTH = 106  # ISA is fixed-width: 105 characters plus the segment terminator


class X12Error(ValueError):
    """The input is not well-formed X12 for the subset this system parses."""


@dataclass(frozen=True)
class Delimiters:
    element: str
    composite: str
    segment: str

    @classmethod
    def from_isa(cls, raw: str) -> Delimiters:
        """Element separator is the 4th character of ISA, the composite separator is
        ISA16 (character 105), and the segment terminator immediately follows it."""
        text = raw.lstrip()
        if not text.startswith("ISA") or len(text) < ISA_LENGTH:
            raise X12Error("input does not start with a complete ISA segment")
        return cls(element=text[3], composite=text[104], segment=text[105])


@dataclass(frozen=True)
class Segment:
    tag: str
    elements: tuple[str, ...]
    composite_sep: str = ":"

    def el(self, position: int) -> str:
        """1-based element access, matching the implementation guide's numbering
        (CLP01 is `el(1)`). Missing trailing elements read as empty strings, because X12
        omits trailing empty elements."""
        if position < 1:
            raise IndexError("X12 element positions start at 1")
        return self.elements[position - 1] if position <= len(self.elements) else ""

    def composite(self, position: int) -> tuple[str, ...]:
        """Split a composite element such as SVC01 `HC:T1019:U4` into its components."""
        value = self.el(position)
        return tuple(value.split(self.composite_sep)) if value else ()


def tokenize(raw: str) -> list[Segment]:
    """Split an X12 interchange into segments. Tolerates newlines after terminators,
    which most real files and every hand-written fixture contain."""
    delims = Delimiters.from_isa(raw)
    segments: list[Segment] = []
    for chunk in raw.strip().split(delims.segment):
        chunk = chunk.strip("\r\n ")
        if not chunk:
            continue
        tag, *elements = chunk.split(delims.element)
        segments.append(Segment(tag=tag, elements=tuple(elements), composite_sep=delims.composite))
    return segments
