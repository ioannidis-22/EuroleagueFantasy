import json

from elfantasy.settings import Settings, load_settings, save_settings


def test_defaults_when_missing(tmp_path):
    s = load_settings(tmp_path / "none.json")
    assert s.season == "E2026" and s.boom == 20.0 and s.win_bonus is None
    assert s.history_seasons == ("E2023", "E2024", "E2025")


def test_roundtrip_non_ascii_and_unknown_keys(tmp_path):
    p = tmp_path / "s.json"
    save_settings(Settings(win_bonus=1.5), p)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["junk"] = "Παπαπέτρου"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    s = load_settings(p)
    assert s.win_bonus == 1.5 and s.history_seasons == ("E2023", "E2024", "E2025")
