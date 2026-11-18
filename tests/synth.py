"""Synthetic game logs shared by the xPIR and value tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from elfantasy.pir import BOX_COMPONENTS, pir_box


def _date(round_: int) -> str:
    return (pd.Timestamp("2026-10-01") + pd.Timedelta(days=7 * (round_ - 1))).strftime("%Y-%m-%dT20:00:00")


def make_log(players: dict[str, dict]) -> pd.DataFrame:
    """players: {code: {"position", "games": [{stat: n, ...}], optional "team", "opp"}}.

    Game i is round i + 1 unless the game dict sets "round". Minutes default to 20; a game dict may
    also set dnp, opp_tv, is_home. Points follow from the makes unless given.
    """
    rows = []
    for code, spec in players.items():
        for i, g in enumerate(spec["games"]):
            r = dict.fromkeys(BOX_COMPONENTS, 0)
            r.update(minutes=20.0, dnp=0, is_starter=1, is_home=1, won=0,
                     team_tv=spec.get("team", "AAA"), opp_tv=spec.get("opp", "BBB"))
            r.update(g)
            r.setdefault("round", i + 1)
            if "pts" not in g:
                r["pts"] = 2 * r["fgm2"] + 3 * r["fgm3"] + r["ftm"]
            r.update(season="E2026", player_code=code, position=spec["position"],
                     game_code=r["round"], local_date=_date(r["round"]))
            rows.append(r)
    log = pd.DataFrame(rows)
    log["pir"] = pir_box(log)
    return log.sort_values(["local_date", "game_code", "player_code"]).reset_index(drop=True)


def pir_games(pirs: list[float]) -> list[dict]:
    """Games whose PIR equals each value (assists for positive, turnovers for negative)."""
    return [{"ast": p} if p >= 0 else {"tov": -p} for p in pirs]


POSITION_RATES = {   # per-minute volumes by position, roughly this season's league rates
    "Guard": {"fga2": .14, "fga3": .16, "fd": .10, "oreb": .02, "dreb": .08, "ast": .14, "stl": .03,
              "blk": .005, "tov": .07, "blka": .01, "pf": .08},
    "Forward": {"fga2": .17, "fga3": .11, "fd": .09, "oreb": .05, "dreb": .13, "ast": .06, "stl": .03,
                "blk": .02, "tov": .05, "blka": .01, "pf": .10},
    "Center": {"fga2": .26, "fga3": .02, "fd": .14, "oreb": .11, "dreb": .19, "ast": .04, "stl": .02,
               "blk": .05, "tov": .06, "blka": .01, "pf": .13},
}


def synth_season(rounds: int, players: int, seed: int) -> pd.DataFrame:
    """A season of games for `players` players on players // 5 teams, drawn from fixed true rates.

    Each player has true per-minute volumes, shooting percentages and average minutes; each game
    draws minutes, Poisson volumes and binomial makes, so channel PIR is right by construction.
    """
    rng = np.random.default_rng(seed)
    n_teams = max(2, players // 5)
    teams = [f"T{i}" for i in range(n_teams)]
    spec = {}
    for i in range(players):
        pos = ("Guard", "Forward", "Center")[i % 3]
        spec[f"P{i:03d}"] = {
            "position": pos, "team": teams[i % n_teams], "min": rng.uniform(8, 32), "dnp": rng.uniform(0, .25),
            "rates": {s: r * rng.lognormal(0, .35) for s, r in POSITION_RATES[pos].items()},
            "p2": rng.uniform(.45, .65), "p3": rng.uniform(.28, .42), "ftp": rng.uniform(.6, .9),
            "ftr": rng.uniform(.7, 1.4), "games": []}
    for r in range(1, rounds + 1):
        order = list(rng.permutation(teams))
        opp = {}
        for a, b in zip(order[::2], order[1::2]):
            opp[a], opp[b] = (b, 1), (a, 0)
        for s in spec.values():
            o, home = opp[s["team"]]
            g = {"round": r, "opp_tv": o, "is_home": home}
            if rng.uniform() < s["dnp"]:
                g.update(dnp=1, minutes=0.0)
            else:
                m = float(np.clip(rng.normal(s["min"], 5), 2, 40))
                g["minutes"] = m
                g.update({k: int(rng.poisson(v * m)) for k, v in s["rates"].items()})
                g["fgm2"] = int(rng.binomial(g["fga2"], s["p2"]))
                g["fgm3"] = int(rng.binomial(g["fga3"], s["p3"]))
                g["fta"] = int(rng.poisson(s["ftr"] * g["fd"]))
                g["ftm"] = int(rng.binomial(g["fta"], s["ftp"]))
            s["games"].append(g)
    return make_log(spec)


def synth_poss(log: pd.DataFrame) -> pd.DataFrame:
    return log[["season", "game_code"]].drop_duplicates().assign(poss=70.0)


def seed_season_db(conn, log: pd.DataFrame, snapshot_rounds: list[int]) -> None:
    """Write a synth_season log into the DB as games, box scores and fantasy exports.

    Every player is matched (fantasy id "F" + code) and priced 4-13 credits in each export.
    """
    from elfantasy.store import upsert_rows

    log = log.copy()
    teams = sorted(set(log["team_tv"]))
    home = log[log["is_home"] == 1][["round", "team_tv", "opp_tv"]].drop_duplicates()
    home["game_code"] = home["round"] * 100 + home["team_tv"].map(teams.index)
    code = {**{(r, h): g for r, h, g in home[["round", "team_tv", "game_code"]].itertuples(index=False)},
            **{(r, a): g for r, a, g in home[["round", "opp_tv", "game_code"]].itertuples(index=False)}}
    log["game_code"] = [code[(r, t)] for r, t in zip(log["round"], log["team_tv"])]
    pts = log.groupby(["game_code", "team_tv"])["pts"].sum()
    upsert_rows(conn, "teams", pd.DataFrame({"club_code": teams, "tv_code": teams, "name": teams}))
    upsert_rows(conn, "games", pd.DataFrame({
        "season": "E2026", "game_code": home["game_code"], "round": home["round"], "phase": "RS",
        "local_date": home["round"].map(_date), "home_club": home["team_tv"], "away_club": home["opp_tv"],
        "home_score": [pts.get((g, t), 0) for g, t in zip(home["game_code"], home["team_tv"])],
        "away_score": [pts.get((g, t), 0) for g, t in zip(home["game_code"], home["opp_tv"])],
        "played": 1}))
    box = log.assign(club_code=log["team_tv"], pir_official=log["pir"])
    upsert_rows(conn, "box_player", box[["season", "game_code", "player_code", "club_code", "is_starter",
                                         "minutes", "dnp", *BOX_COMPONENTS, "pir_official"]])
    upsert_rows(conn, "box_team", box.groupby(["season", "game_code", "club_code"], as_index=False)
                [BOX_COMPONENTS].sum())
    players = log.drop_duplicates("player_code")[["player_code", "position", "team_tv"]].reset_index(drop=True)
    upsert_rows(conn, "player_map", pd.DataFrame({"fantasy_id": "F" + players["player_code"],
                                                  "player_code": players["player_code"], "method": "name"}))
    for md in snapshot_rounds:
        upsert_rows(conn, "fantasy_players", pd.DataFrame({
            "matchday": md, "fantasy_id": "F" + players["player_code"], "name": "N",
            "surname": players["player_code"], "position": players["position"], "team": players["team_tv"],
            "price": 4.0 + players.index % 10}))
    upsert_rows(conn, "snapshots", pd.DataFrame({"matchday": snapshot_rounds, "reference_matchdays": "[]",
                                                 "imported_at": "x", "file_hash": "h"}))
