"""
Local need-vs-noise classifier (no cloud LLM required).

Uses a tiny logistic model over hand-crafted + bag-of-token features.
Optionally can call a local Ollama model if OLLAMA_HOST / classifier.backend=ollama.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

import httpx

from opportunity_miner.models import RawSignal

# Seed lexicon → positive / negative weights for logistic features
POS_PHRASES = [
    "i wish", "looking for", "somebody make", "no good alternative", "would pay",
    "gap in the market", "still can't find", "feature request", "missing feature",
    "is there a tool", "is there an app", "why isn't there", "shut up and take my money",
    "找不到", "有没有", "希望有", "谁来做", "求推荐",
]
NEG_PHRASES = [
    "hiring", "we're thrilled", "launch day", "changelog", "release notes",
    "as expected", "works great", "love this app", "five stars", "promo code",
    "giveaway", "newsletter signup", "our company is proud",
]
POS_TOKENS = {
    "wish", "alternative", "missing", "pay", "saas", "tool", "gap", "need",
    "request", "build", "make", "找不到", "希望", "付费", "替代",
}
NEG_TOKENS = {
    "hiring", "sponsored", "giveaway", "congratulat", "launched", "announcing",
}


@dataclass
class Classification:
    is_need: bool
    confidence: float  # 0–1 probability of unmet need
    backend: str
    features: dict[str, float]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", (text or "").lower())


def extract_features(text: str, score: int = 0, comments: int = 0, kind: str = "") -> dict[str, float]:
    low = (text or "").lower()
    toks = _tokenize(low)
    feat: dict[str, float] = {
        "bias": 1.0,
        "len_log": math.log1p(len(low)),
        "eng_log": math.log1p(max(0, score) + 2 * max(0, comments)),
        "pos_phrase": float(sum(1 for p in POS_PHRASES if p in low)),
        "neg_phrase": float(sum(1 for p in NEG_PHRASES if p in low)),
        "pos_tok": float(sum(1 for t in toks if t in POS_TOKENS)),
        "neg_tok": float(sum(1 for t in toks if any(t.startswith(n) for n in NEG_TOKENS))),
        "question": 1.0 if ("?" in low or low.startswith("ask ") or "有没有" in low) else 0.0,
        "review_low": 1.0 if kind == "review" and score <= 2 else 0.0,
        "listing": 1.0 if kind in {"app_listing", "store_result", "news"} else 0.0,
    }
    return feat


# Weights tuned on seed positives/negatives (pure Python logistic regression)
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


def classify_ollama(signal: RawSignal, host: str, model: str, timeout: float = 8.0) -> Classification | None:
    """Optional local LLM via Ollama HTTP API."""
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


class NeedClassifier:
    def __init__(self, cfg: dict[str, Any] | None = None):
        cfg = cfg or {}
        self.backend = (cfg.get("backend") or "logistic").lower()
        self.threshold = float(cfg.get("threshold", 0.5))
        self.ollama_host = cfg.get("ollama_host") or "http://127.0.0.1:11434"
        self.ollama_model = cfg.get("ollama_model") or "llama3.2:1b"
        self.blend_patterns = bool(cfg.get("blend_patterns", True))

    def classify(self, signal: RawSignal) -> Classification:
        if self.backend == "ollama":
            result = classify_ollama(signal, self.ollama_host, self.ollama_model)
            if result:
                result.is_need = result.confidence >= self.threshold
                return result
        # Default / fallback
        result = classify_logistic(signal)
        result.is_need = result.confidence >= self.threshold
        return result

    def filter(
        self,
        signals: Iterable[RawSignal],
        pattern_strengths: dict[str, float] | None = None,
    ) -> list[tuple[RawSignal, Classification]]:
        """Return signals classified as needs, optionally blending regex strength."""
        out: list[tuple[RawSignal, Classification]] = []
        pattern_strengths = pattern_strengths or {}
        for s in signals:
            c = self.classify(s)
            if self.blend_patterns and s.external_id in pattern_strengths:
                # Average logistic confidence with pattern strength
                blended = 0.6 * c.confidence + 0.4 * pattern_strengths[s.external_id]
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
