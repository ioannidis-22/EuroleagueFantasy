import json

import pytest

from conftest import FIXTURES
from elfantasy.el_parse import parse_boxscore, parse_games, parse_people, parse_teams
from elfantasy.pir import pir_box


def load(n):
    return json.loads((FIXTURES / n).read_text(encoding="utf-8"))


def test_boxscore_players_and_dnp():
    p, t = parse_boxscore(load("box_E2025_1.json"), "E2025", 1)
    lar = p.set_index("player_code").loc["007200"]
    assert lar["minutes"] == pytest.approx(33 + 21 / 60) and lar["pir_official"] == 12
    assert lar["is_starter"] == 1 and lar["club_code"] == "IST" and lar["dnp"] == 0
    assert pir_box(p.set_index("player_code").loc[["007200"]]).iloc[0] == 12
    beau = p.set_index("player_code").loc["006590"]
    assert beau["dnp"] == 1 and beau["minutes"] == 0.0
    assert set(t["club_code"]) == {"IST", "TEL"}
    assert (p["season"] == "E2025").all() and (p["game_code"] == 1).all()


def test_official_pir_equals_formula_for_every_player():
    files = ["box_E2025_1.json", "box_E2026_1.json"] + [f"box_E2026_{n}.json" for n in range(91, 101)]
    for f in files:
        p, _ = parse_boxscore(load(f), "X", 1)
        bad = p[pir_box(p) != p["pir_official"]]
        assert bad.empty, (f, bad[["player_code", "pir_official"]].to_dict("records"))


def test_team_totals():
    _, t = parse_boxscore(load("box_E2026_1.json"), "E2026", 1)
    assert len(t) == 2 and 77 in set(t["pts"])


def test_games_and_teams():
    g = parse_games(load("games_E2026_r10_11.json"), "E2026")
    assert len(g) == 20 and g["played"].sum() == 10
    assert set(g["round"]) == {10, 11} and set(g["phase"]) == {"RS"}
    t = parse_teams(load("games_E2026_r10_11.json"))
    assert len(t) == 20 and ("IST", "EFS") in set(zip(t.club_code, t.tv_code))


def test_people_players_only():
    pe = parse_people(load("people_E2026_OLY.json"), "E2026")
    assert len(pe) == 18 and set(pe["position"]) == {"Guard", "Forward", "Center"}
    assert set(pe["club_code"]) == {"OLY"}
