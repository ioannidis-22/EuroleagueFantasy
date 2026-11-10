"""Download fixtures, rosters and new box scores for a season into SQLite."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Callable

from .el_client import ELApiError
from .el_parse import parse_boxscore, parse_games, parse_people, parse_stats_v3, parse_teams
from .store import read_df, upsert_many, upsert_rows


@dataclass
class RefreshReport:
    season: str
    games_total: int = 0
    new_box_scores: int = 0
    failed: list[tuple[int, str]] = field(default_factory=list)


def refresh_season(conn: sqlite3.Connection, client, season: str,
                   progress: Callable[[int, int], None] | None = None,
                   source: str = "live") -> RefreshReport:
    """source: "live" (official box score incl. DNPs, rate-limited) or "v3" (fast; no DNP rows)."""
    report = RefreshReport(season)
    payload = client.games(season)
    games = parse_games(payload, season)
    teams = parse_teams(payload)
    upsert_many(conn, [("games", games), ("teams", teams)])
    report.games_total = len(games)

    for club in sorted(set(games["home_club"]) | set(games["away_club"])):
        try:
            upsert_rows(conn, "el_players", parse_people(client.people(season, club), season))
        except ELApiError as e:
            report.failed.append((0, f"roster {club}: {e}"))

    have = set(read_df(conn, "SELECT DISTINCT game_code FROM box_player WHERE season = ?",
                       (season,))["game_code"])
    todo = [int(c) for c in games.loc[games["played"] == 1, "game_code"] if int(c) not in have]
    for i, code in enumerate(todo, 1):
        try:
            items = []
            if source == "v3":
                players, team_rows, people = parse_stats_v3(client.stats_v3(season, code), season, code)
                items.append(("el_players", people))
            else:
                players, team_rows = parse_boxscore(client.boxscore(season, code), season, code)
            if players.empty:
                raise ELApiError("empty box score")
            upsert_many(conn, [("box_player", players), ("box_team", team_rows), *items])
            report.new_box_scores += 1
        except (ELApiError, KeyError, ValueError, TypeError) as e:
            report.failed.append((code, str(e)))
        if progress:
            progress(i, len(todo))
    return report
