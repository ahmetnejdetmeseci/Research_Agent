# ResearchPilot

ResearchPilot is a local-first personal AI research assistant. It will discover,
rank, analyze, and summarize research papers and software repositories according
to a configurable interest profile.

The project is intentionally being built in small, runnable milestones. The
current foundation contains the project documentation, Python package, and CLI
entry point only. It does not yet contact external services or process research
items.

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
pytest
```

Read [docs/PROGRESS.md](docs/PROGRESS.md) for the exact current status and next
milestone.

