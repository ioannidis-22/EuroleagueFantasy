import pandas as pd
import pytest

from elfantasy.pir import fpt, pir_box, pir_export


def test_pir_box_matches_official_larkin():
    # Larkin, E2025 game 1: official Valuation 12
    row = dict(pts=14, fgm2=5, fga2=8, fgm3=0, fga3=4, ftm=4, fta=6, oreb=1, dreb=3, ast=5,
               stl=0, tov=2, blk=0, blka=1, pf=3, fd=4)
    assert pir_box(pd.DataFrame([row])).iloc[0] == 12


def test_pir_export_vezenkov():
    row = {"pts": 19.1, "reb": 6, "ast": 1, "stl": 0.6, "blk": 0, "fd": 3.9, "tov": 1, "blka": 0.2,
           "pf": 0.7, "fg_missed": 5.2, "ft_missed": 0.6}
    assert pir_export(pd.DataFrame([row])).iloc[0] == pytest.approx(22.9)


def test_fpt_adds_bonus_only_on_wins():
    assert list(fpt(pd.Series([10.0, 10.0]), pd.Series([1, 0]), 2.0)) == [12.0, 10.0]
