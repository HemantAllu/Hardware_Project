# Running the board on real market data (any company)

## What you get
* `hft_dashboard.py` sends real 1-minute bars of the company you name to the FPGA as ticks and checks
  every report live. Companies: **apple** (AAPL), **nvidia** (NVDA), **google** (GOOGL),
  **microsoft** (MSFT), **amazon** (AMZN), **walmart** (WMT), **meta** (META), **tesla** (TSLA), or
  `all` for these eight. Any other Yahoo Finance ticker works too (e.g. `--company JPM`).
  Graphs: price with the hardware's BUY/SELL marks, hardware position, **return on the starting cash**
  (mark-to-market, %), and HW vs SW latency. `--no-plot --save-png run.png` saves the same picture.
* `verify_run.py` checks a finished run on its own and draws `<log>_verify.png`:
  the Yahoo price downloaded again vs the price the FPGA echoed, their difference (a flat zero line
  means the graph matches the market), and the board's position vs the reference model.

## One-time setup (PC)
```
pip install yfinance pandas matplotlib pyserial
```
Program the board with the new bitstream first: this version changes the firmware (`src/mem/imem.mem`)
and adds a reset/config path to the accelerator, so re-run synthesis, implementation and bitstream.

## Run it (from the `extras` folder)
| What | Command |
|---|---|
| Replay the latest US session of one company (works any time) | `python hft_dashboard.py --company nvidia --port COM6` |
| Replay a chosen day (last ~7 days) | `python hft_dashboard.py --company tesla --day 2026-10-09 --port COM6` |
| Real time, during US market hours | `python hft_dashboard.py --source live --company meta --port COM6` |
| **All eight companies, latest session each** | `python hft_dashboard.py --company all --port COM6` |
| All eight, the last 4 sessions each | `python hft_dashboard.py --company all --days 4 --port COM6` |
| A chosen set | `python hft_dashboard.py --company apple,microsoft,WMT --port COM6 --out-dir results_demo` |
| Save data, replay offline later | `python download_market_data.py --company all` then `python hft_dashboard.py --source csv --company walmart` (reads `WMT_ticks.csv`) |
| Check a run afterwards | `python verify_run.py run_NVDA_<day>_<time>.csv` (several logs at once: `python verify_run.py results_demo/*.csv`) |
| No board (Python model only) | add `--port none` |

The old commands still work: `--source apple-replay` / `apple-live` are the same as `--source replay` /
`live` (the default company is Apple), and `download_apple_data.py` is the same as `download_market_data.py`.

## Several companies (`--company all`, a list, or `--days N`)
No live window: each company and session is one run, one after another, through the same board.
Every run starts clean with the same settings (RESET, $1,000,000,000 starting cash, 5000-lot position
limit, breakout levels from that company's previous session). Replays go as fast as the board answers,
about 390 bars in a few seconds; add `--speed 10` to slow down. The output folder
(`results_<date>_<time>` or `--out-dir`) holds:
* `<TICKER>_<day>.csv` + `.cfg`: the log of each run (check with `verify_run.py`), and `<TICKER>_<day>.png`
  with the dashboard picture (price + trades, position, returns, latency)
* `summary.csv`: one row per run, with trades, refused BUYs, final position, **strategy return**,
  **buy-and-hold return** (bought at the first bar's close, valued at the last bar's close), best and
  worst return, the FPGA checks (HW = SW, HW = model, echo, missing reports) and PASS/FAIL
* `summary.md`: the same per company (average per session when there are several), ready to paste
* `comparison.png`: strategy return (blue) next to buy-and-hold (gray) for every company, best at the
  top, with the averages and on how many companies the strategy did better

How to read it: the returns are what the strategy really did on those sessions. They are intraday,
mark-to-market on the whole-bar notional, with no fees or slippage. Expect values of a fraction of a
percent per session, positive on some companies and negative on others; buy-and-hold is the fair
yardstick for the same session. More sessions (`--days 4`, the most Yahoo keeps for 1-minute bars)
give a steadier picture than one day. The FPGA column shows that the board's hardware decisions
equal the RISC-V software and the Python model on every tick. That is the hardware result, whatever
the market did.

A company whose data cannot be downloaded (no internet, rate limit, unknown ticker) is listed as FAIL
with the reason, and the other companies still run.

US market hours: 09:30-16:00 New York = **19:00-01:30 IST** until 1 Nov 2026, then 20:00-02:30 IST.
Live mode first sends the day's bars so far (fast), then one new bar per minute.
Keep **SW0 (kill switch) off** during a verification run: the PC cannot see the switch, so a blocked trade
would show up as a model mismatch.

## How real data is sent
* one tick = one 1-minute bar; `price` = close in **cents**, `vol` = volume in **lots of 1000 shares**,
  rounded to the nearest whole lot. A bar with less than half a lot (or no volume) is sent with vol = 0:
  it still updates the moving average but never trades and adds nothing to VWAP (v11 sent such a bar
  as 1 lot, i.e. 1000 traded shares)
* breakout levels = the **previous session's high and low** of the same company (override with
  `--brk-high/--brk-low` in USD; with several companies the override applies to all of them, so normally leave it out)
* position limit = 5000 lots (`--limit`)
* starting cash = $1,000,000,000 (`--starting-cash`). Every trade is the whole bar volume, and one lot
  costs about $250,000, so a typical 100-lot bar costs about $25M. With much less cash every BUY is
  refused, and the run "passes" without a single trade. The dashboard and `verify_run.py` print how many
  signals were refused and warn about it.
* at start the dashboard sends RESET, then the breakout levels, position limit and starting cash, so every run starts clean
  (no more leftover position from an earlier run; the CPU RESET button is not needed)

## How to tell it is correct
1. During the run, the dashboard box shows `HW = SW`, `HW = model` and `price echo errors`; it turns red on any mismatch.
2. Afterwards, `verify_run.py` prints PASS/FAIL for link, HW vs SW, model, latency, market data and returns,
   plus the number of trades and of refused signals. A run with 0 trades proves very little: raise
   `--starting-cash`.
3. Open the same day on Yahoo Finance (AAPL, 1D, 1-minute) or TradingView: the candles in the dashboard and the
   black line in `_verify.png` follow the same shape. Times are New York time.
4. On the board: the 7-segment display shows the hardware position in decimal lots; LED2 lights on any HW/SW difference;
   LED3 lights if packets were dropped (see "Flow control").

## Limits to mention in the presentation
* Free data is 1-minute bars, not exchange tick-by-tick data, and Yahoo can lag by up to about a minute.
  Yahoo serves 1-minute bars for roughly the last 30 days only, and at most about 7-8 days per request
  (unofficial limits that change without notice); keep the CSV files you used, with the download date.
* The signal uses a bar's close and the trade is booked at that same close. In a backtest this is
  optimistic: the close is only known when the bar has ended, so a real order would fill at the next
  available price. Treat the return figures as an illustration of the mechanism, not as achievable
  profit, and always show buy-and-hold next to them (the comparison chart does).
* The synthetic companies (README_SYNTHETIC_DATA.md) were generated so that this strategy is
  profitable on them: a gain there shows that the system works end to end, not that the strategy has an edge.
* Yahoo can revise the newest bar for a few minutes, so verify a live run a few minutes after it ends.
* Trade size is the whole bar volume (a design choice of the accelerator: 100 % of the market's volume in
  that minute, which no real trader could get), so P&L in dollars is notional. Portfolio mode can cap it
  with `MAX_LOTS` (`--max-lots`).
  `--starting-cash` sets the fully-funded account balance (default: $1,000,000,000 for real data). Buys that exceed it
  are rejected; sells are rejected unless the lots are already held; zero-volume ticks never trade. Cash and holdings
  cannot become negative.

## Protocol (PC <-> FPGA, 115200 8N1)
* PC -> FPGA, 12 bytes: id, price, vol (uint32, little endian). Ids with bit 31 set are commands:
  `0x80000000` RESET, `0x80000001` breakout (price = high, vol = low), `0x80000002` limit (price = limit),
  `0x80000003` starting cash (price = low 32 bits, vol = high 32 bits). The final RESET applies all configuration.
* FPGA -> PC, 40 bytes: `0xAA55AA55`, id, price, vol, HW decision, HW latency, SW decision, SW latency,
  HW position, `0x55AA55AA`. Decision: 0 none, 1 BUY, 2 SELL.

## Flow control
The PC must wait for the report of one packet before it sends the next one. The dashboard always does this.
Every report carries the id of the packet it answers, and the PC tools only accept the report whose id
matches the packet just sent (a report that arrives late for an earlier packet is dropped). If no report
arrives within 1.5 s the run **stops** with a message: the board may or may not have processed that packet,
so the comparison with the Python model could no longer be trusted (v11 carried on and could stay shifted
by one tick for the rest of the run). Press CPU RESET and start the run again.

Throughput: one tick costs a 12-byte packet (1.04 ms) plus a 40-byte report (3.47 ms) at 115200 baud, i.e.
about 4.5 ms of line time, plus the USB-serial adapter's latency timer (FTDI default 16 ms, which then
dominates). On Linux the dashboard lowers it to 2 ms automatically when it is allowed to; on Windows set it in
Device Manager -> the COM port -> Port Settings -> Advanced -> Latency Timer = 2 ms. Estimate: about
50 ticks per second with the 16 ms default, about 150 with 2 ms (measure it on your PC). The on-chip
decision itself takes 5 cycles = 50 ns; the link, not the FPGA, sets the rate.
A report takes about 3.5 ms (40 bytes) and a packet only about 1 ms, so a sender that streams without waiting
gets ahead of the board. If a packet arrives while the previous one has not been read by the CPU, the board
drops the **new** packet for both the CPU and the accelerator, so hardware and software never drift apart.
The drop is counted in OVERRUN (0x3000_002C, cleared by RESET) and lights LED3, and that packet gets no report.

## Replaying a real run in the RTL simulation
Any dashboard log can be replayed through the Verilog simulation (soc_top running the firmware) to show
that the simulated hardware takes exactly the same decisions as the board:
```
python3 tools/check_hft.py fromlog results_demo/NVDA_2026-10-09.csv nvda_ticks.txt
iverilog -g2012 -o sys.vvp tb/tb_hft.v ../src/rtl/*.v
vvp -n sys.vvp +IMEM=../src/mem/imem.mem +DMEM=../src/mem/dmem.mem +TICKS=nvda_ticks.txt > nvda_sim.log
python3 tools/check_hft.py check nvda_ticks.txt nvda_sim.log
```

## Log columns (CSV)
tick, time, open, high, low, close, volume, price_sent, vol_sent, price_echo, vol_echo, hw_dec, hw_lat, sw_dec,
sw_lat, hw_pos, model_dec, model_pos, cash_usd, equity_usd (cash + holdings at the bar close), return_pct.
