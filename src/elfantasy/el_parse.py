"""Pure parsing of Euroleague API payloads into table-shaped DataFrames."""
from __future__ import annotations

import pandas as pd

BOX_FIELDS = {
    "Points": "pts", "FieldGoalsMade2": "fgm2", "FieldGoalsAttempted2": "fga2",
    "FieldGoalsMade3": "fgm3", "FieldGoalsAttempted3": "fga3", "FreeThrowsMade": "ftm",
    "FreeThrowsAttempted": "fta", "OffensiveRebounds": "oreb", "DefensiveRebounds": "dreb",
    "Assistances": "ast", "Steals": "stl", "Turnovers": "tov", "BlocksFavour": "blk",
    "BlocksAgainst": "blka", "FoulsCommited": "pf", "FoulsReceived": "fd",
}


def parse_games(payload: dict, season: str) -> pd.DataFrame:
    rows = []
    for g in payload.get("data", []):
        rows.append({
            "season": season, "game_code": int(g["gameCode"]), "round": int(g["round"]),
            "phase": g["phaseType"]["code"], "local_date": g.get("localDate"),
            "utc_date": g.get("utcDate"),
            "home_club": g["local"]["club"]["code"], "away_club": g["road"]["club"]["code"],
            "home_score": int(g["local"].get("score") or 0),
            "away_score": int(g["road"].get("score") or 0),
            "played": int(bool(g.get("played"))),
        })
    return pd.DataFrame(rows, columns=["season", "game_code", "round", "phase", "local_date",
                                       "utc_date", "home_club", "away_club", "home_score",
                                       "away_score", "played"])


def parse_teams(payload: dict) -> pd.DataFrame:
    seen = {}
    for g in payload.get("data", []):
        for side in ("local", "road"):
            c = g[side]["club"]
            seen[c["code"]] = {"club_code": c["code"], "tv_code": c["tvCode"], "name": c["name"]}
    return pd.DataFrame(list(seen.values()), columns=["club_code", "tv_code", "name"])


def _minutes(s: str) -> tuple[float, int]:
    s = (s or "").strip()
    if not s or s.upper() == "DNP":
        return 0.0, 1
    mm, _, ss = s.partition(":")
    return int(mm) + int(ss or 0) / 60, 0


def parse_boxscore(payload: dict, season: str, game_code: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    players, teams = [], []
    for side in payload.get("Stats", []):
        ps = side.get("PlayersStats", [])
        club = ps[0]["Team"].strip() if ps else None
        for p in ps:
            minutes, dnp = _minutes(p.get("Minutes"))
            row = {"season": season, "game_code": int(game_code),
                   "player_code": p["Player_ID"].strip().lstrip("P"), "club_code": p["Team"].strip(),
                   "is_starter": int(p.get("IsStarter") or 0), "minutes": minutes, "dnp": dnp}
            row.update({dst: int(p.get(src) or 0) for src, dst in BOX_FIELDS.items()})
            row["pir_official"] = int(p.get("Valuation") or 0)
            players.append(row)
        tot = side.get("totr") or {}
        if club and tot:
            trow = {"season": season, "game_code": int(game_code), "club_code": club}
            trow.update({dst: int(tot.get(src) or 0) for src, dst in BOX_FIELDS.items()})
            teams.append(trow)
    return pd.DataFrame(players), pd.DataFrame(teams)


def parse_people(payload: dict, season: str) -> pd.DataFrame:
    items = payload["data"] if isinstance(payload, dict) and "data" in payload else payload
    rows = [{"season": season, "player_code": x["person"]["code"].strip(),
             "club_code": x["club"]["code"], "name": x["person"]["name"],
             "position": x.get("positionName")}
            for x in items if x.get("typeName") == "Player"]
    return pd.DataFrame(rows, columns=["season", "player_code", "club_code", "name", "position"])


V3_FIELDS = {
    "points": "pts", "fieldGoalsMade2": "fgm2", "fieldGoalsAttempted2": "fga2",
    "fieldGoalsMade3": "fgm3", "fieldGoalsAttempted3": "fga3", "freeThrowsMade": "ftm",
    "freeThrowsAttempted": "fta", "offensiveRebounds": "oreb", "defensiveRebounds": "dreb",
    "assistances": "ast", "steals": "stl", "turnovers": "tov", "blocksFavour": "blk",
    "blocksAgainst": "blka", "foulsCommited": "pf", "foulsReceived": "fd",
}


def parse_stats_v3(payload: dict, season: str, game_code: int
                   ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """v3 game stats -> (box_player rows, box_team rows, el_players rows with in-game position)."""
    players, teams, people = [], [], []
    for side in ("local", "road"):
        block = payload.get(side) or {}
        club = None
        for item in block.get("players", []):
            person, st = item["player"]["person"], item["stats"]
            club = item["player"]["club"]["code"]
            secs = float(st.get("timePlayed") or 0)
            row = {"season": season, "game_code": int(game_code), "player_code": person["code"].strip(),
                   "club_code": club, "is_starter": int(bool(st.get("startFive"))),
                   "minutes": secs / 60, "dnp": int(secs == 0)}
            row.update({dst: int(st.get(src) or 0) for src, dst in V3_FIELDS.items()})
            row["pir_official"] = int(st.get("valuation") or 0)
            players.append(row)
            people.append({"season": season, "player_code": row["player_code"], "club_code": club,
                           "name": person["name"], "position": item["player"].get("positionName")})
        tot = block.get("total") or {}
        if club and tot:
            trow = {"season": season, "game_code": int(game_code), "club_code": club}
            trow.update({dst: int(tot.get(src) or 0) for src, dst in V3_FIELDS.items()})
            teams.append(trow)
    return pd.DataFrame(players), pd.DataFrame(teams), pd.DataFrame(people)
