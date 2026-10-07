"""Configuration loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "default.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with cfg_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Env overrides for secrets
    data.setdefault("secrets", {})
    data["secrets"]["product_hunt_token"] = os.getenv(
        "PRODUCT_HUNT_API_TOKEN", data["secrets"].get("product_hunt_token", "")
    )
    data["secrets"]["reddit_client_id"] = os.getenv(
        "REDDIT_CLIENT_ID", data["secrets"].get("reddit_client_id", "")
    )
    data["secrets"]["reddit_client_secret"] = os.getenv(
        "REDDIT_CLIENT_SECRET", data["secrets"].get("reddit_client_secret", "")
    )
    data["secrets"]["openai_api_key"] = os.getenv(
        "OPENAI_API_KEY", data["secrets"].get("openai_api_key", "")
    )
    data["secrets"]["github_token"] = os.getenv(
        "GITHUB_TOKEN", data["secrets"].get("github_token", "")
    )
    # Optional Ollama override for local LLM classifier
    clf = (data.get("extraction") or {}).setdefault("classifier", {})
    if os.getenv("OLLAMA_HOST"):
        clf["ollama_host"] = os.getenv("OLLAMA_HOST")
    if os.getenv("OLLAMA_MODEL"):
        clf["ollama_model"] = os.getenv("OLLAMA_MODEL")
    if os.getenv("CLASSIFIER_BACKEND"):
        clf["backend"] = os.getenv("CLASSIFIER_BACKEND")
    cat = (data.get("extraction") or {}).setdefault("category", {})
    if os.getenv("OLLAMA_HOST"):
        cat.setdefault("ollama_host", os.getenv("OLLAMA_HOST"))
    if os.getenv("OLLAMA_MODEL"):
        cat.setdefault("ollama_model", os.getenv("OLLAMA_MODEL"))
    if os.getenv("CATEGORY_BACKEND"):
        cat["backend"] = os.getenv("CATEGORY_BACKEND")
    return data
