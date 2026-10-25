"""Single entry point for configuration: `.env` + YAML/JSON files under config/.

Nothing else in the project reads environment variables or config files directly.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = CONFIG_DIR / ".env.example"

load_dotenv(ENV_FILE, override=False)


class ConfigError(RuntimeError):
    pass


_MISSING = object()


def env(name: str, default: Any = _MISSING, cast: Callable[[str], Any] = str) -> Any:
    """Read an env var. Without a default, the variable must be set (see .env.example)."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if default is _MISSING:
            raise ConfigError(
                f"Environment variable {name} is not set. Copy config/.env.example to .env "
                f"(python store.py setup) and fill it in."
            )
        return default
    return cast(raw)


def env_bool(name: str, default: Any = _MISSING) -> bool:
    return env(name, default, cast=lambda v: v.strip().lower() in {"1", "true", "yes", "on"})


def env_list(name: str, default: Any = _MISSING) -> list[str]:
    return env(name, default, cast=lambda v: [p.strip() for p in v.split(",") if p.strip()])


def project_path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


@lru_cache(maxsize=None)
def _load_yaml(name: str) -> dict:
    import yaml

    path = CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def business() -> dict:
    return _load_yaml("business.yaml")


def ml() -> dict:
    return _load_yaml("ml.yaml")


def categories() -> list[dict]:
    return _load_yaml("categories.yaml")["categories"]


def india() -> dict:
    return _load_yaml("india.yaml")


def text_templates() -> dict:
    return _load_yaml("text_templates.yaml")


def intents() -> dict:
    return _load_yaml("intents.yaml")


@lru_cache(maxsize=None)
def theme() -> dict:
    with (CONFIG_DIR / "theme.json").open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get(section: dict, dotted: str) -> Any:
    """get(business(), 'risk.high_threshold') with a clear error when a key is missing."""
    node: Any = section
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(f"Missing config key: {dotted}")
        node = node[part]
    return node
