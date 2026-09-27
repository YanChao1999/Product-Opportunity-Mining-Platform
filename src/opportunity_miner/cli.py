"""CLI entrypoint."""

from __future__ import annotations

import json
import time
from pathlib import Path

import click
import schedule
from rich.console import Console
from rich.table import Table

from opportunity_miner.config import load_config
from opportunity_miner.pipeline.scan import run_scan

console = Console()


def _print_table(result) -> None:
    table = Table(title="Product Opportunities (需求×竞争缺口×可开发性×付费)")
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Opportunity", style="bold")
    table.add_column("Cat")
    table.add_column("Score", justify="right", style="green")
    table.add_column("需求", justify="right")
    table.add_column("竞争", justify="right")
    table.add_column("难度", justify="right")
    table.add_column("付费", justify="right")
    table.add_column("Src")

    for i, o in enumerate(result.opportunities[:30], start=1):
        d = o.dimensions
        title = o.title if len(o.title) <= 56 else o.title[:53] + "..."
        table.add_row(
            str(i),
            title,
            o.category,
            f"{o.opportunity_score:.1f}",
            f"{d.demand:.1f}",
            f"{d.competition:.1f}",
            f"{d.difficulty:.1f}",
            f"{d.monetization:.1f}",
            ",".join(s.value[:2] for s in o.sources),
        )
    console.print(table)


@click.group()
@click.version_option(package_name="opportunity-miner")
def main() -> None:
    """Daily product-opportunity miner across Reddit / Steam / App Store / PH / HN."""


@main.command("scan")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--demo", is_flag=True, help="Use offline demo fixtures (no network).")
@click.option("--json-out", is_flag=True, help="Print machine-readable JSON summary.")
def scan_cmd(config_path: str | None, demo: bool, json_out: bool) -> None:
    """Run one scan cycle and write ranked reports."""
    config = load_config(config_path)
    with console.status("Scanning sources & ranking opportunities..."):
        result, paths = run_scan(config, demo=demo)
    if json_out:
        click.echo(
            json.dumps(
                {
                    "scanned_at": result.scanned_at.isoformat(),
                    "raw_count": result.raw_count,
                    "opportunity_count": result.opportunity_count,
                    "source_stats": result.source_stats,
                    "reports": {k: str(v) for k, v in paths.items()},
                    "top": [
                        {
                            "rank": i,
                            "title": o.title,
                            "score": o.opportunity_score,
                            "demand": o.dimensions.demand,
                            "competition": o.dimensions.competition,
                            "difficulty": o.dimensions.difficulty,
                            "monetization": o.dimensions.monetization,
                        }
                        for i, o in enumerate(result.opportunities[:20], start=1)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        console.print(
            f"[bold]Done.[/bold] raw={result.raw_count} opportunities={result.opportunity_count} "
            f"sources={result.source_stats}"
        )
        _print_table(result)
        for kind, path in paths.items():
            console.print(f"  • {kind}: {path}")


@main.command("schedule")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
@click.option("--at", "at_time", default=None, help="HH:MM local time (default from config).")
@click.option("--demo", is_flag=True)
def schedule_cmd(config_path: str | None, at_time: str | None, demo: bool) -> None:
    """Run forever, scanning once per day."""
    config = load_config(config_path)
    when = at_time or ((config.get("schedule") or {}).get("daily_at") or "08:00")

    def job() -> None:
        console.print(f"[cyan]Scheduled scan starting…[/cyan]")
        result, paths = run_scan(config, demo=demo)
        console.print(
            f"raw={result.raw_count} opportunities={result.opportunity_count} → {paths.get('markdown_latest')}"
        )

    schedule.every().day.at(when).do(job)
    console.print(f"Scheduler armed for daily {when}. Ctrl+C to stop. Running first scan now.")
    job()
    while True:
        schedule.run_pending()
        time.sleep(30)


@main.command("show-latest")
@click.option("--config", "config_path", type=click.Path(exists=True), default=None)
def show_latest(config_path: str | None) -> None:
    """Print the latest markdown report if present."""
    config = load_config(config_path)
    latest = Path((config.get("output") or {}).get("dir") or "data/reports") / "latest.md"
    if not latest.exists():
        raise click.ClickException(f"No report at {latest}. Run `opportunity-miner scan` first.")
    console.print(latest.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
