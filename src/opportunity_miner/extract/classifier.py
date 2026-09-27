"""
Local need-vs-noise classifier — small on-device ML, not string matching alone.

Backends:
  - logistic      : hand-crafted features + logistic regression (default, zero deps)
  - naive_bayes   : multinomial NB over character/word n-grams, trained on seed corpus
  - ensemble      : average of logistic + naive_bayes
  - ollama        : optional local LLM (e.g. llama3.2:1b via Ollama HTTP API)

"JAV" / tiny local models → use `naive_bayes` or `ensemble` (pure Python),
or point `ollama` at any local GGUF model.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import httpx

from opportunity_miner.models import RawSignal

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_PATH = ROOT / "data" / "models" / "need_nb.json"

# ---------------------------------------------------------------------------
# Labeled seed corpus for training the local NB model
# ---------------------------------------------------------------------------
SEED_POSITIVES: list[str] = [
    "I wish there was a tool that mines App Store 1-star reviews for feature gaps",
    "Looking for an alternative to Notion that works fully offline",
    "Somebody make a SaaS for Steam refund-risk analytics. Would pay.",
    "Why isn't there a cross-platform mod conflict detector?",
    "No good alternative for indie hackers to score demand vs competition",
    "Still can't find a privacy-first family budget app. Gap in the market.",
    "Feature request: local-first CRM for freelancers. Urgently blocking us.",
    "Is there a tool that batches LinkedIn outreach without getting banned?",
    "Please add HealthKit sync. Looking for an alternative that actually syncs.",
    "有没有不上传数据的本地密码管理应用？希望有，愿意付费。",
    "找不到靠谱的离线习惯打卡工具，谁来做？",
    "求推荐类似的软件但是没有广告的，现在市面上找不到",
    "Shut up and take my money — need an app for pre-build idea diligence",
    "Missing feature: detect incompatible mods before launch on Steam Deck",
    "Would pay $49/mo for automated opportunity scanning across Reddit and HN",
]

SEED_NEGATIVES: list[str] = [
    "We're hiring a senior engineer for our growth team",
    "Changelog: version 2.1 released with bug fixes",
    "Love this app! Five stars, works great every day",
    "Our company is proud to announce the Series A",
    "Promo code SAVE20 for newsletter signup this week",
    "Launch day giveaway — retweet to win a hoodie",
    "As expected the quarterly results beat estimates",
    "Personal finance budget app. Genre=Finance.",
    "Claude by Anthropic — AI assistant for everyone",
    "Release notes for Microsoft To Do April update",
    "Sponsored post: best CRM software of 2026",
    "Congratulations to the team on shipping v3",
    "Job opening: product manager, remote OK",
    "Stock price rose after the earnings call",
    "这款应用很好用，五星好评，推荐给大家",
]

POS_PHRASES = [
    "i wish", "looking for", "somebody make", "no good alternative", "would pay",
    "gap in the market", "still can't find", "feature request", "missing feature",
    "is there a tool", "is there an app", "why isn't there", "shut up and take my money",
    "找不到", "有没有", "希望有", "谁来做", "求推荐",
]
NEG_PHRASES = [
    "hiring", "we're thrilled", "launch day", "changelog", "release notes",
    "as expected", "works great", "love this app", "five stars", "promo code",
    "giveaway", "newsletter signup", "our company is proud", "sponsored",
]


@dataclass
class Classification:
    is_need: bool
    confidence: float
    backend: str
    features: dict[str, float] = field(default_factory=dict)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", (text or "").lower())


def _ngrams(tokens: list[str], n: int = 2) -> list[str]:
    grams = list(tokens)
    for i in range(len(tokens) - n + 1):
        grams.append("_".join(tokens[i : i + n]))
    return grams


# ---------------------------------------------------------------------------
# Logistic (feature) backend
# ---------------------------------------------------------------------------

def extract_features(text: str, score: int = 0, comments: int = 0, kind: str = "") -> dict[str, float]:
    low = (text or "").lower()
    toks = _tokenize(low)
    return {
        "bias": 1.0,
        "len_log": math.log1p(len(low)),
        "eng_log": math.log1p(max(0, score) + 2 * max(0, comments)),
        "pos_phrase": float(sum(1 for p in POS_PHRASES if p in low)),
        "neg_phrase": float(sum(1 for p in NEG_PHRASES if p in low)),
        "pos_tok": float(sum(1 for t in toks if t in {
            "wish", "alternative", "missing", "pay", "saas", "tool", "gap", "need",
            "request", "build", "make", "找不到", "希望", "付费", "替代",
        })),
        "neg_tok": float(sum(1 for t in toks if any(
            t.startswith(n) for n in ("hiring", "sponsored", "giveaway", "congratulat", "launched", "announcing")
        ))),
        "question": 1.0 if ("?" in low or low.startswith("ask ") or "有没有" in low) else 0.0,
        "review_low": 1.0 if kind == "review" and score <= 2 else 0.0,
        "listing": 1.0 if kind in {"app_listing", "store_result", "news"} else 0.0,
    }


WEIGHTS: dict[str, float] = {
    "bias": -1.8,
    "len_log": 0.05,
    "eng_log": 0.12,
    "pos_phrase": 1.35,
    "neg_phrase": -1.6,
    "pos_tok": 0.35,
    "neg_tok": -0.55,
    "question": 0.55,
    "review_low": 0.9,
    "listing": -2.5,
}


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def classify_logistic(signal: RawSignal) -> Classification:
    kind = (signal.metadata or {}).get("kind") or ""
    feat = extract_features(signal.text, signal.score, signal.comments, kind)
    logit = sum(WEIGHTS.get(k, 0.0) * v for k, v in feat.items())
    prob = _sigmoid(logit)
    return Classification(is_need=prob >= 0.5, confidence=round(prob, 4), backend="logistic", features=feat)


# ---------------------------------------------------------------------------
# Multinomial Naive Bayes (trained local model)
# ---------------------------------------------------------------------------

@dataclass
class NaiveBayesModel:
    log_prior_need: float
    log_prior_noise: float
    log_prob_need: dict[str, float]
    log_prob_noise: dict[str, float]
    vocab: list[str]
    alpha: float = 1.0

    def predict_proba(self, text: str) -> float:
        toks = _ngrams(_tokenize(text))
        if not toks:
            return 0.5
        need = self.log_prior_need
        noise = self.log_prior_noise
        # Unknown tokens use smoothed uniform over vocab
        default_need = math.log(self.alpha / (self.alpha * max(1, len(self.vocab))))
        default_noise = default_need
        for t in toks:
            need += self.log_prob_need.get(t, default_need)
            noise += self.log_prob_noise.get(t, default_noise)
        # log-sum-exp → P(need|text)
        m = max(need, noise)
        p_need = math.exp(need - m)
        p_noise = math.exp(noise - m)
        return p_need / (p_need + p_noise)

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_prior_need": self.log_prior_need,
            "log_prior_noise": self.log_prior_noise,
            "log_prob_need": self.log_prob_need,
            "log_prob_noise": self.log_prob_noise,
            "vocab": self.vocab,
            "alpha": self.alpha,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NaiveBayesModel":
        return cls(
            log_prior_need=float(data["log_prior_need"]),
            log_prior_noise=float(data["log_prior_noise"]),
            log_prob_need={k: float(v) for k, v in data["log_prob_need"].items()},
            log_prob_noise={k: float(v) for k, v in data["log_prob_noise"].items()},
            vocab=list(data.get("vocab") or []),
            alpha=float(data.get("alpha") or 1.0),
        )


def train_naive_bayes(
    positives: Iterable[str] | None = None,
    negatives: Iterable[str] | None = None,
    alpha: float = 1.0,
) -> NaiveBayesModel:
    pos = list(positives or SEED_POSITIVES)
    neg = list(negatives or SEED_NEGATIVES)
    need_counts: Counter[str] = Counter()
    noise_counts: Counter[str] = Counter()
    for text in pos:
        need_counts.update(_ngrams(_tokenize(text)))
    for text in neg:
        noise_counts.update(_ngrams(_tokenize(text)))
    vocab = sorted(set(need_counts) | set(noise_counts))
    v = max(1, len(vocab))
    need_total = sum(need_counts.values())
    noise_total = sum(noise_counts.values())
    log_prob_need = {
        t: math.log((need_counts.get(t, 0) + alpha) / (need_total + alpha * v)) for t in vocab
    }
    log_prob_noise = {
        t: math.log((noise_counts.get(t, 0) + alpha) / (noise_total + alpha * v)) for t in vocab
    }
    n_doc = len(pos) + len(neg)
    return NaiveBayesModel(
        log_prior_need=math.log(len(pos) / n_doc),
        log_prior_noise=math.log(len(neg) / n_doc),
        log_prob_need=log_prob_need,
        log_prob_noise=log_prob_noise,
        vocab=vocab,
        alpha=alpha,
    )


def save_model(model: NaiveBayesModel, path: Path | None = None) -> Path:
    path = path or DEFAULT_MODEL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_model(path: Path | None = None) -> NaiveBayesModel:
    path = path or DEFAULT_MODEL_PATH
    if path.exists():
        return NaiveBayesModel.from_dict(json.loads(path.read_text(encoding="utf-8")))
    model = train_naive_bayes()
    save_model(model, path)
    return model


_NB_CACHE: NaiveBayesModel | None = None


def get_nb_model(path: str | Path | None = None) -> NaiveBayesModel:
    global _NB_CACHE
    if _NB_CACHE is None:
        _NB_CACHE = load_model(Path(path) if path else DEFAULT_MODEL_PATH)
    return _NB_CACHE


def classify_naive_bayes(signal: RawSignal, model: NaiveBayesModel | None = None) -> Classification:
    kind = (signal.metadata or {}).get("kind") or ""
    if kind in {"app_listing", "store_result", "news"}:
        return Classification(is_need=False, confidence=0.05, backend="naive_bayes", features={"listing": 1.0})
    model = model or get_nb_model()
    prob = model.predict_proba(signal.text)
    return Classification(
        is_need=prob >= 0.5,
        confidence=round(prob, 4),
        backend="naive_bayes",
        features={"nb_proba": round(prob, 4)},
    )


# ---------------------------------------------------------------------------
# Ollama (optional local LLM)
# ---------------------------------------------------------------------------

def classify_ollama(signal: RawSignal, host: str, model: str, timeout: float = 8.0) -> Classification | None:
    prompt = (
        "Classify whether the following text expresses an unmet product need "
        "(someone wants a tool/app that does not exist or is poorly served). "
        'Reply ONLY JSON: {"is_need": true|false, "confidence": 0.0-1.0}\n\n'
        f"TEXT:\n{signal.text[:1500]}"
    )
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{host.rstrip('/')}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            )
            resp.raise_for_status()
            raw = resp.json().get("response") or "{}"
            data = json.loads(raw)
            conf = float(data.get("confidence", 0.5))
            is_need = bool(data.get("is_need"))
            return Classification(
                is_need=is_need,
                confidence=max(0.0, min(1.0, conf)),
                backend=f"ollama:{model}",
                features={},
            )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------

class NeedClassifier:
    def __init__(self, cfg: dict[str, Any] | None = None):
        cfg = cfg or {}
        self.backend = (cfg.get("backend") or "ensemble").lower()
        self.threshold = float(cfg.get("threshold", 0.5))
        self.ollama_host = cfg.get("ollama_host") or "http://127.0.0.1:11434"
        self.ollama_model = cfg.get("ollama_model") or "llama3.2:1b"
        self.blend_patterns = bool(cfg.get("blend_patterns", True))
        self.model_path = cfg.get("model_path")
        self._nb = get_nb_model(self.model_path) if self.backend in {"naive_bayes", "nb", "ensemble"} else None

    def classify(self, signal: RawSignal) -> Classification:
        backend = self.backend
        if backend in {"naive_bayes", "nb"}:
            result = classify_naive_bayes(signal, self._nb)
        elif backend == "ensemble":
            a = classify_logistic(signal)
            b = classify_naive_bayes(signal, self._nb or get_nb_model(self.model_path))
            conf = round(0.45 * a.confidence + 0.55 * b.confidence, 4)
            result = Classification(
                is_need=conf >= self.threshold,
                confidence=conf,
                backend="ensemble",
                features={**a.features, **b.features},
            )
        elif backend == "ollama":
            result = classify_ollama(signal, self.ollama_host, self.ollama_model)
            if result is None:
                # Fall back to ensemble if Ollama is down
                return NeedClassifier({**{"backend": "ensemble", "threshold": self.threshold}}).classify(signal)
        else:
            result = classify_logistic(signal)

        result.is_need = result.confidence >= self.threshold
        return result

    def filter(
        self,
        signals: Iterable[RawSignal],
        pattern_strengths: dict[str, float] | None = None,
    ) -> list[tuple[RawSignal, Classification]]:
        out: list[tuple[RawSignal, Classification]] = []
        pattern_strengths = pattern_strengths or {}
        for s in signals:
            c = self.classify(s)
            if self.blend_patterns and s.external_id in pattern_strengths:
                blended = 0.65 * c.confidence + 0.35 * pattern_strengths[s.external_id]
                c = Classification(
                    is_need=blended >= self.threshold,
                    confidence=round(blended, 4),
                    backend=c.backend + "+patterns",
                    features=c.features,
                )
            if c.is_need:
                out.append((s, c))
        out.sort(key=lambda t: t[1].confidence, reverse=True)
        return out


def ensure_default_model() -> Path:
    """Train & persist NB model if missing (called from CLI / first scan)."""
    if DEFAULT_MODEL_PATH.exists():
        return DEFAULT_MODEL_PATH
    model = train_naive_bayes()
    return save_model(model)
