"""Bounded GitHub source-file retrieval for repository analysis."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

from researchpilot.domain import (
    ContentReference,
    RetrievedContent,
    SoftwareRepository,
)
from researchpilot.domain.ports import ContentRetrievalError
from researchpilot.integrations.github import GitHubError, GitHubSource


class GitHubContentError(ContentRetrievalError):
    """A GitHub source-tree or source-file acquisition failure."""


class GitHubContentSource(GitHubSource):
    """Retrieve explicitly selected, bounded text files from GitHub."""

    def retrieve(
        self,
        repository: SoftwareRepository,
        *,
        include_patterns: list[str] | tuple[str, ...],
        exclude_patterns: list[str] | tuple[str, ...],
        max_files: int,
        max_file_bytes: int,
        max_total_characters: int,
    ) -> RetrievedContent:
        """Return matching source files with per-file and aggregate bounds."""

        if not include_patterns:
            raise ValueError("at least one source include pattern is required")
        if min(max_files, max_file_bytes, max_total_characters) < 1:
            raise ValueError("repository content limits must be positive")

        try:
            return self._retrieve(
                repository,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
                max_files=max_files,
                max_file_bytes=max_file_bytes,
                max_total_characters=max_total_characters,
            )
        except GitHubContentError:
            raise
        except GitHubError as exc:
            raise GitHubContentError(str(exc)) from exc

    def _retrieve(
        self,
        repository: SoftwareRepository,
        *,
        include_patterns: list[str] | tuple[str, ...],
        exclude_patterns: list[str] | tuple[str, ...],
        max_files: int,
        max_file_bytes: int,
        max_total_characters: int,
    ) -> RetrievedContent:
        owner = quote(repository.owner, safe="")
        name = quote(repository.name, safe="")
        branch = quote(repository.default_branch, safe="")
        payload = self._get_json(
            f"/repos/{owner}/{name}/git/trees/{branch}",
            params={"recursive": "1"},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("tree"), list):
            raise GitHubContentError("GitHub source tree response is invalid")

        warnings: list[str] = []
        tree_truncated = payload.get("truncated") is True
        if tree_truncated:
            warnings.append("GitHub returned a truncated recursive source tree")

        candidates: list[tuple[str, int]] = []
        for entry in payload["tree"]:
            candidate = self._candidate(
                entry,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
            )
            if candidate is None:
                continue
            path, size = candidate
            if size > max_file_bytes:
                warnings.append(
                    f"skipped {path}: file exceeds the configured byte limit"
                )
                continue
            candidates.append((path, size))

        candidates.sort(key=lambda item: (item[0].count("/"), item[0]))
        sections: list[str] = []
        references: list[ContentReference] = []
        total_characters = 0
        aggregate_truncated = tree_truncated or len(candidates) > max_files

        for path, _ in candidates:
            if len(references) >= max_files or total_characters >= max_total_characters:
                aggregate_truncated = True
                break
            encoded_path = quote(path, safe="/")
            response = self._request(
                f"/repos/{owner}/{name}/contents/{encoded_path}",
                params={"ref": repository.default_branch},
                headers={"Accept": "application/vnd.github.raw+json"},
                allow_not_found=True,
            )
            if response is None:
                warnings.append(f"skipped {path}: file was not found")
                continue
            if len(response.content) > max_file_bytes:
                warnings.append(
                    f"skipped {path}: file exceeds the configured byte limit"
                )
                continue
            try:
                text = response.content.decode("utf-8")
            except UnicodeDecodeError:
                warnings.append(f"skipped {path}: file is not UTF-8 text")
                continue
            if "\x00" in text:
                warnings.append(f"skipped {path}: file appears to be binary")
                continue
            text = text.strip()
            if not text:
                warnings.append(f"skipped {path}: file is empty")
                continue

            header = f"FILE: {path}\n"
            separator = "\n\n" if sections else ""
            remaining = max_total_characters - total_characters
            available_text = remaining - len(separator) - len(header)
            if available_text <= 0:
                aggregate_truncated = True
                break
            file_truncated = len(text) > available_text
            bounded_text = text[:available_text].rstrip()
            if not bounded_text:
                aggregate_truncated = True
                break
            section = f"{header}{bounded_text}"
            sections.append(section)
            total_characters += len(separator) + len(section)
            references.append(
                ContentReference(
                    label=path,
                    locator=f"{repository.url}/blob/{repository.default_branch}/{path}",
                    characters=len(bounded_text),
                    truncated=file_truncated,
                )
            )
            if file_truncated:
                aggregate_truncated = True
                break

        if not sections:
            detail = f" ({'; '.join(warnings)})" if warnings else ""
            raise GitHubContentError(
                "no matching source files were available within configured limits"
                + detail
            )

        return RetrievedContent(
            text="\n\n".join(sections),
            references=references,
            truncated=aggregate_truncated,
            warnings=warnings,
        )

    @classmethod
    def _candidate(
        cls,
        entry: Any,
        *,
        include_patterns: list[str] | tuple[str, ...],
        exclude_patterns: list[str] | tuple[str, ...],
    ) -> tuple[str, int] | None:
        if not isinstance(entry, dict) or entry.get("type") != "blob":
            return None
        path = entry.get("path")
        size = entry.get("size")
        if (
            not isinstance(path, str)
            or not path
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            return None
        source_path = PurePosixPath(path)
        if not any(source_path.match(pattern) for pattern in include_patterns):
            return None
        if any(source_path.match(pattern) for pattern in exclude_patterns):
            return None
        return path, size
