from pathlib import Path

import pytest

from ai_service.ingest import Section, chunk, parse

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
    paragraphs = chunk([Section("para one.\n\npara two.", heading="H")], size=12, overlap=0)
    word = chunk([Section("x" * 25)], size=10, overlap=0)

    assert paragraphs == [Section("para one.", heading="H"), Section("para two.", heading="H")]
    assert [c.text for c in word] == ["x" * 10, "x" * 10, "x" * 5]


def test_chunks_never_exceed_the_size() -> None:
    text = (CORPUS / "runbook-rollback.md").read_bytes()

    chunks = chunk(parse("runbook-rollback.md", text), size=300, overlap=50)

    assert len(chunks) > 5
    assert max(len(c.text) for c in chunks) <= 300
