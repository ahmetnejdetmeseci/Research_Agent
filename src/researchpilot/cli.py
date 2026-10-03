"""Command-line entry point for ResearchPilot."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from researchpilot import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level ResearchPilot argument parser."""

    parser = argparse.ArgumentParser(
        prog="researchpilot",
        description="A local-first personal AI research assistant.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ResearchPilot CLI."""

    build_parser().parse_args(argv)
    return 0

