"""Safe filesystem exporter for managed Obsidian Markdown notes."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path, PurePosixPath

from researchpilot.digests.paths import validate_markdown_filename
from researchpilot.domain import DigestExportReceipt, ExportDisposition

MANAGED_MARKER = re.compile(
    r"\A<!-- researchpilot:managed-digest sha256=([0-9a-f]{64}) -->\n\n"
)


class ObsidianExportError(Exception):
    """An Obsidian note could not be exported without risking user data."""


class ObsidianExporter:
    """Create and update only explicitly managed notes inside one vault."""

    def __init__(
        self,
        vault_path: str | Path,
        *,
        folder: str = "ResearchPilot",
    ) -> None:
        self._vault_path = Path(vault_path).expanduser()
        self._folder_parts = self._validate_folder(folder)

    def export(self, filename: str, content: str) -> DigestExportReceipt:
        """Export Markdown, refusing links and unrelated filename collisions."""

        validate_markdown_filename(filename)
        if not content.strip():
            raise ValueError("digest export content must not be empty")

        target_directory = self._target_directory()
        target = target_directory / filename
        document = self._managed_document(content)
        try:
            if target.is_symlink():
                raise ObsidianExportError(
                    f"refusing to export through symbolic link: {target}"
                )
            if not target.exists():
                self._create_without_overwrite(target, document)
                disposition = ExportDisposition.CREATED
            elif not target.is_file():
                raise ObsidianExportError(
                    f"Obsidian destination is not a regular file: {target}"
                )
            else:
                existing = target.read_text(encoding="utf-8")
                if MANAGED_MARKER.match(existing) is None:
                    raise ObsidianExportError(
                        "refusing to overwrite unrelated Obsidian note: "
                        f"{target}"
                    )
                if existing == document:
                    disposition = ExportDisposition.UNCHANGED
                else:
                    self._replace_managed(target, document)
                    disposition = ExportDisposition.UPDATED
        except ObsidianExportError:
            raise
        except (OSError, UnicodeError) as exc:
            raise ObsidianExportError(
                f"could not export Obsidian note {target}: {exc}"
            ) from exc
        return DigestExportReceipt(path=str(target), disposition=disposition)

    @staticmethod
    def _validate_folder(folder: str) -> tuple[str, ...]:
        folder = folder.strip()
        path = PurePosixPath(folder)
        if (
            not folder
            or folder.startswith("/")
            or "\\" in folder
            or ":" in folder
            or "//" in folder
            or folder.endswith("/")
            or path.is_absolute()
            or not path.parts
            or ".." in path.parts
            or str(path) != folder
        ):
            raise ValueError(
                "Obsidian folder must be a normalized relative POSIX path"
            )
        return path.parts

    def _target_directory(self) -> Path:
        try:
            vault = self._vault_path.resolve(strict=True)
        except OSError as exc:
            raise ObsidianExportError(
                f"Obsidian vault does not exist: {self._vault_path}"
            ) from exc
        if not vault.is_dir():
            raise ObsidianExportError(
                f"Obsidian vault is not a directory: {self._vault_path}"
            )

        current = vault
        try:
            for part in self._folder_parts:
                current = current / part
                if current.is_symlink():
                    raise ObsidianExportError(
                        "refusing symbolic link inside Obsidian export path: "
                        f"{current}"
                    )
                if current.exists() and not current.is_dir():
                    raise ObsidianExportError(
                        f"Obsidian export path is not a directory: {current}"
                    )
                current.mkdir(exist_ok=True)
            resolved = current.resolve(strict=True)
        except ObsidianExportError:
            raise
        except OSError as exc:
            raise ObsidianExportError(
                f"could not prepare Obsidian export directory {current}: {exc}"
            ) from exc
        if not resolved.is_relative_to(vault):
            raise ObsidianExportError(
                f"Obsidian export path escapes the configured vault: {resolved}"
            )
        return resolved

    @staticmethod
    def _managed_document(content: str) -> str:
        digest_id = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return (
            f"<!-- researchpilot:managed-digest sha256={digest_id} -->\n\n"
            f"{content}"
        )

    @staticmethod
    def _temporary_file(target: Path, content: str) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        return temporary_path

    @classmethod
    def _create_without_overwrite(cls, target: Path, content: str) -> None:
        temporary = cls._temporary_file(target, content)
        try:
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise ObsidianExportError(
                    f"refusing to overwrite existing Obsidian note: {target}"
                ) from exc
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _replace_managed(cls, target: Path, content: str) -> None:
        temporary = cls._temporary_file(target, content)
        try:
            if target.is_symlink():
                raise ObsidianExportError(
                    f"refusing to replace symbolic link: {target}"
                )
            current = target.read_text(encoding="utf-8")
            if MANAGED_MARKER.match(current) is None:
                raise ObsidianExportError(
                    f"refusing to overwrite unrelated Obsidian note: {target}"
                )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
