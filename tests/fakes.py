"""Test doubles shared across test modules."""
from __future__ import annotations

import json

import requests


class FakeResponse:
    def __init__(self, status: int, payload, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class FakeSession:
    """routes: {url-substring: (status, payload) | Exception}."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        for key, val in self.routes.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                if isinstance(val, list):          # sequence of responses, one per call
                    val = val.pop(0) if len(val) > 1 else val[0]
                return FakeResponse(*val)
        return FakeResponse(404, {})


class FakeClient:
    """Serves real API fixtures: games for rounds 10-11 of E2026, round-10 box scores 91-100."""

    def __init__(self, fixtures_dir, fail_on=(), rosters=None):
        self.dir = fixtures_dir
        self.fail_on = set(fail_on)
        self.rosters = rosters          # {club: [player codes]}; None serves the OLY roster for every club
        self.box_calls = 0
        self.people_calls = []

    def _load(self, name):
        return json.loads((self.dir / name).read_text(encoding="utf-8"))

    def games(self, season):
        return self._load("games_E2026_r10_11.json")

    def people(self, season, club_code):
        self.people_calls.append(club_code)
        if self.rosters is None:
            return self._load("people_E2026_OLY.json")
        return {"data": [{"typeName": "Player", "person": {"code": code, "name": code}, "club": {"code": club_code},
                          "positionName": None} for code in self.rosters.get(club_code, [])]}

    def stats_v3(self, season, game_code):
        self.box_calls += 1
        return self._load("stats_v3_E2026_1.json")

    def boxscore(self, season, game_code):
        from elfantasy.el_client import ELApiError
        self.box_calls += 1
        if game_code in self.fail_on:
            raise ELApiError(f"boom {game_code}")
        return self._load(f"box_E2026_{game_code}.json")
