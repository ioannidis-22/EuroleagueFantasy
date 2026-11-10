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
