import pandas as pd

from elfantasy.slots import assign_slots, next_round, team_slots


def games_df(round_, dates):
    return pd.DataFrame({"season": "E2026", "game_code": range(1, len(dates) + 1), "round": round_,
                         "local_date": [f"{d}T20:00:00" for d in dates]})


def test_slots_three_dates():
    g = games_df(4, ["2026-10-07", "2026-10-08", "2026-10-09", "2026-10-08"])
    assert list(assign_slots(g)["slot"]) == [1, 2, 3, 2]


def test_two_dates_round():
    assert set(assign_slots(games_df(1, ["2026-09-24", "2026-09-25"]))["slot"]) == {1, 2}


def test_slots_are_per_round():
    g = pd.concat([games_df(1, ["2026-09-24"]), games_df(2, ["2026-09-29", "2026-09-30"])])
    assert list(assign_slots(g)["slot"]) == [1, 1, 2]


def test_team_slots_and_next_round(fixture_conn):
    assert next_round(fixture_conn, "E2026") == 11
    ts = team_slots(fixture_conn, "E2026", 11)
    assert len(ts) == 20 and set(ts["slot"]) == {1, 2, 3}
    efs = ts[ts.tv_code == "EFS"].iloc[0]
    assert efs["opp_tv"] in set(ts.tv_code) and efs["opp_tv"] != "EFS"
    assert ts["is_home"].sum() == 10


def seed_games(conn, spec):
    """spec: list of (round, date, played)."""
    from elfantasy.store import upsert_rows
    upsert_rows(conn, "games", pd.DataFrame(
        [{"season": "E2026", "game_code": i, "round": r, "phase": "RS", "local_date": f"{d}T20:00:00",
          "home_club": "A", "away_club": "B", "home_score": 80 * p, "away_score": 70 * p, "played": p}
         for i, (r, d, p) in enumerate(spec, 1)]))


TODAY = "2026-11-10"


def test_next_round_skips_postponed_game(conn):
    seed_games(conn, [(5, "2026-10-14", 1), (5, "2026-10-14", 0),       # postponed, date passed
                      (6, "2026-10-21", 1), (7, "2026-11-12", 0)])
    assert next_round(conn, "E2026", today=TODAY) == 7


def test_next_round_ignores_postponed_game_rescheduled_later(conn):
    seed_games(conn, [(5, "2026-12-20", 0), (5, "2026-10-14", 1),       # moved to December
                      (6, "2026-10-21", 1), (7, "2026-11-12", 0)])
    assert next_round(conn, "E2026", today=TODAY) == 7


def test_next_round_postponed_in_latest_played_round(conn):
    seed_games(conn, [(10, "2026-11-05", 1), (10, "2026-11-05", 0), (11, "2026-11-12", 0)])
    assert next_round(conn, "E2026", today=TODAY) == 11


def test_next_round_mid_round_stays(conn):
    seed_games(conn, [(11, "2026-11-11", 1), (11, "2026-11-12", 0), (12, "2026-11-17", 0)])
    assert next_round(conn, "E2026", today="2026-11-12") == 11
