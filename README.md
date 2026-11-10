# Euroleague Fantasy PIR Assistant

A local app for a PIR-scored Euroleague fantasy game. It combines your fantasy export (prices and
fantasy points) with Euroleague box scores to show form, consistency, value, T-slots and
Defense vs Position.

Design: `docs/superpowers/specs/2026-11-10-euroleague-fantasy-pir-design.md`

## Setup (once)

Requires Python 3.12+. Keep the folder on a short path (for example `C:\elfantasy`): Windows'
260-character path limit breaks the install in deeply nested folders.

1. Double-click `setup.bat`. It creates `.venv` and installs everything.
2. Double-click `run_app.bat`. The app opens in your browser.
3. On the **Data** page, click **Refresh games**. It downloads this season's fixtures and box
   scores (a few minutes the first time).

## Every round

1. Download `players_stats.xlsx` from the fantasy site.
2. **Data** page → *Import fantasy export*.
3. **Data** page → *Refresh games*.
4. Read the **Round dashboard**, then dig into **Players**, **Player**, **Compare** and **Opponents**.

From a terminal, `.venv\Scripts\python -m elfantasy refresh` and
`.venv\Scripts\python -m elfantasy import path\to\players_stats.xlsx` do the same.

## Pages

| Page | What it shows |
|---|---|
| Round dashboard | Next round by T-slot, data freshness and alerts, in/out of form, value, price risers/fallers, most reliable |
| Players | Filterable, sortable table of every player; CSV export |
| Player | Game log, minutes, PIR breakdown, floor/ceiling, price history, next matchup, this season vs each team |
| Compare | 2–4 players side by side |
| Opponents | Defense vs Position heatmap, team detail, fixture difficulty for the next rounds |
| Data | Import, refresh, unmatched players and manual links, settings |

## Where data lives

Everything is in `data/` (not in git): `elfantasy.db` (SQLite), `cache/` (downloaded box scores),
`imports/` (your exports by matchday), `player_overrides.json` (manual player links) and
`settings.json`.

## Data sources and limits

- Only the current season is used. Box scores come from the official live box-score service,
  which rate-limits bursts. The app waits when told to, so a refresh can pause for a few minutes.
- The fantasy game's win bonus is estimated from your data (Data → Settings shows it). You can
  set it by hand.
- Players with no games this season, usually injured or departed, show as unmatched. That's expected.

## Tests

```bash
.venv\Scripts\python -m pytest            # offline suite
.venv\Scripts\python -m pytest -m live    # also hits the real API (~2 min)
```
