"""Shared validation for generated digest filenames."""

from __future__ import annotations

import re
from pathlib import Path

SAFE_MARKDOWN_FILENAME = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9_-])?\.md$"
)


def validate_markdown_filename(filename: str) -> str:
    """Return a plain safe Markdown filename or raise ``ValueError``."""

    if (
        Path(filename).name != filename
        or not SAFE_MARKDOWN_FILENAME.fullmatch(filename)
    ):
        raise ValueError(
            "digest filename must be a plain Markdown filename using only "
            "letters, numbers, dots, dashes, and underscores"
        )
    return filename
