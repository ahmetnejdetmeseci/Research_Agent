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
from researchpilot.integrations.github import (
    GITHUB_API_URL,
    GitHubError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubSource,
    repository_from_github_item,
)
from researchpilot.integrations.arxiv_content import (
    ArxivContentError,
    ArxivPDFContentProvider,
)
from researchpilot.integrations.github_content import (
    GitHubContentError,
    GitHubContentSource,
)

__all__ = [
    "ARXIV_API_URL",
    "ArxivError",
    "ArxivContentError",
    "ArxivPDFContentProvider",
    "ArxivResponseError",
    "ArxivSource",
    "GITHUB_API_URL",
    "GitHubError",
    "GitHubContentError",
    "GitHubContentSource",
    "GitHubRateLimitError",
    "GitHubResponseError",
    "GitHubSource",
    "OllamaError",
    "OllamaProvider",
    "OllamaResponseError",
    "parse_arxiv_feed",
    "repository_from_github_item",
]
