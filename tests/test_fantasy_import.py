import openpyxl
import pytest

from conftest import FIXTURES
from elfantasy.fantasy_import import EXPECTED_COLUMNS, ExportFormatError, import_export, parse_export
from elfantasy.store import read_df

X = FIXTURES / "players_stats.xlsx"


def test_parse_real_export():
    e = parse_export(X)
    assert len(e.players) == 340 and len(e.coaches) == 20
    assert e.reference_matchdays == list(range(1, 12))
    v = e.players.set_index("fantasy_id").loc["3469"]
    assert (v["surname"], v["team"], v["price"], v["fpt"]) == ("Vezenkov", "OLY", 18.9, 24.5)
    k = e.coaches.set_index("team").loc["MTA"]
    assert k["fpt"] == -6.5 and k["loss_1_10"] == 0.3
    assert len(e.file_hash) == 64


def test_missing_column_rejected(tmp_path):
    wb = openpyxl.load_workbook(X)
    ws = wb.active
    ws.delete_cols(EXPECTED_COLUMNS.index("Quotation") + 1)
    wb.save(tmp_path / "bad.xlsx")
    with pytest.raises(ExportFormatError) as ei:
        parse_export(tmp_path / "bad.xlsx")
    assert ei.value.missing == ["Quotation"]


def test_missing_footer_rejected(tmp_path):
    wb = openpyxl.load_workbook(X)
    ws = wb.active
    ws.delete_rows(ws.max_row)
    wb.save(tmp_path / "nofooter.xlsx")
    with pytest.raises(ExportFormatError) as ei:
        parse_export(tmp_path / "nofooter.xlsx")
    assert ei.value.missing == ["Reference matchdays footer"]


def test_reimport_replaces_snapshot(conn):
    assert import_export(conn, X) == 11
    import_export(conn, X)
    assert read_df(conn, "select count(*) n from snapshots")["n"][0] == 1
    assert read_df(conn, "select count(*) n from fantasy_players")["n"][0] == 340
    assert read_df(conn, "select count(*) n from fantasy_coaches")["n"][0] == 20


def test_non_numeric_fantasy_id_kept_as_text():
    e = parse_export(X)
    llull = e.players.set_index("fantasy_id").loc["TGB"]
    assert (llull["surname"], llull["team"]) == ("Llull", "RMB")
