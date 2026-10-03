# ResearchPilot Roadmap

Only the active milestone may be implemented unless scope is explicitly changed.
Every milestone must leave the project runnable and update `PROGRESS.md` with
verified commands and test results.

## 1. Foundation

Create product and architecture documentation, Python packaging, a help-only CLI
entry point, and pytest configuration. No product workflow is implemented.

Acceptance: editable installation succeeds, `python -m researchpilot --help`
exits successfully, and the test suite passes.

## 2. Configuration and domain

Define the interest-profile YAML schema and provider-independent paper models.
Add a `config check` command and validation tests, including environment
overrides where appropriate.

Acceptance: a checked-in example profile validates; invalid or missing settings
produce actionable errors without contacting external services.

## 3. Local persistence

Add SQLite initialization, numbered migrations, paper repositories, run history,
and uniqueness-based deduplication. Add `db init` and `db status` commands.

Acceptance: migrations and data round trips work in temporary databases;
duplicate identifiers do not create duplicate records; failed transactions roll
back.

## 4. ArXiv discovery

Add an ArXiv adapter and discovery service. `discover arxiv` uses configured
dates, categories, and limits, then persists normalized paper metadata.

Acceptance: XML parsing, pagination, timeouts, malformed responses, and repeated
runs are covered with mocked HTTP; repeated ArXiv IDs are skipped.

## 5. Deterministic ranking

Rank papers through weighted term matching, exclusions, recency, and configurable
thresholds. Add `rank papers` and preserve human-readable score explanations.

Acceptance: ranking is deterministic, explainable, and covered for ties,
exclusions, thresholds, and missing optional metadata.

## 6. Ollama abstract analysis

Add an LLM provider port and Ollama adapter. `analyze papers` processes selected
abstracts into validated structured results and retains diagnostic raw output.

Acceptance: unavailable Ollama, timeouts, malformed responses, and safe retries
are tested; failures are not marked complete.

## 7. GitHub discovery and analysis

Add repository search, optional token authentication, rate-limit handling,
README retrieval, persistence, ranking, and Ollama analysis. Add `discover
github` and `analyze repositories`.

Acceptance: GitHub transport models remain adapter-local; offline tests cover
pagination, rate limits, missing READMEs, deduplication, and retries.

## 8. Full-content analysis

Add optional full-paper extraction and selected GitHub source-file analysis with
explicit content limits. Abstract-only and README-only processing remain valid
fallbacks.

Acceptance: unsupported or unavailable content does not prevent a partial,
traceable analysis.

## 9. Digest generation

Build local Markdown digests from ranked analyses with source links and
provenance. Add `digest build`.

Acceptance: output is deterministic for a fixed run and rebuilding does not
duplicate entries.

## 10. Obsidian export

Add an exporter port and filesystem-based Obsidian adapter. Add `digest export
--target obsidian` with a configurable vault path.

Acceptance: paths and filenames are safe and unrelated notes are never silently
overwritten.

## 11. Periodic end-to-end runs

Add an idempotent `run` command that performs the configured pipeline. Document
cron and launchd usage rather than adding an in-process scheduler.

Acceptance: step outcomes are recorded and an interrupted run can safely resume.

## 12. API and dashboard

Expose stable application services through FastAPI and build the dashboard on
those endpoints. Route handlers contain no business logic.

Acceptance: CLI and API exercise the same use cases and produce equivalent
domain outcomes.

## 13. Additional delivery channels

Add Telegram and Notion adapters behind delivery or export interfaces.

Acceptance: channel credentials and delivery failures remain isolated from
digest creation.

## 14. Agent loop

Add a small explicit loop in which the LLM chooses from typed application tools.
Bound iterations, validate tool input, retain traces, and require approval for
side effects.

Acceptance: tests cover tool selection, invalid calls, iteration limits, and
approval gates without adding an agent framework.

