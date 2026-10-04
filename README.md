# ResearchPilot

ResearchPilot is a local-first personal AI research assistant. It will discover,
rank, analyze, and summarize research papers and software repositories according
to a configurable interest profile.

The project is intentionally being built in small, runnable milestones. The
current version contains the project foundation, validated YAML interest
profiles, provider-independent paper models, local SQLite persistence, and
ArXiv paper discovery. It can deterministically rank stored papers with an
explainable interest profile and analyze selected abstracts through a local
Ollama model. Full-paper analysis and digest generation are not implemented.

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
python -m researchpilot rank papers --config config/profile.example.yaml
python -m researchpilot analyze papers --config config/profile.example.yaml
pytest
```

`discover arxiv` makes live requests to ArXiv and requires an initialized
database. Repeating the command safely skips paper identities already stored.
`rank papers` displays weighted keyword matches, recency contribution,
exclusions, and the final selection decision for every stored paper.
`analyze papers` requires a running Ollama server and the configured model
(the example uses `llama3.2`). It analyzes only selected papers, skips successful
provider/model analyses, and safely retries failed attempts on later runs.

Read [docs/PROGRESS.md](docs/PROGRESS.md) for the exact current status and next
milestone.
