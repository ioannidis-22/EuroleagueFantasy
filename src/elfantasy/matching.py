"""Link fantasy-export players to Euroleague player codes."""
from __future__ import annotations

import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from .store import read_df, replace_rows

_TRANSLIT = str.maketrans({"đ": "d", "Đ": "D", "ł": "l", "Ł": "L", "ø": "o", "Ø": "O",
                           "ß": "ss", "ı": "i", "æ": "ae"})
FUZZY_MIN = 0.80
FUZZY_MARGIN = 0.05


def normalize_name(s: str) -> str:
    s = (s or "").translate(_TRANSLIT)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    for ch in "-.',":
        s = s.replace(ch, " ")
    return " ".join(s.split())


def _el_parts(el_name: str) -> tuple[str, str]:
    """'SURNAME, NAME' -> (normalized surname, normalized 'name surname')."""
    surname, _, first = el_name.partition(",")
    return normalize_name(surname), normalize_name(f"{first} {surname}")


def _ratio(a: str, b: str) -> float:
    return max(SequenceMatcher(None, a, b).ratio(),
               SequenceMatcher(None, a.replace(" ", ""), b.replace(" ", "")).ratio())


@dataclass
class MatchReport:
    matched: int
    unmatched: pd.DataFrame


def _load_overrides(path: Path) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in raw.items() if not str(k).startswith("_")}


def match_players(conn: sqlite3.Connection, season: str, overrides_path: Path) -> MatchReport:
    fp = read_df(conn, """SELECT fantasy_id, name, surname, team FROM fantasy_players
                          WHERE matchday = (SELECT MAX(matchday) FROM snapshots)""")
    el = read_df(conn, """SELECT DISTINCT e.player_code, e.name, t.tv_code
                          FROM el_players e LEFT JOIN teams t ON t.club_code = e.club_code
                          WHERE e.season = ?""", (season,))
    parts = el["name"].map(_el_parts)
    el["surname_n"] = [p[0] for p in parts]
    el["full_n"] = [p[1] for p in parts]
    el["tokens"] = el["full_n"].map(lambda s: frozenset(s.split()))
    overrides = _load_overrides(overrides_path)

    # Assign links strongest method first; an Euroleague code is never given to two players.
    taken: set[str] = set()
    links: dict[str, tuple[str, str]] = {}
    for method in METHODS:
        free = el[~el["player_code"].isin(taken)]
        for f in fp.itertuples(index=False):
            if f.fantasy_id in links:
                continue
            code = _try(method, f, free, overrides)
            if code is not None and code not in taken:
                links[f.fantasy_id] = (code, method)
                taken.add(code)

    rows = [{"fantasy_id": k, "player_code": c, "method": m} for k, (c, m) in links.items()]
    unmatched = fp[~fp["fantasy_id"].isin(links)][["fantasy_id", "name", "surname", "team"]]
    replace_rows(conn, "player_map", pd.DataFrame(rows, columns=["fantasy_id", "player_code", "method"]),
                 where={})
    return MatchReport(len(rows), unmatched.reset_index(drop=True))


METHODS = ("override", "name", "surname", "fuzzy", "name_any_team")
FUZZY_SURNAME_MIN = 0.80


def _try(method: str, f, el: pd.DataFrame, overrides: dict[str, str]) -> str | None:
    """Code for fantasy row f by one method, or None. `el` holds only still-free codes."""
    if method == "override":
        return overrides.get(f.fantasy_id)
    full = normalize_name(f"{f.name} {f.surname}")
    tokens = frozenset(full.split())
    sur = normalize_name(f.surname)
    team = el[el["tv_code"] == f.team]

    if method == "name":
        exact = team[team["tokens"] == tokens]
        return exact.iloc[0]["player_code"] if len(exact) == 1 else None

    if method == "surname":
        sur_tokens = set(sur.split())
        by_sur = team[team["surname_n"].map(lambda s: s == sur or (bool(sur_tokens) and sur_tokens <= set(s.split())))]
        return by_sur.iloc[0]["player_code"] if len(by_sur) == 1 else None

    if method == "fuzzy":
        # surnames must already be close, so a shared first name can't carry the match
        ok = team[team["surname_n"].map(lambda s: _ratio(sur, s) >= FUZZY_SURNAME_MIN)]
        if ok.empty:
            return None
        scores = ok["full_n"].map(lambda s: _ratio(full, s)).sort_values(ascending=False)
        best = scores.iloc[0]
        second = scores.iloc[1] if len(scores) > 1 else 0.0
        if best >= FUZZY_MIN and best - second >= FUZZY_MARGIN:
            return ok.loc[scores.index[0], "player_code"]
        return None

    anywhere = el[el["tokens"] == tokens]
    return anywhere.iloc[0]["player_code"] if anywhere["player_code"].nunique() == 1 else None


def unmatched_players(conn: sqlite3.Connection) -> pd.DataFrame:
    """Latest-snapshot fantasy players without a player_map entry."""
    return read_df(conn, """SELECT fp.fantasy_id, fp.name, fp.surname, fp.team, fp.position
                            FROM fantasy_players fp
                            LEFT JOIN player_map pm ON pm.fantasy_id = fp.fantasy_id
                            WHERE fp.matchday = (SELECT MAX(matchday) FROM snapshots)
                              AND pm.fantasy_id IS NULL
                            ORDER BY fp.team, fp.surname""")


def save_override(path: Path, fantasy_id: str, player_code: str) -> None:
    """Add/replace one manual link in the overrides JSON (UTF-8)."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[str(fantasy_id)] = str(player_code)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
