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

## Local need classifier（小模型，不只字符串匹配）

`extraction.classifier` — 判断「是未满足需求 / 还是噪音」：

| Backend | 说明 |
|---------|------|
| **`ensemble`**（默认） | Logistic 特征模型 + **Naive Bayes n-gram** 本地训练模型加权 |
| **`naive_bayes`** | 纯 Python 多项式 NB，种子语料训练，权重存 `data/models/need_nb.json` |
| **`logistic`** | 手工特征 + 逻辑回归 |
| **`ollama`** | 本机小 LLM（如 `llama3.2:1b`），挂了会回退 ensemble |

```bash
opportunity-miner train-classifier
opportunity-miner classify "I wish there was an offline CRM for freelancers"
opportunity-miner classify "We're hiring a senior engineer" --backend naive_bayes
```

可与 regex **混合**（`blend_patterns: true`），但分类主路径是 ML 概率，不是 `if "wish" in text`。

### Category labels（本地 AI）

`extraction.category` — 给机会打品类标签（ai / gaming / devtools / …）：

| Backend | 说明 |
|---------|------|
| **`auto`**（默认） | Ollama 可用则用本地 LLM，否则 **Naive Bayes**，再否则 rules |
| **`ollama`** | 本机小模型 JSON 分类，失败回退 NB/rules |
| **`naive_bayes`** | 纯 Python 多类 NB（种子语料），无网络 |
| **`rules`** | 标题加权关键词（最快） |

```bash
# force local LLM categories (requires Ollama running)
CATEGORY_BACKEND=ollama opportunity-miner scan -v -j 8

# offline local ML only
CATEGORY_BACKEND=naive_bayes opportunity-miner scan
```

## Quick start (uv)

This project is managed with [uv](https://docs.astral.sh/uv/).

```bash
# Install uv: https://docs.astral.sh/uv/getting-started/installation/
curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync                          # create .venv + install deps from uv.lock
uv run opportunity-miner scan --demo
uv run opportunity-miner scan -v -j 8   # verbose timings + parallel collectors
uv run opportunity-miner scan
uv run opportunity-miner schedule --at 08:00
uv run opportunity-miner show-latest
uv run opportunity-miner train-classifier
uv run opportunity-miner classify "I wish there was an offline CRM"
```

Common uv commands:

```bash
uv add httpx                     # add runtime dep
uv add --group dev ruff          # add dev dep
uv lock                          # refresh uv.lock
uv run pytest -q                 # run tests
uv sync --frozen                 # CI-style install from lockfile
```

Reports → `data/reports/latest.{md,csv,json}`

### Secrets / env

| Variable | Purpose |
|----------|---------|
| `PRODUCT_HUNT_API_TOKEN` | Product Hunt GraphQL |
| `GITHUB_TOKEN` | 提高 GitHub Search 限额 |
| `CLASSIFIER_BACKEND` | `ensemble` / `naive_bayes` / `logistic` / `ollama` |
| `CATEGORY_BACKEND` | `auto` / `ollama` / `naive_bayes` / `rules` |
| `OLLAMA_HOST` / `OLLAMA_MODEL` | 本地 LLM（需求分类 + 品类分类共用） |

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
uv.lock
.github/workflows/daily-scan.yml
```

## Tests

```bash
uv run pytest -q
```

## License

MIT
