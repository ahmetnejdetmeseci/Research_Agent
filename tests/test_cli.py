from datetime import datetime, timezone

from researchpilot import __version__
from researchpilot.cli import main
from researchpilot.domain import Paper, PaperSource
from researchpilot.persistence import Database, SQLitePaperRepository


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
    assert "Profile: AI systems research (2 interests)" in captured.out
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
    assert status_result == 0
    assert "Status: ready" in status_output.out
    assert "Schema version: 2/2" in status_output.out
    assert "Papers: 0" in status_output.out
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
        "config/profile.example.yaml",
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
            "config/profile.example.yaml",
            "--database",
            str(database_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "Analyses failed: 1" in captured.out
    assert "invalid structured analysis" in captured.err
    assert Database(database_path).status().analysis_attempt_count == 1
