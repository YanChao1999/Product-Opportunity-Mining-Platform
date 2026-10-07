"""Unmet-need extraction and clustering."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any, Iterable

from opportunity_miner.models import Opportunity, RawSignal, SourceName

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "must", "shall",
    "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
    "me", "my", "your", "our", "their", "with", "from", "as", "by", "about", "into",
    "over", "after", "before", "between", "out", "up", "down", "not", "no", "so",
    "if", "then", "than", "too", "very", "just", "can", "app", "apps", "tool",
    "tools", "software", "like", "get", "got", "make", "made", "want", "need",
}


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z\u4e00-\u9fff]{2,}", text.lower())
    return [w for w in words if w not in STOPWORDS]


# Marketplace listings are competition context, not unmet-need seeds.
_COMPETITION_ONLY_KINDS = frozenset({"app_listing", "store_result", "news"})
# Curated placeholders used when live APIs are thin — exclude from live ranking.
_SEED_KINDS = frozenset({"seed_wish", "fallback_post"})
# Conventional-commit titles from GitHub search are almost never product gaps.
_COMMIT_TITLE = re.compile(
    r"^(feat|fix|docs|chore|refactor|test|ci|style|perf|build)(\([^)]*\))?:\s+",
    re.IGNORECASE,
)
# Language that suggests a *new product* gap, not an in-repo polish request.
_PRODUCT_GAP_MARKERS = (
    "i wish",
    "looking for",
    "somebody make",
    "somebody please",
    "somebody build",
    "no good alternative",
    "gap in the market",
    "would pay",
    "willing to pay",
    "is there a",
    "is there an",
    "is there any",
    "why isn't there",
    "why isnt there",
    "need a way",
    "need an app",
    "need a tool",
    "need a saas",
    "has anyone built",
    "anyone built",
    "alternative to",
    "求推荐",
    "有没有",
    "希望有",
    "谁来做",
    "找不到",
)


def _has_product_gap_language(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in _PRODUCT_GAP_MARKERS)


def _is_noise_signal(signal: RawSignal) -> bool:
    """Drop chats, news, launches, and in-repo chores that aren't product opportunities."""
    kind = (signal.metadata or {}).get("kind")
    title = (signal.title or "").strip()
    title_l = title.lower()
    text = signal.text

    if kind == "pull_request":
        return True
    if "/pull/" in (signal.url or "").lower():
        return True
    # Bare "Feature Request(s)" with no substance
    if re.fullmatch(r"\[?feature requests?\]?", title_l or ""):
        return True

    # GitHub issues: in-product feature asks need explicit *new product* gap language
    if signal.source == SourceName.GITHUB:
        if not _has_product_gap_language(text):
            return True

    # HN / Lobsters / RSS mirrors of HN
    if title_l.startswith("show hn:"):
        return True  # already-built product = supply, not unmet need
    if title_l.startswith("tell hn:") and not _has_product_gap_language(text):
        return True
    if title_l.startswith("ask hn:"):
        if _has_product_gap_language(text):
            return False
        # Capability / tool-seeking Ask HN (not chatty threads)
        ask_needish = (
            "tool",
            "app",
            "saas",
            "alternative",
            "access to",
            "way to",
            "without ",
            "support for",
            "integrate",
            "self-host",
            "self host",
            "offline",
            "open source",
        )
        if any(x in title_l for x in ask_needish):
            return False
        return True

    return False


def signal_strength(signal: RawSignal, patterns: list[re.Pattern[str]]) -> float:
    text = signal.text
    if not text:
        return 0.0
    kind = (signal.metadata or {}).get("kind")
    hits = sum(1 for p in patterns if p.search(text))
    # Existing product listings must show clear wish/gap language — never rank on popularity alone.
    if kind in _COMPETITION_ONLY_KINDS:
        if hits < 2:
            return 0.0
        return round(min(1.0, 0.2 * hits), 3)

    engagement = math.log1p(max(0, signal.score) + 2 * max(0, signal.comments))
    if hits == 0:
        return 0.0
    base = min(1.0, 0.25 * hits + 0.08 * engagement)
    # Low App Store ratings with complaint language get a boost
    if signal.source == SourceName.APP_STORE and kind == "review":
        try:
            rating = int(signal.metadata.get("rating") or 5)
        except (TypeError, ValueError):
            rating = 5
        if rating <= 2 and hits:
            base = min(1.0, base + 0.2)
        elif rating >= 4 and hits < 2:
            # Praise reviews are not unmet needs
            return 0.0
    return round(base, 3)


def filter_unmet_signals(
    signals: Iterable[RawSignal],
    patterns: list[str],
    min_score: float = 0.35,
    *,
    include_seeds: bool = False,
) -> list[tuple[RawSignal, float]]:
    compiled = _compile_patterns(patterns)
    scored: list[tuple[RawSignal, float]] = []
    seen: set[str] = set()

    title_markers = (
        "i wish",
        "looking for",
        "somebody make",
        "somebody please",
        "is there a",
        "is there an",
        "why isn't there",
        "why isnt there",
        "no good alternative",
        "would pay",
        "gap in the market",
        "有没有",
        "求推荐",
        "希望有",
        "谁来做",
    )

    for s in signals:
        kind = (s.metadata or {}).get("kind")
        if kind in _COMPETITION_ONLY_KINDS:
            continue
        if kind in _SEED_KINDS and not include_seeds:
            continue
        if s.source == SourceName.GITHUB and _COMMIT_TITLE.match(s.title or ""):
            continue
        if _is_noise_signal(s):
            continue

        # App Store reviews: only low-star complaints with pattern hits
        if kind == "review":
            try:
                rating = int((s.metadata or {}).get("rating") or 5)
            except (TypeError, ValueError):
                rating = 5
            if rating > 3:
                continue

        strength = signal_strength(s, compiled)
        title_l = (s.title or "").lower()
        if strength < min_score and any(m in title_l for m in title_markers):
            strength = max(strength, 0.45)

        if strength >= min_score and s.external_id not in seen:
            seen.add(s.external_id)
            scored.append((s, strength))

    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_signals(
    scored: list[tuple[RawSignal, float]],
    threshold: float = 0.55,
) -> list[list[tuple[RawSignal, float]]]:
    clusters: list[list[tuple[RawSignal, float]]] = []
    centroids: list[set[str]] = []

    for signal, strength in scored:
        tokens = set(tokenize(signal.text)[:40])
        best_i = -1
        best_sim = 0.0
        for i, centroid in enumerate(centroids):
            sim = _jaccard(tokens, centroid)
            if sim > best_sim:
                best_sim = sim
                best_i = i
        if best_i >= 0 and best_sim >= threshold:
            clusters[best_i].append((signal, strength))
            centroids[best_i] |= tokens
        else:
            clusters.append([(signal, strength)])
            centroids.append(tokens)
    return clusters


def _category_for(keywords: list[str], texts: str, title: str = "") -> str:
    """Backward-compatible wrapper — prefer CategoryClassifier for new code."""
    from opportunity_miner.extract.category import classify_category_rules

    return classify_category_rules(keywords, texts, title=title)


def _title_from_cluster(cluster: list[tuple[RawSignal, float]]) -> str:
    # Prefer the highest-strength title that looks like a wish/request
    ranked = sorted(cluster, key=lambda t: (t[1], t[0].score + t[0].comments), reverse=True)
    for signal, _ in ranked:
        title = (signal.title or "").strip()
        if title and len(title) > 12:
            return title[:140]
    # Fallback: keyword phrase
    tokens = Counter()
    for signal, _ in cluster:
        tokens.update(tokenize(signal.text)[:20])
    top = [w for w, _ in tokens.most_common(6)]
    return "Unmet need: " + (" / ".join(top) if top else "untitled opportunity")


def clusters_to_opportunities(
    clusters: list[list[tuple[RawSignal, float]]],
    need_confidences: dict[str, float] | None = None,
    *,
    category_cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return intermediate opportunity dicts (scoring applied later)."""
    from opportunity_miner.extract.category import CategoryClassifier

    need_confidences = need_confidences or {}
    cat_clf = CategoryClassifier(category_cfg or {})
    results: list[dict[str, Any]] = []
    for cluster in clusters:
        if not cluster:
            continue
        signals = [s for s, _ in cluster]
        strengths = [st for _, st in cluster]
        tokens = Counter()
        for s in signals:
            tokens.update(tokenize(s.text)[:30])
        keywords = [w for w, _ in tokens.most_common(10)]
        sources = sorted({s.source for s in signals}, key=lambda x: x.value)
        text_blob = " ".join(s.text for s in signals)[:4000]
        title = _title_from_cluster(cluster)
        oid = hashlib.sha1(title.lower().encode("utf-8")).hexdigest()[:12]
        confs = [need_confidences[s.external_id] for s in signals if s.external_id in need_confidences]
        need_confidence = sum(confs) / len(confs) if confs else (sum(strengths) / len(strengths))
        cat = cat_clf.classify(title, text_blob, keywords)
        summary = (
            f"{len(signals)} signals across {', '.join(s.value for s in sources)}. "
            f"Top keywords: {', '.join(keywords[:5]) or 'n/a'}. "
            f"Need-confidence={need_confidence:.2f}. "
            f"Category={cat.category} ({cat.backend}, conf={cat.confidence:.2f})."
        )
        results.append(
            {
                "id": oid,
                "title": title,
                "summary": summary,
                "category": cat.category,
                "category_backend": cat.backend,
                "category_confidence": cat.confidence,
                "sources": sources,
                "evidence": signals,
                "keywords": keywords,
                "avg_strength": sum(strengths) / len(strengths),
                "need_confidence": need_confidence,
                "total_score": sum(max(0, s.score) for s in signals),
                "total_comments": sum(max(0, s.comments) for s in signals),
                "text_blob": text_blob,
            }
        )
    return results


def competition_context(signals: list[RawSignal]) -> list[RawSignal]:
    """App Store / Steam listings kept for crowding estimates, not as opportunities."""
    return [
        s
        for s in signals
        if (s.metadata or {}).get("kind") in _COMPETITION_ONLY_KINDS
    ]


def extract_opportunity_candidates(signals: list[RawSignal], extract_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    from opportunity_miner.extract.classifier import NeedClassifier

    patterns = extract_cfg.get("unmet_need_patterns") or []
    min_score = float(extract_cfg.get("min_signal_score", 0.35))
    threshold = float(extract_cfg.get("cluster_similarity_threshold", 0.55))
    include_seeds = bool(extract_cfg.get("include_seeds", False))
    clf_cfg = extract_cfg.get("classifier") or {}
    use_classifier = bool(clf_cfg.get("enabled", True))

    pattern_scored = filter_unmet_signals(
        signals, patterns, min_score=min_score, include_seeds=include_seeds
    )
    pattern_map = {s.external_id: st for s, st in pattern_scored}

    need_confidences: dict[str, float] = {}
    if use_classifier:
        clf = NeedClassifier(clf_cfg)
        # Classify all non-listing / non-seed signals; blend with pattern strengths
        candidates_raw = []
        for s in signals:
            kind = (s.metadata or {}).get("kind")
            if kind in _COMPETITION_ONLY_KINDS:
                continue
            if kind in _SEED_KINDS and not include_seeds:
                continue
            if s.source == SourceName.GITHUB and _COMMIT_TITLE.match(s.title or ""):
                continue
            if _is_noise_signal(s):
                continue
            candidates_raw.append(s)
        classified = clf.filter(candidates_raw, pattern_strengths=pattern_map)
        scored = [(s, max(c.confidence, pattern_map.get(s.external_id, 0.0))) for s, c in classified]
        need_confidences = {s.external_id: c.confidence for s, c in classified}
        # Always keep strong pattern hits even if logistic is shy
        seen = {s.external_id for s, _ in scored}
        for s, st in pattern_scored:
            if s.external_id not in seen and st >= max(min_score, 0.5):
                scored.append((s, st))
                need_confidences[s.external_id] = st
    else:
        scored = pattern_scored
        need_confidences = {s.external_id: st for s, st in scored}

    scored.sort(key=lambda t: t[1], reverse=True)
    clusters = cluster_signals(scored, threshold=threshold)
    # Category: prefer extraction.category; inherit Ollama host/model from need classifier
    category_cfg = dict(extract_cfg.get("category") or {})
    if not category_cfg.get("ollama_host") and clf_cfg.get("ollama_host"):
        category_cfg["ollama_host"] = clf_cfg["ollama_host"]
    if not category_cfg.get("ollama_model") and clf_cfg.get("ollama_model"):
        category_cfg["ollama_model"] = clf_cfg["ollama_model"]
    candidates = clusters_to_opportunities(
        clusters, need_confidences=need_confidences, category_cfg=category_cfg
    )
    # Attach marketplace listings so competition scoring sees existing supply
    catalog = competition_context(signals)
    if catalog:
        for c in candidates:
            keys = set(c.get("keywords") or [])
            related = []
            for listing in catalog:
                listing_tokens = set(tokenize(listing.text)[:30])
                if keys and _jaccard(keys, listing_tokens) >= 0.15:
                    related.append(listing)
            if related:
                c["competition_listings"] = related[:15]
                c["text_blob"] = (c.get("text_blob") or "") + "\n" + "\n".join(
                    f"[listing] {x.title}" for x in related[:8]
                )
    return candidates
