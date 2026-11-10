# Euroleague Fantasy PIR Assistant — Design Spec

Date: 2026-11-10
Status: Draft for review

## 1. Purpose and success criteria

**What it is:** a personal, locally run app that helps one user make better decisions in a PIR-scored Euroleague fantasy game: who to buy/sell, value vs. price, next-matchday projections, captain choice, and squad T-slot planning (sub / captain-swap flexibility).

**Who it is for:** the user only, on their own Windows PC. No hosting, no accounts.

**Success looks like:**
- Each matchday the user can import the fantasy export, refresh game data and get a full decision dashboard in a few minutes.
- Projections measurably beat a "season average FPT" baseline in walk-forward backtests (lower MAE, higher Spearman rank correlation), and the 20–80% ranges are calibrated (≈60% of outcomes fall inside).
- Defense-vs-Position opponent analysis is at least as detailed as the official per-position "PIR conceded" tables that used to exist.
- The squad page quantifies the value of T-slot spread (expected points gained from captain swaps and bench subs).

### What the user said vs. assumptions

| Said by user | Assumed (to confirm/configure) |
|---|---|
| Use: PIR-scored fantasy | Fantasy game rules not given in full: squad size, starters, captain multiplier, lineup position rules, win bonus — all are **settings** with defaults |
| Local, just for me | Python is acceptable on the PC (already installed) |
| All four decisions: buy/sell, value, projections, captain/consistency | — |
| Fantasy export `players_stats.xlsx` downloadable every round | Its column layout stays stable between rounds (validated on import) |
| Python + Streamlit | — |
| Complex projection: stat-by-stat, ML, outcome ranges, game situation | Euroleague public API provides box scores for this and the previous 3 seasons |
| Very analytical opponent stats / PIR vs team by position | Positions = the fantasy game's Guard/Forward/Center |
| T1/T2/T3 = game day within a round; subs/captain moves allowed only to players who haven't played yet | T-slots are numbered by distinct game dates within a matchday |

## 2. Data sources

### 2.1 Fantasy export (per matchday)
File `players_stats.xlsx`, one sheet, ~360 rows + a footer line `Reference matchdays: 1, 2, …, N`.

Columns: `ID, Name, Surname, Active, Position, Team, FPT, Quotation, Plus, Pts, Reb, Ast, Stl, Tov, Blk, Blka, Fd, Pf, Fg missed, Ft missed, Win 1-10, Win 11-20, Win 20, Win ot, Loss 1-10, Loss 11-20, Loss 20, Loss ot`.

- Players: `ID` numeric; stat columns are per-game averages over the reference matchdays; win/loss columns are `-`.
- Head coaches: `ID` = `-`, stat columns `-`; win/loss columns are the share of games in each margin band.
- `Quotation` = price (credits), `Plus` = price change, `FPT` = average fantasy points.
- Observed: `FPT − PIR(from components)` ranges 0 to +1.9 and grows with team win rate → the game adds a win bonus. Its size is estimated from data (§4.6) unless the user configures it.

### 2.2 Euroleague public API
Used for: season fixtures (round, date/time, home/away, final status), per-game box scores (per player: minutes, starter flag, points, 2P/3P/FT made/attempted, OREB/DREB, AST, STL, TOV, BLK, blocks against, fouls committed/drawn, official PIR), team totals (for pace), and player positions for players absent from the fantasy file.

Seasons: current (`E2026`) and the previous three (`E2023`–`E2025`) for priors and ML training.

The exact endpoints (api-live.euroleague.net v1/v2/v3, or the `euroleague-api` Python package wrapping them) are confirmed in a **first implementation task (spike)**. The client module hides the choice from the rest of the app.

## 3. Architecture

```
 Fantasy export (.xlsx) ─┐
                         ├─► SQLite (local) ─► metrics / DvP / projection engine ─► Streamlit pages
 Euroleague API ─────────┘
```

Python 3, pandas, numpy, scikit-learn, SQLite (stdlib), Streamlit, Plotly (charts), openpyxl (xlsx). Tests with pytest.

### Modules (each one purpose, testable alone)

| Module | Responsibility | Depends on |
|---|---|---|
| `store` | SQLite schema, read/write helpers | — |
| `fantasy_import` | Parse + validate the export, store as matchday snapshot | `store` |
| `el_client` | Fetch fixtures and box scores; incremental, cached | `store` |
| `matching` | Link fantasy players/teams ↔ Euroleague IDs; override file | `store` |
| `pir` | PIR / FPT calculation from components | — |
| `metrics` | Form, minutes trend, consistency, PIR breakdown, value, price history | `store`, `pir` |
| `dvp` | Defense vs Position aggregates, indices, ranks, splits | `store`, `pir` |
| `slots` | T-slot assignment per matchday | `store` |
| `projection` | Minutes model, stat rates, Monte Carlo sim, ML challenger, blend | `metrics`, `dvp`, `slots` |
| `backtest` | Walk-forward evaluation | `projection` |
| `squad` | Squad T coverage, captain-swap and sub strategy simulation, what-if transfers | `projection`, `slots` |
| `app/` | Streamlit pages only — no calculation logic | all above |
| `settings` | Game rules and thresholds (JSON file + UI) | — |

### Storage (SQLite tables, main ones)
`snapshots` (matchday, imported_at, file hash), `fantasy_players` (snapshot × player: price, plus, FPT, stat averages, position, team), `fantasy_coaches` (snapshot × coach: price, FPT, margin-band shares), `el_players`, `el_teams`, `games` (season, round, datetime, home, away, scores, final flag), `box_player` (game × player: all components, minutes, starter, official PIR), `box_team` (game × team totals), `player_map` (fantasy ID ↔ EL player code), `availability` (matchday × player: out / doubtful, set by user), `squad` (user's roster, starters, captain), `projections` (matchday × player: all outputs, model version).

## 4. Metrics

All per-game metrics use the game logs; DNP games are counted separately (DNP rate) and excluded from averages.

### 4.1 Buy / sell
- Form: avg PIR last 3 and last 5 vs season; trend arrow (↑ / → / ↓, threshold configurable).
- Minutes trend: last 5 vs season avg minutes.
- PIR per 30 minutes.
- PIR breakdown: scoring, rebounding, playmaking (AST+FD), defense (STL+BLK) vs negatives (misses, TOV, blocks against, fouls).

### 4.2 Consistency / captain
Floor (P20), ceiling (P80), standard deviation, boom rate (% ≥ 20 PIR), bust rate (% < 5), DNP rate. Thresholds configurable.

### 4.3 Value
Projected FPT per credit (next matchday), season FPT per credit, price trend from stored snapshots.

### 4.4 PIR / FPT
`PIR = PTS + REB + AST + STL + BLK + FD − (FGA−FGM) − (FTA−FTM) − TOV − BLKA − PF`.
`FPT = PIR + win_bonus × win` for players. Coaches: FPT from margin band of the result (band points per setting, initially estimated from the export).

### 4.5 Unit tests anchor
`pir` is verified against the official PIR in every box score fetched.

### 4.6 Win bonus estimate
Regress `snapshot FPT avg − PIR avg (from game logs over the same matchdays)` on each player's share of games won. Shown in Settings; user can override.

## 5. Defense vs Position (DvP)

Positions: fantasy Guard / Forward / Center. Players not in the current export: position from the EL API, mapped (PG/SG/G→Guard, SF/PF/F→Forward, C→Center; hybrids by first listed).

For each team × position, aggregate opposing players' production in games vs that team:
- PIR and FPT-equivalent conceded; every component (PTS, OREB, DREB, AST, STL, BLK, FD, TOV, BLKA, PF, FG missed, FT missed); 2P/3P/FT made, attempted, %.
- Three normalisations: per game, per 40 player-minutes, per 100 possessions (possessions ≈ FGA + 0.44·FTA − OREB + TOV, averaged for both teams).
- Index vs league average (%), rank 1–20. Empirical-Bayes shrinkage toward the league average weighted by minutes sample.
- "How they concede": components with largest positive/negative index.
- Splits: season, last 5 games, home/away, starters/bench, previous seasons.

Views: heatmap (teams × positions, metric and window selectable), team page with trends, fixture difficulty grid (next 3–5 matchdays per position), player matchup view (player component strengths × next opponent's component indices + the player's history vs that team).

## 6. T-slots

For each matchday, distinct game dates (local CET date) of that round's games are ordered and numbered T1, T2, T3, … Each player/coach gets the T of their team's game. If a team plays twice in one matchday (rare), the player has both slots and both games are summed for projections.

T is shown as a column/filter everywhere players are listed and is an input to the squad simulation (§8).

## 7. Projection engine

Projections are per player per upcoming matchday. Four layers.

### Layer 1 — Minutes
- Baseline: exponentially weighted minutes (recent games weighted more), starter rate.
- Teammates out (from `availability` + recent DNPs): their expected minutes redistributed to same-position teammates in proportion to historical share.
- Blowout risk: expected |margin| (from team-strength model) reduces starters' minutes / raises bench minutes; coefficients fitted on historical games.
- Rest days since last game, second game in ≤ 2 days: fitted adjustment.
- Foul trouble: players with high PF per minute get a wider, lower minutes distribution.
- DNP probability: from recent DNPs and user availability marks (out = 1.0; doubtful = configurable, default 0.5).
- Output: minutes distribution (DNP mass + truncated normal).

### Layer 2 — Stat-by-stat per-minute rates
For each component c (2PA, 2P%, 3PA, 3P%, FTA, FT%, OREB, DREB, AST, STL, BLK, FD, TOV, BLKA, PF):
- Player rate: exponentially weighted current-season rate, shrunk toward a prior built from the player's previous seasons and his position/role average (weight grows with minutes played).
- × opponent DvP index for c at his position (shrunk, from §5).
- × pace factor (expected possessions / league average).
- × home/away factor for c (league-wide, fitted).
- × usage factor when high-usage teammates are out (shot and assist components).
- FG/FT misses are derived: attempts × (1 − expected %), not projected directly.

### Layer 3 — Monte Carlo simulation (10,000 sims per matchday, fixed seed)
Per game: draw margin from N(expected margin, σ fitted) — shared by all players in that game; determines win bonus, coach band and blowout minutes.
Per player: draw minutes (Layer 1); draw a shared "night" factor (log-normal, fitted) scaling efficiency; draw counting components from negative binomial with mean = rate × minutes; shot makes from binomial with Beta-drawn %. Compute PIR → FPT.
Outputs: mean, median, P20, P80, P(≥20), P(≥30), P(DNP). Coaches from the same margin draws.

### Layer 4 — ML challenger
- Gradient boosting (scikit-learn `HistGradientBoostingRegressor`) predicting FPT; quantile models for P20/P80.
- Training rows: player-games from E2023–current, features computed strictly from data before each game.
- Features: rolling form (3/5/10), EW minutes, starter rate, rest days, home/away, opponent DvP indices per component, pace, teammates-out minutes share, expected margin, Layer 1–3 outputs.
- Final projection = w·sim + (1−w)·ML, w chosen per backtest; both shown.

### Backtest (walk-forward)
For each past matchday m: train/fit on data before m, project m, compare to actuals. Report MAE, Spearman rank correlation, P20–P80 coverage, for: baseline (season avg), simulation, ML, blend. A leakage test asserts no training row is dated on/after m.

## 8. Squad and T-slot strategy

User enters their squad on the Squad page: players + coach, starters, captain. Settings hold squad size, starters count, lineup position rules and captain multiplier (defaults to confirm with the user's game rules).

- **T coverage:** count of starters / bench / captain candidates per T.
- **Captain-swap simulation:** using Layer 3 joint draws, evaluate "captain C (slot Ti); after his game, if FPT < θ, move captain to the best not-yet-played player in a later slot". Grid-search θ; report expected FPT with and without the swap option, gain, and swap probability. Also ranks the best starting captain *given* the swap option.
- **Bench-sub simulation:** if a starter DNPs or scores < θs, sub in a later-slot bench player (respecting lineup rules); report expected gain.
- **What-if transfer:** replace player A with B → change in expected squad FPT including swap/sub option value and the T coverage change, plus price difference.

## 9. App pages (Streamlit)

1. **Round dashboard** — next matchday, data freshness, top projections, value picks, captain shortlist, risers/fallers, alerts (unmatched players, stale data, outs not set).
2. **Player explorer** — filter (position, team, price, T), sortable columns (price, FPT, proj, P20/P80, value, form, minutes trend, next opponent DvP rank, T), CSV export.
3. **Player profile** — PIR/minutes game log with rolling averages, projection distribution, PIR breakdown, price history, matchup view, history vs teams.
4. **Compare** — 2–4 players, overlaid projection distributions.
5. **Captain picker** — ranked by expected FPT with safe↔upside slider (P20 vs P(≥30) weighting).
6. **Squad** — roster entry, T coverage, captain-swap and sub simulations, what-if transfers.
7. **Opponents (DvP)** — heatmap, team pages, fixture difficulty.
8. **Model** — backtest results, blend weights, settings (game rules, win bonus, thresholds).
9. **Data** — import export, refresh games, matching overrides, mark out/doubtful.

## 10. Round workflow
Download export → Data: import → Refresh games → mark outs/doubtfuls → dashboard / squad.

## 11. Error handling
- API unavailable/changed: fall back to cached data, show staleness, clear error.
- Export layout change: validator lists missing/unexpected columns; import refused rather than partial.
- Re-importing a matchday replaces that snapshot (by matchday), keeps file hash.
- Unfinished/live games excluded until final.
- Unmatched players/teams listed on the dashboard and Data page; never silently dropped.

## 12. Testing
pytest:
- Importer on a copy of the real export (players, coaches, footer matchdays, validation errors on altered copies).
- `pir` vs official PIR in fetched box scores.
- `metrics`, `dvp`, `slots` on small hand-built fixtures with known answers.
- Simulation: seed reproducibility; sample means converge to analytic means on a synthetic player.
- ML leakage test; backtest runs end-to-end on a small cached dataset.
- `squad`: swap strategy never worse than no-swap on the same draws; lineup rules respected.

## 13. Out of scope (possible later)
Budget-constrained squad optimizer; multiple fantasy teams; hosting/sharing; automatic injury feeds.

## 14. Open items (settings with defaults, confirm during build)
Squad size, number of starters, lineup position rules, captain multiplier, coach band points, win bonus (estimated), boom/bust thresholds, doubtful DNP probability.
