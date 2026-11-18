"""Synthetic game logs shared by the xPIR and value tests."""
from __future__ import annotations

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
