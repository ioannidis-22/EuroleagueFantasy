# Euroleague Fantasy Value Picks

One local page for a PIR-scored Euroleague fantasy game played like a stock exchange, where profit
comes from price rises. Each matchday you upload the game's export. The page shows every player's
expected price change for the next round, labelled BUY, HOLD or SELL, along with the formula and
its fitted numbers.

Design: `docs/superpowers/specs/2026-11-18-value-function-design.md`

## Setup (once)

Requires Python 3.12+. Keep the folder on a short path (for example `C:\elfantasy`): Windows'
260-character path limit breaks the install in deeply nested folders.

1. Double-click `setup.bat`. It creates `.venv` and installs everything.
2. Double-click `run_app.bat`. The page opens in your browser.

## Every matchday

1. Download `players_stats.xlsx` from the fantasy site.
2. Open the page (`run_app.bat`), upload the file and click **Run**.
3. The page imports the export, downloads new box scores, refits the model and scores the first
   round with no game played yet. The box-score server rate-limits bursts, so the first run of
   the season, or a run after a long gap, can pause for a few minutes.
4. Read the formula card, then the table. Filter it by label or position, and download the Excel
   file for the per-channel stat analysis and the full model.

Upload every matchday's export. The game's price rule is fitted from exports of consecutive
matchdays, and until two are stored the page uses default numbers and says so. The backtest's
BUY/SELL hit rates also come from stored exports.

## What the page shows

- **Formula.** `value = P(play) × k × (xPIR − break-even) + (1 − P(play)) × d`, where
  `break-even = a × price + c`. The page shows the fitted `k, a, c, d` and where they came from.
- **xPIR**, the expected PIR if he plays. It is built per scoring channel (2-point and 3-point
  attempts, fouls drawn, rebounds, assists, steals, blocks, turnovers, blocks against, fouls
  committed) as volume × efficiency, scaled by the next opponent's Defense vs Position. It is then
  calibrated with home/away and last-game terms. The expander lists how strongly each stat is
  pulled toward its position average, along with the bounce-back weight.
- **Check accuracy.** A button that runs the backtest (about 10 seconds) and shows one line: how
  far xPIR missed in past rounds against the season average, and how often BUY and SELL calls
  were right.
- **Table.** Every player in the export, best value first: price, last price change, opponent and
  T-slot, P(play), xPIR, break-even, value, ROI, label and DIP. **DIP** marks a BUY with a season
  average of 10+ PIR whose price fell by 0.3 or more last round. **NO DATA** marks a player not
  linked to Euroleague data or without a game next round. These rows stay at the bottom.

## Settings and manual links

Both files are optional and live in `data/`:

- `settings.json`: `value_buy` and `value_sell` (the BUY/SELL thresholds, default ±0.10),
  `dip_min_avg` and `dip_drop` (default 10 and 0.3), `api_delay_s` and `season`.
- `player_overrides.json`: `{"<fantasy ID>": "<Euroleague player code>"}` for players the name
  matcher misses.

## Where data lives

Everything is in `data/` (not in git): `elfantasy.db` (SQLite), `cache/` (downloaded box scores),
`imports/` (your exports by matchday), `player_overrides.json` and `settings.json`.

From a terminal, `.venv\Scripts\python -m elfantasy refresh` and
`.venv\Scripts\python -m elfantasy import path\to\players_stats.xlsx` still download games and
import an export without the page.

## Tests

```bash
.venv\Scripts\python -m pytest            # offline suite
.venv\Scripts\python -m pytest -m live    # also hits the real API (~2 min)
```
