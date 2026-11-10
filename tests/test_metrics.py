import json
import math

import pandas as pd
import pytest

from elfantasy.metrics import (effective_win_bonus, estimate_win_bonus, game_log, player_summary,
                               price_history, value_table)
from elfantasy.pir import BOX_COMPONENTS
from elfantasy.settings import Settings
from elfantasy.store import upsert_rows


def mk_log(code, pir, minutes, dnp=None):
    n = len(pir)
    df = pd.DataFrame({c: 0 for c in BOX_COMPONENTS}, index=range(n))
    df["pts"] = pir
    df["pir"] = pir
    df["player_code"] = code
    df["local_date"] = [f"2026-10-{d + 1:02d}" for d in range(n)]
    df["minutes"] = minutes
    df["dnp"] = dnp or [0] * n
    return df


def test_summary_form_and_consistency():
    log = mk_log("p1", pir=[10] * 5 + [20] * 5, minutes=[30] * 10)
    s = player_summary(log, Settings()).loc["p1"]
    assert s.pir_avg == 15 and s.pir_last5 == 20 and s.pir_last3 == 20 and s.form_trend == "up"
    assert s.pir_per30 == 15 and s.boom_rate == 0.5 and s.bust_rate == 0.0
    assert s.p20 == pytest.approx(10) and s.p80 == pytest.approx(20) and s.scoring == 15


def test_dnps_excluded_and_counted():
    s = player_summary(mk_log("p1", pir=[12, 0], minutes=[25, 0], dnp=[0, 1]), Settings()).loc["p1"]
    assert s.games == 1 and s.dnp_rate == 0.5 and s.pir_avg == 12


def test_only_dnps_gives_nan_row():
    s = player_summary(mk_log("p2", pir=[0], minutes=[0], dnp=[1]), Settings()).loc["p2"]
    assert s.games == 0 and math.isnan(s.pir_avg) and s.dnp_rate == 1.0


def test_negatives_breakdown():
    log = mk_log("p3", pir=[0], minutes=[20])
    log[["fga2", "fga3", "fta", "tov", "pf"]] = [3, 2, 1, 1, 2]   # 6 misses + 3
    assert player_summary(log, Settings()).loc["p3"].negatives == 9


def test_game_log_from_fixture(fixture_conn):
    log = game_log(fixture_conn, "E2026")
    assert len(log) > 200 and set(log["round"]) == {10}
    assert (log["pir"] == log["pir_official"]).all()
    g = log[log["game_code"] == 91]
    assert set(g["team_tv"]) == set(g["opp_tv"]) and len(set(g["team_tv"])) == 2
    assert set(g.groupby("team_tv")["won"].first()) == {0, 1}
    oly = log[log["team_tv"] == "OLY"]
    assert oly["position"].notna().all()


def test_value_table_and_price_history(fixture_conn):
    v = value_table(fixture_conn, 11).set_index("fantasy_id").loc["3469"]
    assert v.fpt_per_credit == pytest.approx(24.5 / 18.9)
    h = price_history(fixture_conn, "3469")
    assert list(h["matchday"]) == [11] and h["price"].iloc[0] == 18.9


def seed_players_with_gap(conn, n, bonus, reference=None, played_rounds=range(1, 11)):
    """Half the players on club A (wins 7 of 10), half on B (wins 3). fpt = mean pir + bonus*share."""
    reference = reference or list(played_rounds)
    rounds = list(range(1, max(reference) + 1))
    upsert_rows(conn, "teams", pd.DataFrame({"club_code": ["A", "B"], "tv_code": ["AAA", "BBB"], "name": ["a", "b"]}))
    games, box, fps, pmap = [], [], [], []
    for r in rounds:
        played = int(r in played_rounds)
        a_wins = r <= 7
        games.append({"season": "E2026", "game_code": r, "round": r, "phase": "RS",
                      "local_date": f"2026-10-{r:02d}T20:00:00", "home_club": "A", "away_club": "B",
                      "home_score": (80 if a_wins else 70) * played, "away_score": (70 if a_wins else 80) * played,
                      "played": played})
    for i in range(n):
        club = "A" if i % 2 == 0 else "B"
        share = (7 if club == "A" else 3) / len(played_rounds)
        pir = 10 + i
        for r in played_rounds:
            row = {c: 0 for c in BOX_COMPONENTS}
            row.update(season="E2026", game_code=r, player_code=f"{i:06d}", club_code=club, is_starter=1,
                       minutes=25.0, dnp=0, pts=pir, pir_official=pir)
            box.append(row)
        fps.append({"matchday": max(reference), "fantasy_id": str(i), "name": f"N{i}", "surname": f"S{i}",
                    "position": "Guard", "team": "AAA" if club == "A" else "BBB", "price": 10.0,
                    "fpt": pir + bonus * share})
        pmap.append({"fantasy_id": str(i), "player_code": f"{i:06d}", "method": "name"})
    upsert_rows(conn, "games", pd.DataFrame(games))
    upsert_rows(conn, "box_player", pd.DataFrame(box))
    upsert_rows(conn, "fantasy_players", pd.DataFrame(fps))
    upsert_rows(conn, "player_map", pd.DataFrame(pmap))
    upsert_rows(conn, "snapshots", pd.DataFrame([{"matchday": max(reference),
                                                  "reference_matchdays": json.dumps(reference),
                                                  "imported_at": "x", "file_hash": "h"}]))


def test_win_bonus_recovered(conn):
    seed_players_with_gap(conn, n=30, bonus=2.0)
    assert estimate_win_bonus(conn, "E2026", 10) == pytest.approx(2.0, abs=0.05)


def test_win_bonus_ignores_unplayed_reference_round(conn):
    seed_players_with_gap(conn, n=30, bonus=2.0, reference=list(range(1, 12)), played_rounds=range(1, 11))
    assert estimate_win_bonus(conn, "E2026", 11) == pytest.approx(2.0, abs=0.05)


def test_win_bonus_none_with_few_players(conn):
    seed_players_with_gap(conn, n=10, bonus=2.0)
    assert estimate_win_bonus(conn, "E2026", 10) is None


def test_effective_win_bonus_prefers_setting(conn):
    seed_players_with_gap(conn, n=30, bonus=2.0)
    assert effective_win_bonus(conn, Settings(win_bonus=1.0)) == 1.0
    assert effective_win_bonus(conn, Settings()) == pytest.approx(2.0, abs=0.05)
