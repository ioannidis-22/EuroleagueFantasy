"""Location of local data (DB, caches, overrides, settings)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    d = Path(os.environ.get("ELFANTASY_DATA") or ROOT / "data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "elfantasy.db"


def cache_dir() -> Path:
    return data_dir() / "cache"


def overrides_path() -> Path:
    return data_dir() / "player_overrides.json"


def settings_path() -> Path:
    return data_dir() / "settings.json"
