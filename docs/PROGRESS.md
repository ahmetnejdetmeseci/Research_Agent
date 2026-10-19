# ResearchPilot Progress

## Current milestone

Milestone 9 — Digest generation. Complete and verified offline.

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
- Provider-independent repository discovery, persistence, ranking, and analysis
  models and ports.
- GitHub REST repository search with ordered configured queries, recent-activity
  and non-archived filters, pagination, stable-ID deduplication across queries,
  and optional `GITHUB_TOKEN` authentication.
- README retrieval with missing-README handling and a configurable character
  limit applied before persistence and LLM use.
- Actionable GitHub transport, HTTP, malformed-response, and rate-limit errors,
  including reset time when GitHub supplies it.
- SQLite repository round trips and database-enforced `(source, external_id)`
  deduplication.
- Deterministic repository ranking across names, descriptions, topics, primary
  language, and README content using the existing explainable ranking policy.
- Immutable repository-analysis attempt history with retry-to-success behavior
  and one success per repository/provider/model.
- Bounded Ollama README analysis with validated summaries, capabilities,
  relevance, notable technologies, and limitations.
- Missing READMEs are reported and skipped without a failed LLM attempt;
  provider outages stop the run and malformed structured output remains
  retryable.
- `discover github`, `rank repositories`, and `analyze repositories` commands,
  repository counts in `db status`, and GitHub status in `config check`.
- Opt-in full-paper acquisition through an ArXiv PDF content provider with
  streamed byte limits, PDF validation, `pypdf` extraction, page limits,
  character limits, truncation reporting, and fallback-safe errors.
- Opt-in GitHub source-file acquisition through recursive tree inspection,
  relative include/exclude patterns, deterministic file selection, UTF-8 and
  binary checks, per-file byte limits, file-count limits, and aggregate
  character limits.
- Repository source files can augment a README or provide analysis input when a
  README is unavailable.
- Abstract-only and README-only behavior remains the default. Unavailable,
  unsupported, encrypted, image-only, oversized, binary, or missing content
  falls back when baseline content exists and otherwise produces a partial,
  non-failed outcome.
- Persisted content provenance records content kind, locators, character counts,
  page count where available, truncation state, and acquisition warnings without
  storing extracted PDF or source text.
- Analysis-success identity now includes content kind, so a previous abstract
  or README analysis does not prevent a later full-paper or source-enhanced
  analysis.
- Fourth SQLite migration upgrades legacy analysis attempts to `abstract` or
  `readme` provenance while preserving their results and retry history.
- Independent `content.papers` and `content.repositories` configuration with
  explicit limits and safe relative source patterns.
- CLI analysis summaries report enriched inputs, fallbacks, and unavailable
  content.
- Provider-independent digest and entry models for normalized Markdown input.
- Deterministic digest construction from on-demand paper and repository
  rankings plus successful analyses for the configured Ollama model.
- Richest-analysis selection prefers full-paper over abstract results and
  README-plus-source over source-only or README-only results.
- Stable snapshot time derived from stored publication and repository activity,
  preventing wall-clock score drift when the local state is unchanged.
- Configurable, independent paper and repository digest limits; selected items
  without matching analyses and analyzed items omitted by limits are reported.
- Markdown entries contain source links, ranking scores and matches, structured
  summaries, relevance, limitations, provider/model identity, analyzed content
  kind, completion time, content references, truncation state, and warnings.
- Profile-specific safe filenames and idempotent atomic file replacement;
  rebuilding an unchanged snapshot is byte-for-byte stable and never appends
  duplicate entries.
- `digest build` command with configuration/database path precedence and a
  one-command `--output-directory` override. Digest building is entirely local
  and does not contact Ollama or source APIs.
- Backwards-compatible `digest` configuration defaults for output directory and
  item limits. The generated root `digests/` directory is ignored by Git.
- Project version `0.9.0`.

Obsidian export, scheduling, and web functionality are not implemented.
Extracted full content is intentionally ephemeral; ranking results remain
computed on demand, and Markdown digests are derived local output.

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
python -m researchpilot discover github --config config/profile.example.yaml
GITHUB_TOKEN=your_token researchpilot discover github --config /path/to/profile.yaml --database /path/to/researchpilot.db
python -m researchpilot rank repositories --config config/profile.example.yaml
python -m researchpilot analyze repositories --config config/profile.example.yaml
python -m researchpilot digest build --config config/profile.example.yaml
python -m researchpilot digest build --config /path/to/profile.yaml --database /path/to/researchpilot.db --output-directory /path/to/digests
pytest
```

Full-content analysis uses the same `analyze papers` and `analyze repositories`
commands. Enable and bound it under `content.papers` or
`content.repositories` in the selected profile. Both remain disabled in the
checked-in example.

Digest generation requires at least one selected paper or repository with a
successful analysis for the configured Ollama model. It reads local state only;
an Ollama server is not required while building the digest.

## Tests and status

- Verified on 2026-10-15 in the project virtual environment.
- Host interpreter: Python 3.14.6.
- Pytest: 134 tests passed.
- `python -m researchpilot --help`: passed.
- `researchpilot --version`: passed and reported version `0.9.0`.
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
- GitHub request construction, optional authentication, normalization,
  pagination, cross-query deduplication, missing READMEs, malformed responses,
  and rate limits: passed with mocked HTTP.
- Repository persistence, deterministic ranking, successful-analysis skipping,
  retry-to-success, missing-README behavior, provider outages, and CLI
  workflows: passed offline.
- Live GitHub API access was not invoked; the default suite remains offline and
  deterministic.
- ArXiv PDF download limits, PDF validation, text extraction, character
  truncation, and invalid-document handling: passed with generated PDFs and
  mocked HTTP.
- GitHub tree selection, include/exclude filtering, source retrieval, binary and
  size handling, aggregate truncation, no-match behavior, and rate-limit
  fallback: passed with mocked HTTP.
- Full-paper/source-enhanced success identity, persisted provenance, baseline
  fallback, no-content partial outcomes, and CLI composition: passed with
  temporary databases and fake content/LLM providers.
- `pypdf` 6.20.1 is installed for local extraction. Live paper downloads and
  live source-file retrieval were not invoked.
- Deterministic digest rendering, enriched-analysis preference, paper and
  repository source links, content provenance, missing-analysis reporting, and
  stable item ordering: passed with provider-independent fakes.
- Local Markdown directory creation, safe filename enforcement, identical-file
  reuse, atomic replacement, and non-appending rebuild behavior: passed with
  temporary directories.
- `digest build` CLI composition, exact rebuild stability, one-entry-only
  output, output-directory override, and actionable missing-analysis behavior:
  passed with a temporary SQLite database.

## Next milestone

Milestone 10 — Obsidian export. Add an exporter port and filesystem-based
Obsidian adapter with configurable vault paths and safe filenames. Unrelated
notes must never be silently overwritten.
