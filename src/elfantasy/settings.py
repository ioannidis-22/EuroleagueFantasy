"""User-adjustable settings, read from UTF-8 JSON."""
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class Settings:
    season: str = "E2026"
    api_delay_s: float = 0.3


def load_settings(path: Path) -> Settings:
    path = Path(path)
    if not path.exists():
        return Settings()
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Settings)}
    kwargs = {k: v for k, v in raw.items() if k in known}
    return Settings(**kwargs)
