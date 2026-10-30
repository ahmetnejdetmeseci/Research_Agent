# ResearchPilot Architecture

## Architectural style

ResearchPilot uses a small layered architecture. Dependencies point inward:

```text
CLI / local HTTP API / dashboard
          |
          v
application services ---> domain models and ports
          ^                         ^
          |                         |
external integrations      persistence/export adapters
```

The domain and application layers must not import ArXiv, GitHub, Ollama,
FastAPI, or SQLite-specific types. `ResearchPilotRuntime` is the shared
composition root: it loads configuration, constructs concrete adapters, and
invokes application use cases. The CLI and FastAPI interface translate those
outcomes into terminal or HTTP representations without duplicating workflow
rules.

Only modules required by the active milestone should be added. The target
package shape will grow toward:

```text
src/researchpilot/
├── cli.py
├── config.py
├── runtime.py       # Shared CLI/API composition of concrete adapters
├── domain/          # Provider-independent models and ports
├── application/     # Use-case orchestration
├── integrations/    # ArXiv, GitHub, and Ollama HTTP adapters
├── persistence/     # SQLite connection, migrations, repositories
├── digests/         # Digest construction
├── exporters/       # Obsidian and later delivery adapters
├── web/             # Thin FastAPI routes and static dashboard
└── agent/           # Future bounded agent loop and typed tools
```

## Layer responsibilities

### Domain

Pydantic domain models will represent concepts such as papers, software
repositories, interest profiles, ranked items, analyses, and digests. They use
stable source identifiers but never embed external response objects.

Small `Protocol` ports will be introduced only at genuine boundaries: discovery
sources, LLM providers, repositories, and exporters. A port should not be added
merely to anticipate an unknown implementation.

### Application

Application services coordinate discovery, persistence, ranking, analysis, and
digest workflows. They may depend on domain ports but must not perform raw HTTP,
SQL, filesystem export, or CLI formatting.

### Integrations

Each integration owns transport details, authentication, rate limits, response
parsing, and conversion to domain models. `httpx` clients and base URLs will be
injectable so normal tests remain offline.

`ArxivSource` implements the paper-discovery port. It builds category and GMT
submission-date queries, retrieves sequential Atom pages through an injected
`httpx.Client`, normalizes entries into `Paper`, and translates transport or
response failures into `ArxivError`. It waits three seconds between paginated
requests, following the legacy API rate limit, while an injected sleeper keeps
tests instantaneous. The adapter contains no persistence or ranking logic.

`DiscoverPapers` is the provider-independent application service connecting a
paper source to a paper repository. It returns fetched, inserted, and duplicate
counts; the same service can later accept another source without importing
ArXiv-specific types.

`GitHubSource` implements the repository-discovery port through the GitHub REST
API. It runs configured repository queries with a pushed-date and non-archived
filter, paginates in API order, deduplicates stable numeric repository IDs
across queries, and retrieves README Markdown when available. Optional
authentication comes only from `GITHUB_TOKEN`. Search and README payloads remain
adapter-local; the adapter returns normalized `SoftwareRepository` models and
translates transport, response, and rate-limit failures into `GitHubError`.
README content is bounded by the configured character limit before it enters
the domain.

`DiscoverRepositories` connects a repository source to a repository store and
returns the same fetched, inserted, and duplicate counts. A missing README is
valid repository metadata rather than a failed discovery.

### Full-content acquisition

Full-content acquisition is optional and bounded before content reaches an LLM.
`ArxivPDFContentProvider` streams a paper PDF with a byte limit, validates the
document, and extracts text through `pypdf` with page and character limits.
Encrypted, malformed, image-only, oversized, unavailable, or partially
extractable documents produce a provider-independent content error or warning;
the application can continue with the abstract.

`GitHubContentSource` retrieves a recursive repository tree, applies configured
include and exclude patterns, and fetches only selected UTF-8 files. Per-file
bytes, file count, and aggregate characters are bounded. Missing, binary,
oversized, rate-limited, or unavailable files do not invalidate stored README
content. A repository without a README may still be analyzed when selected
source files are available.

Extracted PDF and source text is ephemeral and is not stored in SQLite. Analysis
attempts retain a compact `AnalysisContentTrace`: content kind, locators,
character counts, page count where applicable, truncation state, and warnings.

### Deterministic ranking

`RankPapers` loads normalized papers through the repository port and delegates
to `DeterministicPaperRanker`. Matching is case-insensitive and respects term
boundaries independently within title and abstract. Each distinct configured
keyword contributes its interest weight once, regardless of repeated mentions.

A paper with at least one keyword match receives a recency bonus that decays
linearly from `recency_weight` to zero across `recency_window_days`. A paper with
no keyword match receives no recency bonus. The final score is keyword score plus
recency bonus; `minimum_score` controls selection, while any matching exclusion
is a hard gate even when the score is high.

`RankedPaper` retains every keyword contribution, matched exclusion, score
component, and decision. Rankings are currently derived on demand rather than
persisted because they depend on the active profile and evaluation time. This
avoids stale stored scores while the ranking contract is still evolving.

`RankRepositories` applies the same contribution, exclusion, threshold, and
recency policy to repository names, descriptions, topics, primary language, and
README content. Recent activity uses `pushed_at` when available and otherwise
`updated_at`. Repository rankings are also computed on demand.

### LLM analysis

`LLMProvider` is a provider-independent port accepting a system prompt, user
prompt, and JSON schema, and returning raw generated text. `OllamaProvider`
implements it with a non-streaming `/api/generate` request, the configured local
model, the Pydantic response schema, and temperature zero. It translates HTTP,
timeout, connectivity, and malformed-envelope failures into `LLMProviderError`.

`AnalyzePapers` recomputes deterministic rankings, processes only selected
papers, and uses bounded full-paper text when enabled and available. Otherwise
it uses the abstract and records the fallback reason. It validates raw output as
`AbstractAnalysis`, containing a summary, one to five key contributions,
profile relevance, and up to five limitations. The prompt treats supplied
content as data and asks the model not to invent unsupported details.

Analysis runs are bounded by `max_papers_per_run`. A provider outage fails the
current attempt and stops the run rather than repeatedly contacting a down
service; invalid structured output fails only that paper and allows the run to
continue.

`AnalyzeRepositories` follows the same bounded, auditable workflow. When source
content is enabled, selected files augment the README or provide the complete
input when no README exists. Acquisition failure falls back to the README;
items with neither source text nor a README are reported as partial outcomes
without creating a failed LLM attempt.

Successful analyses are unique by item, provider, model, and content kind. An
existing abstract or README success therefore does not prevent a later
full-paper or source-enhanced analysis. Failed structured output remains
retryable.

### Digest generation

`BuildDigest` is a provider-independent workflow over paper, repository, and
analysis ports. It recomputes deterministic rankings, considers only selected
items, and reads successful analyses for the configured provider and model. A
full-paper analysis is preferred over an abstract analysis. A combined README
and source-file analysis is preferred over source-only and README-only results.
The configured paper and repository limits bound digest length; selected items
without a matching analysis are reported rather than analyzed implicitly.

When no explicit snapshot time is supplied, the digest ranking clock is the
latest publication or repository-activity timestamp in the stored input. This
makes unchanged local state and configuration render byte-for-byte identical
Markdown instead of allowing wall-clock recency drift. Each entry includes the
source link, score and keyword matches, structured summary, relevance,
limitations, provider/model identity, content kind, analysis completion time,
and retained content references and warnings.

`LocalMarkdownDigestWriter` is a narrow filesystem adapter. It writes a safe,
profile-specific filename under the configured directory, replaces the whole
file through an atomic rename, and leaves an identical existing file untouched.
It never appends, so rebuilding a snapshot cannot duplicate entries. Markdown
is derived output and is ignored by version control; SQLite analysis history
remains the source of truth.

### Obsidian export

`DigestReader` and `DigestExporter` are provider-independent ports for loading
one generated digest and delivering it to a configured destination.
`ExportDigest` connects those ports and reports the digest content hash,
destination path, and whether the export was created, updated, or unchanged. It
does not rebuild the digest, read SQLite, or contact Ollama or source APIs.

`LocalMarkdownDigestReader` reads only a validated plain Markdown filename from
the configured digest directory. It rejects missing, empty, non-regular, and
symbolic-link inputs. `ObsidianExporter` requires an existing vault directory,
creates only a normalized relative folder beneath it, rejects symbolic links in
the destination path, and retains the profile-specific digest filename.

Each exported note begins with a ResearchPilot ownership marker containing the
source digest hash. A missing destination is created without overwriting a
concurrent file; an identical managed note is left untouched; and a changed
managed note is atomically replaced. Any existing note without the ownership
marker is treated as unrelated and causes an actionable error. There is no
force-overwrite option in this milestone.

### Periodic end-to-end runs

`RunPipeline` is a provider-independent coordinator over ordered typed step
definitions and a `PipelineRepository` port. The shared runtime composes the
existing discovery, analysis, digest, and export use cases into six explicit steps:
ArXiv discovery, GitHub discovery, paper analysis, repository analysis, digest
building, and Obsidian export. Source steps follow their enabled settings;
Obsidian export is enabled only when a vault is configured. Digest and export
steps may record an intentional skip when no analyzed content is available.

Each pipeline is identified by its resolved configuration and database paths.
The original run start time is reused as the discovery and ranking clock after
a resume. Step status, attempt count, scalar metrics, errors, and timestamps are
persisted. A normal step exception records both the step and run as failed. A
hard process interruption leaves the current step and run in `running` state;
the next invocation skips succeeded or skipped steps and restarts only the
interrupted step. All underlying operations remain independently idempotent, so
a new run after a recorded failure is also safe.

`LocalRunLock` holds a non-blocking advisory lock beside the selected database
for the lifetime of the command. This prevents cron or launchd invocations from
overlapping while allowing the operating system to release the lock after a
crash. ResearchPilot does not contain a timer, background thread, or daemon;
`docs/SCHEDULING.md` documents absolute-path cron and launchd invocations.

### Persistence

SQLite will be accessed with the Python `sqlite3` module through repository
implementations. Numbered SQL migrations will evolve the schema. Database
uniqueness constraints and application checks will both protect against
duplicate processing.

`Database` owns connection lifetime, commit-on-success, rollback-on-error, and
ordered migration application. Applied versions are recorded in
`schema_migrations`. Paper identity is the unique pair `(source, external_id)`;
authors and categories are serialized as JSON arrays at the SQLite boundary and
restored as domain values by `SQLitePaperRepository`. `SQLiteRunRepository`
records command executions as running, succeeded, or failed and permits each run
to be finished only once.

`SQLiteAnalysisRepository` stores every analysis attempt rather than replacing
earlier diagnostics. Each attempt records provider, model, attempt number,
state, raw output when available, validated structured output on success, error
on failure, and timestamps. A partial unique index permits only one successful
analysis for each paper/provider/model/content-kind while failed or interrupted
attempts can be retried as new rows.

`SQLiteRepositoryStore` persists normalized repository metadata and enforces
unique `(source, external_id)` identity. `SQLiteRepositoryAnalysisStore`
retains immutable README-analysis attempts and permits only one successful
result per repository/provider/model/content-kind while preserving retry
diagnostics.

The fourth migration adds content kind and JSON provenance to both analysis
attempt tables. Legacy attempts become `abstract` or `readme` attempts. Partial
unique indexes include content kind so baseline and enriched analyses can
coexist without being repeated.

The fifth migration adds a nullable pipeline identity to existing run history
and an ordered `run_steps` table. A partial unique index permits only one active
run per pipeline identity. Legacy run rows remain valid and have no pipeline
identity.

The database path uses the following precedence: the CLI `--database` option,
`RESEARCHPILOT_DATABASE`, then `researchpilot.db`. Database commands do not
require the research-profile configuration.

### API and dashboard

FastAPI routes are interface adapters over `ResearchPilotRuntime`. They expose
versioned JSON endpoints for health, safe configuration/database status,
timestamped paper and repository rankings, recent pipeline history, individual
run detail, and pipeline triggering. Route handlers validate query parameters,
invoke one runtime operation, and serialize its domain outcome; discovery,
ranking, analysis, digest, and export rules remain in application services.

Application startup uses FastAPI's lifespan hook to load and validate the
selected configuration and current SQLite database once. Synchronous route
handlers keep blocking SQLite and `httpx.Client` workflows out of the event
loop. Persistence failures produce a service-unavailable response and an
overlapping pipeline lock produces a conflict response. A pipeline step failure
remains a recorded domain outcome returned by the trigger endpoint rather than
being hidden as a transport failure.

The dashboard is a static, dependency-free HTML/CSS/JavaScript client served by
the same application. It reads only `/api/v1` endpoints, renders text through
DOM text nodes, and does not access SQLite or configuration directly. The server
binds to `127.0.0.1` by default. This milestone adds no authentication,
multi-user state, CORS policy for remote clients, or hosted deployment.

## Configuration and secrets

User-editable settings and weighted interests will live in YAML and be validated
with Pydantic. Environment variables are reserved for secrets and deployment
overrides, including GitHub credentials and the Ollama endpoint. No secret or
user-specific profile belongs in version control; the repository provides an
example profile as the documented starting point.

The configuration path uses the following precedence: the CLI `--config`
option, `RESEARCHPILOT_CONFIG`, then `config/profile.yaml`. The checked-in
`config/profile.example.yaml` documents the schema; `config/profile.yaml` is
ignored so a user's profile is not committed accidentally.

The `ranking` section controls `minimum_score`, `recency_weight`, and
`recency_window_days`. Defaults preserve compatibility with profiles created
before deterministic ranking was introduced.

The `ollama` section controls local base URL, model, and request timeout;
`RESEARCHPILOT_OLLAMA_URL` overrides the configured endpoint. The `analysis`
section limits attempts per command run. Defaults preserve compatibility with
older profiles.

The optional `sources.github` section controls whether GitHub discovery is
enabled, ordered search queries, activity lookback, result limit, and README
character limit. It defaults to disabled so older profiles remain valid. The
`GITHUB_TOKEN` environment variable enables authenticated API requests; tokens
are never read from YAML. Paper and repository analysis have independent
per-run limits.

The `content` section independently enables paper PDFs and repository source
files. Paper settings bound download bytes, pages, and extracted characters.
Repository settings define relative POSIX include/exclude patterns plus file,
byte, and aggregate-character limits. Both paths default to disabled, preserving
the existing abstract-only and README-only behavior.

The `digest` section selects a local output directory and independently bounds
paper and repository entries. Defaults are `digests`, ten papers, and ten
repositories. `digest build --output-directory` can override the directory for
one command without changing the profile.

The `exports.obsidian` section contains an optional vault path and a normalized
relative folder, defaulting to `ResearchPilot`. The example leaves the vault
unset because it is user-specific. `digest export --target obsidian` requires a
configured path or a one-command `--vault-path` override; `--digest-directory`
can locate a digest built with an earlier output-directory override.

## Planned data flow

```text
ArXiv adapter  -> DiscoverPapers       -> Paper              -> SQLite
GitHub adapter -> DiscoverRepositories -> SoftwareRepository -> SQLite
       -> deterministic ranking -> bounded analysis -> LLMProvider
       -> immutable attempt history -> digest builder -> local Markdown
       -> ExportDigest -> Obsidian filesystem adapter
OS scheduler -> RunPipeline -> persisted run/step outcomes
CLI / API -> ResearchPilotRuntime -> shared application services
dashboard -> /api/v1 -> ranked items and pipeline history
```

Each step records enough status to be safely retried. Exported Markdown is
derived output; SQLite remains the local source of truth.

## Error handling and observability

- Integration failures are translated into project-level errors at adapter
  boundaries.
- A failed analysis is not marked complete and may be retried.
- CLI commands return nonzero exit codes for failed operations and concise,
  actionable messages.
- Scheduled runs record step outcomes and identifiers so interrupted runs can
  resume without duplicating work.

## Testing strategy

- Unit tests cover validation, deterministic ranking, orchestration, and state
  transitions.
- Integration tests cover SQLite implementations and adapters using mocked HTTP
  transports.
- The default test suite is offline and deterministic.
- Optional live-service checks are explicitly marked and never required by the
  normal test command.

## Initial architectural decisions

- Python 3.11+ with a `src` package layout and `pyproject.toml`.
- Standard `venv` and `pip` workflow.
- `argparse` before FastAPI.
- YAML plus environment variables for configuration.
- `sqlite3` repositories rather than an ORM.
- ArXiv before GitHub.
- Transparent deterministic ranking before LLM-assisted analysis.
- Ollama behind a provider-independent port.
- OS-level scheduling rather than an in-process scheduler.
- No agent framework; future agent concepts will be implemented explicitly.
