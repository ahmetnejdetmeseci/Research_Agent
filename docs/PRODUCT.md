# ResearchPilot Product

## Vision

ResearchPilot is a personal AI research assistant that periodically discovers
research papers and software repositories relevant to a user's technical
interests. It reduces the effort needed to monitor fast-moving fields while
keeping the user in control of local data, ranking criteria, and model usage.

## Target user

The initial product is for one technically proficient user running ResearchPilot
locally. The user wants a transparent, inspectable workflow rather than a hosted
black box or a fully autonomous agent.

## Core workflow

When the planned core workflow is complete, ResearchPilot will:

1. Load a configurable interest profile.
2. Discover recent papers from ArXiv and repositories from GitHub.
3. Normalize and store discoveries locally without repeatedly processing the
   same item.
4. Rank discoveries with understandable scoring rules.
5. Use a local Ollama model to analyze selected content.
6. Build a concise research digest with links and provenance.
7. Export the digest to Obsidian.
8. Run safely on demand or from an operating-system scheduler.

## Product principles

- Local-first storage and local LLM inference are the defaults.
- Users must be able to understand why an item was selected.
- Failed or interrupted processing must be safe to retry.
- External APIs and model providers must be replaceable without rewriting the
  product's core workflows.
- Automation should remain bounded and observable.

## Long-term capabilities

- ArXiv paper discovery and GitHub repository discovery.
- Configurable ranking and exclusion rules.
- Abstract, full-paper, README, and selected source-file analysis.
- Ollama-backed analysis, initially using a Llama-family model.
- Local persistence, deduplication, and processing history.
- Markdown research digests and Obsidian export.
- Telegram and Notion delivery.
- A FastAPI-backed web dashboard.
- A bounded agent loop that selects from typed tools.

## Current product state

The foundation through the local API and dashboard is in place. ResearchPilot
can validate a YAML interest profile; discover recent ArXiv papers and GitHub
repositories; normalize and persist both item types without duplicates; rank
them with explainable deterministic rules; and analyze selected abstracts,
bounded PDF text, READMEs, or explicitly selected source files through a local
Ollama model. Full-content acquisition is opt-in and falls back safely to an
abstract or README, with content provenance and fallback reasons retained.

ResearchPilot can build a concise local Markdown digest from selected items
that have successful analyses for the configured model. Digests include source
links, ranking matches, analysis provenance, and content references. An
unchanged local-state snapshot produces byte-for-byte identical output, and
rebuilding replaces the generated file rather than appending duplicate entries.

An existing generated digest can be exported into a configured Obsidian vault.
ResearchPilot uses a managed-note marker, safe generated filenames, relative
vault folders, and symbolic-link checks. It updates only notes it previously
created; a colliding ordinary note is never silently overwritten. Other export
targets are not implemented yet.

One `run` command or the local dashboard performs the configured discovery,
analysis, digest, and optional Obsidian-export pipeline. Step outcomes are
persisted locally, overlapping invocations for the same database are rejected,
and a run left incomplete by a hard interruption resumes without repeating
completed steps. Scheduling is delegated to cron or launchd rather than an
in-process daemon.

A local FastAPI application now exposes health and configuration status, live
paper and repository rankings, persisted pipeline history, individual run
detail, and pipeline triggering. A dependency-free HTML/CSS/JavaScript
dashboard consumes only those JSON endpoints. The CLI and HTTP interface share
one runtime composition layer, so they execute the same application services
and produce the same domain outcomes. The server binds to localhost by default;
authentication, multi-user access, and remote deployment remain out of scope.

## Non-goals for the initial milestones

- Multi-user accounts, cloud hosting, or distributed execution.
- An autonomous agent before deterministic workflows are proven.
- LangChain or another agent framework.
- Supporting every research source, LLM provider, or export destination.
