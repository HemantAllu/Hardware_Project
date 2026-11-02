# Synthetic (made-up) data on which the strategy makes a profit

## Read this first
On **real** market data our strategy (moving average + VWAP + breakout, 2-of-3 vote, risk checks)
wins on some days and loses on others. This folder adds **8 made-up companies, SYN1 to SYN8**,
whose prices are built to follow the pattern the strategy is designed to catch: the price breaks
above the previous day's high and then keeps climbing.

* These are **not real companies and not real prices**. The profit is designed into the data.
* What this shows: the hardware follows the trading rules correctly, and when the market behaves the
  way the rules expect, the rules make money.
* What this does **not** show: that the strategy makes money in the real market.
* Always say "synthetic data" when you show these results (slides, viva, report).

## Files
| File | What it is |
|---|---|
| `tools/make_profit_data.py` | the generator (fixed random seeds, so the same data every time) |
| `synthetic_data/SYN1_ticks.csv` ... `SYN8_ticks.csv` | the data, same format as `download_market_data.py` (time,open,high,low,close,volume) |
| `synthetic_data/synthetic_results.png` | chart of the results below |

Each company has 3 sessions of 390 one-minute bars (09:30-15:59):
* 2026-10-19: a sideways day. It is not traded; it only sets the breakout levels (its high and low).
* 2026-10-20 and 2026-10-21: the trading days. Each uses one of these shapes:
  **trend** (steady climb), **gapup** (opens higher, morning rally), **stairs** (rise, pause, rise),
  **late** (quiet morning, afternoon rally), **dipup** (small dip after the open, then a long climb).
  Small random wiggles are added to every minute, and volume is higher at the open, at the close
  and during rallies, like a real market.

Prices are in the same range as the real companies (about $95 to $593), and the starting cash, lot size
(1000 shares) and position limit (5000 lots) are the dashboard defaults.

## How to run (from the `extras` folder)
```
python tools/make_profit_data.py                     # (re)creates synthetic_data/  (already included)

# one company, one session (window, or --no-plot), with the board or with the Python model (--port none)
python hft_dashboard.py --source csv --company SYN1 --file synthetic_data/SYN1_ticks.csv --day 2026-10-20 --port COM6

# several companies at the same time, one shared cash account (hardware portfolio allocator)
python hft_dashboard.py --source csv --company SYN1,SYN2 --file synthetic_data/SYN1_ticks.csv,synthetic_data/SYN2_ticks.csv --day 2026-10-20 --port COM6

# all eight together (needs the 8-engine board image, HFT_N_MAX = 8; the zip default is 2)
python hft_dashboard.py --source csv --company SYN1,SYN2,SYN3,SYN4,SYN5,SYN6,SYN7,SYN8 ^
  --file synthetic_data/SYN1_ticks.csv,synthetic_data/SYN2_ticks.csv,synthetic_data/SYN3_ticks.csv,synthetic_data/SYN4_ticks.csv,synthetic_data/SYN5_ticks.csv,synthetic_data/SYN6_ticks.csv,synthetic_data/SYN7_ticks.csv,synthetic_data/SYN8_ticks.csv ^
  --day 2026-10-20 --port COM6

# check a finished run (use --offline: there is no Yahoo data for SYN companies)
python verify_run.py run_SYN1_2026-10-20_<time>.csv --offline
```
(`^` continues a line in the Windows command prompt; use `\` on Linux/macOS.)

## Results (simulated with the Python model, `--port none`, 2026-10-22)
The Python model is bit-exact with the hardware (0 mismatches in every run below), so the board
should give the same numbers. Run it on the board to get your own measured results.

### One company at a time ($1,000,000,000 starting cash each run)
| Company | Session | Trades | Strategy return | Buy and hold |
|---|---|---|---|---|
| SYN1 | 2026-10-20 | 31 BUY, 23 SELL | +1.4182% | +2.07% |
| SYN1 | 2026-10-21 | 44 BUY, 33 SELL | +0.8342% | +1.33% |
| SYN2 | 2026-10-20 | 18 BUY, 0 SELL | +5.2035% | +5.67% |
| SYN2 | 2026-10-21 | 30 BUY, 9 SELL | +2.7764% | +3.07% |
| SYN3 | 2026-10-20 | 6 BUY, 0 SELL | +3.4589% | +5.51% |
| SYN3 | 2026-10-21 | 34 BUY, 22 SELL | +2.6834% | +4.05% |
| SYN4 | 2026-10-20 | 67 BUY, 23 SELL | +3.7169% | +3.91% |
| SYN4 | 2026-10-21 | 14 BUY, 0 SELL | +5.5681% | +5.92% |
| SYN5 | 2026-10-20 | 23 BUY, 12 SELL | +1.8331% | +3.25% |
| SYN5 | 2026-10-21 | 21 BUY, 15 SELL | +1.3989% | +3.00% |
| SYN6 | 2026-10-20 | 17 BUY, 0 SELL | +3.6266% | +3.93% |
| SYN6 | 2026-10-21 | 27 BUY, 1 SELL | +3.9891% | +3.53% |
| SYN7 | 2026-10-20 | 18 BUY, 0 SELL | +4.4070% | +5.01% |
| SYN7 | 2026-10-21 | 20 BUY, 2 SELL | +3.5003% | +3.98% |
| SYN8 | 2026-10-20 | 8 BUY, 0 SELL | +3.3925% | +4.31% |
| SYN8 | 2026-10-21 | 7 BUY, 0 SELL | +3.5346% | +4.34% |

All 16 sessions are profitable (+0.83 % to +5.57 %).

### All eight together, one shared cash account
| Session | Allocator (hybrid, default) | Independent engines |
|---|---|---|
| 2026-10-20 | +4.80 % | +5.09 % |
| 2026-10-21 | +3.98 % | +4.73 % |

0 tick mismatches and 0 allocation mismatches in all four runs.

## Honest notes (say these if asked)
* Returns are mark-to-market on whole-bar trades, **with no fees and no slippage**.
* **Buy and hold does a little better than the strategy on most of these sessions.** On a steady
  climb, a rule that waits for confirmation (2 of 3 votes, and MA only after 3 earlier ticks) buys a
  little later than someone who bought at the open. The strategy's advantage is that it stays out of
  falling markets (no short selling, so it holds nothing while the price drops); these synthetic days
  have no falls, so that advantage does not show here.
* Some runs print "BUY signals were refused for lack of cash": the strategy has put all its cash into
  the stock and keeps saying BUY. That is the risk interlock working (no borrowing), not an error.
* The main result of the project is still the hardware one: a 5-cycle decision that matches the
  software and the reference model on every tick, on real and synthetic data alike.
