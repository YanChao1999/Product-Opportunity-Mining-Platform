"""
Product-category classifier for ranked opportunities.

Backends:
  - rules       : title-weighted token/phrase rules (fast, no deps)
  - naive_bayes : multinomial NB over n-grams trained on seed labels (local ML)
  - ollama      : local LLM via Ollama HTTP API
  - auto        : ollama if a model is installed, else naive_bayes/rules
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import httpx

from opportunity_miner.sources.http import normalize_proxy_env

CATEGORIES: tuple[str, ...] = (
    "ai",
    "gaming",
    "devtools",
    "productivity",
    "fintech",
    "health",
    "mobile",
    "general",
)

# (category, example text) — enough to bias NB without a large corpus
SEED_LABELED: list[tuple[str, str]] = [
    ("ai", "Ask HN: Allow agents access to cloud files with least privilege"),
    ("ai", "I wish there was a local LLM gateway for Claude and GPT tool calls"),
    ("ai", "Looking for an alternative to ChatGPT that works fully offline"),
    ("ai", "Somebody make a SaaS for prompt versioning across teams. Would pay."),
    ("ai", "Show HN: self-hosted approval gateway for AI agent tool calls"),
    ("gaming", "I wish there was a universal cross-play party finder across Steam"),
    ("gaming", "Somebody make a Steam Workshop conflict detector before launch"),
    ("gaming", "Igalia Improving the Firefox Experience for Valve's Steam Deck"),
    ("gaming", "Feature Request: Game-Based Tag Organization for my library"),
    ("gaming", "Looking for a mod manager that detects incompatible mods"),
    ("devtools", "Looking for a GitHub-compatible self-hosted Git forge for small teams"),
    ("devtools", "I wish there was a CI deploy API for indie SaaS developers"),
    ("devtools", "Is there a tool that scores open-source dependency risk daily?"),
    ("devtools", "Need an alternative to Jenkins that is simpler for solo founders"),
    ("devtools", "Feature request: better Kubernetes deploy previews for PRs"),
    ("productivity", "Looking for an offline habit tracker without accounts"),
    ("productivity", "I wish there was a Notion alternative that works fully offline"),
    ("productivity", "Somebody make a local-first task manager with calendar sync"),
    ("productivity", "Ask HN: What task manager do you use? What do you miss?"),
    ("productivity", "Need a note-taking app with end-to-end encryption"),
    ("fintech", "Somebody make a family shared budget app that stays private"),
    ("fintech", "Looking for an alternative to QuickBooks for freelancers"),
    ("fintech", "I wish there was a crypto tax tool that handles DeFi properly"),
    ("fintech", "Would pay for invoice automation with bank reconciliation"),
    ("health", "Looking for a calorie tracker that works offline on iOS"),
    ("health", "I wish there was a sleep coach without uploading data"),
    ("health", "Somebody make a meditation app that syncs with Apple Health"),
    ("mobile", "I wish there was a Chrome extension that batches App Store reviews"),
    ("mobile", "Looking for an Android alternative to this iOS habit app"),
    ("mobile", "Ask HN: React Native or Flutter when the backend is Node?"),
    ("general", "Ask HN: How do you get your first users for an MVP?"),
    ("general", "What blog posts influenced your thinking the most?"),
    ("general", "US sanctions force Netherlands off Microsoft toward alternatives"),
    ("general", "Ask HN: Who's still keeping a DOS machine up for business?"),
    ("general", "How I use a single .zshrc file on macOS and Windows"),
    ("general", "Adding Floating-Point Decimals for Fun and Profit"),
    ("devtools", "My experience writing automated tests for a SPA"),
    ("devtools", "EC2 Autodiscovery rules for new machines"),
]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", (text or "").lower())


def _ngrams(tokens: list[str], n: int = 2) -> list[str]:
    grams = list(tokens)
    for i in range(len(tokens) - n + 1):
        grams.append("_".join(tokens[i : i + n]))
    return grams


def classify_category_rules(keywords: list[str], texts: str, title: str = "") -> str:
    """Title-weighted whole-token rules. Safe default when ML/LLM unavailable."""
    title_tokens = set(_tokenize(title)) if title else set()
    body_tokens = set(_tokenize(texts))
    kw_tokens = {t.lower() for t in keywords}
    title_blob = (title or "").lower()
    body_blob = (texts or "").lower()

    rules: list[tuple[str, set[str], tuple[str, ...]]] = [
        (
            "ai",
            {
                "ai", "llm", "llms", "gpt", "agent", "agents", "chatgpt", "claude",
                "openai", "prompt", "prompts", "embedding", "embeddings",
            },
            ("large language", "language model", "machine learning", "multi-model", "multi agent"),
        ),
        (
            "gaming",
            {
                "game", "games", "gaming", "steam", "mod", "mods", "fps", "multiplayer",
                "steamdeck", "esports", "xbox", "playstation",
            },
            ("steam deck", "video game", "game engine"),
        ),
        (
            "devtools",
            {
                "api", "apis", "sdk", "cli", "ci", "cd", "deploy", "deployment", "github",
                "gitlab", "developer", "developers", "devtools", "saas", "devops",
                "kubernetes", "docker", "rust", "testing", "spa",
            },
            ("developer tool", "open source", "unit test", "autodiscovery"),
        ),
        (
            "productivity",
            {
                "todo", "todos", "note", "notes", "habit", "habits", "calendar", "task",
                "tasks", "focus", "notion", "obsidian", "workflow",
            },
            ("to-do", "note taking", "task manager"),
        ),
        (
            "fintech",
            {
                "budget", "finance", "financial", "bank", "banking", "invoice", "payment",
                "payments", "crypto", "bitcoin", "fintech",
            },
            ("personal finance", "expense tracker"),
        ),
        (
            "health",
            {
                "fitness", "calorie", "calories", "meditation", "sleep", "health",
                "healthcare", "diet", "workout", "cancer", "medical",
            },
            ("mental health", "weight loss", "apple health"),
        ),
        (
            "mobile",
            {"ios", "android", "iphone", "ipad", "apk", "oneplus"},
            ("app store", "play store", "mobile app"),
        ),
    ]
    best_name = "general"
    best_score = 0.0
    for name, keys, phrases in rules:
        title_score = 3.0 * len(title_tokens & keys)
        title_score += 2.0 * len(kw_tokens & keys)
        title_score += 3.0 * sum(1 for p in phrases if p in title_blob)
        body_score = 0.5 * len((body_tokens - title_tokens) & keys)
        body_score += 0.5 * sum(1 for p in phrases if p in body_blob and p not in title_blob)
        if title_score > 0:
            score = title_score + body_score
        elif body_score >= 2.0:
            score = body_score
        else:
            score = 0.0
        if score > best_score:
            best_score = score
            best_name = name
    return best_name if best_score > 0 else "general"


@dataclass
class CategoryNB:
    classes: list[str] = field(default_factory=list)
    vocab: dict[str, int] = field(default_factory=dict)
    class_log_prior: dict[str, float] = field(default_factory=dict)
    feature_log_prob: dict[str, dict[str, float]] = field(default_factory=dict)

    def predict(self, text: str) -> tuple[str, float]:
        tokens = _ngrams(_tokenize(text)[:80])
        # Only score known vocab — UNK previously favored small classes (health).
        known = [t for t in tokens if t in self.vocab]
        if len(known) < 2 or not self.classes:
            return "general", 0.0
        scores: dict[str, float] = {}
        for cls in self.classes:
            s = self.class_log_prior.get(cls, -10.0)
            feats = self.feature_log_prob.get(cls) or {}
            for t in known:
                s += feats.get(t, -10.0)
            scores[cls] = s
        m = max(scores.values())
        exps = {c: math.exp(v - m) for c, v in scores.items()}
        z = sum(exps.values()) or 1.0
        best = max(exps, key=exps.get)
        conf = float(exps[best] / z)
        coverage = len(known) / max(len(tokens), 1)
        conf *= 0.35 + 0.65 * coverage
        return best, conf


_NB_CACHE: CategoryNB | None = None


def train_category_nb(examples: list[tuple[str, str]] | None = None) -> CategoryNB:
    examples = examples or SEED_LABELED
    docs: dict[str, list[list[str]]] = defaultdict(list)
    vocab_counter: Counter[str] = Counter()
    for cls, text in examples:
        if cls not in CATEGORIES:
            continue
        toks = _ngrams(_tokenize(text)[:80])
        docs[cls].append(toks)
        vocab_counter.update(toks)

    vocab = {t: i for i, (t, _) in enumerate(vocab_counter.most_common(4000))}
    classes = [c for c in CATEGORIES if docs.get(c)]
    total_docs = sum(len(v) for v in docs.values()) or 1
    class_log_prior = {c: math.log(len(docs[c]) / total_docs) for c in classes}

    feature_log_prob: dict[str, dict[str, float]] = {}
    alpha = 0.5
    vsize = max(len(vocab), 1)
    for cls in classes:
        counts: Counter[str] = Counter()
        for toks in docs[cls]:
            for t in toks:
                if t in vocab:
                    counts[t] += 1
        total = sum(counts.values()) + alpha * vsize
        feature_log_prob[cls] = {
            t: math.log((counts.get(t, 0) + alpha) / total) for t in vocab
        }

    return CategoryNB(
        classes=classes,
        vocab=vocab,
        class_log_prior=class_log_prior,
        feature_log_prob=feature_log_prob,
    )


def get_category_nb() -> CategoryNB:
    global _NB_CACHE
    if _NB_CACHE is None:
        _NB_CACHE = train_category_nb()
    return _NB_CACHE


def classify_category_nb(title: str, texts: str, keywords: list[str] | None = None) -> tuple[str, float]:
    blob = f"{title}\n{' '.join(keywords or [])}\n{texts}"[:3000]
    return get_category_nb().predict(blob)


_OLLAMA_OK: bool | None = None
_OLLAMA_MODELS: list[str] | None = None
_OLLAMA_WARNED = False


def reset_ollama_cache() -> None:
    global _OLLAMA_OK, _OLLAMA_MODELS, _OLLAMA_WARNED, _NB_CACHE
    _OLLAMA_OK = None
    _OLLAMA_MODELS = None
    _OLLAMA_WARNED = False
    _NB_CACHE = None


def list_ollama_models(host: str, timeout: float = 2.0) -> list[str]:
    global _OLLAMA_MODELS, _OLLAMA_OK
    if _OLLAMA_MODELS is not None:
        return _OLLAMA_MODELS
    try:
        normalize_proxy_env()
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{host.rstrip('/')}/api/tags")
            if resp.status_code != 200:
                _OLLAMA_OK = False
                _OLLAMA_MODELS = []
                return []
            names = [m.get("name") or "" for m in (resp.json().get("models") or [])]
            _OLLAMA_MODELS = [n for n in names if n]
            _OLLAMA_OK = True
            return _OLLAMA_MODELS
    except Exception:
        _OLLAMA_OK = False
        _OLLAMA_MODELS = []
        return []


def ollama_available(host: str, timeout: float = 0.8) -> bool:
    global _OLLAMA_OK
    if _OLLAMA_OK is not None:
        return _OLLAMA_OK
    return bool(list_ollama_models(host, timeout=timeout))


def resolve_ollama_model(host: str, preferred: str) -> str | None:
    models = list_ollama_models(host)
    if not models:
        return None
    if preferred in models:
        return preferred
    stem = preferred.split(":")[0]
    for m in models:
        if m.startswith(stem):
            return m
    return models[0]


def classify_category_ollama(
    title: str,
    texts: str,
    *,
    host: str,
    model: str,
    timeout: float = 20.0,
) -> tuple[str, float] | None:
    resolved = resolve_ollama_model(host, model)
    if not resolved:
        return None
    allowed = ", ".join(CATEGORIES)
    prompt = (
        "You label product opportunities for a startup idea scanner.\n"
        f"Choose EXACTLY one category from: [{allowed}]\n"
        "Rules:\n"
        "- ai = LLM/agents/prompts/ChatGPT/Claude\n"
        "- gaming = games/Steam/mods/consoles\n"
        "- devtools = APIs/CI/Git/infra/developer tools/programming\n"
        "- productivity = notes/tasks/habits/calendar\n"
        "- fintech = money/banking/payments/crypto\n"
        "- health = fitness/medical/sleep/diet\n"
        "- mobile = iOS/Android/app stores\n"
        "- general = none of the above (blog posts, news, shell tips, etc.)\n"
        'Reply ONLY JSON: {"category":"<one>", "confidence":0.0-1.0}\n\n'
        f"TITLE: {title[:200]}\n"
        f"TEXT: {(texts or '')[:900]}\n"
    )
    try:
        normalize_proxy_env()
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{host.rstrip('/')}/api/generate",
                json={"model": resolved, "prompt": prompt, "stream": False, "format": "json"},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            raw = resp.json().get("response") or "{}"
            data = json.loads(raw)
            cat = str(data.get("category") or "general").strip().lower()
            if cat not in CATEGORIES:
                cat = next((c for c in CATEGORIES if c in cat), "general")
            conf = float(data.get("confidence", 0.6))
            return cat, max(0.0, min(1.0, conf))
    except Exception:
        return None


def _warn_ollama(host: str, model: str) -> None:
    global _OLLAMA_WARNED
    if _OLLAMA_WARNED:
        return
    _OLLAMA_WARNED = True
    models = list_ollama_models(host)
    if models:
        msg = f"Ollama up but '{model}' missing; installed={models[:5]}. Using rules."
    else:
        msg = (
            f"Ollama has no models at {host}. "
            f"Run: `ollama pull {model}` then re-scan. Using rules for now."
        )
    try:
        from rich.console import Console

        Console(stderr=True).print(f"[yellow]category:[/yellow] {msg}")
    except Exception:
        print(f"category: {msg}", flush=True)


@dataclass
class CategoryResult:
    category: str
    confidence: float
    backend: str


class CategoryClassifier:
    """Local category classifier — rules / NB / Ollama / auto."""

    def __init__(self, cfg: dict[str, Any] | None = None):
        cfg = cfg or {}
        self.backend = (cfg.get("backend") or "auto").lower()
        self.ollama_host = cfg.get("ollama_host") or "http://127.0.0.1:11434"
        self.ollama_model = cfg.get("ollama_model") or "llama3.2:1b"
        self.min_nb_confidence = float(cfg.get("min_nb_confidence") or 0.45)
        self.min_ollama_confidence = float(cfg.get("min_ollama_confidence") or 0.4)

    def classify(
        self,
        title: str,
        texts: str = "",
        keywords: list[str] | None = None,
    ) -> CategoryResult:
        keywords = keywords or []
        rules_cat = classify_category_rules(keywords, texts, title=title)
        backend = self.backend

        def _nb_or_rules() -> CategoryResult:
            cat, conf = classify_category_nb(title, texts, keywords)
            if conf >= self.min_nb_confidence and cat != "general":
                return CategoryResult(cat, conf, "naive_bayes")
            if rules_cat != "general":
                return CategoryResult(rules_cat, max(conf, 0.5), "rules")
            if conf >= self.min_nb_confidence:
                return CategoryResult(cat, conf, "naive_bayes")
            return CategoryResult(rules_cat, conf, "rules")

        if backend == "rules":
            return CategoryResult(rules_cat, 1.0 if rules_cat != "general" else 0.4, "rules")

        if backend in {"naive_bayes", "nb"}:
            return _nb_or_rules()

        if backend == "ollama":
            resolved = resolve_ollama_model(self.ollama_host, self.ollama_model)
            if not resolved:
                _warn_ollama(self.ollama_host, self.ollama_model)
                return CategoryResult(rules_cat, 0.5, "rules(ollama_unavailable)")
            hit = classify_category_ollama(
                title, texts, host=self.ollama_host, model=resolved, timeout=20.0
            )
            if hit and hit[1] >= self.min_ollama_confidence:
                return CategoryResult(hit[0], hit[1], f"ollama:{resolved}")
            return CategoryResult(rules_cat, 0.45, "rules(ollama_weak)")

        # auto
        resolved = resolve_ollama_model(self.ollama_host, self.ollama_model)
        if resolved:
            hit = classify_category_ollama(
                title, texts, host=self.ollama_host, model=resolved, timeout=20.0
            )
            if hit and hit[1] >= self.min_ollama_confidence:
                return CategoryResult(hit[0], hit[1], f"ollama:{resolved}")
        return _nb_or_rules()
