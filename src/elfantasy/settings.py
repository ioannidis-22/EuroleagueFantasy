"""User-adjustable settings, stored as UTF-8 JSON."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Settings:
    season: str = "E2026"
    boom: float = 20.0
    bust: float = 5.0
    form_threshold: float = 2.0
    win_bonus: float | None = None
    dvp_shrink_minutes: float = 400.0
    api_delay_s: float = 0.3


def load_settings(path: Path) -> Settings:
    path = Path(path)
    if not path.exists():
        return Settings()
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Settings)}
    kwargs = {k: v for k, v in raw.items() if k in known}
    return Settings(**kwargs)


def save_settings(s: Settings, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")
