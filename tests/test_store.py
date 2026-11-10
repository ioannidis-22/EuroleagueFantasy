import pandas as pd

from elfantasy.store import read_df, replace_rows, upsert_rows


def test_schema_created(conn):
    names = set(read_df(conn, "select name from sqlite_master where type='table'")["name"])
    assert {"snapshots", "fantasy_players", "fantasy_coaches", "teams", "games",
            "box_player", "box_team", "el_players", "player_map"} <= names


def test_replace_rows_only_touches_where(conn):
    df = pd.DataFrame({"club_code": ["IST", "PAN"], "tv_code": ["EFS", "PAO"], "name": ["Efes", "Pana"]})
    upsert_rows(conn, "teams", df)
    replace_rows(conn, "teams", df.iloc[[0]].assign(name="Anadolu"), where={"club_code": "IST"})
    t = read_df(conn, "select * from teams order by club_code")
    assert list(t["name"]) == ["Anadolu", "Pana"]


def test_replace_rows_empty_where_deletes_all(conn):
    df = pd.DataFrame({"club_code": ["IST", "PAN"], "tv_code": ["EFS", "PAO"], "name": ["Efes", "Pana"]})
    upsert_rows(conn, "teams", df)
    replace_rows(conn, "teams", df.iloc[[1]], where={})
    assert list(read_df(conn, "select club_code from teams")["club_code"]) == ["PAN"]
