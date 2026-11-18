import json

from elfantasy.settings import Settings, load_settings


def test_defaults_when_missing(tmp_path):
    s = load_settings(tmp_path / "none.json")
    assert s == Settings() and s.season == "E2026"
    assert not hasattr(s, "history_seasons")


def test_reads_non_ascii_and_ignores_unknown_keys(tmp_path):
    p = tmp_path / "s.json"
    data = {"season": "E2025", "junk": "Παπαπέτρου", "history_seasons": ["E2023"], "boom": 20.0}
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert load_settings(p).season == "E2025"


def test_value_settings_defaults():
    s = Settings()
    assert (s.value_buy, s.value_sell, s.dip_min_avg, s.dip_drop) == (0.10, -0.10, 10.0, 0.3)
