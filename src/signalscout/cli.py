"""Command-line entry point.

Typer keeps each command a plain typed function, so commands stay testable through
``CliRunner`` without spawning a process.
"""

from __future__ import annotations

import typer

from signalscout import __version__

app = typer.Typer(
    help="Find accounts that need GTM-ops help now, from public signals.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """SignalScout: seeds -> public signals -> tiered accounts -> Clay and HubSpot."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)
