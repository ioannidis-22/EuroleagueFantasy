from elfantasy.metrics import game_log


def test_game_log_from_fixture(fixture_conn):
    log = game_log(fixture_conn, "E2026")
    assert len(log) > 200 and set(log["round"]) == {10}
    assert (log["pir"] == log["pir_official"]).all()
    g = log[log["game_code"] == 91]
    assert set(g["team_tv"]) == set(g["opp_tv"]) and len(set(g["team_tv"])) == 2
    assert set(g.groupby("team_tv")["won"].first()) == {0, 1}
    oly = log[log["team_tv"] == "OLY"]
    assert oly["position"].notna().all()
