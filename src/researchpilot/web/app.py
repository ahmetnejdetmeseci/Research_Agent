"""FastAPI application and thin HTTP route handlers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime

from researchpilot import __version__
from researchpilot.persistence import PersistenceError, RunLockError
from researchpilot.runtime import ResearchPilotRuntime
from researchpilot.web.models import (
    HealthResponse,
    PaperRankingResponse,
    PipelineExecutionResponse,
    PipelineRunListResponse,
    PipelineRunResponse,
    RepositoryRankingResponse,
    StatusResponse,
)

STATIC_DIRECTORY = Path(__file__).with_name("static")


def _runtime(request: Request) -> ResearchPilotRuntime:
    return request.app.state.runtime


def create_app(
    *,
    config_path: str | Path | None = None,
    database_path: str | Path | None = None,
    runtime: ResearchPilotRuntime | None = None,
) -> FastAPI:
    """Create a local ResearchPilot web application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.runtime = (
            runtime
            if runtime is not None
            else ResearchPilotRuntime.load(config_path, database_path)
        )
        yield

    app = FastAPI(
        title="ResearchPilot API",
        version=__version__,
        description="Local API for ranked discoveries and pipeline execution.",
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")

    @app.exception_handler(PersistenceError)
    async def persistence_error(
        _request: Request,
        exc: PersistenceError,
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(RunLockError)
    async def run_lock_error(
        _request: Request,
        exc: RunLockError,
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIRECTORY / "index.html")

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get("/api/v1/status", response_model=StatusResponse)
    def status(request: Request) -> StatusResponse:
        return StatusResponse.from_runtime(_runtime(request), version=__version__)

    @app.get("/api/v1/papers", response_model=PaperRankingResponse)
    def papers(
        request: Request,
        as_of: Annotated[AwareDatetime | None, Query()] = None,
    ) -> PaperRankingResponse:
        return PaperRankingResponse.from_snapshot(
            _runtime(request).rank_papers(as_of)
        )

    @app.get("/api/v1/repositories", response_model=RepositoryRankingResponse)
    def repositories(
        request: Request,
        as_of: Annotated[AwareDatetime | None, Query()] = None,
    ) -> RepositoryRankingResponse:
        return RepositoryRankingResponse.from_snapshot(
            _runtime(request).rank_repositories(as_of)
        )

    @app.get("/api/v1/runs", response_model=PipelineRunListResponse)
    def runs(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> PipelineRunListResponse:
        return PipelineRunListResponse.from_history(
            _runtime(request).list_pipeline_runs(limit=limit)
        )

    @app.get("/api/v1/runs/{run_id}", response_model=PipelineRunResponse)
    def run(request: Request, run_id: int) -> PipelineRunResponse:
        history = _runtime(request).get_pipeline_run(run_id)
        if history is None:
            raise HTTPException(status_code=404, detail="pipeline run not found")
        return PipelineRunResponse.from_history(history)

    @app.post("/api/v1/runs", response_model=PipelineExecutionResponse)
    def start_run(request: Request) -> PipelineExecutionResponse:
        return PipelineExecutionResponse.from_result(
            _runtime(request).run_pipeline()
        )

    return app


app = create_app()
