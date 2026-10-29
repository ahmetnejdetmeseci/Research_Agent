"""Filesystem adapter for reading locally generated Markdown digests."""

from __future__ import annotations

from pathlib import Path

from researchpilot.digests.paths import validate_markdown_filename


class DigestReadError(Exception):
    """A generated local digest could not be read safely."""


class LocalMarkdownDigestReader:
    """Read a generated digest by safe filename from one configured directory."""

    def __init__(self, input_directory: str | Path) -> None:
        self._input_directory = Path(input_directory).expanduser()

    def read(self, filename: str) -> str:
        """Return digest Markdown while refusing links and non-regular files."""

        validate_markdown_filename(filename)
        source = self._input_directory / filename
        try:
            if source.is_symlink():
                raise DigestReadError(
                    f"generated digest cannot be a symbolic link: {source}"
                )
            if not source.exists():
                raise DigestReadError(
                    f"generated digest not found: {source}. Run 'digest build' first."
                )
            if not source.is_file():
                raise DigestReadError(
                    f"generated digest is not a regular file: {source}"
                )
            content = source.read_text(encoding="utf-8")
        except DigestReadError:
            raise
        except (OSError, UnicodeError) as exc:
            raise DigestReadError(
                f"could not read generated digest {source}: {exc}"
            ) from exc
        if not content.strip():
            raise DigestReadError(f"generated digest is empty: {source}")
        return content
