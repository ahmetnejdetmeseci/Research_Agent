"""ArXiv Atom API adapter."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree

import httpx
from pydantic import ValidationError

from researchpilot import __version__
from researchpilot.domain import Paper, PaperSource

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_REQUEST_DELAY_SECONDS = 3.0
DEFAULT_PAGE_SIZE = 100
ATOM = "{http://www.w3.org/2005/Atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
VERSION_SUFFIX = re.compile(r"v\d+$")
USER_AGENT = f"ResearchPilot/{__version__} (personal research assistant)"


class ArxivError(Exception):
    """An ArXiv request or response problem safe to show to a user."""


class ArxivResponseError(ArxivError):
    """An ArXiv response that cannot be converted to domain data."""


@dataclass(frozen=True)
class ArxivPage:
    """One parsed Atom result page."""

    total_results: int
    papers: tuple[Paper, ...]


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _required_text(
    element: ElementTree.Element,
    tag: str,
    field: str,
) -> str:
    child = element.find(tag)
    if child is None or child.text is None or not child.text.strip():
        raise ArxivResponseError(f"ArXiv entry is missing required {field}")
    return _normalized_text(child.text)


def _external_id(entry_url: str) -> str:
    path = unquote(urlparse(entry_url).path)
    marker = "/abs/"
    if marker not in path:
        raise ArxivResponseError(f"ArXiv entry has an invalid ID URL: {entry_url}")
    identifier = path.partition(marker)[2].strip("/")
    identifier = VERSION_SUFFIX.sub("", identifier)
    if not identifier:
        raise ArxivResponseError(f"ArXiv entry has an invalid ID URL: {entry_url}")
    return identifier


def _paper_from_entry(entry: ElementTree.Element) -> Paper:
    entry_url = _required_text(entry, f"{ATOM}id", "id")
    authors = [
        _normalized_text(author.text)
        for author in entry.findall(f"{ATOM}author/{ATOM}name")
        if author.text is not None and author.text.strip()
    ]
    categories = list(
        dict.fromkeys(
            category.attrib["term"].strip()
            for category in entry.findall(f"{ATOM}category")
            if category.attrib.get("term", "").strip()
        )
    )
    pdf_url = next(
        (
            link.attrib.get("href")
            for link in entry.findall(f"{ATOM}link")
            if link.attrib.get("title") == "pdf"
            or link.attrib.get("type") == "application/pdf"
        ),
        None,
    )

    try:
        return Paper(
            source=PaperSource.ARXIV,
            external_id=_external_id(entry_url),
            title=_required_text(entry, f"{ATOM}title", "title"),
            abstract=_required_text(entry, f"{ATOM}summary", "summary"),
            authors=authors,
            published_at=_required_text(entry, f"{ATOM}published", "published date"),
            updated_at=_required_text(entry, f"{ATOM}updated", "updated date"),
            url=entry_url,
            pdf_url=pdf_url,
            categories=categories,
        )
    except ValidationError as exc:
        raise ArxivResponseError(f"ArXiv entry contains invalid metadata: {exc}") from exc


def parse_arxiv_feed(content: bytes) -> ArxivPage:
    """Convert an ArXiv Atom document into normalized paper models."""

    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ArxivResponseError(f"ArXiv returned malformed XML: {exc}") from exc

    if root.tag != f"{ATOM}feed":
        raise ArxivResponseError("ArXiv response does not contain an Atom feed")

    total_element = root.find(f"{OPENSEARCH}totalResults")
    if total_element is None or total_element.text is None:
        raise ArxivResponseError("ArXiv response is missing totalResults")
    try:
        total_results = int(total_element.text.strip())
    except ValueError as exc:
        raise ArxivResponseError("ArXiv totalResults is not an integer") from exc
    if total_results < 0:
        raise ArxivResponseError("ArXiv totalResults cannot be negative")

    papers = tuple(
        _paper_from_entry(entry) for entry in root.findall(f"{ATOM}entry")
    )
    return ArxivPage(total_results=total_results, papers=papers)


class ArxivSource:
    """Discover papers through ArXiv's paginated Atom API."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        base_url: str = ARXIV_API_URL,
        page_size: int = DEFAULT_PAGE_SIZE,
        request_delay: float = ARXIV_REQUEST_DELAY_SECONDS,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if page_size < 1 or page_size > 2_000:
            raise ValueError("page_size must be between 1 and 2000")
        if request_delay < 0:
            raise ValueError("request_delay cannot be negative")
        self._client = client
        self._base_url = base_url
        self._page_size = page_size
        self._request_delay = request_delay
        self._sleep = sleeper

    def search(
        self,
        *,
        categories: Sequence[str],
        submitted_after: datetime,
        submitted_before: datetime,
        max_results: int,
    ) -> list[Paper]:
        """Search configured categories over a GMT submission-date range."""

        if not categories:
            raise ValueError("at least one ArXiv category is required")
        if submitted_after.tzinfo is None or submitted_before.tzinfo is None:
            raise ValueError("ArXiv query timestamps must include a timezone")
        if submitted_after >= submitted_before:
            raise ValueError("submitted_after must be earlier than submitted_before")
        if max_results < 1:
            raise ValueError("max_results must be positive")

        search_query = self._search_query(
            categories,
            submitted_after,
            submitted_before,
        )
        papers: list[Paper] = []
        start = 0

        while len(papers) < max_results:
            page_limit = min(self._page_size, max_results - len(papers))
            page = self._request_page(search_query, start, page_limit)
            remaining = max_results - len(papers)
            papers.extend(page.papers[:remaining])
            returned = len(page.papers)
            start += returned

            target = min(page.total_results, max_results)
            if returned == 0 or start >= target or len(papers) >= max_results:
                break
            self._sleep(self._request_delay)

        return papers

    @staticmethod
    def _search_query(
        categories: Sequence[str],
        submitted_after: datetime,
        submitted_before: datetime,
    ) -> str:
        category_query = " OR ".join(f"cat:{category}" for category in categories)
        start = submitted_after.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
        end = submitted_before.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
        return (
            f"({category_query}) AND "
            f"submittedDate:[{start} TO {end}]"
        )

    def _request_page(
        self,
        search_query: str,
        start: int,
        max_results: int,
    ) -> ArxivPage:
        try:
            response = self._client.get(
                self._base_url,
                params={
                    "search_query": search_query,
                    "start": start,
                    "max_results": max_results,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ArxivError("ArXiv request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise ArxivError(
                f"ArXiv returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise ArxivError(f"ArXiv request failed: {exc}") from exc
        return parse_arxiv_feed(response.content)
