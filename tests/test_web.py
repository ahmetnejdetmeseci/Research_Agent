from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from researchpilot.application import (
    PipelineStepDefinition,
    PipelineStepExecution,
    RunPipeline,
)
from researchpilot.domain import Paper, PaperSource, RepositorySource, SoftwareRepository
from researchpilot.persistence import (
    Database,
    RunLockError,
    SQLitePaperRepository,
    SQLitePipelineRepository,
    SQLiteRepositoryStore,
)
from researchpilot.runtime import ResearchPilotRuntime
from researchpilot.web import create_app

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@asynccontextmanager
async def app_client(app):
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client


def write_config(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text(
        """
profile:
  name: Web test
  interests:
    - name: Agent systems
      keywords: [planning, tool use]
      weight: 1.5
sources:
  arxiv:
    enabled: false
    categories: [cs.AI]
  github:
    enabled: false
ranking:
  minimum_score: 1
  recency_weight: 0
ollama:
  model: llama-test
""".strip(),
        encoding="utf-8",
    )
    return path


def make_runtime(tmp_path) -> ResearchPilotRuntime:
    database_path = tmp_path / "researchpilot.db"
    database = Database(database_path)
    database.initialize()
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    SQLitePaperRepository(database).add(
        Paper(
            source=PaperSource.ARXIV,
            external_id="2610.00001",
            title="Planning with tool use",
            abstract="A practical agent system.",
            authors=["Ada Lovelace"],
            published_at=now,
            url="https://arxiv.org/abs/2610.00001",
        )
    )
    SQLiteRepositoryStore(database).add(
        SoftwareRepository(
            source=RepositorySource.GITHUB,
            external_id="42",
            full_name="example/planning-tools",
            owner="example",
            name="planning-tools",
            description="Tool use for planning agents.",
            url="https://github.com/example/planning-tools",
            default_branch="main",
            primary_language="Python",
            stars=12,
            created_at=now,
            updated_at=now,
        )
    )
    return ResearchPilotRuntime.load(write_config(tmp_path), database_path)


async def test_dashboard_and_static_assets_are_served(tmp_path) -> None:
    async with app_client(create_app(runtime=make_runtime(tmp_path))) as client:
        dashboard = await client.get("/")
        stylesheet = await client.get("/static/styles.css")
        script = await client.get("/static/app.js")

    assert dashboard.status_code == 200
    assert "ResearchPilot" in dashboard.text
    assert stylesheet.status_code == 200
    assert "--accent" in stylesheet.text
    assert script.status_code == 200
    assert "/api/v1/papers" in script.text


async def test_health_status_and_rankings_expose_shared_domain_outcomes(
    tmp_path,
) -> None:
    runtime = make_runtime(tmp_path)
    as_of = "2026-10-29T12:00:00Z"
    expected_papers = runtime.rank_papers(
        datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    )

    async with app_client(create_app(runtime=runtime)) as client:
        health = await client.get("/api/v1/health")
        status = await client.get("/api/v1/status")
        papers = await client.get("/api/v1/papers", params={"as_of": as_of})
        repositories = await client.get(
            "/api/v1/repositories",
            params={"as_of": as_of},
        )

    assert health.json() == {"status": "ok", "version": "0.12.0"}
    assert status.status_code == 200
    assert status.json()["profile"] == "Web test"
    assert status.json()["database"]["papers"] == 1
    assert status.json()["ollama_model"] == "llama-test"
    assert papers.status_code == 200
    assert papers.json()["selected_count"] == expected_papers.selected_count == 1
    assert papers.json()["items"][0]["paper"]["external_id"] == "2610.00001"
    assert repositories.json()["selected_count"] == 1
    assert repositories.json()["items"][0]["repository"]["external_id"] == "42"


async def test_ranking_rejects_naive_as_of_timestamp(tmp_path) -> None:
    async with app_client(create_app(runtime=make_runtime(tmp_path))) as client:
        response = await client.get(
            "/api/v1/papers",
            params={"as_of": "2026-10-29T12:00:00"},
        )

    assert response.status_code == 422


async def test_run_history_and_detail_are_read_from_pipeline_repository(
    tmp_path,
) -> None:
    runtime = make_runtime(tmp_path)
    result = RunPipeline(SQLitePipelineRepository(runtime.database)).execute(
        "web-test-key",
        (
            PipelineStepDefinition(
                "test_step",
                True,
                lambda _context: PipelineStepExecution({"items": 2}),
            ),
        ),
    )

    async with app_client(create_app(runtime=runtime)) as client:
        listing = await client.get("/api/v1/runs")
        detail = await client.get(f"/api/v1/runs/{result.run.id}")
        missing = await client.get("/api/v1/runs/999")
        invalid_limit = await client.get("/api/v1/runs?limit=101")

    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert listing.json()["items"][0]["steps"][0]["result"] == {"items": 2}
    assert detail.json()["run"]["id"] == result.run.id
    assert missing.status_code == 404
    assert invalid_limit.status_code == 422


async def test_pipeline_endpoint_calls_shared_runtime_use_case(tmp_path) -> None:
    runtime = make_runtime(tmp_path)
    expected = RunPipeline(SQLitePipelineRepository(runtime.database)).execute(
        "api-trigger",
        (
            PipelineStepDefinition(
                "shared_use_case",
                True,
                lambda _context: PipelineStepExecution({"complete": True}),
            ),
        ),
    )

    class RuntimeSpy:
        calls = 0

        def run_pipeline(self):
            self.calls += 1
            return expected

    spy = RuntimeSpy()
    async with app_client(create_app(runtime=spy)) as client:
        response = await client.post("/api/v1/runs")

    assert response.status_code == 200
    assert response.json()["run"]["id"] == expected.run.id
    assert response.json()["steps"][0]["name"] == "shared_use_case"
    assert spy.calls == 1


async def test_overlapping_pipeline_returns_conflict(tmp_path) -> None:
    class BusyRuntime:
        def run_pipeline(self):
            raise RunLockError("another pipeline is already running")

    async with app_client(create_app(runtime=BusyRuntime())) as client:
        response = await client.post("/api/v1/runs")

    assert response.status_code == 409
    assert response.json() == {"detail": "another pipeline is already running"}
