import json

import pandas as pd
import pytest

from elfantasy.pir import BOX_COMPONENTS
from elfantasy.price_rule import PriceRule, fit_price_rule
from elfantasy.store import upsert_rows


def seed_two_snapshots(conn, k, a, c, d, n, mds=(11, 12)):
    """n players who played round mds[0] priced by the rule, plus 5 matched players who did not play."""
    prev, cur = mds
    upsert_rows(conn, "teams", pd.DataFrame({"club_code": ["A", "B"], "tv_code": ["AAA", "BBB"],
                                             "name": ["a", "b"]}))
    upsert_rows(conn, "games", pd.DataFrame([
        {"season": "E2026", "game_code": 1, "round": prev, "phase": "RS", "local_date": "2026-11-12T20:00:00",
         "home_club": "A", "away_club": "B", "home_score": 80, "away_score": 70, "played": 1},
        {"season": "E2026", "game_code": 2, "round": prev, "phase": "RS", "local_date": "2026-11-13T20:00:00",
         "home_club": "B", "away_club": "A", "home_score": 0, "away_score": 0, "played": 0}]))
    box, fps, pmap = [], [], []
    for i in range(n + 5):
        code, fid = f"P{i:03d}", str(1000 + i)
        price = 4.0 + (i * 7 % 17)
        played = i < n
        pir = float((i * 11) % 31)
        if played or i >= n + 3:          # the last two idle players have a DNP row
            row = dict.fromkeys(BOX_COMPONENTS, 0)
            row.update(season="E2026", game_code=1, player_code=code, club_code="A" if i % 2 else "B",
                       is_starter=0, minutes=25.0 if played else 0.0, dnp=0 if played else 1,
                       pts=pir if played else 0, pir_official=pir if played else 0)
            box.append(row)
        new = price + (k * (pir - (a * price + c)) if played else d)
        for md, p in ((prev, price), (cur, new)):
            fps.append({"matchday": md, "fantasy_id": fid, "name": "N", "surname": f"S{i}",
                        "position": "Guard", "team": "AAA", "price": p})
        pmap.append({"fantasy_id": fid, "player_code": code, "method": "name"})
    upsert_rows(conn, "box_player", pd.DataFrame(box))
    upsert_rows(conn, "fantasy_players", pd.DataFrame(fps))
    upsert_rows(conn, "player_map", pd.DataFrame(pmap))
    upsert_rows(conn, "snapshots", pd.DataFrame(
        [{"matchday": md, "reference_matchdays": json.dumps(list(range(1, md + 1))), "imported_at": "x",
          "file_hash": str(md)} for md in mds]))


def test_rule_arithmetic():
    r = PriceRule()
    assert r.break_even(4.8) == pytest.approx(4.472)
    assert r.change(20, 4.8) == pytest.approx(0.042 * (20 - 4.472))


def test_fit_recovers_known_rule(conn):
    seed_two_snapshots(conn, k=0.05, a=1.2, c=-0.5, d=-0.1, n=60)
    r = fit_price_rule(conn, "E2026")
    assert (r.source, r.n) == ("fitted", 60)
    assert r.k == pytest.approx(0.05, abs=1e-6) and r.a == pytest.approx(1.2, abs=1e-6)
    assert r.c == pytest.approx(-0.5, abs=1e-6) and r.d == pytest.approx(-0.1)
    assert r.r2 == pytest.approx(1.0)


def test_defaults_without_consecutive_snapshots(conn):
    seed_two_snapshots(conn, k=0.05, a=1.2, c=-0.5, d=-0.1, n=60, mds=(9, 12))
    assert fit_price_rule(conn, "E2026") == PriceRule()


def test_defaults_with_too_few_players(conn):
    seed_two_snapshots(conn, k=0.05, a=1.2, c=-0.5, d=-0.1, n=10)
    assert fit_price_rule(conn, "E2026").source == "default"
