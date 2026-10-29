"""Filesystem adapter for local generated Markdown digests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from researchpilot.digests.paths import validate_markdown_filename


class DigestWriteError(Exception):
    """A local digest file could not be written safely."""


class LocalMarkdownDigestWriter:
    """Idempotently replace one generated Markdown file using an atomic rename."""

    def __init__(self, output_directory: str | Path) -> None:
        self._output_directory = Path(output_directory).expanduser()

    def write(self, filename: str, content: str) -> str:
        """Write complete content, never append, and return the target path."""

        validate_markdown_filename(filename)
        target = self._output_directory / filename
        temporary_path: Path | None = None
        try:
            self._output_directory.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_text(encoding="utf-8") == content:
                return str(target)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._output_directory,
                prefix=f".{filename}.",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, target)
        except OSError as exc:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise DigestWriteError(f"could not write digest {target}: {exc}") from exc
        return str(target)
