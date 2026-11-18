# Value Function Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python -m elfantasy value` labels every player BUY / HOLD / SELL for the next round by expected price change, from a measured price rule and a fitted volume × efficiency PIR model, and writes an Excel file with the value table, the per-channel stat analysis and the fitted model.

**Architecture:** Three new modules over the existing data layer:
- `price_rule.py` fits the game's price rule from consecutive export snapshots.
- `xpir.py` builds per-channel rates and efficiencies, shrunk by fitted per-stat strengths, then calibrates expected PIR.
- `value.py` combines them into value, labels and the stat-analysis sheet, plus a walk-forward backtest.

The CLI gets a `value` subcommand. No app pages.

**Tech Stack:** Python 3.12, pandas, numpy, openpyxl (all present). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-18-value-function-design.md`

## Global Constraints

- Current season only (`Settings.season`, today `"E2026"`).
- Every text file read/write passes `encoding="utf-8"`.
- No new dependencies. Fits use numpy least squares and grid search, not scikit-learn.
- Run Python and tests with `"/c/Users/GIORGO~1.IOA/AppData/Local/Temp/claude/709f4e1f53051a69/910ac168-1501-41f0-b465-76a384a3ee06/scratchpad/venv/Scripts/python"`. Below this is written `$PY`.
- **Price rule:**
  - Played: `Δprice = k · (PIR − (a · price + c))`.
  - Didn't play: `Δprice = d`.
  - Defaults when it can't be fitted: `k=0.042, a=1.14, c=-1.0, d=-0.06`.
  - Export matchday N's prices reflect rounds ≤ N−1, so the change from export N−1 to N comes from round N−1.
- **Value:** `value = P(play)·k·(xPIR − BE(price)) + (1 − P(play))·d`; `ROI = value / price`.
- **Labels:** BUY if `value ≥ 0.10`, SELL if `value ≤ −0.10`, else HOLD (Settings `value_buy`, `value_sell`).
- **DIP:** season PIR average ≥ 10 (`dip_min_avg`), last price change ≤ −0.3 (`dip_drop`), and label BUY.
- **P(play):** `(played + 0.9·2) / (n + 2)` over his current team's last 5 played games before the round.
- **Channel values:**
  - 2PA `3·p2 − 1`; 3PA `4·p3 − 1`; FD `1 + r·(2·ftp − 1)`, where `r` = FTA per FD.
  - OREB, DREB, AST, STL, BLK `+1`; TOV, BLKA, PF `−1`.
- Nothing computed for round r may use games from round ≥ r.

## Review Focus

1. **Players with no or few games** (new signings, long-injured): xPIR falls back to position priors, P(play) to its prior, no crash. *Test: Task 2 `test_player_without_games_gets_position_prior`.*
2. **Export player unmatched to Euroleague data:** he stays in the table labelled `NO DATA`, never dropped. *Test: Task 4 `test_unmatched_player_kept_as_no_data`.*
3. **Round already partly played** (today round 12 has 9 of 10 games done): by default, score the next round with no games played, and say which round. *Test: Task 5 `test_default_round_is_next_unstarted`.*
4. **Only one export stored, or no consecutive pair:** the rule falls back to the defaults and the output says so. *Test: Task 1 `test_defaults_without_consecutive_snapshots`.*
5. **Mid-season transfer:** the fixture comes from his team in the latest export, not the team in his old games. *Test: Task 4 `test_fixture_uses_export_team`.*

---

## File Structure

```
src/elfantasy/settings.py     + value_buy, value_sell, dip_min_avg, dip_drop
src/elfantasy/slots.py        + next_unstarted_round
src/elfantasy/price_rule.py   PriceRule dataclass, fit_price_rule
src/elfantasy/xpir.py         channel arithmetic, channel_table, XpirModel, fit_xpir, predict_xpir
src/elfantasy/value.py        p_play, build_value_table, backtest, write_value_excel
src/elfantasy/__main__.py     + `value` subcommand
tests/test_price_rule.py  tests/test_xpir.py  tests/test_value.py  tests/test_cli.py (extend)
tests/synth.py                synthetic game-log builder shared by xpir/value tests
```

---

### Task 1: Settings and the price rule

**Files:** Modify `src/elfantasy/settings.py`; Create `src/elfantasy/price_rule.py`; Test `tests/test_price_rule.py`, `tests/test_settings.py`

**Interfaces:**
- Consumes: `metrics.game_log(conn, season)`, the `snapshots` and `fantasy_players` tables.
- Produces:
  - `Settings` gains `value_buy=0.10`, `value_sell=-0.10`, `dip_min_avg=10.0`, `dip_drop=0.3`.
  - `@dataclass(frozen=True) PriceRule`:
    - Fields: `k=0.042, a=1.14, c=-1.0, d=-0.06, n=0, r2=nan, source="default"`.
    - Methods: `break_even(price) -> price-like`, `change(pir, price) -> price-like`.
  - `fit_price_rule(conn, season: str, min_rows: int = 30) -> PriceRule`:
    - Uses every stored snapshot pair (N−1, N).
    - Rows: players in both snapshots, matched via `player_map`, who played round N−1 (non-DNP).
    - OLS `dp = β0 + β1·pir + β2·price_prev`, giving `k=β1, a=−β2/β1, c=−β0/β1`.
    - `d` = mean dp of matched players with no non-DNP game in round N−1 (default if none).
    - `source="fitted"`; if rows < `min_rows`, returns `PriceRule()`.

- [ ] **Step 1: Failing tests**

```python
def test_rule_arithmetic():
    r = PriceRule()
    assert r.break_even(4.8) == pytest.approx(4.472)
    assert r.change(20, 4.8) == pytest.approx(0.042 * (20 - 4.472))

def test_fit_recovers_known_rule(conn):
    seed_two_snapshots(conn, k=0.05, a=1.2, c=-0.5, d=-0.1, n=60)   # prices for md 11 → 12, round-11 PIR
    r = fit_price_rule(conn, "E2026")
    assert (r.source, r.n) == ("fitted", 60)
    assert r.k == pytest.approx(0.05, abs=1e-6) and r.a == pytest.approx(1.2, abs=1e-6)
    assert r.c == pytest.approx(-0.5, abs=1e-6) and r.d == pytest.approx(-0.1)

def test_defaults_without_consecutive_snapshots(conn):
    seed_two_snapshots(conn, k=0.05, a=1.2, c=-0.5, d=-0.1, n=60, mds=(9, 12))   # not consecutive
    assert fit_price_rule(conn, "E2026").source == "default"
```

Also `test_settings.py::test_value_settings_defaults` asserts the four new defaults. `seed_two_snapshots` lives in the test file. It writes `games` (round 11, played, plus one unplayed game), `box_player`, `teams`, `player_map`, two `snapshots` and the `fantasy_players` rows, plus 5 matched players with no round-11 game.

- [ ] **Step 2:** `$PY -m pytest tests/test_price_rule.py tests/test_settings.py -q`. Expected: FAIL (import error / missing fields).
- [ ] **Step 3:** Implement per Interfaces.
- [ ] **Step 4:** Run again. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: measured price rule with defaults`.

---

### Task 2: Channel arithmetic and shrunk per-player rates

**Files:** Create `src/elfantasy/xpir.py`, `tests/synth.py`; Test `tests/test_xpir.py`

**Interfaces:**
- Consumes: game-log columns `player_code, position, local_date, round, minutes, dnp, fgm2, fga2, fgm3, fga3, ftm, fta, oreb, dreb, ast, stl, blk, tov, blka, pf, fd, pir`.
- Produces:
  - `VOLUME_STATS = ["fga2", "fga3", "fd", "oreb", "dreb", "ast", "stl", "blk", "tov", "blka", "pf"]`
  - `EFFICIENCIES = {"p2": ("fgm2", "fga2"), "p3": ("fgm3", "fga3"), "ftp": ("ftm", "fta"), "ftr": ("fta", "fd")}`
  - `foul_value(fta_per_fd, ft_pct)` = `1 + fta_per_fd·(2·ft_pct − 1)`
  - `unit_values(p2, p3, ftp, ftr) -> dict[str, value]`: per-unit PIR of each volume stat (Global Constraints).
  - `channel_table(log_before: pd.DataFrame, k: dict[str, float], half_life: float) -> pd.DataFrame`:
    - Index `player_code`. Columns: `position`, `games`, `min_w` (weighted minutes), `min_season`, `min_last3`, `pir_avg`, `last_dev` (last game PIR − mean of his earlier games, 0 if < 2 games).
    - Per volume stat `r_<stat>` (shrunk per-minute rate) and `v_<stat>` (unit value); `p2, p3, ftp, ftr` (shrunk); `pir_per_min = Σ r·v`.
    - Weights: game weight `0.5 ** (age / half_life)` (age 0 = his latest game; `half_life=inf` means equal weights). DNP rows ignored.
    - Rate shrink: `(Σw·x + prior·k[stat]) / (Σw·min + k[stat])`, with prior = pooled per-minute rate of his position in `log_before`.
    - Efficiency shrink: `(Σw·made + prior·k[e]) / (Σw·att + k[e])`, with the prior pooled the same way.
  - `player_priors(log_before) -> pd.DataFrame` (position-level rates and efficiencies), reused by Task 3 for players with no games.

- [ ] **Step 1: Failing tests** (`tests/synth.py` builds logs: `make_log(players: dict[code, dict(position, games=[{stat: n, ...}, ...])])` with dates by round)

```python
def test_foul_value_matches_season_examples():
    assert foul_value(1.31, 0.92) == pytest.approx(2.1004)      # Maledon
    assert foul_value(0.72, 0.72) == pytest.approx(1.3168)      # Shorts

def test_channels_reproduce_pir_exactly_without_shrinkage():
    log = make_log(...)   # one player, 3 varied games
    t = channel_table(log, k={s: 0.0 for s in [*VOLUME_STATS, *EFFICIENCIES]}, half_life=float("inf"))
    row = t.iloc[0]
    assert row.pir_per_min * log.minutes.sum() == pytest.approx(log.pir.sum())

def test_shrinkage_pulls_small_samples_to_position():
    t = channel_table(two_guards_one_tiny_sample, k={**ZERO, "fga3": 1e9}, half_life=float("inf"))
    assert t.loc["tiny", "r_fga3"] == pytest.approx(t.loc["big", "r_fga3"], rel=0.05)

def test_recency_half_life_weights_latest_game_most():
    t1 = channel_table(log_rising_ast, ZERO, half_life=1.0); t_inf = channel_table(log_rising_ast, ZERO, float("inf"))
    assert t1.loc["p", "r_ast"] > t_inf.loc["p", "r_ast"]

def test_player_without_games_gets_position_prior():
    pri = player_priors(log_with_guards)
    assert pri.loc["Guard", "pir_per_min"] > 0     # Task 3 uses this for players absent from log_before

def test_last_dev():
    t = channel_table(make_log({"p": {"position": "Guard", "games": pir_games([10, 12, 2])}}), ZERO, float("inf"))
    assert t.loc["p", "last_dev"] == pytest.approx(2 - 11)
```

- [ ] **Step 2:** Run `tests/test_xpir.py`. Expected: FAIL.
- [ ] **Step 3:** Implement per Interfaces.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: channel arithmetic and shrunk per-player rates`.

---

### Task 3: Fit and predict xPIR (opponent, home, bounce-back, calibration)

**Files:** Modify `src/elfantasy/xpir.py`; Test `tests/test_xpir.py`

**Interfaces:**
- Consumes: `channel_table`, `player_priors`, `dvp.dvp(..., basis="per40", shrink_minutes=400)` (its `idx_<stat>` columns), `dvp.possessions`.
- Produces:
  - `OPP_STATS = VOLUME_STATS`. The opponent multiplier for a volume stat is `clip(1 + idx_<stat>, 0.5, 1.5)` for his position, or 1.0 if missing.
  - `@dataclass XpirModel`:
    - Fitted pieces: `k: dict[str, float]`, `half_life: float`, `w_season_min: float`, `alpha: float`, `beta: float`, `gamma_home: float`, `delta_bounce: float`.
    - Diagnostics: `use_opp_eff: bool = False`, `train_rows: int`, `mae: float`, `mae_baseline: float`.
  - `features_for_round(log: pd.DataFrame, poss: pd.DataFrame, round_: int, fixtures: pd.DataFrame, k, half_life, w_season_min) -> pd.DataFrame`:
    - Uses only `log[round < round_]`.
    - `fixtures` columns: `player_code` or `tv_code` key (see predict), `opp_tv`, `is_home`.
    - Returns per player: `xmin = w·min_season + (1−w)·min_last3`, `raw = xmin · Σ r·v·opp_mult`, `home`, `last_dev`, `pir_avg`, `position`, plus `r_*`, `v_*`, `opp_*` for the stat sheet.
    - Players absent from `log_before` but present in fixtures get position priors and `xmin` = position median minutes.
  - `fit_xpir(log, poss, rounds: list[int]) -> XpirModel`:
    - **Per-stat `k`:** grid, chosen independently per stat by the weighted squared error of predicting each player's per-minute rate in round r from rounds < r. Volume grid in minutes `{0, 50, 100, 200, 400, 800, 1600}`; efficiency grid in attempts `{0, 5, 10, 20, 40, 80, 160}`.
    - **`w_season_min`:** grid `{0, .25, .5, .75, 1}` by minutes MSE.
    - **`half_life`:** grid `{3, 6, 12, inf}` by calibrated MAE.
    - **Calibration:** OLS `pir = alpha + beta·raw + gamma_home·home + delta_bounce·last_dev` on all training rows (rounds in `rounds`, players who played).
    - Training fixtures come from the log rows themselves (`opp_tv`, `is_home` of the target game).
    - `mae_baseline` = MAE of "season average PIR before the round" on the same rows.
  - `predict_xpir(model, log, poss, round_, fixtures) -> pd.DataFrame` = `features_for_round(...)` plus `xpir = alpha + beta·raw + gamma_home·home + delta_bounce·last_dev` (floored at 0).
  - Opponent-adjusted efficiencies (spec: "only if the backtest shows that helps") stay off in this plan (`use_opp_eff=False`). They're a follow-up once the backtest has more rounds to judge them.

- [ ] **Step 1: Failing tests**

```python
def test_opponent_multiplier_raises_matching_channel():
    # same player, two fixtures: opponent that concedes +40% fouls drawn to guards vs league average
    f_soft, f_avg = features_for_round(log, poss, 6, fix_soft, ZERO, inf, 0.5), features_for_round(log, poss, 6, fix_avg, ZERO, inf, 0.5)
    assert f_soft.loc["p", "opp_fd"] > 1.0 and f_soft.loc["p", "raw"] > f_avg.loc["p", "raw"]

def test_no_leakage_from_target_round_or_later():
    a = features_for_round(log, poss, 6, fix, ZERO, inf, 0.5)
    b = features_for_round(log_with_rounds_6_plus_changed, poss, 6, fix, ZERO, inf, 0.5)
    pd.testing.assert_frame_equal(a, b)

def test_fit_recovers_calibration_on_synthetic_season():
    m = fit_xpir(synth_season(rounds=10, players=40, seed=1), synth_poss, rounds=list(range(4, 11)))
    assert 0.6 < m.beta < 1.4 and m.mae < m.mae_baseline
    assert set(m.k) == {*VOLUME_STATS, *EFFICIENCIES} and m.half_life in (3, 6, 12, float("inf"))

def test_predict_handles_player_without_history():
    out = predict_xpir(m, log, poss, 11, fixtures_including_new_guard)
    assert out.loc["new", "xpir"] > 0 and out.loc["new", "games"] == 0
```

`synth_season` (in `tests/synth.py`) draws each player's true per-minute rates and FT% and his games, with seed-fixed noise. The true rates make channel PIR correct by construction.

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement per Interfaces.
- [ ] **Step 4:** Run. Expected: PASS, test file under 60 s.
- [ ] **Step 5:** Commit: `feat: fitted xPIR with opponent channels, home, bounce-back and calibration`.

---

### Task 4: Value table, P(play), DIP and stat analysis

**Files:** Create `src/elfantasy/value.py`; Test `tests/test_value.py`

**Interfaces:**
- Consumes: `PriceRule`, `XpirModel`, `predict_xpir`, `metrics.game_log`, `slots.team_slots`, tables `snapshots`, `fantasy_players`, `player_map`, `games`, `teams`.
- Produces:
  - `p_play(log: pd.DataFrame, games: pd.DataFrame, team_of: pd.Series, before_round: int) -> pd.Series`:
    - Index `player_code`. `team_of` maps `player_code → tv_code`.
    - His team's last 5 played games with round < `before_round`. `played` = his non-DNP appearances in them. Result `(played + 1.8) / (n + 2)`.
  - `build_value_table(conn, season: str, round_: int, rule: PriceRule, model: XpirModel, s: Settings) -> tuple[pd.DataFrame, pd.DataFrame]`, returning `(value_df, stat_df)`:
    - `value_df`: one row per latest-snapshot player.
      - Columns: `fantasy_id, player, team, position, price, last_price_change, opp, home, slot, p_play, xpir, break_even, value, roi, label, dip, pir_avg, games`, sorted by `value` descending.
      - Fixture via `team_slots(conn, season, round_)` on the **export** team.
      - `last_price_change` = price minus the previous stored snapshot's price, NaN if none.
      - Unmatched players or players without a fixture: `label = "NO DATA"`, `value` NaN.
    - `stat_df`: long table `player, team, channel, volume_per_game, efficiency, value_per_unit, opp_mult, pir_per_game`.
      - `volume_per_game = r·xmin`; `pir_per_game = volume·value·opp`.
      - FD rows show efficiency as `"FTA/FD 1.31 · FT% 92%"`.

- [ ] **Step 1: Failing tests** (build a DB with `fixture_conn` from `conftest.py`, round 10 played and round 11 fixtures, plus a fake second snapshot)

```python
def test_value_formula_and_labels(fixture_conn):
    v, _ = build_value_table(fixture_conn, "E2026", 11, PriceRule(), FIXED_MODEL, Settings())
    r = v[v.label != "NO DATA"].iloc[0]
    expected = r.p_play * 0.042 * (r.xpir - (1.14 * r.price - 1.0)) + (1 - r.p_play) * -0.06
    assert r.value == pytest.approx(expected) and r.roi == pytest.approx(r.value / r.price)
    assert set(v.label) <= {"BUY", "HOLD", "SELL", "NO DATA"}
    assert (v.loc[v.label == "BUY", "value"] >= 0.10).all() and (v.loc[v.label == "SELL", "value"] <= -0.10).all()

def test_dip_flag(fixture_conn):
    # seed a matchday-10 snapshot copy where Vezenkov's price is 0.4 higher
    v, _ = build_value_table(fixture_conn, "E2026", 11, PriceRule(), FIXED_MODEL, Settings(dip_min_avg=0))
    r = v.set_index("fantasy_id").loc["3469"]
    assert r.last_price_change == pytest.approx(-0.4) and r.dip == (r.label == "BUY")

def test_unmatched_player_kept_as_no_data(fixture_conn):
    v, _ = build_value_table(fixture_conn, "E2026", 11, PriceRule(), FIXED_MODEL, Settings())
    assert len(v) == 340 and (v.loc[v.p_play.isna(), "label"] == "NO DATA").all()

def test_fixture_uses_export_team(fixture_conn):
    # set fantasy_players.team of 3469 to "PAO" (he still has OLY games in the log)
    v, _ = build_value_table(fixture_conn, "E2026", 11, PriceRule(), FIXED_MODEL, Settings())
    pao = team_slots(fixture_conn, "E2026", 11).set_index("tv_code").loc["PAO", "opp_tv"]
    assert v.set_index("fantasy_id").loc["3469", "opp"] == pao

def test_p_play_prior_and_recent_dnps():
    s = p_play(log_two_of_five_played, games, team_of, before_round=6)
    assert s["p"] == pytest.approx((2 + 1.8) / (5 + 2))

def test_stat_analysis_sums_to_raw(fixture_conn):
    v, st = build_value_table(...)
    one = st[st.player == st.player.iloc[0]]
    assert one.pir_per_game.sum() == pytest.approx(RAW_OF_THAT_PLAYER)
```

`FIXED_MODEL` = an `XpirModel` with `k` all 100/20, `half_life=inf`, `w_season_min=0.5`, `alpha=0`, `beta=1`, `gamma_home=0`, `delta_bounce=0`.

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement per Interfaces.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: value table with BUY/HOLD/SELL, DIP and stat analysis`.

---

### Task 5: Backtest, CLI, Excel output and a real-data run

**Files:** Modify `src/elfantasy/value.py`, `src/elfantasy/slots.py`, `src/elfantasy/__main__.py`, `README.md`; Test `tests/test_value.py`, `tests/test_slots.py`, `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `slots.next_unstarted_round(conn, season) -> int | None`: smallest round ≥ `next_round(...)` with no played game.
  - `backtest(conn, season, rule: PriceRule, first_round: int = 5) -> pd.DataFrame`:
    - One row per round r ≥ `first_round` with games: fit `fit_xpir` on rounds `[4, r)`, predict r.
    - Columns `round, n, mae_xpir, mae_baseline, buy_n, buy_hit, sell_n, sell_hit`.
    - Hit rates only where a snapshot with matchday == r exists (prices known). A hit means the realised `rule.change(actual_pir, price)` has the label's sign. Otherwise NaN.
  - `write_value_excel(path: Path, value_df, stat_df, model: XpirModel, rule: PriceRule, round_: int) -> None`:
    - Sheets `Value`, `Stat analysis`, `Model`.
    - `Model` lists the rule's k/a/c/d and source, every fitted `k[stat]` (the stat-line importance table), `half_life`, `w_season_min`, `alpha, beta, gamma_home, delta_bounce`, MAE vs baseline.
  - CLI `python -m elfantasy value [--round N] [--out PATH] [--backtest]`:
    - Default round `next_unstarted_round`; prints `Scoring round N`.
    - Default out `data/value_round_<N>.xlsx`.
    - Prints the top 15 BUY and SELL as `player team price value label`.
    - `--backtest` prints the backtest table and the current `delta_bounce`.

- [ ] **Step 1: Failing tests**

```python
def test_default_round_is_next_unstarted(conn):
    seed_games(conn, [(12, "2026-11-17", 1), (12, "2026-11-19", 0), (13, "2026-11-24", 0)])
    assert next_unstarted_round(conn, "E2026") == 13

def test_backtest_shape(fixture_conn_multi_round):     # synthetic DB with rounds 1-8 played
    bt = backtest(fixture_conn_multi_round, "E2026", PriceRule(), first_round=5)
    assert list(bt["round"]) == [5, 6, 7, 8] and (bt.mae_xpir > 0).all()

def test_excel_has_three_sheets(tmp_path, fixture_conn):
    write_value_excel(tmp_path / "v.xlsx", v, st, FIXED_MODEL, PriceRule(), 11)
    assert openpyxl.load_workbook(tmp_path / "v.xlsx").sheetnames == ["Value", "Stat analysis", "Model"]

def test_cli_value_writes_file(fixture_data_dir, capsys):
    assert main(["value", "--round", "11"]) == 0
    assert (fixture_data_dir / "value_round_11.xlsx").exists() and "Scoring round 11" in capsys.readouterr().out
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement per Interfaces. Add a README section "Value picks before a round".
- [ ] **Step 4:** Run the full suite `$PY -m pytest -q`. Expected: all PASS.
- [ ] **Step 5: Real data.**
  - Import the new export (`$PY -m elfantasy import "C:\Users\giorgos.ioannidis\OneDrive - TheMart\Desktop\EFP\players_stats.xlsx"`), then refresh.
  - Run `$PY -m elfantasy value --backtest`, then `$PY -m elfantasy value`.
  - Expected:
    - The rule is fitted from the md 11→12 pair: k ≈ 0.04, a ≈ 1.1, n ≈ 240.
    - xPIR MAE is below baseline in most backtest rounds.
    - The Excel file exists, and the top BUY / SELL lists look sane (no 1-game players at the top unless P(play) and the shrunk rates justify it).
    - Report the numbers to the user.
- [ ] **Step 6:** Commit: `feat: value command with backtest and Excel output`.
