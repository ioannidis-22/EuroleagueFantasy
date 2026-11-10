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

    rows, unmatched = [], []
    for f in fp.itertuples(index=False):
        hit = _match_one(f, el, overrides)
        if hit:
            rows.append({"fantasy_id": f.fantasy_id, "player_code": hit[0], "method": hit[1]})
        else:
            unmatched.append({"fantasy_id": f.fantasy_id, "name": f.name, "surname": f.surname,
                              "team": f.team})
    replace_rows(conn, "player_map", pd.DataFrame(rows, columns=["fantasy_id", "player_code", "method"]),
                 where={})
    return MatchReport(len(rows), pd.DataFrame(unmatched, columns=["fantasy_id", "name", "surname", "team"]))


def _match_one(f, el: pd.DataFrame, overrides: dict[str, str]) -> tuple[str, str] | None:
    if f.fantasy_id in overrides:
        return overrides[f.fantasy_id], "override"
    full = normalize_name(f"{f.name} {f.surname}")
    tokens = frozenset(full.split())
    sur = normalize_name(f.surname)
    team = el[el["tv_code"] == f.team]

    exact = team[team["tokens"] == tokens]
    if len(exact) == 1:
        return exact.iloc[0]["player_code"], "name"

    sur_tokens = set(sur.split())
    by_sur = team[team["surname_n"].map(lambda s: s == sur or (sur_tokens and sur_tokens <= set(s.split())))]
    if len(by_sur) == 1:
        return by_sur.iloc[0]["player_code"], "surname"

    if len(team):
        scores = team["full_n"].map(lambda s: _ratio(full, s)).sort_values(ascending=False)
        best = scores.iloc[0]
        second = scores.iloc[1] if len(scores) > 1 else 0.0
        if best >= FUZZY_MIN and best - second >= FUZZY_MARGIN:
            return team.loc[scores.index[0], "player_code"], "fuzzy"

    anywhere = el[el["tokens"] == tokens]
    if anywhere["player_code"].nunique() == 1:
        return anywhere.iloc[0]["player_code"], "name_any_team"
    return None


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
