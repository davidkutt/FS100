import asyncio
import json
import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from importlib.metadata import version
from io import BytesIO
from pathlib import Path, PurePath
from typing import Any
from uuid import UUID

from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.table.table import TableItem
from docling_core.types.doc.items.text import SectionHeaderItem, TextItem, TitleItem
from pypdf import PdfReader

from ai_service.storage import Store

HEADING_SEPARATOR = " › "  # noqa: RUF001 — plan.md §7.5 format
# A stored parse is reused while it comes from this version (D59).
PARSER = f"docling {version('docling-slim')}"
DOCLING_TIMEOUT_S = 300  # a 36-page PDF takes ~30 s warm (ADR-0018)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = ("```", "~~~")
_SEPARATORS = ("\n\n", "\n", ". ", " ", "")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Section:
    """A piece of a document with its location: PDF page (1-based) or Markdown heading path. A
    chunk may carry its context and sub-topics (D60, `contextual.py`)."""

    text: str
    page: int | None = None
    heading: str | None = None
    context: str | None = None
    topics: tuple[str, ...] = ()


def supported(filename: str) -> bool:
    return PurePath(filename).suffix.lower() in (".pdf", ".md", ".markdown", ".txt")


def parse(filename: str, data: bytes) -> list[Section]:
    """PDF by Docling (pypdf if it fails), Markdown section by section, TXT as one section (D8,
    D59)."""
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".pdf":
        return _pdf(convert_pdf(data), data)
    if suffix in (".md", ".markdown"):
        return _parse_markdown(data.decode("utf-8-sig"))
    if suffix == ".txt":
        return [Section(data.decode("utf-8-sig"))]
    raise ValueError(f"Unsupported file type {suffix!r}; expected PDF, MD or TXT")


async def parse_stored(
    store: Store, doc_id: UUID, version: int, filename: str, data: bytes
) -> list[Section]:
    """`parse` with a PDF's DoclingDocument kept in the store, so a re-index re-parses only for
    another Docling version (D55, D59)."""
    if PurePath(filename).suffix.lower() != ".pdf":
        return await asyncio.to_thread(parse, filename, data)
    document = await store.parsed(doc_id, version, PARSER)
    if document is None and (document := await asyncio.to_thread(convert_pdf, data)):
        await store.put_parsed(doc_id, version, PARSER, document)
    return await asyncio.to_thread(_pdf, document, data)


def convert_pdf(data: bytes) -> dict[str, Any] | None:
    """The PDF's DoclingDocument, converted in a child process so its ~2 GB peak goes back to the
    OS (ADR-0018); None if Docling fails or times out."""
    with tempfile.TemporaryDirectory() as folder:
        source, target = Path(folder, "in.pdf"), Path(folder, "out.json")
        source.write_bytes(data)
        command = [sys.executable, "-I", "-m", __name__, str(source), str(target)]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=DOCLING_TIMEOUT_S)  # noqa: S603
        except subprocess.CalledProcessError as error:
            logger.warning(
                "Docling failed, pypdf instead: %s", error.stderr.decode(errors="replace")[-1000:]
            )
            return None
        except subprocess.TimeoutExpired:
            logger.warning("Docling took over %d s, pypdf instead", DOCLING_TIMEOUT_S)
            return None
        return json.loads(target.read_bytes())


def pdf_sections(document: dict[str, Any]) -> list[Section]:
    """The body in reading order, cut at each heading and page break, under its heading path;
    tables as Markdown. Pictures are left out: no OCR (D59)."""
    doc = DoclingDocument.model_validate(document)
    path: list[tuple[int, str]] = []  # (level, heading); the title is level 0
    blocks: list[tuple[Section, list[str], bool]] = []  # location, lines, starts with a heading
    for item, _ in doc.iterate_items():
        if not isinstance(item, TextItem | TableItem):
            continue
        page = item.prov[0].page_no if item.prov else None
        if isinstance(item, TitleItem | SectionHeaderItem):
            level = item.level if isinstance(item, SectionHeaderItem) else 0
            path = [(above, text) for above, text in path if above < level] + [(level, item.text)]
            here = Section("", page, HEADING_SEPARATOR.join(text for _, text in path))
            blocks.append((here, [f"{'#' * (level + 1)} {item.text}"], True))
            continue
        here = Section("", page, HEADING_SEPARATOR.join(text for _, text in path) or None)
        if not blocks or blocks[-1][0] != here:
            blocks.append((here, [], False))
        text = _table(item.export_to_markdown(doc)) if isinstance(item, TableItem) else item.text
        blocks[-1][1].append(text)
    return [
        replace(here, text="\n\n".join(lines))
        for here, lines, headed in blocks
        if len(lines) > headed  # skip heading-only blocks
    ]


def _table(markdown: str) -> str:
    """Docling pads each cell to its column's width (36-58 % of a table's characters in NIST PDFs)
    and keeps the dot leaders of a table of contents: both would fill the chunks."""
    markdown = re.sub(r"\.{4,}", " … ", markdown)
    markdown = re.sub(r"-{3,}", "---", markdown)
    return re.sub(r" {2,}", " ", markdown)


def _pdf(document: dict[str, Any] | None, data: bytes) -> list[Section]:
    return pdf_sections(document) if document else _pages(data)


def _pages(data: bytes) -> list[Section]:
    pages = PdfReader(BytesIO(data)).pages
    return [Section(page.extract_text(), page=number) for number, page in enumerate(pages, 1)]


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
        if re.search(r"\w", text)  # a rule (`---`) between sections is no chunk
    ]


def parents(
    sections: list[Section], size: int, overlap: int, parent_size: int
) -> list[tuple[Section, list[Section]]]:
    """Each parent with its children (D59): parents of at most `parent_size` characters (0: each
    child is its own parent), children chunked inside them."""
    if not parent_size:
        return [(child, [child]) for child in chunk(sections, size, overlap)]
    return [(parent, chunk([parent], size, overlap)) for parent in chunk(sections, parent_size, 0)]


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


def _convert(source: str, target: str) -> None:
    """The child process of `convert_pdf`."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pdf = PdfFormatOption(pipeline_options=PdfPipelineOptions(do_ocr=False))
    converter = DocumentConverter(format_options={InputFormat.PDF: pdf})
    Path(target).write_text(converter.convert(source).document.model_dump_json())


if __name__ == "__main__":
    _convert(*sys.argv[1:])
