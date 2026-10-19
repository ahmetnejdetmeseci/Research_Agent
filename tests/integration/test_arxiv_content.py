from datetime import datetime, timezone

import httpx
import pytest

from researchpilot.domain import Paper, PaperSource
from researchpilot.integrations.arxiv_content import (
    ArxivContentError,
    ArxivPDFContentProvider,
)


def paper() -> Paper:
    return Paper(
        source=PaperSource.ARXIV,
        external_id="2601.00001",
        title="Planning paper",
        abstract="Planning abstract.",
        authors=["Ada Lovelace"],
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        url="https://arxiv.org/abs/2601.00001",
        pdf_url="https://arxiv.org/pdf/2601.00001",
    )


def text_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode())
        document.extend(body)
        document.extend(b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(document)


def test_pdf_is_downloaded_and_extracted_with_provenance() -> None:
    content = text_pdf("Full paper planning contribution")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=content,
            headers={"Content-Type": "application/pdf"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ArxivPDFContentProvider(client).retrieve(
            paper(),
            max_download_bytes=100_000,
            max_pages=10,
            max_characters=10_000,
        )

    assert "Full paper planning contribution" in result.text
    assert result.references[0].pages == 1
    assert result.references[0].locator == "https://arxiv.org/pdf/2601.00001"
    assert result.truncated is False


def test_pdf_text_is_truncated_at_character_limit() -> None:
    content = text_pdf("A long planning contribution")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ArxivPDFContentProvider(client).retrieve(
            paper(),
            max_download_bytes=100_000,
            max_pages=10,
            max_characters=8,
        )

    assert result.text == "A long p"
    assert result.truncated is True


def test_oversized_pdf_is_rejected_before_extraction() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"%PDF-1.4",
            headers={"Content-Length": "100001"},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArxivContentError, match="download limit"):
            ArxivPDFContentProvider(client).retrieve(
                paper(),
                max_download_bytes=100_000,
                max_pages=10,
                max_characters=1_000,
            )


def test_non_pdf_response_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not a pdf", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArxivContentError, match="not a PDF"):
            ArxivPDFContentProvider(client).retrieve(
                paper(),
                max_download_bytes=100_000,
                max_pages=10,
                max_characters=1_000,
            )
