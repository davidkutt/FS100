import subprocess
from pathlib import Path
from typing import Any

import pytest

from ai_service import ingest
from ai_service.ingest import Section, chunk, convert_pdf, parents, parse, pdf_sections
from support import docling_document

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = Path(__file__).parents[3] / "data/sample-docs"

MARKDOWN = b"""# Runbook
Intro text.

## Rollback
Undo the release.

```bash
# not a heading inside a fence
kubectl rollout undo deployment/api
```

### Verify
Check the dashboard.

## Empty

# Appendix
Done.
"""


def test_markdown_sections_carry_their_heading_path() -> None:
    sections = parse("runbook.md", MARKDOWN)

    assert [s.heading for s in sections] == [
        "Runbook",
        "Runbook › Rollback",  # noqa: RUF001
        "Runbook › Rollback › Verify",  # noqa: RUF001
        "Appendix",
    ]
    assert "# not a heading inside a fence" in sections[1].text
    assert all(s.page is None for s in sections)


def test_pdf_sections_carry_their_page_number() -> None:
    sections = parse("two-pages.pdf", (FIXTURES / "two-pages.pdf").read_bytes())

    assert [s.page for s in sections] == [1, 2]
    assert "rollout undo" in sections[0].text
    assert "pg_dump" in sections[1].text


def test_docling_sections_follow_headings_and_pages_with_tables_as_markdown() -> None:
    sections = pdf_sections(docling_document())

    assert [(s.page, s.heading) for s in sections] == [
        (1, "SLO handbook › Targets"),  # noqa: RUF001
        (2, "SLO handbook › Targets"),  # noqa: RUF001 — the table continues the section
        (2, "SLO handbook › Alerts › Burn rate"),  # noqa: RUF001 — "Alerts" alone is only a heading
    ]
    assert sections[0].text == "## Targets\n\nChat availability is 99.5 percent."
    assert sections[1].text.splitlines() == [
        "| Journey | Target |",
        "|---|---|",
        "| login | 99.9 |",
    ]
    assert sections[2].text == "### Burn rate\n\nPage on a 14x burn rate."
    untitled = pdf_sections(docling_document(title=False))
    assert [s.heading for s in untitled] == ["Targets", "Targets", "Alerts › Burn rate"]  # noqa: RUF001


def test_pdfs_go_through_docling_in_a_child_process(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def child(command: list[str], **_: Any) -> None:
        commands.append(command)
        Path(command[-1]).write_text('{"name": "parsed"}')

    monkeypatch.setattr(subprocess, "run", child)

    assert convert_pdf(b"%PDF") == {"name": "parsed"}
    assert commands[0][1:4] == ["-I", "-m", "ai_service.ingest"]


@pytest.mark.parametrize(
    "error",
    [subprocess.TimeoutExpired("docling", 300), subprocess.CalledProcessError(1, "x", b"", b"!")],
    ids=["timeout", "crash"],
)
def test_pypdf_takes_over_when_docling_fails(
    monkeypatch: pytest.MonkeyPatch, error: subprocess.SubprocessError
) -> None:
    def child(*_: Any, **__: Any) -> None:
        raise error

    monkeypatch.setattr(ingest, "convert_pdf", convert_pdf)  # the real one, not conftest's
    monkeypatch.setattr(subprocess, "run", child)

    sections = parse("two-pages.pdf", (FIXTURES / "two-pages.pdf").read_bytes())

    assert [s.page for s in sections] == [1, 2]


def test_html_sections_carry_their_heading_path() -> None:
    page = b"""<html><head><title>Service</title><script>var x</script></head><body>
    <nav>Home</nav><h1>Service</h1><p>Expose an app.</p>
    <h2 id="ports">
      Port <code>definitions</code><a href="#ports">#</a>
    </h2><table><tr><th>Type</th><td>ClusterIP</td></tr></table></body></html>"""

    sections = parse("service.html", page)

    assert [(s.heading, s.text.splitlines()[-1]) for s in sections] == [
        (None, "Home"),
        ("Service", "Expose an app."),
        ("Service › Port definitions", "ClusterIP"),  # noqa: RUF001
    ]


def test_txt_is_one_section() -> None:
    assert parse("notes.TXT", b"\xef\xbb\xbfplain text") == [Section("plain text")]


def test_unsupported_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported file type"):
        parse("slides.pptx", b"PK")


def test_chunks_overlap_and_keep_their_location() -> None:
    chunks = chunk([Section("aaaa bbbb cccc dddd eeee", page=3)], size=10, overlap=5)

    assert chunks == [
        Section("aaaa bbbb", page=3),
        Section("bbbb cccc", page=3),
        Section("cccc dddd", page=3),
        Section("dddd eeee", page=3),
    ]


def test_chunker_prefers_paragraphs_and_falls_back_to_characters() -> None:
    paragraphs = chunk([Section("para one.\n\npara two.\n\n---", heading="H")], size=12, overlap=0)
    word = chunk([Section("x" * 25)], size=10, overlap=0)

    assert paragraphs == [Section("para one.", heading="H"), Section("para two.", heading="H")]
    assert [c.text for c in word] == ["x" * 10, "x" * 10, "x" * 5]


def test_parents_hold_their_chunks() -> None:
    section = Section("aaaa bbbb cccc dddd eeee", heading="H")

    assert parents([section], size=9, overlap=0, parent_size=14) == [
        (
            Section("aaaa bbbb cccc", heading="H"),
            [Section("aaaa bbbb", heading="H"), Section("cccc", heading="H")],
        ),
        (Section("dddd eeee", heading="H"), [Section("dddd eeee", heading="H")]),
    ]
    assert parents([section], size=14, overlap=0, parent_size=0) == [
        (Section("aaaa bbbb cccc", heading="H"), [Section("aaaa bbbb cccc", heading="H")]),
        (Section("dddd eeee", heading="H"), [Section("dddd eeee", heading="H")]),
    ]


def test_chunks_never_exceed_the_size() -> None:
    text = (CORPUS / "runbook-rollback.md").read_bytes()

    chunks = chunk(parse("runbook-rollback.md", text), size=300, overlap=50)

    assert len(chunks) > 5
    assert max(len(c.text) for c in chunks) <= 300
