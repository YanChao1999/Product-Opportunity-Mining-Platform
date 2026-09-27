"""Report writers: markdown table, CSV, JSON."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opportunity_miner.models import Opportunity, ScanResult


def _dim(o: Opportunity) -> dict[str, float]:
    d = o.dimensions
    return {
        "demand": d.demand,
        "competition": d.competition,
        "difficulty": d.difficulty,
        "monetization": d.monetization,
        "competition_gap": d.competition_gap,
        "feasibility": d.feasibility,
    }


def opportunities_to_rows(opportunities: list[Opportunity]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, o in enumerate(opportunities, start=1):
        d = _dim(o)
        rows.append(
            {
                "rank": i,
                "title": o.title,
                "category": o.category,
                "score": o.opportunity_score,
                "demand": d["demand"],
                "competition": d["competition"],
                "difficulty": d["difficulty"],
                "monetization": d["monetization"],
                "competition_gap": d["competition_gap"],
                "feasibility": d["feasibility"],
                "signals": o.signal_count,
                "sources": ",".join(s.value for s in o.sources),
                "keywords": ",".join(o.keywords[:8]),
                "summary": o.summary,
                "evidence_urls": " | ".join(
                    e.url for e in o.evidence[:5] if e.url
                ),
            }
        )
    return rows


def write_json(path: Path, result: ScanResult) -> None:
    payload = {
        "scanned_at": result.scanned_at.isoformat(),
        "raw_count": result.raw_count,
        "opportunity_count": result.opportunity_count,
        "source_stats": result.source_stats,
        "formula": (
            "opportunity_score = demand × competition_gap × feasibility × monetization "
            "(competition_gap=(11-competition)/10×10, feasibility=(11-difficulty)/10×10), "
            "scaled to 0–100"
        ),
        "opportunities": [
            {
                **{k: v for k, v in row.items()},
            }
            for row in opportunities_to_rows(result.opportunities)
        ],
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
    lines.append(
        "> Ranking formula: **需求强度 × 竞争缺口 × 可开发性 × 付费可能性**  "
        "(竞争缺口 / 可开发性 = 对「竞争程度 / 开发难度」取反后的 1–10 分)"
    )
    lines.append("")
    lines.append(
        "| Rank | Opportunity | Category | Score | 需求 | 竞争 | 难度 | 付费 | Signals | Sources |"
    )
    lines.append("| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in rows:
        title = row["title"].replace("|", "/")
        if len(title) > 80:
            title = title[:77] + "..."
        lines.append(
            f"| {row['rank']} | {title} | {row['category']} | {row['score']} | "
            f"{row['demand']} | {row['competition']} | {row['difficulty']} | "
            f"{row['monetization']} | {row['signals']} | `{row['sources']}` |"
        )
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


def write_reports(result: ScanResult, output_cfg: dict[str, Any]) -> dict[str, Path]:
    out_dir = Path(output_cfg.get("dir") or "data/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = result.scanned_at.strftime("%Y%m%d_%H%M%S")
    formats = output_cfg.get("formats") or ["markdown", "csv", "json"]
    top_n = int(output_cfg.get("top_n") or 50)
    trimmed = result.model_copy(
        update={"opportunities": result.opportunities[:top_n], "opportunity_count": min(result.opportunity_count, top_n)}
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
