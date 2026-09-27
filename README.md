# Product Opportunity Mining Platform

每天自动扫描 **Reddit · Steam · App Store · Product Hunt · Hacker News**，抓取「人们想要但市场上没有 / 供给不足」的需求信号，并按：

**需求强度 × 竞争缺口 × 可开发性 × 付费可能性**

排成可落地的机会表（Markdown / CSV / JSON）。

> 公式说明：竞争程度、开发难度越高对创业越不利，因此排行使用其**取反分**  
> `竞争缺口 = (11 − 竞争) / 10 × 10`，`可开发性 = (11 − 难度) / 10 × 10`，再与需求、付费相乘后归一到 0–100。

---

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Offline demo (no API keys / network required)
opportunity-miner scan --demo

# Live scan (HN / Reddit public JSON / iTunes / Steam; PH needs token)
opportunity-miner scan

# Print latest report
opportunity-miner show-latest

# Local daily daemon
opportunity-miner schedule --at 08:00
```

Reports land in `data/reports/` (`latest.md`, `latest.csv`, `latest.json`).

### Optional secrets

Copy `.env.example` → `.env` (or set GitHub Actions secrets):

| Variable | Purpose |
|----------|---------|
| `PRODUCT_HUNT_API_TOKEN` | Product Hunt GraphQL (fallback curated posts if missing) |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Reserved for OAuth rate limits (public JSON works today) |

---

## Ranking table columns

| Column | Meaning |
|--------|---------|
| Score | Composite opportunity score (0–100) |
| 需求 | Demand intensity from engagement + wish-language strength + multi-source corroboration |
| 竞争 | How crowded the space looks (store listings, “alternative to X” language) |
| 难度 | Build difficulty heuristics (AI/infra/compliance ↑, extension/template ↓) |
| 付费 | Monetization signals (“would pay”, B2B/SaaS, category priors) |
| Signals / Sources | Evidence count and which platforms contributed |

---

## Architecture

```
src/opportunity_miner/
  sources/     # HN, Reddit, Steam, App Store, Product Hunt collectors
  extract/     # unmet-need regex + clustering
  scoring/     # 4-dimension scorer + ranker
  report/      # markdown table / csv / json writers
  pipeline/    # orchestration + demo fixtures
  cli.py       # `scan` / `schedule` / `show-latest`
config/default.yaml
.github/workflows/daily-scan.yml   # cron 00:00 UTC
```

### Unmet-need detection

Signals match patterns such as *I wish there was*, *looking for an app*, *no good alternative*, *somebody make*, *would pay for*, *找不到/有没有/希望有*… plus Ask HN / low-star App Store reviews.

### Daily automation

- **GitHub Actions**: `.github/workflows/daily-scan.yml` runs every day, uploads artifacts, and commits `data/reports/latest.*` on `main`.
- **Local**: `opportunity-miner schedule --at 08:00`.

---

## Configure

Edit `config/default.yaml` to toggle sources, subreddits, App Store search terms, Steam app IDs, pattern lists, and scoring weights.

---

## Tests

```bash
pytest -q
```

---

## License

MIT
