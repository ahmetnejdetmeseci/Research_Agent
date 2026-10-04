"""Adapters for external ResearchPilot services."""

from researchpilot.integrations.arxiv import (
    ARXIV_API_URL,
    ArxivError,
    ArxivResponseError,
    ArxivSource,
    parse_arxiv_feed,
)
from researchpilot.integrations.ollama import (
    OllamaError,
    OllamaProvider,
    OllamaResponseError,
)

__all__ = [
    "ARXIV_API_URL",
    "ArxivError",
    "ArxivResponseError",
    "ArxivSource",
    "OllamaError",
    "OllamaProvider",
    "OllamaResponseError",
    "parse_arxiv_feed",
]
