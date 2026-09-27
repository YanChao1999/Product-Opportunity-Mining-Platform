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
    if not result.opportunities:
        console.print("[yellow]No opportunities found.[/yellow]")
        return
    spec = [d for d in result.opportunities[0].dimensions.spec if d.get("table", True)]
    title = "Product Opportunities — multi-dimension rank"
    table = Table(title=title)
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Opportunity", style="bold")
    table.add_column("Cat")
    table.add_column("Score", justify="right", style="green")
    for d in spec[:7]:  # keep terminal readable
        table.add_column(d.get("short") or d["id"], justify="right")
    table.add_column("Src")

    for i, o in enumerate(result.opportunities[:30], start=1):
        t = o.title if len(o.title) <= 48 else o.title[:45] + "..."
        cells = [
            str(i),
            t,
            o.category,
            f"{o.opportunity_score:.1f}",
        ]
        for d in spec[:7]:
            cells.append(f"{o.dimensions.get(d['id']):.1f}")
        cells.append(",".join(s.value[:2] for s in o.sources))
        table.add_row(*cells)
    console.print(table)


@click.group()
@click.version_option(package_name="opportunity-miner")
def main() -> None:
    """Multi-source product-opportunity miner with extensible scoring dimensions."""


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
        top = []
        for i, o in enumerate(result.opportunities[:20], start=1):
            item = {
                "rank": i,
                "title": o.title,
                "score": o.opportunity_score,
                "need_confidence": o.need_confidence,
                "sources": [s.value for s in o.sources],
                "dimensions": o.dimensions.raw,
            }
            top.append(item)
        click.echo(
            json.dumps(
                {
                    "scanned_at": result.scanned_at.isoformat(),
                    "raw_count": result.raw_count,
                    "opportunity_count": result.opportunity_count,
                    "source_stats": result.source_stats,
                    "reports": {k: str(v) for k, v in paths.items()},
                    "top": top,
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
        console.print("[cyan]Scheduled scan starting…[/cyan]")
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
