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

**xPIR** is expected PIR next round if he plays: a linear formula whose weights are fitted on this
season's player-games, using only what was known before each round.

- **Inputs, all from games before the round:**
  - Per-game season averages of each PIR part: points, offensive and defensive rebounds, assists,
    fouls drawn, steals, blocks, missed 2s, missed 3s, missed FTs, turnovers, blocks against,
    fouls committed. The fitted weights on these are the "stat-line importance" table.
  - PIR over the last 3 games and in the last game (form).
  - Minutes: season average and last-3 average.
  - Games played (sample size).
  - The next opponent's Defense vs Position PIR index for his position.
  - Home or away.
- **Target:** his PIR in that round (rounds where he played).
- **Fit:** ridge regression on standardised inputs, rounds 4 onward (enough history per row). The
  output shows each input's weight in plain units.
- **P(play):** share of his team's last 5 games he played, smoothed toward 0.9 for small samples.

## Running it

`python -m elfantasy value` (optional `--round N`, `--out file.xlsx`):

1. Uses the latest imported export (prices) and the downloaded games (refresh first).
2. Fits xPIR on all completed rounds, then scores every player for the next round.
3. Prints the top 15 BUY and SELL and writes the full table to `data/value_round_<N>.xlsx`.
   - Columns: player, team, position, price, opponent, home, P(play), xPIR, break-even, value,
     ROI, label.

`python -m elfantasy value --backtest` replays rounds 5 onward. Each round is fitted only on
earlier rounds and predicted, then it reports:
- xPIR error compared with "season average PIR".
- How often BUY / SELL calls would have gained or lost money, using the price rule on the actual
  PIR.

## Approaches considered

- **A. Hand-set weights:** simple, but the weights are guesses.
- **B. Weights fitted on this season's games: chosen.** Still one readable weighted formula, with
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
