# Plan 1 — Data Foundation & Analytics App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local Streamlit app that imports the fantasy export, downloads Euroleague box scores/fixtures, and shows buy/sell form, consistency, value, T-slots and Defense-vs-Position analysis.

**Architecture:** A `src/elfantasy` Python package of small pure-logic modules (import, parse, match, metrics, DvP, slots) over one SQLite file; a thin HTTP client with an on-disk cache; Streamlit pages in `app/` that only call package functions. Plan 2 (projection engine, captain picker, model page) and Plan 3 (squad & T-slot strategy) build on this.

**Tech Stack:** Python 3.12, pandas, numpy, requests, openpyxl, streamlit, plotly, SQLite (stdlib), pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-euroleague-fantasy-pir-design.md` (this plan covers spec §2, §3, §4, §5, §6, §9 pages 1–4, 7, 9, §10, §11, §12 minus projection/squad tests).

## Global Constraints

- Python 3.12 in a project venv at `.venv`; run tools as `.venv/Scripts/python -m ...`.
- **Every text file open/read/write passes `encoding="utf-8"`** — the PC's default code page is cp1253 (Greek); default decoding crashes on API JSON.
- Runtime deps only: `pandas`, `numpy`, `requests`, `openpyxl`, `streamlit`, `plotly`; dev: `pytest`. (Plan 2 adds `scikit-learn`.)
- No calculation logic in `app/`; pages call `elfantasy` functions only.
- Positions are exactly `"Guard"`, `"Forward"`, `"Center"`.
- Teams: the fantasy/TV code (`tv_code`, e.g. `EFS`, `PAO`, `RMB`) is the canonical team id everywhere in the UI and analytics. Box scores use the Euroleague club code (`IST`, `PAN`, `MAD`); map via the `teams` table.
- Seasons: current `"E2026"`; history `"E2023"`, `"E2024"`, `"E2025"`. Competition `E`, regular season phase `RS` plus any later phases.
- API: games `https://api-live.euroleague.net/v2/competitions/E/seasons/{season}/games`; rosters `https://api-live.euroleague.net/v2/competitions/E/seasons/{season}/clubs/{club_code}/people`; box score `https://live.euroleague.net/api/Boxscore?gamecode={n}&seasoncode={season}`.
- At least 0.3 s between HTTP requests; a final game's box score is cached on disk and never re-fetched.
- Only games with `played == true` are stored as results; unplayed games are fixtures only.
- Snapshot matchday = `max(reference_matchdays)` from the export footer; re-import of the same matchday replaces it. "Latest snapshot" = highest matchday, not latest import time.
- Local data lives in `data/` (git-ignored): `elfantasy.db`, `cache/`, `imports/`, `player_overrides.json`, `settings.json`.
- PIR = PTS + OREB + DREB + AST + STL + BLK + FD − (FGA2−FGM2) − (FGA3−FGM3) − (FTA−FTM) − TOV − BLKA − PF.

## Review Focus

1. **Export lists a matchday not yet played** (today's file says matchdays 1–11 while only rounds 1–10 are final) → import keeps the list as given; win-bonus estimate uses only rounds with final games; "next round" comes from fixtures, not the export. Test in Task 9.
2. **Name mismatches between export and API** ("Sasha Vezenkov" vs `VEZENKOV, ALEKSANDAR`, accents, two players sharing a surname on one team, mid-season transfers) → surname-within-team, fuzzy, cross-team and override paths; unmatched players are listed, never dropped. Tests in Task 7.
3. **Non-ASCII text on a cp1253 machine** (Greek/Serbian/Lithuanian names in API JSON, overrides and settings files) → round-trips intact. Tests in Tasks 1 and 5.
4. **Network failure mid-refresh** (timeout/5xx on one box score) → other games stored, the failed one reported and fetched on the next refresh, no half-written game. Test in Task 6.
5. **Players with no games yet / teams with few games** (new signings, round 1) → summary rows with NaN metrics instead of crashes; DvP shrinks to league average. Tests in Tasks 9 and 10.

---

## File Structure

```
pyproject.toml                 package metadata + deps, pytest config
.gitignore                     .venv/, data/, __pycache__/
run_app.bat                    starts the app (Task 15)
README.md                      setup + round workflow (Task 15)
src/elfantasy/
  __init__.py
  __main__.py                  CLI: refresh / import (Task 6)
  settings.py                  Settings dataclass, load/save JSON
  store.py                     SQLite schema + read/write helpers
  pir.py                       PIR / FPT formulas
  fantasy_import.py            export parsing, validation, snapshot storage
  el_parse.py                  pure JSON → DataFrame parsing of API payloads
  el_client.py                 HTTP + disk cache + retries
  refresh.py                   orchestrates client → parse → store
  matching.py                  fantasy ↔ Euroleague player linking
  slots.py                     T-slot assignment
  metrics.py                   game log, player summary, value, win bonus
  dvp.py                       Defense vs Position + fixture difficulty
app/
  Home.py                      Round dashboard
  data_access.py               cached loaders shared by pages
  pages/1_Players.py  2_Player.py  3_Compare.py  4_Opponents.py  5_Data.py
tests/
  fixtures/                    real export + trimmed API JSON
  conftest.py                  shared fixtures (temp DB, loaded fixture DB)
  test_*.py
```

---

### Task 1: Project scaffold, settings and SQLite store

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/elfantasy/__init__.py`, `src/elfantasy/settings.py`, `src/elfantasy/store.py`, `tests/conftest.py`
- Test: `tests/test_settings.py`, `tests/test_store.py`

**Interfaces:**
- Produces:
  - `Settings` dataclass: `season="E2026"`, `history_seasons=("E2023","E2024","E2025")`, `boom=20.0`, `bust=5.0`, `form_threshold=2.0`, `win_bonus: float | None = None`, `dvp_shrink_minutes=400.0`, `api_delay_s=0.3`.
  - `load_settings(path: Path) -> Settings` (missing file → defaults; unknown keys ignored), `save_settings(s: Settings, path: Path) -> None`.
  - `connect(db_path: Path) -> sqlite3.Connection` — creates all tables if missing.
  - `read_df(conn, sql: str, params: tuple = ()) -> pd.DataFrame`
  - `replace_rows(conn, table: str, df: pd.DataFrame, where: dict[str, object] | None) -> None` — in one transaction: if `where` is a dict, delete rows where every `key = value` holds (`{}` deletes all rows); if `None`, delete nothing; then insert `df`.
  - `upsert_rows(conn, table: str, df: pd.DataFrame) -> None` — `INSERT OR REPLACE`.
  - Tables and primary keys:
    - `snapshots(matchday PK, reference_matchdays TEXT json, imported_at TEXT, file_hash TEXT)`
    - `fantasy_players(matchday, fantasy_id, name, surname, position, team, price, plus, fpt, pts, reb, ast, stl, tov, blk, blka, fd, pf, fg_missed, ft_missed; PK(matchday, fantasy_id))`
    - `fantasy_coaches(matchday, name, surname, team, price, plus, fpt, win_1_10, win_11_20, win_20, win_ot, loss_1_10, loss_11_20, loss_20, loss_ot; PK(matchday, team))`
    - `teams(club_code PK, tv_code UNIQUE, name)`
    - `games(season, game_code, round, phase, local_date TEXT, utc_date TEXT, home_club, away_club, home_score, away_score, played INTEGER; PK(season, game_code))`
    - `box_player(season, game_code, player_code, club_code, is_starter, minutes REAL, dnp, pts, fgm2, fga2, fgm3, fga3, ftm, fta, oreb, dreb, ast, stl, tov, blk, blka, pf, fd, pir_official; PK(season, game_code, player_code))`
    - `box_team(season, game_code, club_code, pts, fgm2, fga2, fgm3, fga3, ftm, fta, oreb, dreb, ast, stl, tov, blk, blka, pf, fd; PK(season, game_code, club_code))`
    - `el_players(season, player_code, club_code, name, position; PK(season, player_code, club_code))`
    - `player_map(fantasy_id PK, player_code, method TEXT)`
  - `tests/conftest.py`: fixture `conn` → `connect(tmp_path / "t.db")`; `FIXTURES = Path(__file__).parent / "fixtures"`.

- [ ] **Step 1: Create the venv and project files.** `pyproject.toml` with `[project] name="elfantasy"`, `requires-python=">=3.12"`, the runtime deps, `[project.optional-dependencies] dev=["pytest"]`, setuptools `src` layout, `[tool.pytest.ini_options] testpaths=["tests"]`. `.gitignore`: `.venv/`, `data/`, `__pycache__/`, `*.egg-info/`.

Run: `python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"`
Expected: installs without errors.

- [ ] **Step 2: Write failing tests**

```python
# tests/test_settings.py
def test_defaults_when_missing(tmp_path):
    s = load_settings(tmp_path / "none.json")
    assert s.season == "E2026" and s.boom == 20.0 and s.win_bonus is None

def test_roundtrip_non_ascii_and_unknown_keys(tmp_path):
    p = tmp_path / "s.json"
    save_settings(Settings(win_bonus=1.5), p)
    data = json.loads(p.read_text(encoding="utf-8")); data["junk"] = "Παπαπέτρου"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert load_settings(p).win_bonus == 1.5

# tests/test_store.py
def test_schema_created(conn):
    names = set(read_df(conn, "select name from sqlite_master where type='table'")["name"])
    assert {"snapshots","fantasy_players","fantasy_coaches","teams","games",
            "box_player","box_team","el_players","player_map"} <= names

def test_replace_rows_only_touches_where(conn):
    df = pd.DataFrame({"club_code":["IST","PAN"],"tv_code":["EFS","PAO"],"name":["Efes","Pana"]})
    upsert_rows(conn, "teams", df)
    replace_rows(conn, "teams", df.iloc[[0]].assign(name="Anadolu"), where={"club_code":"IST"})
    t = read_df(conn, "select * from teams order by club_code")
    assert list(t["name"]) == ["Anadolu", "Pana"]
```

- [ ] **Step 3: Run** `.venv/Scripts/python -m pytest tests/test_settings.py tests/test_store.py -v` — Expected: FAIL (import errors).
- [ ] **Step 4: Implement** `settings.py` and `store.py` per the Interfaces (schema as one `CREATE TABLE IF NOT EXISTS` script).
- [ ] **Step 5: Run tests** — Expected: PASS.
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: project scaffold, settings and SQLite store"`

---

### Task 2: PIR and FPT formulas

**Files:** Create `src/elfantasy/pir.py`; Test `tests/test_pir.py`

**Interfaces:**
- Produces:
  - `BOX_COMPONENTS = ["pts","fgm2","fga2","fgm3","fga3","ftm","fta","oreb","dreb","ast","stl","tov","blk","blka","pf","fd"]`
  - `pir_box(df: pd.DataFrame) -> pd.Series` (box-score columns, formula in Global Constraints)
  - `pir_export(df: pd.DataFrame) -> pd.Series` = `pts+reb+ast+stl+blk+fd − tov − blka − pf − fg_missed − ft_missed`
  - `fpt(pir: pd.Series, won: pd.Series, win_bonus: float) -> pd.Series` = `pir + win_bonus * won` (won is 0/1)

- [ ] **Step 1: Failing tests**

```python
def test_pir_box_matches_official_larkin():
    # Larkin, E2025 game 1: official Valuation 12
    row = dict(pts=14,fgm2=5,fga2=8,fgm3=0,fga3=4,ftm=4,fta=6,oreb=1,dreb=3,ast=5,
               stl=0,tov=2,blk=0,blka=1,pf=3,fd=4)
    assert pir_box(pd.DataFrame([row])).iloc[0] == 12

def test_pir_export_vezenkov():
    row = {"pts":19.1,"reb":6,"ast":1,"stl":0.6,"blk":0,"fd":3.9,"tov":1,"blka":0.2,
           "pf":0.7,"fg_missed":5.2,"ft_missed":0.6}
    assert pir_export(pd.DataFrame([row])).iloc[0] == pytest.approx(22.9)

def test_fpt_adds_bonus_only_on_wins():
    assert list(fpt(pd.Series([10.0, 10.0]), pd.Series([1, 0]), 2.0)) == [12.0, 10.0]
```

- [ ] **Step 2: Run** `pytest tests/test_pir.py -v` — FAIL.
- [ ] **Step 3: Implement** `pir.py`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: PIR and FPT formulas`

---

### Task 3: Fantasy export importer

**Files:** Create `src/elfantasy/fantasy_import.py`, `tests/fixtures/players_stats.xlsx` (copy of `C:\Users\GIORGO~1.IOA\AppData\Local\Temp\claude\709f4e1f53051a69\910ac168-1501-41f0-b465-76a384a3ee06\scratchpad\players_stats_zip\players_stats.xlsx`); Test `tests/test_fantasy_import.py`

**Interfaces:**
- Consumes: `store.connect/replace_rows/upsert_rows/read_df`.
- Produces:
  - `EXPECTED_COLUMNS: list[str]` — the 28 export headers exactly as in spec §2.1.
  - `class ExportFormatError(ValueError)` with attributes `missing: list[str]`, `unexpected: list[str]`.
  - `@dataclass FantasyExport: players: pd.DataFrame; coaches: pd.DataFrame; reference_matchdays: list[int]; file_hash: str` (sha256 hex of file bytes). Column names are the snake_case table columns of Task 1 (`Quotation→price`, `Plus→plus`, `FPT→fpt`, `Fg missed→fg_missed`, `Win 1-10→win_1_10`, …, `Loss ot→loss_ot`; `ID→fantasy_id` int for players).
  - `parse_export(path: Path) -> FantasyExport` — rows with `Position == "Head Coach"` are coaches; `"-"` → NaN; footer row starting `Reference matchdays:` parsed to ints; missing footer → `ExportFormatError` with `missing=["Reference matchdays footer"]`.
  - `import_export(conn, path: Path) -> int` — returns matchday; replaces that matchday's rows in `snapshots`, `fantasy_players`, `fantasy_coaches`.

- [ ] **Step 1: Failing tests**

```python
X = FIXTURES / "players_stats.xlsx"

def test_parse_real_export():
    e = parse_export(X)
    assert len(e.players) == 340 and len(e.coaches) == 20
    assert e.reference_matchdays == list(range(1, 12))
    v = e.players.set_index("fantasy_id").loc[3469]
    assert (v["surname"], v["team"], v["price"], v["fpt"]) == ("Vezenkov", "OLY", 18.9, 24.5)
    k = e.coaches.set_index("team").loc["MTA"]
    assert k["fpt"] == -6.5 and k["loss_1_10"] == 0.3

def test_missing_column_rejected(tmp_path):
    wb = openpyxl.load_workbook(X); ws = wb.active
    ws.delete_cols(EXPECTED_COLUMNS.index("Quotation") + 1); wb.save(tmp_path / "bad.xlsx")
    with pytest.raises(ExportFormatError) as ei:
        parse_export(tmp_path / "bad.xlsx")
    assert ei.value.missing == ["Quotation"]

def test_reimport_replaces_snapshot(conn):
    assert import_export(conn, X) == 11
    import_export(conn, X)
    assert read_df(conn, "select count(*) n from snapshots")["n"][0] == 1
    assert read_df(conn, "select count(*) n from fantasy_players")["n"][0] == 340
```

- [ ] **Step 2: Run** `pytest tests/test_fantasy_import.py -v` — FAIL.
- [ ] **Step 3: Implement** `fantasy_import.py` (read with `openpyxl` `read_only=True, data_only=True`; header = first row; validate set equality with `EXPECTED_COLUMNS`).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: fantasy export importer with validation`

---

### Task 4: Euroleague payload parsing (pure)

**Files:** Create `src/elfantasy/el_parse.py`; fixtures in `tests/fixtures/`: `box_E2025_1.json` (from scratchpad `api/box.json`), `box_E2026_1.json` (`api/box26.json`), `people_E2026_OLY.json` (`api/people.json`), the ten round-10 box scores `box_E2026_{91..100}.json` (`api/box_E2026_{n}.json`, game codes 91–100), `games_E2026_r10_11.json` (from `api/games.json`, keep only `data` entries with `phaseType.code=="RS"` and `round in (10, 11)`, same `{"data": [...]}` shape). Scratchpad dir: `C:\Users\GIORGO~1.IOA\AppData\Local\Temp\claude\709f4e1f53051a69\910ac168-1501-41f0-b465-76a384a3ee06\scratchpad\api\`. Test `tests/test_el_parse.py`

**Interfaces:**
- Produces:
  - `parse_games(payload: dict, season: str) -> pd.DataFrame` — columns of `games` table; `local_date` = `localDate`, `utc_date` = `utcDate`, `home_club`/`away_club` = `local.club.code`/`road.club.code`, `phase` = `phaseType.code`, `played` 0/1.
  - `parse_teams(payload: dict) -> pd.DataFrame` — unique `(club_code, tv_code, name)` from local and road clubs (`club.code`, `club.tvCode`, `club.name`).
  - `parse_boxscore(payload: dict, season: str, game_code: int) -> tuple[pd.DataFrame, pd.DataFrame]` — (`box_player` rows, `box_team` rows). `player_code` = `Player_ID` stripped of whitespace and leading `"P"`; `Minutes` `"MM:SS"` → minutes float, `"DNP"` → `0.0` and `dnp=1`; field map: `FieldGoalsMade2→fgm2`, `FieldGoalsAttempted2→fga2`, `…3→fgm3/fga3`, `FreeThrowsMade/Attempted→ftm/fta`, `OffensiveRebounds→oreb`, `DefensiveRebounds→dreb`, `Assistances→ast`, `Steals→stl`, `Turnovers→tov`, `BlocksFavour→blk`, `BlocksAgainst→blka`, `FoulsCommited→pf`, `FoulsReceived→fd`, `Valuation→pir_official`, `IsStarter→is_starter`, `Points→pts`. Team rows from each `Stats[i].totr`, `club_code` from that side's first player's `Team`.
  - `parse_people(payload: dict, season: str) -> pd.DataFrame` — only `typeName == "Player"`; `player_code` = `person.code`; `name` = `person.name`; `position` = `positionName`; `club_code` = `club.code`.

- [ ] **Step 1: Failing tests**

```python
def load(n): return json.loads((FIXTURES / n).read_text(encoding="utf-8"))

def test_boxscore_players_and_dnp():
    p, t = parse_boxscore(load("box_E2025_1.json"), "E2025", 1)
    lar = p.set_index("player_code").loc["007200"]
    assert lar["minutes"] == pytest.approx(33 + 21/60) and lar["pir_official"] == 12
    assert pir_box(p.set_index("player_code").loc[["007200"]]).iloc[0] == 12
    beau = p.set_index("player_code").loc["006590"]
    assert beau["dnp"] == 1 and beau["minutes"] == 0.0
    assert set(t["club_code"]) == {"IST", "TEL"}

def test_official_pir_equals_formula_for_every_player():
    for f in ("box_E2025_1.json", "box_E2026_1.json"):
        p, _ = parse_boxscore(load(f), "X", 1)
        assert (pir_box(p) == p["pir_official"]).all()

def test_games_and_teams():
    g = parse_games(load("games_E2026_r10_11.json"), "E2026")
    assert len(g) == 20 and g["played"].sum() == 10
    t = parse_teams(load("games_E2026_r10_11.json"))
    assert len(t) == 20 and ("IST", "EFS") in set(zip(t.club_code, t.tv_code))

def test_people_players_only():
    pe = parse_people(load("people_E2026_OLY.json"), "E2026")
    assert len(pe) == 18 and set(pe["position"]) == {"Guard", "Forward", "Center"}
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS. (If `test_official_pir_equals_formula_for_every_player` fails for a player, stop and report the row — it means the PIR definition differs from the spec.)
- [ ] **Step 5: Commit** `feat: parse Euroleague games, box scores and rosters`

---

### Task 5: Euroleague HTTP client with disk cache

**Files:** Create `src/elfantasy/el_client.py`; Test `tests/test_el_client.py`

**Interfaces:**
- Produces:
  - `class ELApiError(RuntimeError)`
  - `class ELClient(cache_dir: Path, delay_s: float = 0.3, timeout_s: float = 20, session: requests.Session | None = None, retries: int = 2)` with:
    - `games(season: str) -> dict` — always fetched (fixtures/results change).
    - `people(season: str, club_code: str) -> dict` — always fetched.
    - `boxscore(season: str, game_code: int) -> dict` — returns `cache_dir/season/box_{game_code}.json` if present; otherwise fetches; writes cache (utf-8) **only if** payload `Live` is false.
  - HTTP errors / timeouts after `retries` retries → `ELApiError` naming the URL. Sleeps `delay_s` before each request (monkeypatchable `time.sleep`).

- [ ] **Step 1: Failing tests** (a `FakeSession` with `get(url, timeout)` returning objects with `status_code`, `json()`, `text`; counts calls)

```python
def test_boxscore_cached_after_first_fetch(tmp_path):
    s = FakeSession({"Boxscore": (200, {"Live": False, "Stats": [], "x": "Ναι"})})
    c = ELClient(tmp_path, delay_s=0, session=s)
    c.boxscore("E2026", 5); c.boxscore("E2026", 5)
    assert s.calls == 1
    assert json.loads((tmp_path/"E2026"/"box_5.json").read_text(encoding="utf-8"))["x"] == "Ναι"

def test_live_game_not_cached(tmp_path):
    s = FakeSession({"Boxscore": (200, {"Live": True, "Stats": []})})
    ELClient(tmp_path, delay_s=0, session=s).boxscore("E2026", 6)
    assert not (tmp_path/"E2026"/"box_6.json").exists()

def test_http_error_raises_after_retries(tmp_path):
    s = FakeSession({"games": (503, {})})
    with pytest.raises(ELApiError):
        ELClient(tmp_path, delay_s=0, session=s, retries=2).games("E2026")
    assert s.calls == 3
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: Euroleague API client with cache and retries`

---

### Task 6: Refresh orchestration and CLI

**Files:** Create `src/elfantasy/refresh.py`, `src/elfantasy/__main__.py`; Test `tests/test_refresh.py`

**Interfaces:**
- Consumes: `ELClient` methods (duck-typed), `el_parse.*`, `store.*`.
- Produces:
  - `@dataclass RefreshReport: season: str; games_total: int; new_box_scores: int; failed: list[tuple[int, str]]`
  - `refresh_season(conn, client, season: str, progress: Callable[[int, int], None] | None = None) -> RefreshReport` — upsert `games` and `teams`; upsert `el_players` for every club in `teams` seen this season; for each `played` game without rows in `box_player`, fetch + parse + write player and team rows in **one transaction**; a failing game is appended to `failed` and the loop continues.
  - `python -m elfantasy refresh [--seasons E2023 E2024 E2025 E2026]` (default: settings season + history) and `python -m elfantasy import <xlsx>`; DB at `data/elfantasy.db`, cache at `data/cache`.

- [ ] **Step 1: Failing tests** (`FakeClient` serving the Task 4 fixtures: `games()` → `games_E2026_r10_11.json`; `boxscore(season, n)` → `box_E2026_{n}.json` (round-10 games 91–100); `people()` → OLY fixture for every club; `fail_on={game_code}` raises `ELApiError`; counts `box_calls`)

```python
def test_refresh_stores_played_games_and_reports_failures(conn):
    g = parse_games(load("games_E2026_r10_11.json"), "E2026")
    bad = int(g[g.played == 1].game_code.iloc[0])
    r = refresh_season(conn, FakeClient(fail_on={bad}), "E2026")
    assert r.games_total == 20 and r.new_box_scores == 9 and r.failed[0][0] == bad
    stored = read_df(conn, "select distinct game_code from box_player")["game_code"]
    assert bad not in set(stored) and len(stored) == 9

def test_second_refresh_fetches_only_missing(conn):
    c = FakeClient()
    refresh_season(conn, c, "E2026"); n = c.box_calls
    r = refresh_season(conn, c, "E2026")
    assert r.new_box_scores == 0 and c.box_calls == n
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: season refresh orchestration and CLI`

---

### Task 7: Player matching

**Files:** Create `src/elfantasy/matching.py`; Test `tests/test_matching.py`

**Interfaces:**
- Consumes: tables `fantasy_players` (latest snapshot), `el_players` (settings season), `teams`.
- Produces:
  - `normalize_name(s: str) -> str` — NFKD, drop combining marks, map `đ→d`, `ł→l`, `ø→o`, `ß→ss`; lower-case; `-`, `.`, `'` → space; collapse spaces.
  - `match_players(conn, season: str, overrides_path: Path) -> MatchReport` where `@dataclass MatchReport: matched: int; unmatched: pd.DataFrame  # fantasy_id, name, surname, team`. Rewrites `player_map`. Order, first hit wins:
    1. override (`{"<fantasy_id>": "<player_code>"}` JSON, utf-8) → `"override"`
    2. same team (fantasy `team` == `teams.tv_code` of el player's club), token sets of `"name surname"` and EL `"SURNAME, NAME"` equal → `"name"`
    3. same team, normalized fantasy surname equals EL surname part, or all its tokens are in it, and exactly one candidate → `"surname"`
    4. same team, single best `difflib.SequenceMatcher` ratio ≥ 0.85 on full normalized names → `"fuzzy"`
    5. any team, exactly one equal token-set name → `"name_any_team"` (mid-season transfer)

- [ ] **Step 1: Failing tests.** Test helpers in the test file: `seed(conn, fantasy: list[tuple[id, name, surname, team]], el: list[tuple[code, "SURNAME, NAME", club]])` inserts a matchday-11 snapshot, the rows, and teams `OLY/OLY`, `PAN/PAO`, `MAD/RMB`, `IST/EFS`; `mapped(conn, fid) -> tuple[str, str] | None` reads `player_map`; `NO = tmp_path / "none.json"` (absent file = no overrides).

```python
def test_normalize():
    assert normalize_name("Šarūnas Jasikevičius") == "sarunas jasikevicius"
    assert normalize_name("Đorđević, T.J.") == "dordevic t j"

def test_surname_within_team(conn, NO):
    seed(conn, [(3469, "Sasha", "Vezenkov", "OLY")], [("001234", "VEZENKOV, ALEKSANDAR", "OLY")])
    match_players(conn, "E2026", NO)
    assert mapped(conn, 3469) == ("001234", "surname")

def test_full_name_with_accents(conn, NO):
    seed(conn, [(5, "Dzanan", "Musa", "RMB")], [("000555", "MUSA, DŽANAN", "MAD")])
    match_players(conn, "E2026", NO)
    assert mapped(conn, 5) == ("000555", "name")

def test_shared_surname_not_guessed(conn, NO):
    seed(conn, [(7, "Bob", "Peters", "OLY")],
         [("000001", "PETERS, ALEC", "OLY"), ("000002", "PETERS, JOHN", "OLY")])
    r = match_players(conn, "E2026", NO)
    assert mapped(conn, 7) is None and list(r.unmatched["fantasy_id"]) == [7]

def test_override_wins_and_non_ascii_file(conn, tmp_path):
    seed(conn, [(3469, "Sasha", "Vezenkov", "OLY")], [("001234", "VEZENKOV, ALEKSANDAR", "OLY")])
    p = tmp_path / "o.json"; p.write_text('{"3469": "009999", "_note": "Βεζένκοφ"}', encoding="utf-8")
    match_players(conn, "E2026", p)
    assert mapped(conn, 3469) == ("009999", "override")

def test_transfer_matched_across_teams(conn, NO):
    seed(conn, [(77, "Kendrick", "Nunn", "PAO")], [("000077", "NUNN, KENDRICK", "MAD")])
    match_players(conn, "E2026", NO)
    assert mapped(conn, 77) == ("000077", "name_any_team")
```

(Override keys that are not integers, like `_note`, are ignored.)

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: fantasy to Euroleague player matching`

---

### Task 8: T-slots

**Files:** Create `src/elfantasy/slots.py`; Test `tests/test_slots.py`

**Interfaces:**
- Produces:
  - `assign_slots(games: pd.DataFrame) -> pd.DataFrame` — adds `slot` (1-based dense rank of `local_date[:10]` within `(season, round)`).
  - `team_slots(conn, season: str, round_: int) -> pd.DataFrame` — columns `tv_code, slot, game_code, opp_tv, is_home, local_date`; one row per team per game (two rows if a team plays twice in the round).
  - `next_round(conn, season: str) -> int | None` — smallest round having any `played == 0` game.

- [ ] **Step 1: Failing tests**

```python
def test_slots_three_dates():
    g = games_df(round_=4, dates=["2026-10-07","2026-10-08","2026-10-09","2026-10-08"])
    assert list(assign_slots(g)["slot"]) == [1, 2, 3, 2]

def test_two_dates_round():
    assert set(assign_slots(games_df(1, ["2026-09-24","2026-09-25"]))["slot"]) == {1, 2}

def test_team_slots_and_next_round(fixture_conn):  # fixture DB from games_E2026_r10_11.json
    assert next_round(fixture_conn, "E2026") == 11
    ts = team_slots(fixture_conn, "E2026", 11)
    assert len(ts) == 20 and set(ts["slot"]) == {1, 2, 3}
    assert ts.loc[ts.tv_code == "EFS", "opp_tv"].iloc[0] in set(ts.tv_code)
```

- [ ] **Step 2–4:** run → FAIL, implement, run → PASS. Add `fixture_conn` to `conftest.py`: temp DB, `refresh_season` with the Task 6 `FakeClient` (move `FakeClient` into `conftest.py`), plus `import_export` of the real export.
- [ ] **Step 5: Commit** `feat: T-slot assignment per round`

---

### Task 9: Metrics — game log, player summary, value, win bonus

**Files:** Create `src/elfantasy/metrics.py`; Test `tests/test_metrics.py`

**Interfaces:**
- Consumes: `pir.pir_box`, tables, `Settings`.
- Produces:
  - `game_log(conn, season: str) -> pd.DataFrame` — one row per `box_player` row of played games: `player_code, fantasy_id (nullable), name, position, season, game_code, round, local_date, team_tv, opp_tv, is_home, won, margin (team − opp), minutes, dnp, is_starter, <BOX_COMPONENTS>, pir`. `position` = latest-snapshot fantasy position if mapped, else `el_players.position`.
  - `player_summary(log: pd.DataFrame, s: Settings) -> pd.DataFrame` — index `player_code`; over non-DNP games sorted by date: `games, dnp_rate, min_avg, min_last5, pir_avg, pir_last3, pir_last5, form_trend` (`"up"` if `pir_last5 − pir_avg ≥ s.form_threshold`, `"down"` if ≤ −threshold, else `"flat"`), `pir_per30, p20, p80, sd, boom_rate (pir ≥ s.boom), bust_rate (pir < s.bust)`, breakdown per game `scoring (pts), rebounding (oreb+dreb), playmaking (ast+fd), defense (stl+blk), negatives (missed FG+FT, tov, blka, pf)`. A player with only DNPs → row with `games = 0` and NaN metrics.
  - `value_table(conn, matchday: int) -> pd.DataFrame` — `fantasy_id, name, surname, team, position, price, plus, fpt, fpt_per_credit`.
  - `price_history(conn, fantasy_id: int) -> pd.DataFrame` — `matchday, price, fpt` over all snapshots.
  - `estimate_win_bonus(conn, season: str, matchday: int) -> float | None` — for mapped players with ≥ 3 non-DNP games in rounds that are both in the snapshot's `reference_matchdays` and fully played: `gap = snapshot fpt − mean pir`, `share = mean won`; least squares through origin `b = Σ gap·share / Σ share²`; `None` if < 20 players qualify.
  - `effective_win_bonus(conn, s: Settings) -> float` — `s.win_bonus` if set, else the estimate for the latest snapshot, else `0.0`.

- [ ] **Step 1: Failing tests** (hand-built `log` DataFrames)

```python
def test_summary_form_and_consistency():
    log = mk_log("p1", pir=[10, 10, 10, 10, 10, 20, 20, 20, 20, 20], minutes=[30]*10)
    s = player_summary(log, Settings()).loc["p1"]
    assert s.pir_avg == 15 and s.pir_last5 == 20 and s.form_trend == "up"
    assert s.pir_per30 == 15 and s.boom_rate == 0.5 and s.bust_rate == 0.0

def test_dnps_excluded_and_counted():
    log = mk_log("p1", pir=[12, 0], minutes=[25, 0], dnp=[0, 1])
    s = player_summary(log, Settings()).loc["p1"]
    assert s.games == 1 and s.dnp_rate == 0.5 and s.pir_avg == 12

def test_only_dnps_gives_nan_row():
    s = player_summary(mk_log("p2", pir=[0], minutes=[0], dnp=[1]), Settings()).loc["p2"]
    assert s.games == 0 and math.isnan(s.pir_avg)

def test_win_bonus_recovered(conn):
    seed_players_with_gap(conn, n=30, bonus=2.0)   # fpt = mean pir + 2.0 * share
    assert estimate_win_bonus(conn, "E2026", 11) == pytest.approx(2.0, abs=0.05)

def test_win_bonus_ignores_unplayed_reference_round(conn):
    seed_players_with_gap(conn, n=30, bonus=2.0, reference=list(range(1, 12)), played_rounds=range(1, 11))
    assert estimate_win_bonus(conn, "E2026", 11) == pytest.approx(2.0, abs=0.05)

def test_value_table(fixture_conn):
    v = value_table(fixture_conn, 11).set_index("fantasy_id").loc[3469]
    assert v.fpt_per_credit == pytest.approx(24.5 / 18.9)
```

- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat: game log, player summary, value and win-bonus estimate`

---

### Task 10: Defense vs Position and fixture difficulty

**Files:** Create `src/elfantasy/dvp.py`; Test `tests/test_dvp.py`

**Interfaces:**
- Consumes: `metrics.game_log` output, `box_team` table, `slots.team_slots`, `Settings`.
- Produces:
  - `POSITIONS = ("Guard", "Forward", "Center")`; `DVP_COMPONENTS = BOX_COMPONENTS + ["pir", "fpt"]` where per player-game `fpt = pir + win_bonus * won`.
  - `possessions(box_team: pd.DataFrame) -> pd.DataFrame` — per `(season, game_code)`: mean over both teams of `fga2 + fga3 + 0.44*fta − oreb + tov`.
  - `dvp(log, poss, win_bonus: float, window="season"|"last5"|"home"|"away", role="all"|"starters"|"bench", basis="game"|"per40"|"per100", shrink_minutes: float = 400) -> pd.DataFrame` — index `(def_tv, position)` where `def_tv` = the attacking player's `opp_tv`; columns: each component value in the chosen basis, `games`, `minutes`, `idx_<component>` (shrunk per-40 rate ÷ league per-40 rate − 1), `rank_pir` (1 = highest `idx_pir`, i.e. softest). Window filters the **defending** team's games (`last5` = its 5 most recent; `home` = defending team at home). DNP rows excluded.
    - per game: Σ over attacking players of that position per game, mean over the defending team's games in window.
    - per40: Σ component ÷ Σ minutes × 40.
    - per100: mean over games of (game Σ ÷ game possessions × 100).
    - shrinkage: `(rate·min + league_rate·k) / (min + k)` on per-40 rates, `k = shrink_minutes`.
    - shooting allowed: `fg2_pct = Σfgm2/Σfga2`, `fg3_pct`, `ft_pct` (from sums, any basis), plus `idx_` versions vs league.
  - `how_they_concede(row: pd.Series, n: int = 3) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]` — top-n highest and lowest `idx_` components excluding `pir`, `fpt`.
  - `fixture_difficulty(conn, season, from_round: int, n_rounds: int, position: str, dvp_table: pd.DataFrame) -> pd.DataFrame` — index `tv_code`, columns `R{round}`; cell = dict-like string `"OPP T{slot} {idx_pir:+.0%}"` plus a parallel numeric frame via `fixture_difficulty_values(...) -> pd.DataFrame` (same shape, `idx_pir` of the opponent) for heatmap colouring.

- [ ] **Step 1: Failing tests** (hand-built logs: two defending teams `AAA`, `BBB`, centres only)

```python
def test_per_game_and_per40():
    # vs AAA: game1 two centres 10+6 PIR in 20+20 min; game2 one centre 8 PIR in 40 min
    t = dvp(log, poss, 0.0, basis="game", shrink_minutes=0).loc[("AAA", "Center")]
    assert t.pir == 12 and t.games == 2
    t40 = dvp(log, poss, 0.0, basis="per40", shrink_minutes=0).loc[("AAA", "Center")]
    assert t40.pir == pytest.approx(24 / 80 * 40)

def test_index_rank_and_shrinkage():
    raw = dvp(log, poss, 0.0, shrink_minutes=0)
    assert raw.loc[("AAA","Center"), "rank_pir"] == 1          # AAA concedes more than BBB
    big = dvp(log, poss, 0.0, shrink_minutes=1e9)
    assert abs(big.loc[("AAA","Center"), "idx_pir"]) < 1e-6    # fully shrunk to league

def test_last5_and_home_windows():
    t = dvp(log7games, poss, 0.0, window="last5", shrink_minutes=0).loc[("AAA","Center")]
    assert t.games == 5
    h = dvp(log, poss, 0.0, window="home", shrink_minutes=0)
    assert set(h.index.get_level_values(0)) == {"AAA"}         # only AAA hosted games

def test_per100_uses_possessions():
    t = dvp(log, poss_70, 0.0, basis="per100", shrink_minutes=0).loc[("AAA","Center")]
    assert t.pir == pytest.approx(mean([16/70*100, 8/70*100]))

def test_fpt_includes_bonus_for_attacking_wins():
    t = dvp(log_all_wins, poss, 2.0, shrink_minutes=0).loc[("AAA","Center")]
    assert t.fpt == pytest.approx(t.pir + 2.0 * t_players_per_game)

def test_fixture_difficulty_shape(fixture_conn):
    tab = dvp(game_log(fixture_conn, "E2026"), possessions(read_df(fixture_conn, "select * from box_team")), 0.0)
    fd = fixture_difficulty_values(fixture_conn, "E2026", 11, 1, "Guard", tab)
    assert fd.shape == (20, 1)
```

- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat: Defense vs Position analytics and fixture difficulty`

---

### Task 11: App shell, shared data access and Data page

**Files:** Create `app/data_access.py`, `app/pages/5_Data.py`, minimal `app/Home.py` (title only, filled in Task 12); Test `tests/test_app_smoke.py`

**Interfaces:**
- Consumes: everything above.
- Produces (`app/data_access.py`, all paths relative to repo root `ROOT = Path(__file__).resolve().parents[1]`):
  - `DATA = ROOT / "data"`, `DB = DATA / "elfantasy.db"`, `OVERRIDES = DATA / "player_overrides.json"`, `SETTINGS = DATA / "settings.json"`; env var `ELFANTASY_DATA` overrides `DATA` (used by tests).
  - `get_conn()` (`st.cache_resource`), `get_settings() -> Settings`, `load_log(season) -> DataFrame` (`st.cache_data`), `load_summary(season)`, `load_dvp(season, window, role, basis)`, `latest_matchday() -> int | None`, `clear_caches()`.
- Data page sections:
  1. **Import export** — `st.file_uploader("xlsx")` → save to `data/imports/matchday_<n>.xlsx` → `import_export` → `match_players` → success message with matchday and matched count; `ExportFormatError` → show missing/unexpected columns.
  2. **Refresh games** — button; runs `refresh_season` for current + history seasons with `st.progress`; shows each `RefreshReport` (new games, failures); then `match_players`, `clear_caches()`.
  3. **Unmatched players** — table from `MatchReport.unmatched`; editable override entry (fantasy_id → player_code picked from a selectbox of that team's EL players) saved to `OVERRIDES` (utf-8).
  4. **Settings** — form for `boom`, `bust`, `form_threshold`, `win_bonus` (blank = estimated; show current estimate), `dvp_shrink_minutes`.

- [ ] **Step 1: Failing smoke test** (uses `streamlit.testing.v1.AppTest`; a `fixture_data_dir` fixture builds a data dir with the fixture DB and sets `ELFANTASY_DATA`)

```python
@pytest.mark.parametrize("page", ["app/Home.py", "app/pages/5_Data.py"])
def test_page_runs(page, fixture_data_dir):
    at = AppTest.from_file(page, default_timeout=60).run()
    assert not at.exception
```

- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Manual check** — `.venv/Scripts/python -m streamlit run app/Home.py`; on the Data page import `tests/fixtures/players_stats.xlsx` → "Matchday 11 imported". Stop the server.
- [ ] **Step 6: Commit** `feat: app shell, data access and Data page`

---

### Task 12: Round dashboard and Player explorer

**Files:** Modify `app/Home.py`; Create `app/pages/1_Players.py`; Modify `tests/test_app_smoke.py` (add both pages to the parametrize list)

**Interfaces:**
- Consumes: `data_access.*`, `metrics.value_table/estimate_win_bonus`, `slots.next_round/team_slots`, `dvp.dvp`.
- Home sections (in order):
  1. Header: next round number, its dates by T-slot, and each slot's games (`team_slots`).
  2. Freshness: latest snapshot matchday + import time, last final game date; warning if the latest fully played round > latest snapshot matchday ("import a newer export").
  3. Alerts: unmatched count (link to Data page), refresh failures from session state.
  4. Four top-10 tables, each filterable by position (radio, default all): **In form** (`pir_last5 − pir_avg`), **Best value** (`fpt_per_credit`), **Price risers / fallers** (`plus`), **Most reliable** (`p20`).
- Players page: one table joining `value_table` (latest snapshot) + `player_summary` (via `player_map`) + next-round `slot` and opponent + opponent's `rank_pir` for the player's position (season window, per-40). Filters: position multiselect, team multiselect, price range slider, slot multiselect, minimum games. Column picker (`st.multiselect` of available columns, sensible default). `st.download_button` CSV.

- [ ] **Step 1: Extend the smoke test**; run → FAIL for the new page.
- [ ] **Step 2: Implement** both pages.
- [ ] **Step 3: Run** smoke tests → PASS; manual check in the browser that tables render and filters change row counts.
- [ ] **Step 4: Commit** `feat: round dashboard and player explorer`

---

### Task 13: Player profile and Compare pages

**Files:** Create `app/pages/2_Player.py`, `app/pages/3_Compare.py`; extend smoke test.

**Interfaces:**
- Consumes: `metrics.game_log/player_summary/price_history`, `dvp.dvp/how_they_concede`, `slots.team_slots/next_round`.
- Player page (player chosen by searchable selectbox `"Surname Name (TEAM)"`; selection kept in `st.session_state["player"]` so other pages can link):
  1. Header metrics: price, FPT, PIR avg, last-5, form arrow, slot next round.
  2. Plotly chart: per-game PIR bars + 3-game rolling line; second chart minutes per game; DNPs shown as gaps with a marker.
  3. PIR breakdown stacked bar (scoring, rebounding, playmaking, defense, negatives).
  4. Consistency: P20, P80, SD, boom/bust, DNP rate; histogram of game PIR.
  5. Price history line (snapshots).
  6. Matchup vs next opponent: table of the player's per-40 component rates beside the opponent's `idx_<component>` for his position, plus `how_they_concede` lists.
  7. History vs teams: per opponent mean PIR, games (this season + history seasons).
- Compare page: multiselect 2–4 players; side-by-side metric table; overlaid PIR-per-game lines; grouped breakdown bars.

- [ ] **Step 1:** Extend smoke test with both pages (Player page test sets `session_state["player"]` to Vezenkov's fantasy_id) → FAIL.
- [ ] **Step 2: Implement.** **Step 3:** smoke → PASS; manual browser check of charts.
- [ ] **Step 4: Commit** `feat: player profile and compare pages`

---

### Task 14: Opponents (DvP) page

**Files:** Create `app/pages/4_Opponents.py`; extend smoke test.

**Interfaces:**
- Consumes: `data_access.load_dvp`, `dvp.how_they_concede/fixture_difficulty/fixture_difficulty_values`.
- Tabs:
  1. **Heatmap** — controls: metric (`pir`, `fpt`, any component), window (season/last5/home/away), role (all/starters/bench), basis (game/per40/per100), value shown (raw or index). Plotly heatmap rows = 20 teams sorted by `rank_pir`, columns = 3 positions; diverging colour on index, centred at 0 (red = soft for the attacker).
  2. **Team** — select team; table per position of every component (raw + index + rank), `how_they_concede` text per position, and a line chart of rolling 5-game PIR conceded per position over the season.
  3. **Fixture difficulty** — position selector, next 3–5 rounds (slider); grid coloured by `fixture_difficulty_values`, labels from `fixture_difficulty`.
  4. **Previous seasons** — same heatmap for a chosen history season.

- [ ] **Step 1:** Extend smoke test → FAIL. **Step 2:** Implement. **Step 3:** smoke → PASS; manual browser check that changing window/basis changes values.
- [ ] **Step 4: Commit** `feat: Defense vs Position page`

---

### Task 15: Live end-to-end run, launcher and README

**Files:** Create `run_app.bat`, `README.md`, `tests/test_live.py` (marked `@pytest.mark.live`, skipped unless `-m live`).

**Interfaces:** none new.

- [ ] **Step 1: Live test**

```python
@pytest.mark.live
def test_live_current_season(tmp_path):
    conn = connect(tmp_path / "live.db")
    r = refresh_season(conn, ELClient(tmp_path / "cache"), "E2026")
    assert r.failed == [] and r.new_box_scores >= 100
    p = read_df(conn, "select * from box_player")
    assert (pir_box(p) == p["pir_official"]).mean() == 1.0
    import_export(conn, FIXTURES / "players_stats.xlsx")
    rep = match_players(conn, "E2026", tmp_path / "none.json")
    assert rep.matched >= 320          # ≥ 94% of 340 auto-matched
```

Register the marker in `pyproject.toml`; default `addopts = "-m 'not live'"`.

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest -m live -v` — Expected: PASS. If `matched < 320`, print `rep.unmatched` and improve `normalize_name`/rules in Task 7's module with a new unit test per discovered pattern, then re-run.
- [ ] **Step 3: Full history download** — `.venv/Scripts/python -m elfantasy refresh` (all four seasons; ~1,500 box scores, ~10 min). Expected: every report `failed == []`.
- [ ] **Step 4:** `run_app.bat`: `cd /d "%~dp0"` then `.venv\Scripts\python -m streamlit run app\Home.py`. README: setup commands, round workflow (spec §10), where data lives, how to add overrides.
- [ ] **Step 5: Full suite** `.venv/Scripts/python -m pytest -v` — all PASS.
- [ ] **Step 6: Commit** `chore: launcher, README and live end-to-end test`
