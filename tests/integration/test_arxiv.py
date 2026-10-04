from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from researchpilot.application import DiscoverPapers, DiscoveryRequest
from researchpilot.domain import PaperSource
from researchpilot.integrations.arxiv import (
    ArxivError,
    ArxivResponseError,
    ArxivSource,
    parse_arxiv_feed,
)
from researchpilot.persistence import Database, SQLitePaperRepository

FIXTURES = Path(__file__).parents[1] / "fixtures"


def entry_xml(identifier: str) -> str:
    return f"""
    <entry>
      <id>https://arxiv.org/abs/{identifier}v1</id>
      <updated>2026-01-03T12:00:00Z</updated>
      <published>2026-01-02T12:00:00Z</published>
      <title>Paper {identifier}</title>
      <summary>Abstract {identifier}</summary>
      <author><name>Ada Lovelace</name></author>
      <category term="cs.AI" />
      <link title="pdf" href="https://arxiv.org/pdf/{identifier}v1"
            type="application/pdf" />
    </entry>
    """


def feed_xml(identifiers: list[str], total_results: int | None = None) -> bytes:
    total = len(identifiers) if total_results is None else total_results
    entries = "".join(entry_xml(identifier) for identifier in identifiers)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
      <opensearch:totalResults>{total}</opensearch:totalResults>
      {entries}
    </feed>
    """.encode()


def test_parse_feed_normalizes_domain_metadata() -> None:
    page = parse_arxiv_feed((FIXTURES / "arxiv_feed.xml").read_bytes())

    assert page.total_results == 1
    assert len(page.papers) == 1
    paper = page.papers[0]
    assert paper.source is PaperSource.ARXIV
    assert paper.external_id == "2601.00001"
    assert paper.title == "A Useful Agent Paper"
    assert paper.abstract == "An abstract with normalized whitespace."
    assert paper.authors == ["Ada Lovelace", "Alan Turing"]
    assert paper.categories == ["cs.AI", "cs.CL"]
    assert str(paper.pdf_url) == "https://arxiv.org/pdf/2601.00001v2"
    assert paper.published_at.tzinfo is not None


def test_search_builds_category_date_and_sort_parameters() -> None:
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, content=feed_xml(["2601.00001"]), request=request)

    after = datetime(2026, 1, 1, 6, 30, tzinfo=timezone.utc)
    before = datetime(2026, 1, 8, 6, 30, tzinfo=timezone.utc)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        papers = ArxivSource(client).search(
            categories=["cs.AI", "cs.CL"],
            submitted_after=after,
            submitted_before=before,
            max_results=5,
        )

    assert len(papers) == 1
    assert captured_request is not None
    assert captured_request.url.params["search_query"] == (
        "(cat:cs.AI OR cat:cs.CL) AND "
        "submittedDate:[202601010630 TO 202601080630]"
    )
    assert captured_request.url.params["start"] == "0"
    assert captured_request.url.params["max_results"] == "5"
    assert captured_request.url.params["sortBy"] == "submittedDate"
    assert captured_request.url.params["sortOrder"] == "descending"
    assert captured_request.headers["user-agent"].startswith("ResearchPilot/")


def test_search_pages_sequentially_and_delays_between_requests() -> None:
    requests: list[tuple[str, str]] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start = request.url.params["start"]
        maximum = request.url.params["max_results"]
        requests.append((start, maximum))
        identifiers = ["2601.00001", "2601.00002"] if start == "0" else ["2601.00003"]
        return httpx.Response(
            200,
            content=feed_xml(identifiers, total_results=3),
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        papers = ArxivSource(
            client,
            page_size=2,
            sleeper=delays.append,
        ).search(
            categories=["cs.AI"],
            submitted_after=datetime(2026, 1, 1, tzinfo=timezone.utc),
            submitted_before=datetime(2026, 1, 8, tzinfo=timezone.utc),
            max_results=3,
        )

    assert [paper.external_id for paper in papers] == [
        "2601.00001",
        "2601.00002",
        "2601.00003",
    ]
    assert requests == [("0", "2"), ("2", "1")]
    assert delays == [3.0]


def test_timeout_is_translated_to_arxiv_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source = ArxivSource(client)
        with pytest.raises(ArxivError, match="timed out"):
            source.search(
                categories=["cs.AI"],
                submitted_after=datetime(2026, 1, 1, tzinfo=timezone.utc),
                submitted_before=datetime(2026, 1, 2, tzinfo=timezone.utc),
                max_results=1,
            )


def test_http_failure_is_translated_to_arxiv_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        source = ArxivSource(client)
        with pytest.raises(ArxivError, match="HTTP 503"):
            source.search(
                categories=["cs.AI"],
                submitted_after=datetime(2026, 1, 1, tzinfo=timezone.utc),
                submitted_before=datetime(2026, 1, 2, tzinfo=timezone.utc),
                max_results=1,
            )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"<not-closed>", "malformed XML"),
        (b"<root />", "does not contain an Atom feed"),
        (
            b'<feed xmlns="http://www.w3.org/2005/Atom" />',
            "missing totalResults",
        ),
    ],
)
def test_malformed_feeds_are_rejected(content: bytes, message: str) -> None:
    with pytest.raises(ArxivResponseError, match=message):
        parse_arxiv_feed(content)


def test_missing_required_entry_metadata_is_rejected() -> None:
    content = feed_xml(["2601.00001"]).replace(
        b"<summary>Abstract 2601.00001</summary>",
        b"",
    )

    with pytest.raises(ArxivResponseError, match="missing required summary"):
        parse_arxiv_feed(content)


def test_repeated_discovery_run_skips_existing_paper(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=feed_xml(["2601.00001"]),
            request=request,
        )

    database = Database(tmp_path / "researchpilot.db")
    database.initialize()
    repository = SQLitePaperRepository(database)
    request = DiscoveryRequest(
        categories=("cs.AI",),
        submitted_after=datetime(2026, 1, 1, tzinfo=timezone.utc),
        submitted_before=datetime(2026, 1, 8, tzinfo=timezone.utc),
        max_results=5,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = DiscoverPapers(ArxivSource(client), repository)
        first = service.execute(request)
        second = service.execute(request)

    assert (first.fetched, first.inserted, first.duplicates) == (1, 1, 0)
    assert (second.fetched, second.inserted, second.duplicates) == (1, 0, 1)
    assert repository.count() == 1
