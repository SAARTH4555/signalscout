"""Command-line entry point.

Typer keeps each command a plain typed function, so commands stay testable through
``CliRunner`` without spawning a process.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from signalscout import __version__
from signalscout.accounts import Account, merge_accounts
from signalscout.export import write_outputs
from signalscout.fetch import ConfigError, DiskCache, Fetcher, FetchError, HttpFetcher
from signalscout.offline import DEFAULT_DIR, load_offline
from signalscout.pipeline import RunOptions, run
from signalscout.score import ScoredAccount, load_scoring
from signalscout.seeds import YcFilter, csv_accounts, fetch_yc, yc_accounts
from signalscout.settings import get_settings

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


@app.command(name="run")
def run_cmd(
    offline: Annotated[
        bool, typer.Option(help="Use the recorded demo world in examples/offline (no network).")
    ] = False,
    seed_csv: Annotated[Path | None, typer.Option(help="Extra accounts: name,domain CSV.")] = None,
    yc: Annotated[bool, typer.Option(help="Include the YC directory as a seed.")] = True,
    min_team: Annotated[int, typer.Option(help="YC filter: smallest team size.")] = 50,
    max_team: Annotated[int, typer.Option(help="YC filter: largest team size.")] = 500,
    limit: Annotated[int | None, typer.Option(help="Only the first N accounts.")] = None,
    funding: Annotated[bool, typer.Option(help="Look up SEC Form D funding.")] = True,
    crm: Annotated[bool, typer.Option(help="Scan company websites for CRM scripts.")] = True,
    as_of: Annotated[str | None, typer.Option(help="Score as of this date (YYYY-MM-DD).")] = None,
    scoring: Annotated[Path, typer.Option(help="Scoring rules YAML.")] = Path(
        "config/scoring.yaml"
    ),
    out: Annotated[Path, typer.Option(help="Output directory.")] = Path("data/out"),
    hubspot_tiers: Annotated[str, typer.Option(help="Tiers handed to PipelineOS.")] = "A",
    report: Annotated[Path | None, typer.Option(help="Write the run summary JSON here.")] = None,
) -> None:
    """Find accounts that need GTM-ops help now, score them, and write the outputs."""
    settings = get_settings()
    fetcher: Fetcher
    if offline:
        fetcher, day = load_offline(DEFAULT_DIR)
        contact: str | None = "offline-demo@example.com"
    else:
        contact = settings.contact_email
        fetcher = HttpFetcher(
            contact_email=contact,
            cache=DiskCache(settings.cache_dir),
            ttl_s=settings.cache_ttl_hours * 3600,
        )
        day = date.today()
    if as_of is not None:
        day = date.fromisoformat(as_of)

    accounts: list[Account] = []
    try:
        if yc:
            kept, seed_report = yc_accounts(fetch_yc(fetcher), YcFilter(min_team, max_team))
            accounts += kept
            typer.echo(f"YC directory: {seed_report.kept} of {seed_report.loaded} companies kept")
        if seed_csv is not None:
            accounts += csv_accounts(seed_csv)
    except FetchError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    accounts = merge_accounts(accounts)[:limit]
    if not accounts:
        typer.echo("error: no accounts to look at (no seeds kept)", err=True)
        raise typer.Exit(1)

    def progress(i: int, total: int, scored: ScoredAccount) -> None:
        key = scored.signals.account.company_key
        typer.echo(f"  [{i}/{total}] {key:<28} Tier {scored.tier}  score {scored.score:>3}")

    try:
        result = run(
            fetcher,
            accounts,
            load_scoring(scoring),
            RunOptions(as_of=day, with_funding=funding, with_crm=crm),
            contact_email=contact,
            progress=progress,
        )
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    written = write_outputs(result.scored, out, day, hubspot_tiers)
    summary = result.summary()
    summary["as_of"] = day.isoformat()
    summary["mode"] = "offline" if offline else "live"
    tiers = summary["tiers"]
    typer.echo(f"\nTier A {tiers['A']}, Tier B {tiers['B']}, Tier C {tiers['C']}")  # type: ignore[index]
    for name, rows in written.items():
        typer.echo(f"  wrote {out / name} ({rows} rows)")
    top = [s for s in result.scored if s.tier == "A"][:3]
    for s in top:
        typer.echo(f"\n{s.signals.account.name} ({s.signals.account.domain}): Tier A, {s.score}")
        for reason in s.reasons:
            typer.echo(f"  - {reason}")
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
