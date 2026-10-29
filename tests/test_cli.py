from datetime import datetime, timezone

from researchpilot import __version__
from researchpilot.cli import main
from researchpilot.digests import digest_filename
from researchpilot.domain import (
    AbstractAnalysis,
    AnalysisContentKind,
    ContentReference,
    Paper,
    PaperSource,
    RepositorySource,
    RetrievedContent,
    SoftwareRepository,
)
from researchpilot.persistence import (
    Database,
    SQLiteAnalysisRepository,
    SQLitePaperRepository,
    SQLiteRepositoryStore,
)


def write_test_config(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text(
        """
profile:
  name: Test research
  interests:
    - name: AI agents
      keywords: [agentic systems, tool use, planning]
      weight: 1
  exclusions: []
sources:
  arxiv:
    enabled: true
    categories: [cs.AI]
  github:
    enabled: true
    queries: [agent planning]
ranking:
  minimum_score: 1
  recency_weight: 0.5
  recency_window_days: 30
ollama:
  model: llama3.2
analysis:
  max_papers_per_run: 10
  max_repositories_per_run: 10
""".strip(),
        encoding="utf-8",
    )
    return path


def enable_full_content(path, *, papers: bool = False, repositories: bool = False):
    path.write_text(
        path.read_text(encoding="utf-8")
        + f"""

content:
  papers:
    enabled: {str(papers).lower()}
  repositories:
    enabled: {str(repositories).lower()}
    include_patterns: ["*.py"]
""",
        encoding="utf-8",
    )
    return path


def test_help_exits_successfully(capsys) -> None:
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("--help did not exit")

    output = capsys.readouterr().out
    assert "local-first personal AI research assistant" in output


def test_version_exits_successfully(capsys) -> None:
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("--version did not exit")

    assert capsys.readouterr().out.strip() == f"researchpilot {__version__}"


def test_config_check_accepts_example_profile(capsys) -> None:
    result = main(["config", "check", "--config", "config/profile.example.yaml"])

    captured = capsys.readouterr()
    assert result == 0
    assert "Configuration valid: config/profile.example.yaml" in captured.out
    assert "(2 interests)" in captured.out
    assert "GitHub: enabled (2 queries)" in captured.out
    assert captured.err == ""


def test_config_check_reports_missing_file(capsys, tmp_path) -> None:
    missing_path = tmp_path / "missing.yaml"

    result = main(["config", "check", "--config", str(missing_path)])

    captured = capsys.readouterr()
    assert result == 2
    assert f"configuration file not found: {missing_path}" in captured.err


def test_config_check_uses_environment_path(capsys, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCHPILOT_CONFIG", "config/profile.example.yaml")

    result = main(["config", "check"])

    captured = capsys.readouterr()
    assert result == 0
    assert "Configuration valid: config/profile.example.yaml" in captured.out


def test_database_init_and_status(capsys, tmp_path) -> None:
    database_path = tmp_path / "data" / "researchpilot.db"

    init_result = main(["db", "init", "--database", str(database_path)])
    init_output = capsys.readouterr()
    status_result = main(["db", "status", "--database", str(database_path)])
    status_output = capsys.readouterr()

    assert init_result == 0
    assert f"Database ready: {database_path}" in init_output.out
    assert "Applied migrations: 001_initial" in init_output.out
    assert "002_paper_analysis_attempts" in init_output.out
    assert "003_github_repositories" in init_output.out
    assert "004_analysis_content_provenance" in init_output.out
    assert status_result == 0
    assert "Status: ready" in status_output.out
    assert "Schema version: 4/4" in status_output.out
    assert "Papers: 0" in status_output.out
    assert "Repositories: 0" in status_output.out
    assert "Runs: 0" in status_output.out
    assert "Analysis attempts: 0" in status_output.out


def test_database_status_reports_not_initialized(capsys, tmp_path) -> None:
    database_path = tmp_path / "missing.db"

    result = main(["db", "status", "--database", str(database_path)])

    captured = capsys.readouterr()
    assert result == 1
    assert "Status: not initialized" in captured.out
    assert database_path.exists() is False


def test_database_command_uses_environment_path(capsys, monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "environment.db"
    monkeypatch.setenv("RESEARCHPILOT_DATABASE", str(database_path))

    result = main(["db", "init"])

    captured = capsys.readouterr()
    assert result == 0
    assert f"Database ready: {database_path}" in captured.out
    assert database_path.exists()


def test_discover_arxiv_persists_and_then_skips_duplicate(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "researchpilot.db"
    Database(database_path).initialize()

    class FakeArxivSource:
        def __init__(self, client) -> None:
            self.client = client

        def search(self, **kwargs) -> list[Paper]:
            return [
                Paper(
                    source=PaperSource.ARXIV,
                    external_id="2601.00001",
                    title="A useful paper",
                    abstract="A useful abstract.",
                    authors=["Ada Lovelace"],
                    published_at="2026-01-02T12:00:00Z",
                    url="https://arxiv.org/abs/2601.00001",
                    categories=["cs.AI"],
                )
            ]

    monkeypatch.setattr("researchpilot.cli.ArxivSource", FakeArxivSource)
    command = [
        "discover",
        "arxiv",
        "--config",
        "config/profile.example.yaml",
        "--database",
        str(database_path),
    ]

    first_result = main(command)
    first_output = capsys.readouterr()
    second_result = main(command)
    second_output = capsys.readouterr()

    assert first_result == second_result == 0
    assert "ArXiv papers fetched: 1" in first_output.out
    assert "New papers stored: 1" in first_output.out
    assert "Duplicates skipped: 1" in second_output.out


def test_discover_arxiv_requires_initialized_database(capsys, tmp_path) -> None:
    database_path = tmp_path / "missing.db"

    result = main(
        [
            "discover",
            "arxiv",
            "--config",
            "config/profile.example.yaml",
            "--database",
            str(database_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "database is not initialized" in captured.err
    assert database_path.exists() is False


def test_rank_papers_prints_score_explanation(capsys, tmp_path) -> None:
    database_path = tmp_path / "researchpilot.db"
    database = Database(database_path)
    database.initialize()
    SQLitePaperRepository(database).add(
        Paper(
            source=PaperSource.ARXIV,
            external_id="2601.00001",
            title="Planning for agentic systems",
            abstract="A paper about tool use.",
            authors=["Ada Lovelace"],
            published_at=datetime.now(timezone.utc),
            url="https://arxiv.org/abs/2601.00001",
        )
    )
    config_path = write_test_config(tmp_path)

    result = main(
        [
            "rank",
            "papers",
            "--config",
            str(config_path),
            "--database",
            str(database_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Papers ranked: 1" in captured.out
    assert "Papers selected: 1" in captured.out
    assert "[SELECTED]" in captured.out
    assert "AI agents/agentic systems (+1)" in captured.out
    assert "AI agents/planning (+1)" in captured.out


def test_rank_papers_handles_empty_database(capsys, tmp_path) -> None:
    database_path = tmp_path / "researchpilot.db"
    Database(database_path).initialize()

    result = main(
        [
            "rank",
            "papers",
            "--config",
            "config/profile.example.yaml",
            "--database",
            str(database_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Papers ranked: 0" in captured.out
    assert "No stored papers to rank." in captured.out


def test_analyze_papers_persists_success_and_skips_next_run(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "researchpilot.db"
    database = Database(database_path)
    database.initialize()
    SQLitePaperRepository(database).add(
        Paper(
            source=PaperSource.ARXIV,
            external_id="2601.00001",
            title="Planning for agentic systems",
            abstract="A paper about tool use.",
            authors=["Ada Lovelace"],
            published_at=datetime.now(timezone.utc),
            url="https://arxiv.org/abs/2601.00001",
        )
    )
    config_path = write_test_config(tmp_path)

    class FakeOllamaProvider:
        provider_name = "ollama"
        model_name = "llama3.2"
        calls = 0

        def __init__(self, client, *, base_url, model) -> None:
            self.model_name = model

        def generate(self, **kwargs) -> str:
            type(self).calls += 1
            return """{
                "summary": "A concise summary.",
                "key_contributions": ["A useful contribution."],
                "relevance_to_profile": "Directly relevant.",
                "limitations": []
            }"""

    monkeypatch.setattr("researchpilot.cli.OllamaProvider", FakeOllamaProvider)
    command = [
        "analyze",
        "papers",
        "--config",
        str(config_path),
        "--database",
        str(database_path),
    ]

    first_result = main(command)
    first_output = capsys.readouterr()
    second_result = main(command)
    second_output = capsys.readouterr()

    assert first_result == second_result == 0
    assert "Analyses succeeded: 1" in first_output.out
    assert "Already complete: 1" in second_output.out
    assert FakeOllamaProvider.calls == 1
    assert Database(database_path).status().analysis_attempt_count == 1


def test_digest_build_is_deterministic_and_does_not_append(
    capsys,
    tmp_path,
) -> None:
    database_path = tmp_path / "researchpilot.db"
    output_directory = tmp_path / "digests"
    database = Database(database_path)
    database.initialize()
    paper = Paper(
        source=PaperSource.ARXIV,
        external_id="2601.00001",
        title="Planning for agentic systems",
        abstract="A paper about tool use.",
        authors=["Ada Lovelace"],
        published_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        url="https://arxiv.org/abs/2601.00001",
    )
    SQLitePaperRepository(database).add(paper)
    analyses = SQLiteAnalysisRepository(database)
    attempt = analyses.begin_attempt(
        paper,
        "ollama",
        "llama3.2",
        started_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    analyses.succeed(
        attempt.id,
        AbstractAnalysis(
            summary="A concise summary.",
            key_contributions=["A useful contribution."],
            relevance_to_profile="Directly relevant.",
            limitations=[],
        ),
        "{}",
        completed_at=datetime(2026, 1, 3, 0, 1, tzinfo=timezone.utc),
    )
    config_path = write_test_config(tmp_path)
    command = [
        "digest",
        "build",
        "--config",
        str(config_path),
        "--database",
        str(database_path),
        "--output-directory",
        str(output_directory),
    ]

    first_result = main(command)
    first_output = capsys.readouterr()
    digest_path = next(output_directory.glob("*.md"))
    first_content = digest_path.read_text(encoding="utf-8")
    second_result = main(command)
    second_output = capsys.readouterr()

    assert first_result == second_result == 0
    assert "Papers included: 1" in first_output.out
    assert "Repositories included: 0" in first_output.out
    assert "Digest written:" in second_output.out
    assert list(output_directory.glob("*.md")) == [digest_path]
    assert digest_path.read_text(encoding="utf-8") == first_content
    assert first_content.count("Planning for agentic systems") == 1


def test_digest_build_reports_missing_analysis(capsys, tmp_path) -> None:
    database_path = tmp_path / "researchpilot.db"
    database = Database(database_path)
    database.initialize()
    SQLitePaperRepository(database).add(
        Paper(
            source=PaperSource.ARXIV,
            external_id="2601.00001",
            title="Planning for agentic systems",
            abstract="A paper about tool use.",
            authors=["Ada Lovelace"],
            published_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            url="https://arxiv.org/abs/2601.00001",
        )
    )

    result = main(
        [
            "digest",
            "build",
            "--config",
            str(write_test_config(tmp_path)),
            "--database",
            str(database_path),
            "--output-directory",
            str(tmp_path / "digests"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "run the analysis commands first" in captured.err
    assert (tmp_path / "digests").exists() is False


def test_digest_export_to_obsidian_is_idempotent(capsys, tmp_path) -> None:
    config_path = write_test_config(tmp_path)
    digest_directory = tmp_path / "digests"
    digest_directory.mkdir()
    source = digest_directory / digest_filename("Test research")
    source.write_text("# ResearchPilot Digest\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    command = [
        "digest",
        "export",
        "--target",
        "obsidian",
        "--config",
        str(config_path),
        "--digest-directory",
        str(digest_directory),
        "--vault-path",
        str(vault),
    ]

    first_result = main(command)
    first_output = capsys.readouterr()
    second_result = main(command)
    second_output = capsys.readouterr()
    note = vault / "ResearchPilot" / source.name

    assert first_result == second_result == 0
    assert "Obsidian export: created" in first_output.out
    assert "Obsidian export: unchanged" in second_output.out
    assert note.exists()
    assert note.read_text(encoding="utf-8").endswith(
        "# ResearchPilot Digest\n"
    )


def test_digest_export_refuses_unrelated_obsidian_note(capsys, tmp_path) -> None:
    config_path = write_test_config(tmp_path)
    digest_directory = tmp_path / "digests"
    digest_directory.mkdir()
    filename = digest_filename("Test research")
    (digest_directory / filename).write_text("# Digest\n", encoding="utf-8")
    vault = tmp_path / "vault"
    note_directory = vault / "ResearchPilot"
    note_directory.mkdir(parents=True)
    note = note_directory / filename
    note.write_text("# Keep me\n", encoding="utf-8")

    result = main(
        [
            "digest",
            "export",
            "--target",
            "obsidian",
            "--config",
            str(config_path),
            "--digest-directory",
            str(digest_directory),
            "--vault-path",
            str(vault),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "refusing to overwrite unrelated Obsidian note" in captured.err
    assert note.read_text(encoding="utf-8") == "# Keep me\n"


def test_digest_export_requires_configured_vault(capsys, tmp_path) -> None:
    result = main(
        [
            "digest",
            "export",
            "--target",
            "obsidian",
            "--config",
            str(write_test_config(tmp_path)),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "Obsidian vault path is not configured" in captured.err


def test_analyze_papers_reports_invalid_structured_output(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "researchpilot.db"
    database = Database(database_path)
    database.initialize()
    SQLitePaperRepository(database).add(
        Paper(
            source=PaperSource.ARXIV,
            external_id="2601.00001",
            title="Planning systems",
            abstract="Planning research.",
            authors=["Ada Lovelace"],
            published_at=datetime.now(timezone.utc),
            url="https://arxiv.org/abs/2601.00001",
        )
    )
    config_path = write_test_config(tmp_path)

    class InvalidOllamaProvider:
        provider_name = "ollama"
        model_name = "llama3.2"

        def __init__(self, client, *, base_url, model) -> None:
            self.model_name = model

        def generate(self, **kwargs) -> str:
            return "not json"

    monkeypatch.setattr("researchpilot.cli.OllamaProvider", InvalidOllamaProvider)

    result = main(
        [
            "analyze",
            "papers",
            "--config",
            str(config_path),
            "--database",
            str(database_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "Analyses failed: 1" in captured.out
    assert "invalid structured analysis" in captured.err
    assert Database(database_path).status().analysis_attempt_count == 1


def make_repository() -> SoftwareRepository:
    return SoftwareRepository(
        source=RepositorySource.GITHUB,
        external_id="123",
        full_name="example/planning-tools",
        owner="example",
        name="planning-tools",
        description="Agent planning tools.",
        readme="# Planning tools\nTool use for agentic systems.",
        url="https://github.com/example/planning-tools",
        default_branch="main",
        primary_language="Python",
        created_at="2026-01-01T00:00:00Z",
        updated_at=datetime.now(timezone.utc),
        pushed_at=datetime.now(timezone.utc),
    )


def test_discover_github_persists_and_skips_duplicate(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "researchpilot.db"
    Database(database_path).initialize()
    config_path = write_test_config(tmp_path)

    class FakeGitHubSource:
        def __init__(self, client, *, token=None) -> None:
            self.token = token

        def search(self, **kwargs) -> list[SoftwareRepository]:
            return [make_repository()]

    monkeypatch.setattr("researchpilot.cli.GitHubSource", FakeGitHubSource)
    command = [
        "discover",
        "github",
        "--config",
        str(config_path),
        "--database",
        str(database_path),
    ]

    first_result = main(command)
    first_output = capsys.readouterr()
    second_result = main(command)
    second_output = capsys.readouterr()

    assert first_result == second_result == 0
    assert "GitHub repositories fetched: 1" in first_output.out
    assert "New repositories stored: 1" in first_output.out
    assert "Duplicates skipped: 1" in second_output.out


def test_rank_repositories_prints_score_explanation(capsys, tmp_path) -> None:
    database_path = tmp_path / "researchpilot.db"
    database = Database(database_path)
    database.initialize()
    SQLiteRepositoryStore(database).add(make_repository())
    config_path = write_test_config(tmp_path)

    result = main(
        [
            "rank",
            "repositories",
            "--config",
            str(config_path),
            "--database",
            str(database_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Repositories ranked: 1" in captured.out
    assert "Repositories selected: 1" in captured.out
    assert "[SELECTED]" in captured.out
    assert "AI agents/planning (+1)" in captured.out


def test_analyze_repositories_persists_success_and_skips_next_run(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "researchpilot.db"
    database = Database(database_path)
    database.initialize()
    SQLiteRepositoryStore(database).add(make_repository())
    config_path = write_test_config(tmp_path)

    class FakeOllamaProvider:
        provider_name = "ollama"
        model_name = "llama3.2"
        calls = 0

        def __init__(self, client, *, base_url, model) -> None:
            self.model_name = model

        def generate(self, **kwargs) -> str:
            type(self).calls += 1
            return """{
                "summary": "A concise summary.",
                "key_capabilities": ["Agent planning."],
                "relevance_to_profile": "Directly relevant.",
                "notable_technologies": ["Python"],
                "limitations": []
            }"""

    monkeypatch.setattr("researchpilot.cli.OllamaProvider", FakeOllamaProvider)
    command = [
        "analyze",
        "repositories",
        "--config",
        str(config_path),
        "--database",
        str(database_path),
    ]

    first_result = main(command)
    first_output = capsys.readouterr()
    second_result = main(command)
    second_output = capsys.readouterr()

    assert first_result == second_result == 0
    assert "Analyses succeeded: 1" in first_output.out
    assert "Already complete: 1" in second_output.out
    assert FakeOllamaProvider.calls == 1
    assert Database(database_path).status().repository_analysis_attempt_count == 1


def test_analyze_papers_wires_enabled_full_content(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "researchpilot.db"
    database = Database(database_path)
    database.initialize()
    paper = Paper(
        source=PaperSource.ARXIV,
        external_id="2601.00001",
        title="Planning systems",
        abstract="Planning abstract.",
        authors=["Ada Lovelace"],
        published_at=datetime.now(timezone.utc),
        url="https://arxiv.org/abs/2601.00001",
        pdf_url="https://arxiv.org/pdf/2601.00001",
    )
    SQLitePaperRepository(database).add(paper)
    config_path = enable_full_content(write_test_config(tmp_path), papers=True)

    class FakeContentProvider:
        def __init__(self, client) -> None:
            pass

        def retrieve(self, paper, **limits) -> RetrievedContent:
            return RetrievedContent(
                text="Full paper planning content.",
                references=[
                    ContentReference(
                        label="PDF",
                        locator=str(paper.pdf_url),
                        characters=28,
                        pages=2,
                    )
                ],
            )

    class FakeOllamaProvider:
        provider_name = "ollama"
        model_name = "llama3.2"

        def __init__(self, client, *, base_url, model) -> None:
            self.model_name = model

        def generate(self, **kwargs) -> str:
            return """{
                "summary": "Summary",
                "key_contributions": ["Contribution"],
                "relevance_to_profile": "Relevant",
                "limitations": []
            }"""

    monkeypatch.setattr(
        "researchpilot.cli.ArxivPDFContentProvider",
        FakeContentProvider,
    )
    monkeypatch.setattr("researchpilot.cli.OllamaProvider", FakeOllamaProvider)

    result = main(
        [
            "analyze",
            "papers",
            "--config",
            str(config_path),
            "--database",
            str(database_path),
        ]
    )

    captured = capsys.readouterr()
    attempts = SQLiteAnalysisRepository(database).list_attempts(
        paper.source,
        paper.external_id,
    )
    assert result == 0
    assert "Full-paper inputs: 1" in captured.out
    assert attempts[0].content_trace.kind is AnalysisContentKind.FULL_PAPER


def test_analyze_repositories_wires_enabled_source_content(
    capsys,
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "researchpilot.db"
    database = Database(database_path)
    database.initialize()
    item = make_repository()
    SQLiteRepositoryStore(database).add(item)
    config_path = enable_full_content(
        write_test_config(tmp_path),
        repositories=True,
    )

    class FakeContentProvider:
        def __init__(self, client, *, token=None) -> None:
            pass

        def retrieve(self, repository, **limits) -> RetrievedContent:
            return RetrievedContent(
                text="FILE: planner.py\ndef plan(): pass",
                references=[
                    ContentReference(
                        label="planner.py",
                        locator=f"{repository.url}/blob/main/planner.py",
                        characters=16,
                    )
                ],
            )

    class FakeOllamaProvider:
        provider_name = "ollama"
        model_name = "llama3.2"

        def __init__(self, client, *, base_url, model) -> None:
            self.model_name = model

        def generate(self, **kwargs) -> str:
            return """{
                "summary": "Summary",
                "key_capabilities": ["Planning"],
                "relevance_to_profile": "Relevant",
                "notable_technologies": ["Python"],
                "limitations": []
            }"""

    monkeypatch.setattr(
        "researchpilot.cli.GitHubContentSource",
        FakeContentProvider,
    )
    monkeypatch.setattr("researchpilot.cli.OllamaProvider", FakeOllamaProvider)

    result = main(
        [
            "analyze",
            "repositories",
            "--config",
            str(config_path),
            "--database",
            str(database_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Source-enhanced inputs: 1" in captured.out
