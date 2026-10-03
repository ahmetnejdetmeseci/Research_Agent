# ResearchPilot Progress

## Current milestone

Milestone 1 — Foundation. Complete and verified.

## Completed features

- Product, architecture, roadmap, progress, and future-agent documentation.
- Python 3.11+ package metadata using a `src` layout.
- Minimal `argparse` CLI with help and version output.
- Console-script and `python -m researchpilot` entry points.
- Initial pytest configuration and CLI smoke tests.

Research discovery, configuration loading, persistence, ranking, LLM access,
digests, exports, scheduling, and web functionality are not implemented.

## Current runnable commands

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m researchpilot --help
researchpilot --version
pytest
```

## Tests and status

- Verified on 2026-10-03 in a fresh project virtual environment.
- Host interpreter: Python 3.14.6.
- Pytest: 2 tests passed.
- `python -m researchpilot --help`: passed.
- `researchpilot --version`: passed and reported version `0.1.0`.

## Next milestone

Milestone 2 — Configuration and domain. Add the validated YAML interest profile,
provider-independent paper models, and `config check`; do not add SQLite or
external API calls yet.
