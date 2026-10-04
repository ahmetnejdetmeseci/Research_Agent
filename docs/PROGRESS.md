# ResearchPilot Progress

## Current milestone

Milestone 6 — Ollama abstract analysis. Complete and verified offline.

## Completed features

- Product, architecture, roadmap, progress, and future-agent documentation.
- Python 3.11+ package metadata using a `src` layout.
- Minimal `argparse` CLI with help and version output.
- Console-script and `python -m researchpilot` entry points.
- Strict Pydantic models for weighted interests, interest profiles, and
  provider-independent paper metadata.
- YAML configuration loading with actionable file, syntax, and validation
  errors.
- Configuration path precedence: `--config`, `RESEARCHPILOT_CONFIG`, then
  `config/profile.yaml`.
- Checked-in example profile with ArXiv discovery settings.
- `config check` command with a concise validated-configuration summary.
- SQLite database wrapper with commit-on-success and rollback-on-error
  transactions.
- Bundled, consecutively numbered SQL migrations and migration history.
- Paper repository with domain-model round trips, atomic batch inserts, and
  database-enforced `(source, external_id)` deduplication.
- Run-history repository with running, succeeded, and failed states and
  finish-once behavior.
- Database path precedence: `--database`, `RESEARCHPILOT_DATABASE`, then
  `researchpilot.db`.
- `db init` and `db status` commands with schema and row-count reporting.
- Provider-independent paper-discovery port, request, result, and application
  service.
- ArXiv HTTP adapter with category and GMT submission-date queries, descending
  submission-date sorting, sequential pagination, and three-second inter-page
  delays.
- Atom XML normalization into `Paper`, including stable unversioned ArXiv IDs,
  authors, categories, abstract/PDF links, and timezone-aware dates.
- Actionable timeout, request, HTTP-status, malformed-XML, and invalid-metadata
  failures.
- `discover arxiv` command using configured categories, lookback window, result
  limit, and existing SQLite deduplication.
- Configurable minimum score, recency weight, and recency window with backwards-
  compatible defaults.
- Provider-independent `KeywordMatch` and `RankedPaper` explanation models.
- Deterministic title/abstract keyword matching with term boundaries and one
  weighted contribution per configured keyword.
- Linear recency bonus applied only to papers with a relevance match.
- Hard exclusion gating and stable selected/score/date/identity ordering.
- `rank papers` command with score components, matched keywords, exclusions,
  and selection decisions for every stored paper.
- Provider-independent `LLMProvider` interface and Ollama HTTP adapter using
  non-streaming JSON-schema output with temperature zero.
- Structured `AbstractAnalysis` validation for summary, key contributions,
  profile relevance, and limitations.
- `AnalyzePapers` service that ranks on demand, analyzes selected abstracts,
  skips successful provider/model results, and bounds work per run.
- Numbered schema migration for immutable analysis-attempt history, including
  running/succeeded/failed state, raw output, structured result, error, model,
  attempt number, and timestamps.
- Safe retries that preserve failed diagnostics; successful matching analyses
  are not processed again.
- Provider outages stop after one failed attempt, while malformed structured
  output fails one paper and permits later papers to continue.
- Configurable Ollama base URL, model, timeout, environment endpoint override,
  and maximum papers per analysis run.
- `analyze papers` command with attempt, success, failure, and skip counts.
- Offline unit, mocked-HTTP, SQLite integration, and CLI coverage.

Full-paper processing, GitHub discovery, digests, exports, scheduling, and web
functionality are not implemented. Ranking results remain computed on demand.

## Current runnable commands

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m researchpilot --help
researchpilot --version
python -m researchpilot config check --config config/profile.example.yaml
RESEARCHPILOT_CONFIG=config/profile.example.yaml researchpilot config check
python -m researchpilot db init
python -m researchpilot db status
python -m researchpilot db init --database /path/to/researchpilot.db
RESEARCHPILOT_DATABASE=/path/to/researchpilot.db researchpilot db status
python -m researchpilot discover arxiv --config config/profile.example.yaml
python -m researchpilot discover arxiv --config /path/to/profile.yaml --database /path/to/researchpilot.db
python -m researchpilot rank papers --config config/profile.example.yaml
python -m researchpilot rank papers --config /path/to/profile.yaml --database /path/to/researchpilot.db
python -m researchpilot analyze papers --config config/profile.example.yaml
RESEARCHPILOT_OLLAMA_URL=http://localhost:11434 researchpilot analyze papers --config /path/to/profile.yaml --database /path/to/researchpilot.db
pytest
```

## Tests and status

- Verified on 2026-10-03 in the project virtual environment.
- Host interpreter: Python 3.14.6.
- Pytest: 82 tests passed.
- `python -m researchpilot --help`: passed.
- `researchpilot --version`: passed and reported version `0.6.0`.
- Example and environment-selected configuration checks: passed.
- Missing configuration returns exit code 2 with an actionable error: passed.
- Fresh database status returns exit code 1 without creating a file: passed.
- Database initialization and idempotent re-initialization: passed.
- Paper round trips, uniqueness deduplication, and deterministic listing: passed.
- Run-history lifecycle and finish-once behavior: passed.
- Transaction rollback after a simulated failure: passed.
- ArXiv Atom normalization, query construction, sorting, pagination, and delay
  behavior: passed with mocked HTTP.
- ArXiv timeout, HTTP failure, malformed XML, and invalid entry handling: passed.
- Repeated ArXiv discovery stores the paper once and reports the duplicate on
  the next run: passed with mocked HTTP and a temporary SQLite database.
- `discover arxiv` CLI persistence and uninitialized-database handling: passed.
- Weighted matches, repeated terms, term and field boundaries, recency decay,
  exclusions, score thresholds, and deterministic ordering: passed.
- `rank papers` explanations and empty-database behavior: passed.
- Version 1 database upgrade to analysis schema version 2: passed.
- Analysis attempt lifecycle, raw-output retention, retry-to-success, and
  successful-analysis skipping: passed with temporary SQLite databases.
- Ollama request shape, JSON schema, timeout, unavailable server, HTTP error,
  and malformed envelope handling: passed with mocked HTTP.
- Malformed structured analysis is stored as failed and retried safely: passed.
- `analyze papers` success, skip, and validation-failure CLI behavior: passed.
- Python bytecode compilation and dependency consistency checks: passed.
- Ollama client 0.30.7 is installed, but live inference was not verified because
  no local Ollama server was running.

## Next milestone

Milestone 7 — GitHub discovery and analysis. Add GitHub repository search,
optional token authentication, rate-limit handling, README retrieval,
persistence, deduplication, deterministic ranking, and Ollama analysis; do not
add full-content source-file analysis.
