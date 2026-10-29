"""Command-line entry point for ResearchPilot."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from researchpilot import __version__
from researchpilot.application import (
    AnalyzePapers,
    AnalyzeRepositories,
    DiscoverPapers,
    DiscoverRepositories,
    DiscoveryRequest,
    ExportDigest,
    RankPapers,
    RankRepositories,
    RankingPolicy,
    PaperContentPolicy,
    RepositoryContentPolicy,
    RepositoryDiscoveryRequest,
)
from researchpilot.config import (
    ConfigurationError,
    load_config,
    resolve_config_path,
    resolve_github_token,
    resolve_ollama_base_url,
)
from researchpilot.digests import (
    BuildDigest,
    DigestBuildError,
    DigestWriteError,
    DigestReadError,
    LocalMarkdownDigestReader,
    LocalMarkdownDigestWriter,
    digest_filename,
)
from researchpilot.exporters import ObsidianExportError, ObsidianExporter
from researchpilot.integrations import (
    ArxivPDFContentProvider,
    ArxivError,
    ArxivSource,
    GitHubError,
    GitHubContentSource,
    GitHubSource,
    OllamaProvider,
)
from researchpilot.integrations.ollama import OLLAMA_PROVIDER_NAME
from researchpilot.persistence import (
    Database,
    PersistenceError,
    SQLiteAnalysisRepository,
    SQLiteRepositoryAnalysisStore,
    SQLiteRepositoryStore,
    resolve_database_path,
)
from researchpilot.persistence.repositories import SQLitePaperRepository


def _check_config(config_path: str | Path | None) -> int:
    """Validate configuration and print a concise summary."""

    resolved_path = resolve_config_path(config_path)
    try:
        config = load_config(resolved_path)
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    arxiv = config.sources.arxiv
    arxiv_status = "enabled" if arxiv.enabled else "disabled"
    github = config.sources.github
    github_status = "enabled" if github.enabled else "disabled"
    print(f"Configuration valid: {resolved_path}")
    print(
        f"Profile: {config.profile.name} "
        f"({len(config.profile.interests)} interests)"
    )
    print(f"ArXiv: {arxiv_status} ({len(arxiv.categories)} categories)")
    print(f"GitHub: {github_status} ({len(github.queries)} queries)")
    print(f"Ranking minimum score: {config.ranking.minimum_score:g}")
    print(f"Ollama model: {config.ollama.model}")
    print(f"Analysis run limit: {config.analysis.max_papers_per_run}")
    print(
        "Repository analysis run limit: "
        f"{config.analysis.max_repositories_per_run}"
    )
    print(
        "Full-paper content: "
        f"{'enabled' if config.content.papers.enabled else 'disabled'}"
    )
    print(
        "Repository source content: "
        f"{'enabled' if config.content.repositories.enabled else 'disabled'}"
    )
    print(f"Digest output directory: {config.digest.output_directory}")
    print(
        "Digest item limits: "
        f"{config.digest.max_papers} papers, "
        f"{config.digest.max_repositories} repositories"
    )
    obsidian = config.exports.obsidian
    print(
        "Obsidian vault: "
        f"{obsidian.vault_path if obsidian.vault_path is not None else 'not configured'}"
    )
    print(f"Obsidian folder: {obsidian.folder}")
    return 0


def _initialize_database(database_path: str | Path | None) -> int:
    """Initialize or upgrade the local SQLite database."""

    resolved_path = resolve_database_path(database_path)
    database = Database(resolved_path)
    try:
        applied = database.initialize()
        status = database.status()
    except PersistenceError as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 2

    print(f"Database ready: {resolved_path}")
    print(f"Schema version: {status.current_version}/{status.latest_version}")
    if applied:
        migrations = ", ".join(
            f"{migration.version:03d}_{migration.name}" for migration in applied
        )
        print(f"Applied migrations: {migrations}")
    else:
        print("Applied migrations: none (already current)")
    return 0


def _show_database_status(database_path: str | Path | None) -> int:
    """Print schema and row-count status for the local database."""

    resolved_path = resolve_database_path(database_path)
    try:
        status = Database(resolved_path).status()
    except PersistenceError as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 2

    print(f"Database: {resolved_path}")
    if not status.initialized:
        print("Status: not initialized")
        print(f"Schema version: {status.current_version}/{status.latest_version}")
        print("Run 'researchpilot db init' to initialize it.")
        return 1

    print("Status: ready")
    print(f"Schema version: {status.current_version}/{status.latest_version}")
    print(f"Papers: {status.paper_count}")
    print(f"Repositories: {status.repository_count}")
    print(f"Runs: {status.run_count}")
    print(f"Analysis attempts: {status.analysis_attempt_count}")
    print(
        "Repository analysis attempts: "
        f"{status.repository_analysis_attempt_count}"
    )
    return 0


def _discover_arxiv(
    config_path: str | Path | None,
    database_path: str | Path | None,
) -> int:
    """Discover recent ArXiv papers and persist unseen identities."""

    resolved_config = resolve_config_path(config_path)
    resolved_database = resolve_database_path(database_path)
    try:
        config = load_config(resolved_config)
        arxiv_config = config.sources.arxiv
        if not arxiv_config.enabled:
            print("ArXiv discovery is disabled in the configuration.")
            return 0

        database = Database(resolved_database)
        status = database.status()
        if not status.initialized:
            print(
                "Database error: database is not initialized. "
                f"Run 'researchpilot db init --database {resolved_database}'.",
                file=sys.stderr,
            )
            return 2

        now = datetime.now(timezone.utc)
        request = DiscoveryRequest(
            categories=tuple(arxiv_config.categories),
            submitted_after=now - timedelta(days=arxiv_config.lookback_days),
            submitted_before=now,
            max_results=arxiv_config.max_results,
        )
        with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
            service = DiscoverPapers(
                ArxivSource(client),
                SQLitePaperRepository(database),
            )
            result = service.execute(request)
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except (ArxivError, PersistenceError) as exc:
        print(f"Discovery error: {exc}", file=sys.stderr)
        return 2

    print(f"ArXiv papers fetched: {result.fetched}")
    print(f"New papers stored: {result.inserted}")
    print(f"Duplicates skipped: {result.duplicates}")
    print(f"Database: {resolved_database}")
    return 0


def _discover_github(
    config_path: str | Path | None,
    database_path: str | Path | None,
) -> int:
    """Discover GitHub repositories and persist unseen identities."""

    resolved_config = resolve_config_path(config_path)
    resolved_database = resolve_database_path(database_path)
    try:
        config = load_config(resolved_config)
        github_config = config.sources.github
        if not github_config.enabled:
            print("GitHub discovery is disabled in the configuration.")
            return 0

        database = Database(resolved_database)
        status = database.status()
        if not status.initialized:
            print(
                "Database error: database is not initialized or needs migration. "
                f"Run 'researchpilot db init --database {resolved_database}'.",
                file=sys.stderr,
            )
            return 2

        request = RepositoryDiscoveryRequest(
            queries=tuple(github_config.queries),
            pushed_after=(
                datetime.now(timezone.utc)
                - timedelta(days=github_config.lookback_days)
            ),
            max_results=github_config.max_results,
            max_readme_characters=github_config.max_readme_characters,
        )
        with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
            result = DiscoverRepositories(
                GitHubSource(client, token=resolve_github_token()),
                SQLiteRepositoryStore(database),
            ).execute(request)
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except (GitHubError, PersistenceError) as exc:
        print(f"Discovery error: {exc}", file=sys.stderr)
        return 2

    print(f"GitHub repositories fetched: {result.fetched}")
    print(f"New repositories stored: {result.inserted}")
    print(f"Duplicates skipped: {result.duplicates}")
    print(f"Database: {resolved_database}")
    return 0


def _rank_papers(
    config_path: str | Path | None,
    database_path: str | Path | None,
) -> int:
    """Rank stored papers and print explainable decisions."""

    resolved_config = resolve_config_path(config_path)
    resolved_database = resolve_database_path(database_path)
    try:
        config = load_config(resolved_config)
        database = Database(resolved_database)
        status = database.status()
        if not status.initialized:
            print(
                "Database error: database is not initialized. "
                f"Run 'researchpilot db init --database {resolved_database}'.",
                file=sys.stderr,
            )
            return 2

        settings = config.ranking
        ranked = RankPapers(SQLitePaperRepository(database)).execute(
            config.profile,
            RankingPolicy(
                minimum_score=settings.minimum_score,
                recency_weight=settings.recency_weight,
                recency_window_days=settings.recency_window_days,
            ),
            now=datetime.now(timezone.utc),
        )
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except PersistenceError as exc:
        print(f"Ranking error: {exc}", file=sys.stderr)
        return 2

    selected_count = sum(item.selected for item in ranked)
    print(f"Papers ranked: {len(ranked)}")
    print(f"Papers selected: {selected_count}")
    print(f"Minimum score: {config.ranking.minimum_score:g}")
    if not ranked:
        print("No stored papers to rank.")
        return 0

    for position, item in enumerate(ranked, start=1):
        if item.exclusions:
            decision = "EXCLUDED"
        elif item.selected:
            decision = "SELECTED"
        else:
            decision = "BELOW THRESHOLD"
        print(f"{position}. [{decision}] {item.score:.3f} — {item.paper.title}")
        print(f"   Source: {item.paper.source.value}:{item.paper.external_id}")
        print(
            "   Score: "
            f"keywords {item.keyword_score:.3f} + "
            f"recency {item.recency_bonus:.3f}"
        )
        if item.matches:
            match_text = ", ".join(
                f"{match.interest_name}/{match.keyword} "
                f"(+{match.contribution:g})"
                for match in item.matches
            )
            print(f"   Matches: {match_text}")
        else:
            print("   Matches: none")
        if item.exclusions:
            print(f"   Excluded by: {', '.join(item.exclusions)}")
    return 0


def _rank_repositories(
    config_path: str | Path | None,
    database_path: str | Path | None,
) -> int:
    """Rank stored repositories and print explainable decisions."""

    resolved_config = resolve_config_path(config_path)
    resolved_database = resolve_database_path(database_path)
    try:
        config = load_config(resolved_config)
        database = Database(resolved_database)
        status = database.status()
        if not status.initialized:
            print(
                "Database error: database is not initialized or needs migration. "
                f"Run 'researchpilot db init --database {resolved_database}'.",
                file=sys.stderr,
            )
            return 2

        settings = config.ranking
        ranked = RankRepositories(SQLiteRepositoryStore(database)).execute(
            config.profile,
            RankingPolicy(
                minimum_score=settings.minimum_score,
                recency_weight=settings.recency_weight,
                recency_window_days=settings.recency_window_days,
            ),
            now=datetime.now(timezone.utc),
        )
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except PersistenceError as exc:
        print(f"Ranking error: {exc}", file=sys.stderr)
        return 2

    selected_count = sum(item.selected for item in ranked)
    print(f"Repositories ranked: {len(ranked)}")
    print(f"Repositories selected: {selected_count}")
    print(f"Minimum score: {config.ranking.minimum_score:g}")
    if not ranked:
        print("No stored repositories to rank.")
        return 0

    for position, item in enumerate(ranked, start=1):
        if item.exclusions:
            decision = "EXCLUDED"
        elif item.selected:
            decision = "SELECTED"
        else:
            decision = "BELOW THRESHOLD"
        repository = item.repository
        print(f"{position}. [{decision}] {item.score:.3f} — {repository.full_name}")
        print(f"   Source: {repository.source.value}:{repository.external_id}")
        print(
            "   Score: "
            f"keywords {item.keyword_score:.3f} + "
            f"recency {item.recency_bonus:.3f}"
        )
        if item.matches:
            match_text = ", ".join(
                f"{match.interest_name}/{match.keyword} "
                f"(+{match.contribution:g})"
                for match in item.matches
            )
            print(f"   Matches: {match_text}")
        else:
            print("   Matches: none")
        if item.exclusions:
            print(f"   Excluded by: {', '.join(item.exclusions)}")
    return 0


def _analyze_papers(
    config_path: str | Path | None,
    database_path: str | Path | None,
) -> int:
    """Analyze selected papers with optional bounded full text."""

    resolved_config = resolve_config_path(config_path)
    resolved_database = resolve_database_path(database_path)
    try:
        config = load_config(resolved_config)
        database = Database(resolved_database)
        status = database.status()
        if not status.initialized:
            print(
                "Database error: database is not initialized or needs migration. "
                f"Run 'researchpilot db init --database {resolved_database}'.",
                file=sys.stderr,
            )
            return 2

        ranking = config.ranking
        base_url = resolve_ollama_base_url(config.ollama.base_url)
        with httpx.Client(
            timeout=httpx.Timeout(config.ollama.timeout_seconds)
        ) as client:
            service = AnalyzePapers(
                SQLitePaperRepository(database),
                SQLiteAnalysisRepository(database),
                OllamaProvider(
                    client,
                    base_url=base_url,
                    model=config.ollama.model,
                ),
                content_provider=(
                    ArxivPDFContentProvider(client)
                    if config.content.papers.enabled
                    else None
                ),
            )
            paper_content = config.content.papers
            result = service.execute(
                config.profile,
                RankingPolicy(
                    minimum_score=ranking.minimum_score,
                    recency_weight=ranking.recency_weight,
                    recency_window_days=ranking.recency_window_days,
                ),
                max_papers=config.analysis.max_papers_per_run,
                now=datetime.now(timezone.utc),
                content_policy=PaperContentPolicy(
                    enabled=paper_content.enabled,
                    max_download_bytes=paper_content.max_download_bytes,
                    max_pages=paper_content.max_pages,
                    max_characters=paper_content.max_characters,
                ),
            )
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except PersistenceError as exc:
        print(f"Analysis error: {exc}", file=sys.stderr)
        return 2

    print(f"Selected papers: {result.selected}")
    print(f"Analysis attempts: {result.attempted}")
    print(f"Analyses succeeded: {result.succeeded}")
    print(f"Analyses failed: {result.failed}")
    print(f"Already complete: {result.already_complete}")
    print(f"Full-paper inputs: {result.full_content_used}")
    print(f"Abstract fallbacks: {len(result.fallbacks)}")
    for fallback in result.fallbacks:
        print(f"Fallback {fallback.external_id}: {fallback.reason}")
    for failure in result.failures:
        print(
            f"Failure {failure.paper_external_id}: {failure.error}",
            file=sys.stderr,
        )
    return 1 if result.failed else 0


def _analyze_repositories(
    config_path: str | Path | None,
    database_path: str | Path | None,
) -> int:
    """Analyze repositories with optional bounded source files."""

    resolved_config = resolve_config_path(config_path)
    resolved_database = resolve_database_path(database_path)
    try:
        config = load_config(resolved_config)
        database = Database(resolved_database)
        status = database.status()
        if not status.initialized:
            print(
                "Database error: database is not initialized or needs migration. "
                f"Run 'researchpilot db init --database {resolved_database}'.",
                file=sys.stderr,
            )
            return 2

        ranking = config.ranking
        base_url = resolve_ollama_base_url(config.ollama.base_url)
        with httpx.Client(
            timeout=httpx.Timeout(config.ollama.timeout_seconds)
        ) as client:
            source_content = config.content.repositories
            result = AnalyzeRepositories(
                SQLiteRepositoryStore(database),
                SQLiteRepositoryAnalysisStore(database),
                OllamaProvider(
                    client,
                    base_url=base_url,
                    model=config.ollama.model,
                ),
                content_provider=(
                    GitHubContentSource(
                        client,
                        token=resolve_github_token(),
                    )
                    if source_content.enabled
                    else None
                ),
            ).execute(
                config.profile,
                RankingPolicy(
                    minimum_score=ranking.minimum_score,
                    recency_weight=ranking.recency_weight,
                    recency_window_days=ranking.recency_window_days,
                ),
                max_repositories=config.analysis.max_repositories_per_run,
                now=datetime.now(timezone.utc),
                content_policy=RepositoryContentPolicy(
                    enabled=source_content.enabled,
                    include_patterns=tuple(source_content.include_patterns),
                    exclude_patterns=tuple(source_content.exclude_patterns),
                    max_files=source_content.max_files,
                    max_file_bytes=source_content.max_file_bytes,
                    max_total_characters=source_content.max_total_characters,
                ),
            )
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except PersistenceError as exc:
        print(f"Analysis error: {exc}", file=sys.stderr)
        return 2

    print(f"Selected repositories: {result.selected}")
    print(f"Analysis attempts: {result.attempted}")
    print(f"Analyses succeeded: {result.succeeded}")
    print(f"Analyses failed: {result.failed}")
    print(f"Already complete: {result.already_complete}")
    print(f"Missing README: {result.missing_readme}")
    print(f"Source-enhanced inputs: {result.source_content_used}")
    print(f"Content unavailable: {result.content_unavailable}")
    print(f"README fallbacks: {len(result.fallbacks)}")
    for fallback in result.fallbacks:
        print(f"Fallback {fallback.external_id}: {fallback.reason}")
    for failure in result.failures:
        print(
            f"Failure {failure.repository_external_id}: {failure.error}",
            file=sys.stderr,
        )
    return 1 if result.failed else 0


def _build_digest(
    config_path: str | Path | None,
    database_path: str | Path | None,
    output_directory: str | Path | None,
) -> int:
    """Build a deterministic local Markdown digest from stored analyses."""

    resolved_config = resolve_config_path(config_path)
    resolved_database = resolve_database_path(database_path)
    try:
        config = load_config(resolved_config)
        database = Database(resolved_database)
        status = database.status()
        if not status.initialized:
            print(
                "Database error: database is not initialized or needs migration. "
                f"Run 'researchpilot db init --database {resolved_database}'.",
                file=sys.stderr,
            )
            return 2

        ranking = config.ranking
        digest = config.digest
        result = BuildDigest(
            SQLitePaperRepository(database),
            SQLiteAnalysisRepository(database),
            SQLiteRepositoryStore(database),
            SQLiteRepositoryAnalysisStore(database),
            LocalMarkdownDigestWriter(
                digest.output_directory
                if output_directory is None
                else output_directory
            ),
        ).execute(
            config.profile,
            RankingPolicy(
                minimum_score=ranking.minimum_score,
                recency_weight=ranking.recency_weight,
                recency_window_days=ranking.recency_window_days,
            ),
            provider=OLLAMA_PROVIDER_NAME,
            model=config.ollama.model,
            max_papers=digest.max_papers,
            max_repositories=digest.max_repositories,
        )
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except DigestBuildError as exc:
        print(f"Digest not built: {exc}", file=sys.stderr)
        return 1
    except (DigestWriteError, PersistenceError) as exc:
        print(f"Digest error: {exc}", file=sys.stderr)
        return 2

    print(f"Digest written: {result.path}")
    print(f"Digest ID: {result.digest_id[:12]}")
    print(f"Papers included: {result.paper_count}")
    print(f"Repositories included: {result.repository_count}")
    print(f"Selected items without analysis: {result.missing_analysis}")
    print(f"Analyzed items omitted by limits: {result.omitted_by_limit}")
    print(f"Snapshot: {result.as_of.isoformat()}")
    return 0


def _export_digest(
    config_path: str | Path | None,
    target: str,
    digest_directory: str | Path | None,
    vault_path: str | Path | None,
) -> int:
    """Export an existing generated digest to a configured destination."""

    resolved_config = resolve_config_path(config_path)
    try:
        config = load_config(resolved_config)
        if target != "obsidian":
            print(f"Export error: unsupported digest target: {target}", file=sys.stderr)
            return 2

        obsidian = config.exports.obsidian
        selected_vault = obsidian.vault_path if vault_path is None else vault_path
        if selected_vault is None:
            print(
                "Export error: Obsidian vault path is not configured. Set "
                "exports.obsidian.vault_path or pass --vault-path.",
                file=sys.stderr,
            )
            return 2
        selected_digest_directory = (
            config.digest.output_directory
            if digest_directory is None
            else digest_directory
        )
        result = ExportDigest(
            LocalMarkdownDigestReader(selected_digest_directory),
            ObsidianExporter(selected_vault, folder=obsidian.folder),
        ).execute(digest_filename(config.profile.name))
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except (DigestReadError, ObsidianExportError, ValueError) as exc:
        print(f"Export error: {exc}", file=sys.stderr)
        return 2

    print(f"Obsidian export: {result.disposition.value}")
    print(f"Note: {result.path}")
    print(f"Digest ID: {result.digest_id[:12]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level ResearchPilot argument parser."""

    parser = argparse.ArgumentParser(
        prog="researchpilot",
        description="A local-first personal AI research assistant.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command")
    config_parser = commands.add_parser(
        "config",
        help="Inspect ResearchPilot configuration.",
    )
    config_commands = config_parser.add_subparsers(
        dest="config_command",
        required=True,
    )
    config_check = config_commands.add_parser(
        "check",
        help="Load and validate a YAML configuration file.",
    )
    config_check.add_argument(
        "--config",
        type=Path,
        help=(
            "Path to a YAML configuration file. Overrides "
            "RESEARCHPILOT_CONFIG and config/profile.yaml."
        ),
    )
    config_check.set_defaults(handler=lambda args: _check_config(args.config))

    database_parser = commands.add_parser(
        "db",
        help="Initialize or inspect the local SQLite database.",
    )
    database_commands = database_parser.add_subparsers(
        dest="database_command",
        required=True,
    )
    database_init = database_commands.add_parser(
        "init",
        help="Create or upgrade the local database.",
    )
    database_init.add_argument(
        "--database",
        type=Path,
        help=(
            "SQLite path. Overrides RESEARCHPILOT_DATABASE and researchpilot.db."
        ),
    )
    database_init.set_defaults(
        handler=lambda args: _initialize_database(args.database)
    )

    database_status = database_commands.add_parser(
        "status",
        help="Show migration and row-count status.",
    )
    database_status.add_argument(
        "--database",
        type=Path,
        help=(
            "SQLite path. Overrides RESEARCHPILOT_DATABASE and researchpilot.db."
        ),
    )
    database_status.set_defaults(
        handler=lambda args: _show_database_status(args.database)
    )

    discover_parser = commands.add_parser(
        "discover",
        help="Discover new research items from configured sources.",
    )
    discover_commands = discover_parser.add_subparsers(
        dest="discover_command",
        required=True,
    )
    discover_arxiv = discover_commands.add_parser(
        "arxiv",
        help="Discover recent ArXiv papers and store unseen results.",
    )
    discover_arxiv.add_argument(
        "--config",
        type=Path,
        help=(
            "Path to a YAML configuration file. Overrides "
            "RESEARCHPILOT_CONFIG and config/profile.yaml."
        ),
    )
    discover_arxiv.add_argument(
        "--database",
        type=Path,
        help=(
            "SQLite path. Overrides RESEARCHPILOT_DATABASE and researchpilot.db."
        ),
    )
    discover_arxiv.set_defaults(
        handler=lambda args: _discover_arxiv(args.config, args.database)
    )

    discover_github = discover_commands.add_parser(
        "github",
        help="Discover GitHub repositories and store unseen results.",
    )
    discover_github.add_argument(
        "--config",
        type=Path,
        help=(
            "Path to a YAML configuration file. Overrides "
            "RESEARCHPILOT_CONFIG and config/profile.yaml."
        ),
    )
    discover_github.add_argument(
        "--database",
        type=Path,
        help=(
            "SQLite path. Overrides RESEARCHPILOT_DATABASE and researchpilot.db."
        ),
    )
    discover_github.set_defaults(
        handler=lambda args: _discover_github(args.config, args.database)
    )

    rank_parser = commands.add_parser(
        "rank",
        help="Rank locally stored research items.",
    )
    rank_commands = rank_parser.add_subparsers(
        dest="rank_command",
        required=True,
    )
    rank_papers = rank_commands.add_parser(
        "papers",
        help="Rank stored papers with deterministic profile matching.",
    )
    rank_papers.add_argument(
        "--config",
        type=Path,
        help=(
            "Path to a YAML configuration file. Overrides "
            "RESEARCHPILOT_CONFIG and config/profile.yaml."
        ),
    )
    rank_papers.add_argument(
        "--database",
        type=Path,
        help=(
            "SQLite path. Overrides RESEARCHPILOT_DATABASE and researchpilot.db."
        ),
    )
    rank_papers.set_defaults(
        handler=lambda args: _rank_papers(args.config, args.database)
    )

    rank_repositories = rank_commands.add_parser(
        "repositories",
        help="Rank stored repositories with deterministic profile matching.",
    )
    rank_repositories.add_argument(
        "--config",
        type=Path,
        help=(
            "Path to a YAML configuration file. Overrides "
            "RESEARCHPILOT_CONFIG and config/profile.yaml."
        ),
    )
    rank_repositories.add_argument(
        "--database",
        type=Path,
        help=(
            "SQLite path. Overrides RESEARCHPILOT_DATABASE and researchpilot.db."
        ),
    )
    rank_repositories.set_defaults(
        handler=lambda args: _rank_repositories(args.config, args.database)
    )

    analyze_parser = commands.add_parser(
        "analyze",
        help="Analyze selected research items with the configured LLM.",
    )
    analyze_commands = analyze_parser.add_subparsers(
        dest="analyze_command",
        required=True,
    )
    analyze_papers = analyze_commands.add_parser(
        "papers",
        help="Analyze selected papers with optional bounded PDF text.",
    )
    analyze_papers.add_argument(
        "--config",
        type=Path,
        help=(
            "Path to a YAML configuration file. Overrides "
            "RESEARCHPILOT_CONFIG and config/profile.yaml."
        ),
    )
    analyze_papers.add_argument(
        "--database",
        type=Path,
        help=(
            "SQLite path. Overrides RESEARCHPILOT_DATABASE and researchpilot.db."
        ),
    )
    analyze_papers.set_defaults(
        handler=lambda args: _analyze_papers(args.config, args.database)
    )

    analyze_repositories = analyze_commands.add_parser(
        "repositories",
        help="Analyze repositories with optional selected source files.",
    )
    analyze_repositories.add_argument(
        "--config",
        type=Path,
        help=(
            "Path to a YAML configuration file. Overrides "
            "RESEARCHPILOT_CONFIG and config/profile.yaml."
        ),
    )
    analyze_repositories.add_argument(
        "--database",
        type=Path,
        help=(
            "SQLite path. Overrides RESEARCHPILOT_DATABASE and researchpilot.db."
        ),
    )
    analyze_repositories.set_defaults(
        handler=lambda args: _analyze_repositories(args.config, args.database)
    )

    digest_parser = commands.add_parser(
        "digest",
        help="Build and export local research digests.",
    )
    digest_commands = digest_parser.add_subparsers(
        dest="digest_command",
        required=True,
    )
    digest_build = digest_commands.add_parser(
        "build",
        help="Build deterministic Markdown from ranked successful analyses.",
    )
    digest_build.add_argument(
        "--config",
        type=Path,
        help=(
            "Path to a YAML configuration file. Overrides "
            "RESEARCHPILOT_CONFIG and config/profile.yaml."
        ),
    )
    digest_build.add_argument(
        "--database",
        type=Path,
        help=(
            "SQLite path. Overrides RESEARCHPILOT_DATABASE and researchpilot.db."
        ),
    )
    digest_build.add_argument(
        "--output-directory",
        type=Path,
        help="Directory for generated Markdown. Overrides digest.output_directory.",
    )
    digest_build.set_defaults(
        handler=lambda args: _build_digest(
            args.config,
            args.database,
            args.output_directory,
        )
    )
    digest_export = digest_commands.add_parser(
        "export",
        help="Export an existing generated digest.",
    )
    digest_export.add_argument(
        "--target",
        choices=("obsidian",),
        required=True,
        help="Export destination.",
    )
    digest_export.add_argument(
        "--config",
        type=Path,
        help=(
            "Path to a YAML configuration file. Overrides "
            "RESEARCHPILOT_CONFIG and config/profile.yaml."
        ),
    )
    digest_export.add_argument(
        "--digest-directory",
        type=Path,
        help="Generated digest directory. Overrides digest.output_directory.",
    )
    digest_export.add_argument(
        "--vault-path",
        type=Path,
        help="Obsidian vault directory. Overrides exports.obsidian.vault_path.",
    )
    digest_export.set_defaults(
        handler=lambda args: _export_digest(
            args.config,
            args.target,
            args.digest_directory,
            args.vault_path,
        )
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ResearchPilot CLI."""

    parser = build_parser()
    arguments = parser.parse_args(argv)
    handler = getattr(arguments, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(arguments)
