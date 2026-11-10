from conftest import FIXTURES
from elfantasy.__main__ import main
from elfantasy.store import connect, read_df


def test_cli_import(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ELFANTASY_DATA", str(tmp_path))
    assert main(["import", str(FIXTURES / "players_stats.xlsx")]) == 0
    assert "matchday 11" in capsys.readouterr().out.lower()
    conn = connect(tmp_path / "elfantasy.db")
    assert read_df(conn, "select matchday from snapshots")["matchday"].tolist() == [11]


def test_cli_refresh_fetches_current_season_only(tmp_path, monkeypatch):
    from elfantasy import __main__ as cli
    from elfantasy.refresh import RefreshReport
    monkeypatch.setenv("ELFANTASY_DATA", str(tmp_path))
    calls = []
    monkeypatch.setattr(cli, "refresh_season",
                        lambda conn, client, season, progress=None, source="live":
                        calls.append((season, source)) or RefreshReport(season))
    assert main(["refresh"]) == 0
    assert calls == [("E2026", "live")]
