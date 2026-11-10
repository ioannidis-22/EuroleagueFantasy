"""Test doubles shared across test modules."""
from __future__ import annotations

import json

import requests


class FakeResponse:
    def __init__(self, status: int, payload):
        self.status_code = status
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
                return FakeResponse(*val)
        return FakeResponse(404, {})
