"""Shared application composition for CLI and HTTP interfaces."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from researchpilot.application import (
    AnalyzePapers,
    AnalyzeRepositories,
    DiscoverPapers,
    DiscoverRepositories,
    DiscoveryRequest,
    ExportDigest,
    PaperContentPolicy,
    PipelineContext,
    PipelineRunResult,
    PipelineStepDefinition,
    PipelineStepExecution,
    RankPapers,
    RankRepositories,
    RankingPolicy,
    RepositoryContentPolicy,
    RepositoryDiscoveryRequest,
    RunPipeline,
)
from researchpilot.config import (
    ResearchPilotConfig,
    load_config,
    resolve_config_path,
    resolve_github_token,
    resolve_ollama_base_url,
)
from researchpilot.digests import (
    BuildDigest,
    DigestBuildError,
    LocalMarkdownDigestReader,
    LocalMarkdownDigestWriter,
    digest_filename,
)
from researchpilot.domain import (
    PipelineRunHistory,
    RankedPaper,
    RankedRepository,
)
from researchpilot.exporters import ObsidianExporter
from researchpilot.integrations import (
    ArxivPDFContentProvider,
    ArxivSource,
    GitHubContentSource,
    GitHubSource,
    OllamaProvider,
)
from researchpilot.integrations.ollama import OLLAMA_PROVIDER_NAME
from researchpilot.persistence import (
    Database,
    DatabaseStatus,
    LocalRunLock,
    PersistenceError,
    SQLiteAnalysisRepository,
    SQLitePaperRepository,
    SQLitePipelineRepository,
    SQLiteRepositoryAnalysisStore,
    SQLiteRepositoryStore,
    resolve_database_path,
)


@dataclass(frozen=True)
class PaperRankingSnapshot:
    """One reproducible paper-ranking response for an interface."""

    as_of: datetime
    items: tuple[RankedPaper, ...]

    @property
    def selected_count(self) -> int:
        return sum(item.selected for item in self.items)


@dataclass(frozen=True)
class RepositoryRankingSnapshot:
    """One reproducible repository-ranking response for an interface."""

    as_of: datetime
    items: tuple[RankedRepository, ...]

    @property
    def selected_count(self) -> int:
        return sum(item.selected for item in self.items)


def _pipeline_key(config_path: Path, database_path: Path) -> str:
    """Return a stable identity for one config/database pipeline pair."""

    identity = (
        f"{config_path.resolve(strict=False)}\0"
        f"{database_path.resolve(strict=False)}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class ResearchPilotRuntime:
    """Compose concrete adapters around stable application services."""

    def __init__(
        self,
        config_path: Path,
        database_path: Path,
        config: ResearchPilotConfig,
        database: Database,
    ) -> None:
        self.config_path = config_path
        self.database_path = database_path
        self.config = config
        self.database = database

    @classmethod
    def load(
        cls,
        config_path: str | Path | None = None,
        database_path: str | Path | None = None,
    ) -> ResearchPilotRuntime:
        """Load configuration and require an initialized, current database."""

        resolved_config = resolve_config_path(config_path)
        resolved_database = resolve_database_path(database_path)
        config = load_config(resolved_config)
        database = Database(resolved_database)
        if not database.status().initialized:
            raise PersistenceError(
                "database is not initialized or needs migration. "
                f"Run 'researchpilot db init --database {resolved_database}'."
            )
        return cls(resolved_config, resolved_database, config, database)

    def database_status(self) -> DatabaseStatus:
        """Return current schema and row-count status."""

        return self.database.status()

    def rank_papers(
        self,
        as_of: datetime | None = None,
    ) -> PaperRankingSnapshot:
        """Rank every stored paper through the existing application service."""

        ranking_time = datetime.now(timezone.utc) if as_of is None else as_of
        items = RankPapers(SQLitePaperRepository(self.database)).execute(
            self.config.profile,
            self._ranking_policy(),
            now=ranking_time,
        )
        return PaperRankingSnapshot(ranking_time, tuple(items))

    def rank_repositories(
        self,
        as_of: datetime | None = None,
    ) -> RepositoryRankingSnapshot:
        """Rank every stored repository through the existing application service."""

        ranking_time = datetime.now(timezone.utc) if as_of is None else as_of
        items = RankRepositories(SQLiteRepositoryStore(self.database)).execute(
            self.config.profile,
            self._ranking_policy(),
            now=ranking_time,
        )
        return RepositoryRankingSnapshot(ranking_time, tuple(items))

    def list_pipeline_runs(
        self,
        *,
        limit: int = 20,
    ) -> tuple[PipelineRunHistory, ...]:
        """Return recent pipeline runs with their ordered step state."""

        repository = SQLitePipelineRepository(self.database)
        return tuple(
            PipelineRunHistory(
                run=run,
                steps=repository.list_steps(run.id),
            )
            for run in repository.list_runs(limit=limit)
        )

    def get_pipeline_run(self, run_id: int) -> PipelineRunHistory | None:
        """Return one pipeline run with its ordered step state."""

        repository = SQLitePipelineRepository(self.database)
        run = repository.get_run(run_id)
        if run is None:
            return None
        return PipelineRunHistory(run=run, steps=repository.list_steps(run.id))

    def run_pipeline(self) -> PipelineRunResult:
        """Run the configured discovery-to-export pipeline once or resume it."""

        config = self.config
        database = self.database
        papers = SQLitePaperRepository(database)
        repositories = SQLiteRepositoryStore(database)
        paper_analyses = SQLiteAnalysisRepository(database)
        repository_analyses = SQLiteRepositoryAnalysisStore(database)
        ranking_policy = self._ranking_policy()
        arxiv = config.sources.arxiv
        github = config.sources.github
        paper_content = config.content.papers
        repository_content = config.content.repositories
        digest = config.digest
        obsidian = config.exports.obsidian

        with LocalRunLock(self.database_path).acquire(), httpx.Client(
            timeout=httpx.Timeout(30.0)
        ) as source_client, httpx.Client(
            timeout=httpx.Timeout(config.ollama.timeout_seconds)
        ) as llm_client:
            provider = OllamaProvider(
                llm_client,
                base_url=resolve_ollama_base_url(config.ollama.base_url),
                model=config.ollama.model,
            )

            def discover_arxiv(context: PipelineContext) -> PipelineStepExecution:
                result = DiscoverPapers(
                    ArxivSource(source_client),
                    papers,
                ).execute(
                    DiscoveryRequest(
                        categories=tuple(arxiv.categories),
                        submitted_after=(
                            context.run.started_at
                            - timedelta(days=arxiv.lookback_days)
                        ),
                        submitted_before=context.run.started_at,
                        max_results=arxiv.max_results,
                    )
                )
                return PipelineStepExecution(
                    {
                        "fetched": result.fetched,
                        "inserted": result.inserted,
                        "duplicates": result.duplicates,
                    }
                )

            def discover_github(context: PipelineContext) -> PipelineStepExecution:
                result = DiscoverRepositories(
                    GitHubSource(source_client, token=resolve_github_token()),
                    repositories,
                ).execute(
                    RepositoryDiscoveryRequest(
                        queries=tuple(github.queries),
                        pushed_after=(
                            context.run.started_at
                            - timedelta(days=github.lookback_days)
                        ),
                        max_results=github.max_results,
                        max_readme_characters=github.max_readme_characters,
                    )
                )
                return PipelineStepExecution(
                    {
                        "fetched": result.fetched,
                        "inserted": result.inserted,
                        "duplicates": result.duplicates,
                    }
                )

            def analyze_papers(context: PipelineContext) -> PipelineStepExecution:
                result = AnalyzePapers(
                    papers,
                    paper_analyses,
                    provider,
                    content_provider=(
                        ArxivPDFContentProvider(source_client)
                        if paper_content.enabled
                        else None
                    ),
                ).execute(
                    config.profile,
                    ranking_policy,
                    max_papers=config.analysis.max_papers_per_run,
                    now=context.run.started_at,
                    content_policy=PaperContentPolicy(
                        enabled=paper_content.enabled,
                        max_download_bytes=paper_content.max_download_bytes,
                        max_pages=paper_content.max_pages,
                        max_characters=paper_content.max_characters,
                    ),
                )
                if result.failed:
                    details = "; ".join(
                        f"{failure.paper_external_id}: {failure.error}"
                        for failure in result.failures
                    )
                    raise RuntimeError(details or "paper analysis failed")
                return PipelineStepExecution(
                    {
                        "selected": result.selected,
                        "attempted": result.attempted,
                        "succeeded": result.succeeded,
                        "already_complete": result.already_complete,
                        "full_content_used": result.full_content_used,
                        "fallbacks": len(result.fallbacks),
                    }
                )

            def analyze_repositories(
                context: PipelineContext,
            ) -> PipelineStepExecution:
                result = AnalyzeRepositories(
                    repositories,
                    repository_analyses,
                    provider,
                    content_provider=(
                        GitHubContentSource(
                            source_client,
                            token=resolve_github_token(),
                        )
                        if repository_content.enabled
                        else None
                    ),
                ).execute(
                    config.profile,
                    ranking_policy,
                    max_repositories=config.analysis.max_repositories_per_run,
                    now=context.run.started_at,
                    content_policy=RepositoryContentPolicy(
                        enabled=repository_content.enabled,
                        include_patterns=tuple(
                            repository_content.include_patterns
                        ),
                        exclude_patterns=tuple(
                            repository_content.exclude_patterns
                        ),
                        max_files=repository_content.max_files,
                        max_file_bytes=repository_content.max_file_bytes,
                        max_total_characters=(
                            repository_content.max_total_characters
                        ),
                    ),
                )
                if result.failed:
                    details = "; ".join(
                        f"{failure.repository_external_id}: {failure.error}"
                        for failure in result.failures
                    )
                    raise RuntimeError(details or "repository analysis failed")
                return PipelineStepExecution(
                    {
                        "selected": result.selected,
                        "attempted": result.attempted,
                        "succeeded": result.succeeded,
                        "already_complete": result.already_complete,
                        "missing_readme": result.missing_readme,
                        "source_content_used": result.source_content_used,
                        "content_unavailable": result.content_unavailable,
                        "fallbacks": len(result.fallbacks),
                    }
                )

            def build_digest(_context: PipelineContext) -> PipelineStepExecution:
                try:
                    result = BuildDigest(
                        papers,
                        paper_analyses,
                        repositories,
                        repository_analyses,
                        LocalMarkdownDigestWriter(digest.output_directory),
                    ).execute(
                        config.profile,
                        ranking_policy,
                        provider=OLLAMA_PROVIDER_NAME,
                        model=config.ollama.model,
                        max_papers=digest.max_papers,
                        max_repositories=digest.max_repositories,
                    )
                except DigestBuildError as exc:
                    return PipelineStepExecution.skip(str(exc), built=False)
                return PipelineStepExecution(
                    {
                        "built": True,
                        "path": result.path,
                        "digest_id": result.digest_id,
                        "papers": result.paper_count,
                        "repositories": result.repository_count,
                        "missing_analysis": result.missing_analysis,
                        "omitted_by_limit": result.omitted_by_limit,
                    }
                )

            def export_obsidian(context: PipelineContext) -> PipelineStepExecution:
                digest_step = context.steps["build_digest"]
                if digest_step.status.value == "skipped":
                    return PipelineStepExecution.skip(
                        "digest was not built in this pipeline run"
                    )
                result = ExportDigest(
                    LocalMarkdownDigestReader(digest.output_directory),
                    ObsidianExporter(obsidian.vault_path, folder=obsidian.folder),
                ).execute(digest_filename(config.profile.name))
                return PipelineStepExecution(
                    {
                        "path": result.path,
                        "digest_id": result.digest_id,
                        "disposition": result.disposition.value,
                    }
                )

            steps = (
                PipelineStepDefinition(
                    "discover_arxiv",
                    arxiv.enabled,
                    discover_arxiv,
                ),
                PipelineStepDefinition(
                    "discover_github",
                    github.enabled,
                    discover_github,
                ),
                PipelineStepDefinition("analyze_papers", True, analyze_papers),
                PipelineStepDefinition(
                    "analyze_repositories",
                    True,
                    analyze_repositories,
                ),
                PipelineStepDefinition("build_digest", True, build_digest),
                PipelineStepDefinition(
                    "export_obsidian",
                    obsidian.vault_path is not None,
                    export_obsidian,
                ),
            )
            return RunPipeline(SQLitePipelineRepository(database)).execute(
                _pipeline_key(self.config_path, self.database_path),
                steps,
            )

    def _ranking_policy(self) -> RankingPolicy:
        ranking = self.config.ranking
        return RankingPolicy(
            minimum_score=ranking.minimum_score,
            recency_weight=ranking.recency_weight,
            recency_window_days=ranking.recency_window_days,
        )
