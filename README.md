# ResearchPilot

ResearchPilot is a local-first personal AI research assistant. It will discover,
rank, analyze, and summarize research papers and software repositories according
to a configurable interest profile.

The project is intentionally being built in small, runnable milestones. The
current version discovers and stores ArXiv papers and GitHub repositories,
ranks both with an explainable interest profile, analyzes selected content
through a local Ollama model, and builds deterministic local Markdown digests.
Optional bounded PDF extraction and selected GitHub source-file retrieval
enrich the existing abstract and README workflows; unavailable content falls
back safely with persisted provenance.

## Requirements

- Python 3.11 or newer

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Run

```bash
python -m researchpilot --help
python -m researchpilot config check --config config/profile.example.yaml
python -m researchpilot db init
python -m researchpilot db status
python -m researchpilot discover arxiv --config config/profile.example.yaml
python -m researchpilot discover github --config config/profile.example.yaml
python -m researchpilot rank papers --config config/profile.example.yaml
python -m researchpilot rank repositories --config config/profile.example.yaml
python -m researchpilot analyze papers --config config/profile.example.yaml
python -m researchpilot analyze repositories --config config/profile.example.yaml
python -m researchpilot digest build --config config/profile.example.yaml
pytest
```

`discover arxiv` makes live requests to ArXiv and requires an initialized
database. Repeating the command safely skips paper identities already stored.
`rank papers` displays weighted keyword matches, recency contribution,
exclusions, and the final selection decision for every stored paper.
`analyze papers` requires a running Ollama server and the configured model
(the example uses `llama3.2`). It analyzes only selected papers, skips successful
provider/model analyses, and safely retries failed attempts on later runs.

`discover github` searches the configured queries and stores repository metadata
plus available README content. Set `GITHUB_TOKEN` for authenticated requests and
higher API limits. Repository ranking and analysis use the same profile and
Ollama configuration as papers; repositories without a README remain stored but
are skipped by analysis.

Full-content analysis is opt-in under the profile's `content` section. Enabling
`content.papers.enabled` allows bounded PDF extraction. Enabling
`content.repositories.enabled` retrieves only files matching the configured
include patterns, subject to file-count, byte, and character limits. The example
profile documents every setting with both paths disabled by default.

`digest build` uses only selected items with successful analyses for the
configured Ollama model. It writes one profile-specific file under the
configured `digest.output_directory` (or `--output-directory`), includes source
links and content provenance, and atomically replaces the generated file on a
rebuild. It does not contact Ollama. Obsidian export is a later milestone.

Read [docs/PROGRESS.md](docs/PROGRESS.md) for the exact current status and next
milestone.
