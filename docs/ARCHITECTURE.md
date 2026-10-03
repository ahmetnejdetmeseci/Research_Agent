# ResearchPilot Architecture

## Architectural style

ResearchPilot uses a small layered architecture. Dependencies point inward:

```text
CLI / future HTTP API
          |
          v
application services ---> domain models and ports
          ^                         ^
          |                         |
external integrations      persistence/export adapters
```

The domain and application layers must not import ArXiv, GitHub, Ollama,
FastAPI, or SQLite-specific types. The CLI is the initial composition root: it
loads configuration, constructs concrete adapters, invokes an application use
case, and translates errors into terminal output and exit codes.

Only modules required by the active milestone should be added. The target
package shape will grow toward:

```text
src/researchpilot/
├── cli.py
├── config.py
├── domain/          # Provider-independent models and ports
├── application/     # Use-case orchestration
├── integrations/    # ArXiv, GitHub, and Ollama HTTP adapters
├── persistence/     # SQLite connection, migrations, repositories
├── digests/         # Digest construction
├── exporters/       # Obsidian and later delivery adapters
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

### Persistence

SQLite will be accessed with the Python `sqlite3` module through repository
implementations. Numbered SQL migrations will evolve the schema. Database
uniqueness constraints and application checks will both protect against
duplicate processing.

### Interfaces

Before the web milestone, `argparse` commands are the supported interface.
FastAPI routes will later call the same application services and will not own
business logic.

## Configuration and secrets

User-editable settings and weighted interests will live in YAML and be validated
with Pydantic. Environment variables are reserved for secrets and deployment
overrides, including GitHub credentials and the Ollama endpoint. No secret or
user-specific profile belongs in version control; the repository will provide
an example profile when configuration is implemented.

## Planned data flow

```text
source adapter -> domain discovery -> SQLite -> deterministic ranking
       -> LLM analysis -> digest builder -> exporter
```

Each step records enough status to be safely retried. Exported Markdown is
derived output; SQLite remains the local source of truth.

## Error handling and observability

- Integration failures are translated into project-level errors at adapter
  boundaries.
- A failed analysis is not marked complete and may be retried.
- CLI commands return nonzero exit codes for failed operations and concise,
  actionable messages.
- Scheduled runs will record step outcomes and identifiers so interrupted runs
  can resume without duplicating work.

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

