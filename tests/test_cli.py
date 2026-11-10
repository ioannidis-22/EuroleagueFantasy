from conftest import FIXTURES
from elfantasy.__main__ import main
from elfantasy.store import connect, read_df


def test_cli_import(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ELFANTASY_DATA", str(tmp_path))
    assert main(["import", str(FIXTURES / "players_stats.xlsx")]) == 0
    assert "matchday 11" in capsys.readouterr().out.lower()
    conn = connect(tmp_path / "elfantasy.db")
    assert read_df(conn, "select matchday from snapshots")["matchday"].tolist() == [11]
