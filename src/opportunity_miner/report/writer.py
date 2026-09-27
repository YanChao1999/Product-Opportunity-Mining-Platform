"""Report writers: markdown table, CSV, JSON — dimension-aware."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from opportunity_miner.models import DEFAULT_DIMENSIONS, Opportunity, ScanResult
from opportunity_miner.scoring.engine import resolve_dimension_spec


def _spec_from_opps(opportunities: list[Opportunity]) -> list[dict[str, Any]]:
    if opportunities:
        return opportunities[0].dimensions.spec or list(DEFAULT_DIMENSIONS)
    return list(DEFAULT_DIMENSIONS)


def opportunities_to_rows(opportunities: list[Opportunity]) -> list[dict[str, Any]]:
    spec = _spec_from_opps(opportunities)
    rows: list[dict[str, Any]] = []
    for i, o in enumerate(opportunities, start=1):
        row: dict[str, Any] = {
            "rank": i,
            "title": o.title,
            "category": o.category,
            "score": o.opportunity_score,
            "need_confidence": o.need_confidence,
            "signals": o.signal_count,
            "sources": ",".join(s.value for s in o.sources),
            "keywords": ",".join(o.keywords[:8]),
            "summary": o.summary,
            "evidence_urls": " | ".join(e.url for e in o.evidence[:5] if e.url),
        }
        for dim in spec:
            row[dim["id"]] = o.dimensions.get(dim["id"])
            if dim.get("invert"):
                row[f"{dim['id']}_contrib"] = o.dimensions.contribution(dim)
        rows.append(row)
    return rows


def write_json(path: Path, result: ScanResult) -> None:
    spec = _spec_from_opps(result.opportunities)
    labels = [f"{d.get('label', d['id'])}{'↓' if d.get('invert') else ''}" for d in spec]
    payload = {
        "scanned_at": result.scanned_at.isoformat(),
        "raw_count": result.raw_count,
        "opportunity_count": result.opportunity_count,
        "source_stats": result.source_stats,
        "dimensions": spec,
        "formula": (
            "opportunity_score = geometric_mean(dimension_contributions) × 10, "
            "where inverted dims use (11-raw)/10×10; weights from config"
        ),
        "dimension_labels": labels,
        "opportunities": opportunities_to_rows(result.opportunities),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, opportunities: list[Opportunity]) -> None:
    rows = opportunities_to_rows(opportunities)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, result: ScanResult) -> None:
    rows = opportunities_to_rows(result.opportunities)
    spec = _spec_from_opps(result.opportunities)
    table_dims = [d for d in spec if d.get("table", True)]
    lines: list[str] = []
    lines.append("# Product Opportunity Report")
    lines.append("")
    lines.append(f"- Scanned at: `{result.scanned_at.isoformat()}`")
    lines.append(f"- Raw signals: **{result.raw_count}**")
    lines.append(f"- Opportunities: **{result.opportunity_count}**")
    lines.append(
        f"- Sources: "
        + ", ".join(f"{k}={v}" for k, v in sorted(result.source_stats.items()))
    )
    lines.append("")
    dim_desc = " × ".join(
        f"{d.get('label', d['id'])}{'↓' if d.get('invert') else ''}" for d in table_dims
    )
    lines.append(f"> Ranking: geometric mean of **{dim_desc}** (+ hidden dims in JSON).")
    lines.append("")
    header = ["Rank", "Opportunity", "Category", "Score"]
    header += [d.get("short") or d.get("label") or d["id"] for d in table_dims]
    header += ["Signals", "Sources"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---:" if h in {"Rank", "Score", "Signals"} or h in {d.get("short") for d in table_dims} else "---" for h in header) + " |")
    # Simpler align row
    aligns = []
    for h in header:
        if h in {"Opportunity", "Category", "Sources"}:
            aligns.append("---")
        else:
            aligns.append("---:")
    lines[-1] = "| " + " | ".join(aligns) + " |"

    for row in rows:
        title = row["title"].replace("|", "/")
        if len(title) > 70:
            title = title[:67] + "..."
        cells = [str(row["rank"]), title, row["category"], str(row["score"])]
        for d in table_dims:
            cells.append(str(row.get(d["id"], "")))
        cells.append(str(row["signals"]))
        cells.append(f"`{row['sources']}`")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## All dimensions")
    lines.append("")
    for d in spec:
        inv = " (inverted)" if d.get("invert") else ""
        lines.append(f"- `{d['id']}` — {d.get('label', d['id'])}{inv}, weight={d.get('weight', 1)}")
    lines.append("")
    lines.append("## Evidence detail")
    lines.append("")
    for o in result.opportunities[:20]:
        lines.append(f"### {o.title}")
        lines.append("")
        lines.append(o.summary)
        lines.append("")
        for e in o.evidence[:5]:
            lines.append(
                f"- [{e.source.value}] {e.title[:100] or '(no title)'} "
                f"(score={e.score}, comments={e.comments}) — {e.url or 'n/a'}"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_reports(result: ScanResult, output_cfg: dict[str, Any], scoring_cfg: dict[str, Any] | None = None) -> dict[str, Path]:
    out_dir = Path(output_cfg.get("dir") or "data/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = result.scanned_at.strftime("%Y%m%d_%H%M%S")
    formats = output_cfg.get("formats") or ["markdown", "csv", "json"]
    top_n = int(output_cfg.get("top_n") or 50)
    # Ensure opportunities carry dimension spec from config if empty
    if scoring_cfg and result.opportunities:
        spec = resolve_dimension_spec(scoring_cfg)
        for o in result.opportunities:
            if not o.dimensions.spec:
                o.dimensions.spec = spec
    trimmed = result.model_copy(
        update={
            "opportunities": result.opportunities[:top_n],
            "opportunity_count": min(result.opportunity_count, top_n),
        }
    )
    written: dict[str, Path] = {}
    if "json" in formats:
        p = out_dir / f"opportunities_{stamp}.json"
        write_json(p, trimmed)
        written["json"] = p
        latest = out_dir / "latest.json"
        latest.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        written["json_latest"] = latest
    if "csv" in formats:
        p = out_dir / f"opportunities_{stamp}.csv"
        write_csv(p, trimmed.opportunities)
        written["csv"] = p
        latest = out_dir / "latest.csv"
        latest.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        written["csv_latest"] = latest
    if "markdown" in formats:
        p = out_dir / f"opportunities_{stamp}.md"
        write_markdown(p, trimmed)
        written["markdown"] = p
        latest = out_dir / "latest.md"
        latest.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        written["markdown_latest"] = latest
    return written
