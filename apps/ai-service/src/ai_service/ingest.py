import re
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import PurePath

from pypdf import PdfReader

HEADING_SEPARATOR = " › "  # noqa: RUF001 — plan.md §7.5 format
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = ("```", "~~~")
_SEPARATORS = ("\n\n", "\n", ". ", " ", "")


class UnsupportedDocumentError(ValueError):
    pass


@dataclass(frozen=True)
class Section:
    """A piece of a document with its location: PDF page (1-based) or Markdown heading path."""

    text: str
    page: int | None = None
    heading: str | None = None


def parse(filename: str, data: bytes) -> list[Section]:
    """PDF page by page (pypdf), Markdown section by section, TXT as one section (D8)."""
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".pdf":
        pages = PdfReader(BytesIO(data)).pages
        return [Section(page.extract_text(), page=number) for number, page in enumerate(pages, 1)]
    if suffix in (".md", ".markdown"):
        return _parse_markdown(data.decode("utf-8-sig"))
    if suffix == ".txt":
        return [Section(data.decode("utf-8-sig"))]
    raise UnsupportedDocumentError(f"Unsupported file type {suffix!r}; expected PDF, MD or TXT")


def _parse_markdown(text: str) -> list[Section]:
    blocks: list[tuple[list[str], list[str]]] = [([], [])]  # (heading path, lines)
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith(_FENCE):
            fenced = not fenced
        heading = None if fenced else _HEADING.match(line)
        if heading:
            blocks.append(([*blocks[-1][0][: len(heading[1]) - 1], heading[2]], []))
        blocks[-1][1].append(line)
    return [
        Section("\n".join(lines), heading=HEADING_SEPARATOR.join(path) or None)
        for path, lines in blocks
        if any(line.strip() for line in (lines[1:] if path else lines))  # skip heading-only blocks
    ]


def chunk(sections: list[Section], size: int, overlap: int) -> list[Section]:
    """Recursive character splitter; chunks never cross a page or Markdown section."""
    return [
        replace(section, text=text)
        for section in sections
        for text in _split(section.text, size, overlap, _SEPARATORS)
    ]


def _split(text: str, size: int, overlap: int, separators: tuple[str, ...]) -> list[str]:
    if len(text) <= size:
        return [text.strip()] if text.strip() else []
    index = next(i for i, sep in enumerate(separators) if not sep or sep in text)
    separator, finer = separators[index], separators[index + 1 :]
    chunks: list[str] = []
    window: list[str] = []
    for part in text.split(separator) if separator else list(text):
        if len(part) > size:
            chunks += [separator.join(window)] if window else []
            window = []
            chunks += _split(part, size, overlap, finer)
            continue
        if window and len(separator.join([*window, part])) > size:
            chunks.append(separator.join(window))
            while window and (
                len(separator.join(window)) > overlap or len(separator.join([*window, part])) > size
            ):
                window.pop(0)
        window.append(part)
    chunks += [separator.join(window)] if window else []
    return [stripped for c in chunks if (stripped := c.strip())]
