"""User-adjustable settings, read from UTF-8 JSON."""
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class Settings:
    season: str = "E2026"
    api_delay_s: float = 0.3
    value_buy: float = 0.10       # BUY when the expected price change is at least this
    value_sell: float = -0.10     # SELL when it is at most this
    dip_min_avg: float = 10.0     # DIP: season PIR average at least this...
    dip_drop: float = 0.3         # ...after a price fall of at least this last round


def load_settings(path: Path) -> Settings:
    path = Path(path)
    if not path.exists():
        return Settings()
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Settings)}
    kwargs = {k: v for k, v in raw.items() if k in known}
    return Settings(**kwargs)
