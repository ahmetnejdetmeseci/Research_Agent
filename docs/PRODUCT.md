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

Only the foundation milestone exists. ResearchPilot currently provides package
metadata and a help-only CLI. It does not yet discover, store, rank, analyze, or
export anything.

## Non-goals for the initial milestones

- Multi-user accounts, cloud hosting, or distributed execution.
- A web API or dashboard before CLI workflows stabilize.
- An autonomous agent before deterministic workflows are proven.
- LangChain or another agent framework.
- Supporting every research source, LLM provider, or export destination.

