# Value Function — Design (short)

Date: 2026-11-18 · Status: draft for approval · Builds on branch `plan1-data-foundation`

## Intent

The user plays the fantasy game like a stock exchange: profit comes from player **price rises**,
which count 100% even when the player sits on the bench (bench players score only 50% of their
PIR). Before each round they want to run **one function** that labels every player
**BUY / HOLD / SELL** by his expected price change next round.

- **Goals:** a single readable formula; weights learned from this season's games, not guessed;
  buy and sell come from the same number; graded on past rounds.
- **Non-goals:** the app pages (later), the full projection engine (Plan 2), squad or captain
  optimisation. Points are a secondary column only.
- **Anti-goals:** one-game wonders at the top of the list; churning players on noise; a black box
  the user can't read.

## The game's price rule (measured, refit as exports arrive)

The two exports (matchday 11 → 12, n = 240 players who played) give, with R² 0.98 and a typical
error of 0.04 credits:

- Played: `Δprice = k · (PIR_round − BE(price))`, with `BE(price) = a · price + c`
  - Today: `k = 0.042`, `a = 1.14`, `c = −1.0`, so Kamenjas (4.8) breaks even at 4.5 PIR and
    Bryant (17.6) at 19.1.
- Didn't play: `Δprice = d`, today `d ≈ −0.06` (observed −0.1 or 0).
- The win bonus (+0.03) and minutes add nothing, so they are left out.
- Timing: the export labelled matchday N is taken before round N finishes. The price change
  between export N−1 and export N comes from **round N−1's PIR** only. Round N's partial games
  had no effect.

`k, a, c, d` live in one place. A refit fits them on every pair of consecutive stored exports.

## The value function

```
value  = P(play) · k · (xPIR − BE(price)) + (1 − P(play)) · d
ROI    = value / price
label  = BUY if value ≥ +0.10 · HOLD if between · SELL if value ≤ −0.10   (thresholds configurable)
```

**xPIR** is expected PIR next round if he plays. It is built as **volume × efficiency** per
scoring channel, valued with the game's exact PIR arithmetic, because stats interact. A foul drawn
is worth `1 + (FTA per foul) × (2·FT% − 1)`. This season that ranges from 1.32 (Shorts: 0.72 FTA per
foul, 72%) to 2.10 (Maledon: 1.31, 92%).

```
xPIR = xMin × Σ_channels  rate_per_min(c) × value(c)

channel             volume (per minute)        value per unit
2-point attempts    2PA                        3·2P% − 1
3-point attempts    3PA                        4·3P% − 1
fouls drawn         FD                         1 + (FTA/FD)·(2·FT% − 1)
off/def rebounds    OREB, DREB                 +1
assists             AST                        +1
steals, blocks      STL, BLK                   +1
turnovers           TOV                        −1
blocks against      BLKA                       −1
fouls committed     PF                         −1
```

Free throws are reached only through fouls drawn (FTA = FD × FTA/FD), so they aren't double-counted.

- **Rates and efficiencies** use only games before the round, weighted toward recent games.
  - Each one is pulled toward its position average, with a per-stat strength **fitted from how
    repeatable that stat is** this season. FT% settles fast; 3P%, steals and blocks swing, so they
    stay closer to average until the sample is large. These fitted strengths are the
    "stat-line importance" table.
- **Expected minutes:** a weighted average of season and last-3 minutes, with weights fitted.
- **Opponent effect per channel:** the next opponent's Defense vs Position index for that
  component at his position, computed from games before the round, multiplies the matching volume
  (for example, a team that fouls a lot boosts FD). Efficiencies are adjusted by the 2P%, 3P% and
  FT%-allowed indices only if the backtest shows that helps.
- **Home/away:** one fitted factor.
- **Bounce-back term:** last game's PIR minus his norm, with a fitted weight that is refit every
  round.
  - The user expects good players to bounce back after a bad game. This season's data (126 bad games
    by 10+ PIR players) shows no bounce-back: weight +0.09 per PIR, likely range −0.02 to +0.18.
  - The term stays in so the formula picks up the effect if it appears. The backtest reports its
    current weight.
- **Calibration:** a final fitted scale and intercept on xPIR, checked by the backtest against
  "season average PIR". Good players' next games run below their averages (fitted slope 0.83), and
  the calibration absorbs that.
- **Buying the dip** is handled through price: a bad round lowers his price, which lowers
  break-even by about 1.14 × the drop, while xPIR still rests on his whole season.
- **P(play):** share of his team's last 5 games he played, smoothed toward 0.9 for small samples.

**Stat analysis output:** a second sheet per player and channel, showing volume, efficiency, PIR
per unit, PIR per game and the next opponent's effect. This shows *why* a player is a BUY or SELL.

## Running it

`python -m elfantasy value` (optional `--round N`, `--out file.xlsx`):

1. Uses the latest imported export (prices) and the downloaded games (refresh first).
2. Fits xPIR on all completed rounds, then scores every player for the next round.
3. Prints the top 15 BUY and SELL and writes `data/value_round_<N>.xlsx` with two sheets: the value table and the per-channel stat analysis.
   - Columns: player, team, position, price, last price change, opponent, home, P(play), xPIR,
     break-even, value, ROI, label, DIP.
   - **DIP** flags players with a season PIR average of 10+ whose price fell by 0.3 or more last
     round and who are still labelled BUY.

`python -m elfantasy value --backtest` replays rounds 5 onward. Each round is fitted only on
earlier rounds and predicted, then it reports:
- xPIR error compared with "season average PIR".
- How often BUY / SELL calls would have gained or lost money, using the price rule on the actual
  PIR.

## Approaches considered

- **A. Hand-set weights:** simple, but the weights are guesses.
- **B. Weights fitted on this season's games: chosen,** refined after the user's free-throw example into a volume × efficiency channel model. Still one readable formula, with
  evidence behind every weight, and graded by the backtest.
- **C. The full projection engine (Plan 2):** heavier and harder to read; overkill for one
  decision formula.

## Left to the builder

Ridge strength, the exact smoothing prior, module layout (suggested: `src/elfantasy/price_rule.py`
and `src/elfantasy/value.py`) and tests (TDD, fixture-based, plus one real-data backtest run).
Opponent DvP for a past round must be computed only from games before that round.

## Open

Transfer limits or costs in the game are unknown. If transfers are limited, raise the SELL
threshold or sum value over 2–3 rounds. Kept as a setting.
