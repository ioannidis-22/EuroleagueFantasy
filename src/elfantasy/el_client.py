"""HTTP access to the public Euroleague APIs, with a disk cache for final box scores."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

V2 = "https://api-live.euroleague.net/v2/competitions/E/seasons"
LIVE = "https://live.euroleague.net/api"
V3 = "https://api-live.euroleague.net/v3/competitions/E/seasons"


class ELApiError(RuntimeError):
    pass


class ELClient:
    def __init__(self, cache_dir: Path, delay_s: float = 0.3, timeout_s: float = 20,
                 session: requests.Session | None = None, retries: int = 2, max_wait_s: float = 300):
        self.cache_dir = Path(cache_dir)
        self.delay_s = delay_s
        self.timeout_s = timeout_s
        self.session = session or requests.Session()
        self.retries = retries
        self.max_wait_s = max_wait_s

    def _get(self, url: str) -> dict:
        last = ""
        for _ in range(self.retries + 1):
            if self.delay_s:
                time.sleep(self.delay_s)
            try:
                r = self.session.get(url, timeout=self.timeout_s)
            except requests.RequestException as e:
                last = f"{type(e).__name__}: {e}"
                continue
            if r.status_code == 429:  # rate limited: wait as told (capped), then retry
                try:
                    wait = float(getattr(r, "headers", {}).get("Retry-After", 60))
                except (TypeError, ValueError):
                    wait = 60.0
                time.sleep(min(wait, self.max_wait_s))
                last = "HTTP 429 (rate limited)"
                continue
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError as e:
                    last = f"invalid JSON: {e}"
                    continue
            last = f"HTTP {r.status_code}"
        raise ELApiError(f"{url} failed after {self.retries + 1} attempts ({last})")

    def games(self, season: str) -> dict:
        return self._get(f"{V2}/{season}/games")

    def people(self, season: str, club_code: str) -> dict:
        return self._get(f"{V2}/{season}/clubs/{club_code}/people")

    def boxscore(self, season: str, game_code: int) -> dict:
        path = self.cache_dir / season / f"box_{game_code}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        payload = self._get(f"{LIVE}/Boxscore?gamecode={game_code}&seasoncode={season}")
        if not payload.get("Live", False):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload

    def stats_v3(self, season: str, game_code: int) -> dict:
        """v3 per-game stats (used for past seasons); cached once fetched."""
        path = self.cache_dir / season / f"stats_{game_code}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        payload = self._get(f"{V3}/{season}/games/{game_code}/stats")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload
