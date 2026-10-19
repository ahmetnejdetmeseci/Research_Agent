"""Build deterministic research digests from ranked, persisted analyses."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

from researchpilot.application.ranking import (
    DeterministicPaperRanker,
    DeterministicRepositoryRanker,
    RankingPolicy,
)
from researchpilot.domain import (
    AnalysisContentKind,
    DigestEntry,
    DigestItemKind,
    InterestProfile,
    Paper,
    PaperAnalysisRecord,
    RankedPaper,
    RankedRepository,
    RepositoryAnalysisRecord,
    ResearchDigest,
    SoftwareRepository,
)
from researchpilot.domain.ports import (
    AnalysisRepository,
    DigestWriter,
    PaperRepository,
    RepositoryAnalysisStore,
    RepositoryStore,
)


class DigestBuildError(Exception):
    """A digest cannot be built from the available local state."""


@dataclass(frozen=True)
class DigestBuildResult:
    """Summary of one deterministic digest build."""

    path: str
    digest_id: str
    paper_count: int
    repository_count: int
    missing_analysis: int
    omitted_by_limit: int
    as_of: datetime


class BuildDigest:
    """Rank stored items and render their best matching successful analyses."""

    def __init__(
        self,
        paper_repository: PaperRepository,
        paper_analyses: AnalysisRepository,
        repository_store: RepositoryStore,
        repository_analyses: RepositoryAnalysisStore,
        writer: DigestWriter,
        *,
        paper_ranker: DeterministicPaperRanker | None = None,
        repository_ranker: DeterministicRepositoryRanker | None = None,
    ) -> None:
        self._papers = paper_repository
        self._paper_analyses = paper_analyses
        self._repositories = repository_store
        self._repository_analyses = repository_analyses
        self._writer = writer
        self._paper_ranker = paper_ranker or DeterministicPaperRanker()
        self._repository_ranker = (
            repository_ranker or DeterministicRepositoryRanker()
        )

    def execute(
        self,
        profile: InterestProfile,
        policy: RankingPolicy,
        *,
        provider: str,
        model: str,
        max_papers: int,
        max_repositories: int,
        as_of: datetime | None = None,
    ) -> DigestBuildResult:
        """Build and atomically write a digest for one local-state snapshot."""

        provider = provider.strip()
        model = model.strip()
        if not provider or not model:
            raise ValueError("digest analysis provider and model must not be empty")
        if max_papers < 1 or max_repositories < 1:
            raise ValueError("digest item limits must be positive")

        papers = self._papers.list_all()
        repositories = self._repositories.list_all()
        snapshot_time = self._snapshot_time(papers, repositories, as_of)
        ranked_papers = self._paper_ranker.rank(
            papers,
            profile,
            policy,
            now=snapshot_time,
        )
        ranked_repositories = self._repository_ranker.rank(
            repositories,
            profile,
            policy,
            now=snapshot_time,
        )

        paper_entries, missing_papers, omitted_papers = self._paper_entries(
            ranked_papers,
            provider,
            model,
            max_papers,
        )
        repository_entries, missing_repositories, omitted_repositories = (
            self._repository_entries(
                ranked_repositories,
                provider,
                model,
                max_repositories,
            )
        )
        entries = paper_entries + repository_entries
        if not entries:
            raise DigestBuildError(
                "no selected items have a successful analysis for "
                f"{provider}/{model}; run the analysis commands first"
            )

        digest = ResearchDigest(
            profile_name=profile.name,
            as_of=snapshot_time,
            entries=entries,
        )
        markdown = render_markdown(digest)
        digest_id = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        path = self._writer.write(_digest_filename(profile.name), markdown)
        return DigestBuildResult(
            path=path,
            digest_id=digest_id,
            paper_count=len(paper_entries),
            repository_count=len(repository_entries),
            missing_analysis=missing_papers + missing_repositories,
            omitted_by_limit=omitted_papers + omitted_repositories,
            as_of=snapshot_time,
        )

    @staticmethod
    def _snapshot_time(
        papers: list[Paper],
        repositories: list[SoftwareRepository],
        as_of: datetime | None,
    ) -> datetime:
        if as_of is not None:
            if as_of.tzinfo is None:
                raise ValueError("digest snapshot time must include a timezone")
            return as_of.astimezone(timezone.utc)

        timestamps = [paper.published_at for paper in papers]
        timestamps.extend(
            repository.pushed_at or repository.updated_at
            for repository in repositories
        )
        if not timestamps:
            raise DigestBuildError(
                "no stored papers or repositories are available; run discovery first"
            )
        return max(timestamp.astimezone(timezone.utc) for timestamp in timestamps)

    def _paper_entries(
        self,
        ranked: list[RankedPaper],
        provider: str,
        model: str,
        limit: int,
    ) -> tuple[list[DigestEntry], int, int]:
        entries: list[DigestEntry] = []
        seen: set[tuple[str, str]] = set()
        missing = 0
        omitted = 0
        for item in ranked:
            if not item.selected:
                continue
            identity = (item.paper.source.value, item.paper.external_id)
            if identity in seen:
                continue
            seen.add(identity)
            analysis = self._best_paper_analysis(item.paper, provider, model)
            if analysis is None:
                missing += 1
            elif len(entries) >= limit:
                omitted += 1
            else:
                entries.append(self._paper_entry(item, analysis))
        return entries, missing, omitted

    def _best_paper_analysis(
        self,
        paper: Paper,
        provider: str,
        model: str,
    ) -> PaperAnalysisRecord | None:
        for kind in (
            AnalysisContentKind.FULL_PAPER,
            AnalysisContentKind.ABSTRACT,
        ):
            analysis = self._paper_analyses.get_success(
                paper.source,
                paper.external_id,
                provider,
                model,
                kind,
            )
            if analysis is not None:
                return analysis
        return None

    @staticmethod
    def _paper_entry(
        ranked: RankedPaper,
        analysis: PaperAnalysisRecord,
    ) -> DigestEntry:
        if analysis.result is None or analysis.completed_at is None:
            raise DigestBuildError("stored successful paper analysis is incomplete")
        return DigestEntry(
            kind=DigestItemKind.PAPER,
            source=ranked.paper.source.value,
            external_id=ranked.paper.external_id,
            title=ranked.paper.title,
            url=ranked.paper.url,
            score=ranked.score,
            matches=ranked.matches,
            summary=analysis.result.summary,
            highlights=analysis.result.key_contributions,
            relevance_to_profile=analysis.result.relevance_to_profile,
            limitations=analysis.result.limitations,
            analysis_provider=analysis.provider,
            analysis_model=analysis.model,
            content_trace=analysis.content_trace,
            analyzed_at=analysis.completed_at,
        )

    def _repository_entries(
        self,
        ranked: list[RankedRepository],
        provider: str,
        model: str,
        limit: int,
    ) -> tuple[list[DigestEntry], int, int]:
        entries: list[DigestEntry] = []
        seen: set[tuple[str, str]] = set()
        missing = 0
        omitted = 0
        for item in ranked:
            if not item.selected:
                continue
            identity = (
                item.repository.source.value,
                item.repository.external_id,
            )
            if identity in seen:
                continue
            seen.add(identity)
            analysis = self._best_repository_analysis(
                item.repository,
                provider,
                model,
            )
            if analysis is None:
                missing += 1
            elif len(entries) >= limit:
                omitted += 1
            else:
                entries.append(self._repository_entry(item, analysis))
        return entries, missing, omitted

    def _best_repository_analysis(
        self,
        repository: SoftwareRepository,
        provider: str,
        model: str,
    ) -> RepositoryAnalysisRecord | None:
        for kind in (
            AnalysisContentKind.README_AND_SOURCE_FILES,
            AnalysisContentKind.SOURCE_FILES,
            AnalysisContentKind.README,
        ):
            analysis = self._repository_analyses.get_success(
                repository.source,
                repository.external_id,
                provider,
                model,
                kind,
            )
            if analysis is not None:
                return analysis
        return None

    @staticmethod
    def _repository_entry(
        ranked: RankedRepository,
        analysis: RepositoryAnalysisRecord,
    ) -> DigestEntry:
        if analysis.result is None or analysis.completed_at is None:
            raise DigestBuildError("stored successful repository analysis is incomplete")
        return DigestEntry(
            kind=DigestItemKind.REPOSITORY,
            source=ranked.repository.source.value,
            external_id=ranked.repository.external_id,
            title=ranked.repository.full_name,
            url=ranked.repository.url,
            score=ranked.score,
            matches=ranked.matches,
            summary=analysis.result.summary,
            highlights=analysis.result.key_capabilities,
            relevance_to_profile=analysis.result.relevance_to_profile,
            notable_technologies=analysis.result.notable_technologies,
            limitations=analysis.result.limitations,
            analysis_provider=analysis.provider,
            analysis_model=analysis.model,
            content_trace=analysis.content_trace,
            analyzed_at=analysis.completed_at,
        )


def _digest_filename(profile_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", profile_name.casefold()).strip("-")
    slug = (slug or "profile")[:48].rstrip("-")
    profile_id = hashlib.sha256(profile_name.encode("utf-8")).hexdigest()[:8]
    return f"researchpilot-{slug}-{profile_id}.md"


def _markdown_text(value: str) -> str:
    normalized = html.escape(" ".join(value.split()), quote=False)
    for character in ("\\", "`", "*", "_", "[", "]"):
        normalized = normalized.replace(character, f"\\{character}")
    return normalized


def _markdown_link(label: str, locator: object) -> str:
    destination = quote(
        str(locator),
        safe=":/?#[]@!$&'()*+,;=%",
    )
    return f"[{_markdown_text(label)}](<{destination}>)"


def _render_entry(entry: DigestEntry, number: int) -> list[str]:
    lines = [
        f"### {number}. {_markdown_link(entry.title, entry.url)}",
        "",
        f"- **Source:** `{entry.source}:{_markdown_text(entry.external_id)}`",
        f"- **Score:** {entry.score:.6f}",
    ]
    if entry.matches:
        matches = ", ".join(
            f"{_markdown_text(match.interest_name)} / "
            f"{_markdown_text(match.keyword)} (+{match.contribution:g})"
            for match in entry.matches
        )
        lines.append(f"- **Matches:** {matches}")
    lines.extend(
        [
            "",
            f"**Summary:** {_markdown_text(entry.summary)}",
            "",
            "**Highlights**",
            "",
        ]
    )
    lines.extend(f"- {_markdown_text(value)}" for value in entry.highlights)
    lines.extend(
        [
            "",
            "**Profile relevance**",
            "",
            _markdown_text(entry.relevance_to_profile),
        ]
    )
    if entry.notable_technologies:
        lines.extend(["", "**Notable technologies**", ""])
        lines.extend(
            f"- {_markdown_text(value)}" for value in entry.notable_technologies
        )
    if entry.limitations:
        lines.extend(["", "**Limitations**", ""])
        lines.extend(f"- {_markdown_text(value)}" for value in entry.limitations)

    trace = entry.content_trace
    lines.extend(
        [
            "",
            "**Provenance**",
            "",
            f"- Analysis: `{_markdown_text(entry.analysis_provider)}/"
            f"{_markdown_text(entry.analysis_model)}`",
            f"- Completed: `{entry.analyzed_at.astimezone(timezone.utc).isoformat()}`",
            f"- Content kind: `{trace.kind.value}`",
        ]
    )
    for reference in trace.references:
        details = [f"{reference.characters} characters"]
        if reference.pages is not None:
            details.append(f"{reference.pages} pages")
        if reference.truncated:
            details.append("truncated")
        lines.append(
            f"- Input: {_markdown_link(reference.label, reference.locator)} "
            f"— {', '.join(details)}"
        )
    if trace.truncated:
        lines.append("- Input set was truncated to configured limits.")
    lines.extend(
        f"- Warning: {_markdown_text(warning)}" for warning in trace.warnings
    )
    return lines


def render_markdown(digest: ResearchDigest) -> str:
    """Render a digest without wall-clock or iteration-order variability."""

    papers = [
        entry for entry in digest.entries if entry.kind is DigestItemKind.PAPER
    ]
    repositories = [
        entry
        for entry in digest.entries
        if entry.kind is DigestItemKind.REPOSITORY
    ]
    lines = [
        "# ResearchPilot Digest",
        "",
        f"- **Profile:** {_markdown_text(digest.profile_name)}",
        f"- **Snapshot:** `{digest.as_of.astimezone(timezone.utc).isoformat()}`",
        f"- **Items:** {len(digest.entries)}",
        "",
        "## Papers",
        "",
    ]
    if papers:
        for number, entry in enumerate(papers, start=1):
            lines.extend(_render_entry(entry, number))
            lines.append("")
    else:
        lines.extend(["_No analyzed papers matched this snapshot._", ""])

    lines.extend(["## Software repositories", ""])
    if repositories:
        for number, entry in enumerate(repositories, start=1):
            lines.extend(_render_entry(entry, number))
            lines.append("")
    else:
        lines.extend(["_No analyzed repositories matched this snapshot._", ""])
    return "\n".join(lines).rstrip() + "\n"
