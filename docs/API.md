# ResearchPilot Local API

Milestone 12 adds a local FastAPI application and dashboard over the existing
application services. Initialize the database first, then start the server:

```bash
python -m researchpilot db init --database /path/to/researchpilot.db
python -m researchpilot serve \
  --config /path/to/profile.yaml \
  --database /path/to/researchpilot.db
```

The default address is `http://127.0.0.1:8000`. The dashboard is at `/`, the
OpenAPI interface is at `/docs`, and the JSON contract is versioned under
`/api/v1`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Process health and application version. |
| `GET` | `/api/v1/status` | Safe profile, source, model, schema, and row-count status. |
| `GET` | `/api/v1/papers` | Rank all stored papers at an optional timezone-aware `as_of`. |
| `GET` | `/api/v1/repositories` | Rank all stored repositories at an optional timezone-aware `as_of`. |
| `GET` | `/api/v1/runs?limit=20` | Return recent pipeline runs and ordered step outcomes. |
| `GET` | `/api/v1/runs/{run_id}` | Return one pipeline run or `404`. |
| `POST` | `/api/v1/runs` | Start or resume the same pipeline used by the CLI. |

Ranking responses contain all stored items, their selected decision, score
components, matched profile keywords, and exclusions. Run responses contain the
persisted run plus ordered steps, scalar metrics, errors, and timestamps.

An overlapping pipeline request returns `409`. A local persistence failure
returns `503`. A pipeline whose application step fails returns its recorded
failed run outcome, allowing the dashboard to show the exact failed step.

## Security boundary

This is a single-user local interface. It exposes no GitHub token, Ollama URL,
Obsidian vault path, or configuration secrets, but it has a pipeline-triggering
endpoint and no authentication. Keep the default localhost binding unless a
later milestone explicitly designs authentication and remote deployment.
