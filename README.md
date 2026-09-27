# Product Opportunity Mining Platform

每天自动扫描多个社区与商店，抓取「人们想要但市场上没有 / 供给不足」的需求，按**可扩展多维评分**排成表。

## Sources（可扩展）

| Source | 说明 |
|--------|------|
| Hacker News | Ask/New/Top |
| Reddit | 创业/产品相关 subreddit |
| Steam | 商店搜索 + 新闻 + wish seeds |
| App Store | iTunes 搜索 + 低星评价 |
| Product Hunt | GraphQL（无 token 时用 fallback） |
| **GitHub** | Issues 搜索 wish / feature-request |
| **Lobsters** | hottest / ask JSON |
| **V2EX** | 中文热点 / 最新 |
| **Stack Exchange** | feature-request / recommendation |
| **Indie Hackers** | RSS + fallback |
| **Google Play** | wish seeds（可接自定义 search URL） |
| **Chrome Web Store** | extension wish seeds |
| **G2** | B2B 替代品 / 缺口 seeds |
| **RSS** | 任意订阅源（配置 `sources.rss.feeds`） |

在 `config/default.yaml` 里对任意源设 `enabled: true/false`，或增加自己的 RSS。

## Scoring dimensions（可扩展）

默认 **11 维**（不止原来的 4 维），最终分为各维贡献值的**几何平均**（0–100）：

| ID | 含义 | 取反？ |
|----|------|--------|
| demand | 需求强度 | |
| competition | 竞争程度 | ✓ |
| difficulty | 开发难度 | ✓ |
| monetization | 付费可能性 | |
| urgency | 紧迫性 | |
| market_size | 市场规模 | |
| time_to_revenue | 变现速度 | |
| trend | 趋势热度 | |
| defensibility | 护城河 | |
| viral | 传播潜力 | |
| regulatory_risk | 监管风险 | ✓ |

在 `scoring.dimensions` 增删改权重即可；未知 `id` 会落在默认分 5。

## Local need classifier（不只是字符串匹配）

`extraction.classifier`：

- **`logistic`**（默认）：本地轻量逻辑回归，特征 = 短语/词袋/互动/是否 listing 等
- **`ollama`**：可选调用本机 Ollama（`OLLAMA_HOST` / `OLLAMA_MODEL`）做 need vs noise 分类

与 regex 模式**混合**（`blend_patterns: true`）。

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

opportunity-miner scan --demo
opportunity-miner scan
opportunity-miner schedule --at 08:00
opportunity-miner show-latest
```

Reports → `data/reports/latest.{md,csv,json}`

### Secrets / env

| Variable | Purpose |
|----------|---------|
| `PRODUCT_HUNT_API_TOKEN` | Product Hunt GraphQL |
| `GITHUB_TOKEN` | 提高 GitHub Search 限额 |
| `CLASSIFIER_BACKEND` | `logistic` / `ollama` |
| `OLLAMA_HOST` / `OLLAMA_MODEL` | 本地 LLM 分类 |

## Architecture

```
src/opportunity_miner/
  sources/       # 14 collectors
  extract/       # patterns + local classifier + clustering
  scoring/       # pluggable multi-dimension engine
  report/        # markdown / csv / json
  pipeline/      # orchestration
  cli.py
config/default.yaml
.github/workflows/daily-scan.yml
```

## Tests

```bash
pytest -q
```

## License

MIT
