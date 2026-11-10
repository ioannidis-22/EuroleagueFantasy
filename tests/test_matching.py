import json

import pandas as pd
import pytest

from elfantasy.matching import match_players, normalize_name
from elfantasy.store import read_df, replace_rows, upsert_rows

TEAMS = pd.DataFrame({"club_code": ["OLY", "PAN", "MAD", "IST"],
                      "tv_code": ["OLY", "PAO", "RMB", "EFS"],
                      "name": ["Olympiacos", "Panathinaikos", "Real Madrid", "Anadolu Efes"]})


def seed(conn, fantasy, el):
    replace_rows(conn, "snapshots", pd.DataFrame([{"matchday": 11, "reference_matchdays": "[11]",
                                                   "imported_at": "x", "file_hash": "h"}]), where={})
    upsert_rows(conn, "teams", TEAMS)
    upsert_rows(conn, "fantasy_players", pd.DataFrame(
        [{"matchday": 11, "fantasy_id": f, "name": n, "surname": s, "team": t, "position": "Guard"}
         for f, n, s, t in fantasy]))
    upsert_rows(conn, "el_players", pd.DataFrame(
        [{"season": "E2026", "player_code": c, "name": n, "club_code": club, "position": "Guard"}
         for c, n, club in el]))


def mapped(conn, fid):
    m = read_df(conn, "select player_code, method from player_map where fantasy_id = ?", (fid,))
    return None if m.empty else tuple(m.iloc[0])


@pytest.fixture
def NO(tmp_path):
    return tmp_path / "none.json"


def test_normalize():
    assert normalize_name("Šarūnas Jasikevičius") == "sarunas jasikevicius"
    assert normalize_name("Đorđević, T.J.") == "dordevic t j"
    assert normalize_name("O'Neale-Smith") == "o neale smith"


def test_surname_within_team(conn, NO):
    seed(conn, [("3469", "Sasha", "Vezenkov", "OLY")], [("001234", "VEZENKOV, ALEKSANDAR", "OLY")])
    match_players(conn, "E2026", NO)
    assert mapped(conn, "3469") == ("001234", "surname")


def test_full_name_with_accents(conn, NO):
    seed(conn, [("5", "Dzanan", "Musa", "RMB")], [("000555", "MUSA, DŽANAN", "MAD")])
    match_players(conn, "E2026", NO)
    assert mapped(conn, "5") == ("000555", "name")


def test_fuzzy_within_team(conn, NO):
    seed(conn, [("8", "Kostas", "Sloukas", "PAO")],
         [("000801", "SLOUKAS, KONSTANTINOS", "PAN"), ("000802", "SLOUKAS, IOANNIS", "PAN")])
    match_players(conn, "E2026", NO)
    assert mapped(conn, "8") == ("000801", "fuzzy")


def test_shared_surname_not_guessed(conn, NO):
    seed(conn, [("7", "Bob", "Peters", "OLY")],
         [("000001", "PETERS, ALEC", "OLY"), ("000002", "PETERS, JOHN", "OLY")])
    r = match_players(conn, "E2026", NO)
    assert mapped(conn, "7") is None and list(r.unmatched["fantasy_id"]) == ["7"]


def test_override_wins_and_non_ascii_file(conn, tmp_path):
    seed(conn, [("3469", "Sasha", "Vezenkov", "OLY")], [("001234", "VEZENKOV, ALEKSANDAR", "OLY")])
    p = tmp_path / "o.json"
    p.write_text(json.dumps({"3469": "009999", "_note": "Βεζένκοφ"}, ensure_ascii=False), encoding="utf-8")
    r = match_players(conn, "E2026", p)
    assert mapped(conn, "3469") == ("009999", "override") and r.matched == 1


def test_transfer_matched_across_teams(conn, NO):
    seed(conn, [("77", "Kendrick", "Nunn", "PAO")], [("000077", "NUNN, KENDRICK", "MAD")])
    match_players(conn, "E2026", NO)
    assert mapped(conn, "77") == ("000077", "name_any_team")


def test_uses_latest_snapshot_only(conn, NO):
    seed(conn, [("1", "Old", "Player", "OLY")], [("000111", "PLAYER, OLD", "OLY")])
    upsert_rows(conn, "snapshots", pd.DataFrame([{"matchday": 12, "reference_matchdays": "[12]",
                                                  "imported_at": "y", "file_hash": "h2"}]))
    upsert_rows(conn, "fantasy_players", pd.DataFrame([{"matchday": 12, "fantasy_id": "2", "name": "New",
                                                        "surname": "Guy", "team": "OLY", "position": "Guard"}]))
    r = match_players(conn, "E2026", NO)
    assert mapped(conn, "1") is None and list(r.unmatched["fantasy_id"]) == ["2"]


def test_unmatched_players_reads_current_state(conn, NO):
    from elfantasy.matching import unmatched_players
    seed(conn, [("3469", "Sasha", "Vezenkov", "OLY"), ("9", "Nobody", "Here", "OLY")],
         [("001234", "VEZENKOV, ALEKSANDAR", "OLY")])
    match_players(conn, "E2026", NO)
    assert list(unmatched_players(conn)["fantasy_id"]) == ["9"]


def test_save_override_merges(tmp_path):
    from elfantasy.matching import save_override
    p = tmp_path / "o.json"
    save_override(p, "1", "000001"); save_override(p, "TGB", "000002")
    assert json.loads(p.read_text(encoding="utf-8")) == {"1": "000001", "TGB": "000002"}
