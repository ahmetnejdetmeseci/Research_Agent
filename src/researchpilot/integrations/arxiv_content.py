"""Bounded ArXiv PDF download and text extraction."""

from __future__ import annotations

from io import BytesIO

import httpx
from pypdf import PdfReader

from researchpilot.domain import ContentReference, Paper, RetrievedContent
from researchpilot.domain.ports import ContentRetrievalError
from researchpilot.integrations.arxiv import USER_AGENT


class ArxivContentError(ContentRetrievalError):
    """An ArXiv PDF acquisition or extraction failure."""


class ArxivPDFContentProvider:
    """Download and extract bounded text from a paper's ArXiv PDF."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def retrieve(
        self,
        paper: Paper,
        *,
        max_download_bytes: int,
        max_pages: int,
        max_characters: int,
    ) -> RetrievedContent:
        """Return bounded PDF text or a fallback-safe content error."""

        if paper.pdf_url is None:
            raise ArxivContentError("paper does not provide a PDF URL")
        if min(max_download_bytes, max_pages, max_characters) < 1:
            raise ValueError("full-paper content limits must be positive")

        pdf_url = str(paper.pdf_url)
        document = self._download(pdf_url, max_download_bytes)
        if not document.lstrip().startswith(b"%PDF-"):
            raise ArxivContentError("paper download is not a PDF document")

        try:
            reader = PdfReader(BytesIO(document), strict=False)
            if reader.is_encrypted:
                raise ArxivContentError("paper PDF is encrypted")
            total_pages = len(reader.pages)
        except ArxivContentError:
            raise
        except Exception as exc:
            raise ArxivContentError(f"could not read paper PDF: {exc}") from exc

        page_limit = min(total_pages, max_pages)
        extracted_parts: list[str] = []
        warnings: list[str] = []
        characters = 0
        processed_pages = 0
        truncated = total_pages > max_pages

        for page_number in range(page_limit):
            try:
                page_text = reader.pages[page_number].extract_text() or ""
            except Exception as exc:
                warnings.append(
                    f"page {page_number + 1} could not be extracted: {exc}"
                )
                processed_pages += 1
                continue
            processed_pages += 1
            normalized = self._normalize_text(page_text)
            if not normalized:
                continue
            separator_size = 2 if extracted_parts else 0
            remaining = max_characters - characters - separator_size
            if remaining <= 0:
                truncated = True
                break
            if len(normalized) > remaining:
                normalized = normalized[:remaining].rstrip()
                truncated = True
                character_limit_hit = True
            else:
                character_limit_hit = False
            if normalized:
                extracted_parts.append(normalized)
                characters += separator_size + len(normalized)
            if character_limit_hit:
                break

        text = "\n\n".join(extracted_parts).strip()
        if not text:
            detail = f" ({'; '.join(warnings)})" if warnings else ""
            raise ArxivContentError(
                "paper PDF contains no extractable text within configured limits"
                + detail
            )

        return RetrievedContent(
            text=text,
            references=[
                ContentReference(
                    label="ArXiv PDF",
                    locator=pdf_url,
                    characters=len(text),
                    truncated=truncated,
                    pages=max(1, processed_pages),
                )
            ],
            truncated=truncated,
            warnings=warnings,
        )

    def _download(self, url: str, max_bytes: int) -> bytes:
        try:
            with self._client.stream(
                "GET",
                url,
                headers={"User-Agent": USER_AGENT},
            ) as response:
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_size = int(content_length)
                    except ValueError:
                        declared_size = 0
                    if declared_size > max_bytes:
                        raise ArxivContentError(
                            "paper PDF exceeds the configured download limit"
                        )
                document = bytearray()
                for chunk in response.iter_bytes():
                    document.extend(chunk)
                    if len(document) > max_bytes:
                        raise ArxivContentError(
                            "paper PDF exceeds the configured download limit"
                        )
        except ArxivContentError:
            raise
        except httpx.TimeoutException as exc:
            raise ArxivContentError("paper PDF download timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise ArxivContentError(
                f"paper PDF returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise ArxivContentError(f"paper PDF download failed: {exc}") from exc
        return bytes(document)

    @staticmethod
    def _normalize_text(value: str) -> str:
        lines = [" ".join(line.split()) for line in value.splitlines()]
        return "\n".join(line for line in lines if line).strip()
