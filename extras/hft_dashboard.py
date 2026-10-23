"""hft_dashboard.py - drive the FPGA trading accelerator and check it live.

One company (live window):
  python hft_dashboard.py --company nvidia                 replay the latest session of Nvidia
  python hft_dashboard.py --company tesla --day 2026-10-09 replay a chosen session (last ~7 days)
  python hft_dashboard.py --source live --company meta     real time (US market hours)
  python hft_dashboard.py --source csv --file NVDA_ticks.csv --company nvidia
  python hft_dashboard.py --source random                  synthetic random walk
Several companies (no window; one log + picture per run, a summary table and a comparison chart):
  python hft_dashboard.py --company all                    apple, nvidia, google, microsoft, amazon,
                                                           walmart, meta, tesla - latest session each
  python hft_dashboard.py --company all --days 4           the last 4 sessions of each company
  python hft_dashboard.py --company apple,tesla,WMT --out-dir results_demo
Several companies AT THE SAME TIME from ONE cash account (one FPGA engine per company, hft_multi.v;
the board image is built with 2 engines - HFT_N_MAX in soc_top.v).  By default the HARDWARE PORTFOLIO
ALLOCATOR decides for the whole portfolio once per minute (hft_alloc.v: rank + rotate + reweight,
see hft_hybrid.py); the window shows every company's last hour on one screen, click a company for
its whole day:
  python hft_dashboard.py --company apple,nvidia --together              latest common session
  python hft_dashboard.py --source csv --file AAPL_ticks.csv,NVDA_ticks.csv --company apple,nvidia
  python hft_dashboard.py --company apple,nvidia --together --no-rotate  switch one part off (ablation)
  python hft_dashboard.py --company apple,nvidia --together --strategy independent --cap-pct 50
                                                     v10: each engine trades on its own, optional cap
  (without --together a comma list with --source replay still means one separate run per company)
Company = name or Yahoo ticker: apple AAPL, nvidia NVDA, google GOOGL, microsoft MSFT,
amazon AMZN, walmart WMT, meta META, tesla TSLA (other tickers work too).
  options: --port COM6 (or 'none' to use the Python model instead of a board)
           --speed 10 (replay ticks per second; default 10 with the window, as fast as the
           board answers in the several-company mode)  --max-ticks N  --no-plot [--save-png out.png]
           --starting-cash USD (default: 1,000,000,000 for real market data, 1,000,000 otherwise)
           (--source apple-replay / apple-live still work: same as --source replay / live)

At start the dashboard sends RESET and the configuration to the board, so every
run starts from a clean state. Every report is checked as it arrives:
  * the price and volume echoed by the board equal what was sent
  * hardware decision == RISC-V software decision
  * hardware decision and position == the Python reference model (hft_model.py)
Everything is written to a CSV log; check it afterwards with verify_run.py.
Keep SW0 (kill switch) off during a verification run: the PC cannot see it.

The window (and the --save-png snapshot) is a live trading terminal (dash_pro.py): KPI tiles
(equity, return, cash, position, trades, HW = SW = model counter, latency, throughput),
1-minute candlesticks with the engine's MA(4) and VWAP and every BUY / SELL, volume, position,
RETURN on the starting cash (mark-to-market), a latency histogram (RISC-V software vs FPGA,
p50 / p99), FPGA resource gauges read from Vivado's reports (--util-report / --timing-report;
default: the newest report in the project), throughput statistics and a trade blotter.
--classic shows the older plain window.

Every trade is the whole bar volume (a design choice of the accelerator), and the account
is fully funded, so the starting cash must be able to pay for whole bars: one AAPL lot
(1000 shares) costs about $250,000.  With too little cash every BUY is refused and the
run "passes" without a single trade; the dashboard warns when that happens.

Several-company mode: every run starts from the same clean state (RESET, same starting
cash and position limit, breakout levels = that company's previous session).  The summary
puts the strategy's return next to buy-and-hold (bought at the first bar's close, valued
at the last bar's close) for the same session, so the strategy can be judged fairly.
Returns are on the whole-bar notional, without fees or slippage.
"""
import argparse
import csv
import os
import random
import struct
import sys
import threading
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hft_model import HFTModel, NAMES, CMD_RESET, CMD_CFG_BRK, CMD_CFG_LIMIT, CMD_CFG_CASH, LOST_SYNC  # noqa: E402

HEADER = struct.pack('<I', 0xAA55AA55)
FOOTER = 0x55AA55AA
REPORT_BYTES = 40
LOG_FIELDS = ['tick', 'time', 'open', 'high', 'low', 'close', 'volume', 'price_sent', 'vol_sent',
              'price_echo', 'vol_echo', 'hw_dec', 'hw_lat', 'sw_dec', 'sw_lat', 'hw_pos', 'model_dec', 'model_pos',
              'cash_usd', 'equity_usd', 'return_pct']
DEFAULT_CASH_REAL = 1_000_000_000   # USD, real AAPL data (whole-bar trades of ~$250k per lot)
DEFAULT_CASH_UNITS = 1_000_000      # random / old Price,Volume CSV (cash in price x volume units)


def cash_units(cash, scale, lot):
    """Starting cash in displayed currency -> accelerator units (price units x lots), exact.
    The float is converted through its decimal text, so 1234567.89 is not off by one unit."""
    from fractions import Fraction
    units = int(Fraction(str(cash)) * scale / lot)          # floor (cash is never negative)
    if units < 0 or units >= 1 << 64:
        sys.exit('--starting-cash %s is out of range (0 .. %d units of price x lot)' % (cash, (1 << 64) - 1))
    return units


def money(v):
    """$1,234,567 / -$1,234,567 (whole dollars)."""
    return ('-' if v < 0 else '') + '$' + format(abs(int(round(v))), ',')


# --------------------------------------------------------------------------- data sources
class Tick:
    __slots__ = ('time', 'open', 'high', 'low', 'close', 'volume', 'price', 'vol')

    def __init__(self, time_, o, h, l, c, volume, price, vol):
        self.time, self.open, self.high, self.low, self.close = time_, o, h, l, c
        self.volume, self.price, self.vol = volume, price, vol


def source_random(n):
    p = 100
    for i in range(n):
        p = max(10, p + random.randint(-5, 5))
        v = random.randint(10, 100)
        yield Tick('', p, p, p, p, v, p, v)


def source_csv(path, lot):
    """Old Price,Volume CSV: integer price and volume used as they are."""
    with open(path) as f:
        for r in csv.DictReader(f):
            p, v = int(float(r['Price'])), int(float(r['Volume']))
            yield Tick('', p, p, p, p, v, p, v)


def bars_to_ticks(bars):
    for b in bars:
        yield Tick(b.time, b.open, b.high, b.low, b.close, b.volume, b.price, b.vol)


# --------------------------------------------------------------------------- the board
def _lower_ftdi_latency(port, ms=2):
    """Linux only, best effort: the FTDI driver holds short replies for up to its latency timer
    (16 ms by default), which dominates the time per tick.  On Windows set it in Device Manager
    -> the COM port -> Port Settings -> Advanced -> Latency Timer (2 ms)."""
    try:
        dev = os.path.basename(os.path.realpath(port))
        path = '/sys/bus/usb-serial/devices/%s/latency_timer' % dev
        if os.path.exists(path):
            with open(path) as f:
                old = int(f.read().strip())
            if old > ms:
                with open(path, 'w') as f:
                    f.write(str(ms))
                print('FTDI latency timer of %s: %d ms -> %d ms' % (dev, old, ms))
    except (OSError, ValueError):
        pass                        # not permitted / not an FTDI port: keep the driver default


class Board:
    """The FPGA over the USB-UART.  Every report carries the id of the packet it answers; a
    report is only accepted for the packet just sent (v11 took the first complete frame, so a
    late report of tick k was booked as the answer to tick k+1 and every later tick stayed
    shifted by one)."""

    def __init__(self, port, baud=115200):
        import serial
        _lower_ftdi_latency(port)
        self.ser = serial.Serial(port, baud, timeout=0.2)
        time.sleep(0.2)
        self.ser.reset_input_buffer()
        self.stale = 0              # complete reports dropped because they answered an earlier packet

    def exchange(self, tid, price, vol):
        self.ser.write(struct.pack('<III', tid & 0xFFFFFFFF, price, vol))
        return self.read_report(tid & 0xFFFFFFFF)

    def read_report(self, expect_id=None, timeout=1.5):
        """The report for packet `expect_id` (any report if None), resynchronising on header +
        footer if bytes were lost.  Complete reports for other ids are dropped (counted in
        self.stale).  None if it does not arrive in time."""
        buf, deadline = b'', time.time() + timeout
        while time.time() < deadline:
            if len(buf) < REPORT_BYTES:
                buf += self.ser.read(REPORT_BYTES - len(buf))
            i = buf.find(HEADER)
            if i < 0:
                buf = buf[-3:]
                continue
            buf = buf[i:]
            if len(buf) >= REPORT_BYTES:
                w = struct.unpack('<10I', buf[:REPORT_BYTES])
                if w[9] == FOOTER:
                    buf = buf[REPORT_BYTES:]
                    if expect_id is None or w[1] == expect_id:
                        return w[1:9]      # id, price, vol, hw_dec, hw_lat, sw_dec, sw_lat, hw_pos
                    self.stale += 1        # answer to an earlier packet that came too late: drop
                    continue
                buf = buf[4:]
        return None



class SimBoard:
    """No hardware: answers like the firmware, using the Python model (latencies are placeholders)."""

    def __init__(self, cfg):
        self.m = HFTModel(*cfg)

    def exchange(self, tid, price, vol):
        if tid & 0x80000000:
            self.m.command(tid, price, vol)
            return (tid, price, vol, 0, 0, 0, 0, self.m.pos)
        d = self.m.step(price, vol)
        return (tid, price, vol, d, 5, d, random.randint(74, 92), self.m.pos)


# --------------------------------------------------------------------------- run state
class Run:
    def __init__(self, args, cfg, scale, lot, title):
        self.args, self.cfg, self.scale, self.lot, self.title = args, cfg, scale, lot, title
        self.lock = threading.Lock()
        self.rows = []
        self.model = HFTModel(*cfg)
        self.n = self.hw_sw_bad = self.model_bad = self.echo_bad = self.no_report = 0
        self.cash_units = cfg[3]                     # exact, in price x lot units (like the hardware)
        self.start_cash = self.units_usd(cfg[3])
        self.status = 'starting'
        self.done = False
        self.quiet = False          # several-company mode: print only mismatches and the summary
        self.log = None
        self.symbol = ''
        self.rtt = []               # PC -> FPGA -> PC round trip of every tick (ms), for the dashboard
        self.t_start = self.t_end = None

    def usd(self, price):
        return price / self.scale

    def units_usd(self, units):
        """price x lot units -> displayed currency"""
        return units * self.lot / self.scale

    @property
    def cash(self):
        return self.units_usd(self.cash_units)

    def record(self, i, t, rep):
        rid, rp, rv, hwd, hwl, swd, swl, hwp = rep
        md = self.model.step(t.price, t.vol)
        with self.lock:
            self.n += 1
            if (rid, rp, rv) != (i, t.price, t.vol):
                self.echo_bad += 1
            if hwd != swd:
                self.hw_sw_bad += 1
            if hwd != md or hwp != self.model.pos:
                self.model_bad += 1
            # the account follows the HARDWARE decisions (the trade is the whole tick volume)
            if hwd == 1:
                self.cash_units -= t.price * t.vol
            elif hwd == 2:
                self.cash_units += t.price * t.vol
            cash = self.units_usd(self.cash_units)
            equity = self.units_usd(self.cash_units + hwp * rp)     # holdings valued at this bar's close
            ret = 100.0 * (equity - self.start_cash) / self.start_cash if self.start_cash else 0.0
            self.rows.append(dict(tick=i, time=t.time, open=t.open, high=t.high, low=t.low, close=t.close,
                                  volume=t.volume, price_sent=t.price, vol_sent=t.vol, price_echo=rp, vol_echo=rv,
                                  hw_dec=hwd, hw_lat=hwl, sw_dec=swd, sw_lat=swl, hw_pos=hwp,
                                  model_dec=md, model_pos=self.model.pos,
                                  cash_usd=cash, equity_usd=equity, return_pct=ret))
        return md


def worker(run, board, ticks, logw, logf):
    a = run.args
    # clean start: reset, then configuration (each command is echoed by the firmware)
    pos_limit, brk_high, brk_low, starting_cash = run.cfg
    for cmd, p, v in ((CMD_RESET, 0, 0), (CMD_CFG_BRK, brk_high, brk_low),
                      (CMD_CFG_LIMIT, pos_limit, 0),
                      (CMD_CFG_CASH, starting_cash & 0xffffffff, starting_cash >> 32),
                      (CMD_RESET, 0, 0)):
        rep = board.exchange(cmd, p, v)
        if rep is None or rep[0] != cmd:
            run.status = 'board did not answer the %s command (check COM port / bitstream)' % hex(cmd)
            print(run.status)
            run.done = True
            return
    if not run.quiet:
        print('board reset and configured: POS_LIMIT=%d BRK_HIGH=%d BRK_LOW=%d STARTING_CASH=%d' % run.cfg)
    run.status = 'running'
    run.t_start = time.perf_counter()
    t_next = time.time()
    for i, t in enumerate(ticks, start=1):
        if a.max_ticks and i > a.max_ticks:
            break
        t_tx = time.perf_counter()
        rep = board.exchange(i, t.price, t.vol)
        with run.lock:
            run.rtt.append(1000.0 * (time.perf_counter() - t_tx))
        if rep is None:
            run.no_report += 1
            print('tick %d: no report from the board; %s' % (i, LOST_SYNC))
            run.status = 'stopped: no report for tick %d' % i
            break
        md = run.record(i, t, rep)
        logw.writerow(run.rows[-1])
        logf.flush()
        _, _, _, hwd, hwl, swd, swl, hwp = rep
        flag = '' if (hwd == swd == md and hwp == run.model.pos) else '   <-- MISMATCH'
        if not run.quiet or flag:
            print('tick %4d %s | price %s | HW %-4s %d cyc | SW %-4s %d cyc | pos %d%s'
                  % (i, t.time, ('%.2f' % run.usd(t.price)), NAMES.get(hwd, hwd), hwl, NAMES.get(swd, swd), swl, hwp, flag))
        if a.source != 'live' and a.speed:
            t_next += 1.0 / a.speed
            time.sleep(max(0.0, t_next - time.time()))
    run.t_end = time.perf_counter()
    if not run.no_report:
        run.status = 'finished'
    run.done = True
    print('done: %d ticks | HW/SW mismatches %d | model mismatches %d | echo errors %d | missing reports %d'
          % (run.n, run.hw_sw_bad, run.model_bad, run.echo_bad, run.no_report))
    for line in run_summary(run):
        print(line)
    print('log written to', run.log, ' -> check it with: python verify_run.py', run.log)


def run_summary(run):
    """Trades, return and the signals the risk interlock refused, with a warning when the run
    barely traded (a verification run without trades proves very little)."""
    rows, m = run.rows, run.model
    if not rows:
        return []
    buys = sum(1 for r in rows if r['hw_dec'] == 1)
    sells = sum(1 for r in rows if r['hw_dec'] == 2)
    out = ['trades: %d BUY, %d SELL | final return %+.4f%% (%s mark-to-market on %s starting cash)'
           % (buys, sells, rows[-1]['return_pct'], money(rows[-1]['equity_usd']), money(run.start_cash)),
           'signals refused by the risk interlock: %d BUY (not enough cash), %d BUY (position limit), '
           '%d SELL (nothing held), %d on zero-volume ticks'
           % (m.blocked_cash, m.blocked_limit, m.blocked_nostock, m.zero_vol)]
    if m.blocked_cash and m.blocked_cash >= buys:
        costs = sorted(r['price_sent'] * r['vol_sent'] for r in rows if r['vol_sent'])
        median = run.units_usd(costs[len(costs) // 2]) if costs else 0
        out.append('WARNING: %d BUY signals were refused for lack of cash (only %d BUY executed). One bar costs '
                   'about %s (median), the starting cash is %s: raise --starting-cash.'
                   % (m.blocked_cash, buys, money(median), money(run.start_cash)))
    if buys + sells == 0:
        out.append('WARNING: no trade was executed in this run, so the checks above only show that both sides agree on '
                   '"do nothing".')
    return out


# --------------------------------------------------------------------------- plotting
def plot_loop(run, snapshot=None):
    """the live window: the trading-terminal view (dash_pro.py), or the v12 window with --classic"""
    a = run.args
    if getattr(a, 'classic', False):
        return plot_loop_classic(run, snapshot)
    import dash_pro
    return dash_pro.run_single(run, snapshot, util=getattr(a, 'util_report', None),
                               timing=getattr(a, 'timing_report', None))


def plot_loop_classic(run, snapshot=None):
    import matplotlib
    if snapshot:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.ticker import PercentFormatter
    # four graphs: price + trades, position, RETURN, latency.  The right 25 % of the figure
    # holds the status box (wide enough for 13-digit dollar amounts).
    fig, (ax1, ax2, ax4, ax3) = plt.subplots(4, 1, figsize=(15, 13.5),
                                             gridspec_kw=dict(height_ratios=[3, 1.3, 1.6, 1.3]))
    fig.canvas.manager.set_window_title(run.title)

    def time_ticks(ax, rows):
        xs = list(range(len(rows)))
        step = max(1, len(rows) // 10)
        ax.set_xticks(xs[::step])
        ax.set_xticklabels([r['time'][-5:] if r['time'] else str(r['tick']) for r in rows][::step], fontsize=8)
        ax.set_xlim(-1, max(len(rows), 1))

    def update(_):
        with run.lock:
            rows = list(run.rows)
            n, hs, mb, eb = run.n, run.hw_sw_bad, run.model_bad, run.echo_bad
            start_cash = run.start_cash
            blocked_cash = run.model.blocked_cash
        for ax in (ax1, ax2, ax3, ax4):
            ax.clear()
        for t in list(fig.texts):
            t.remove()
        if rows:
            xs = list(range(len(rows)))
            for x, r in zip(xs, rows):
                up = r['close'] >= r['open']
                col = '#1a9850' if up else '#d73027'
                ax1.plot([x, x], [r['low'], r['high']], color=col, linewidth=0.8)
                ax1.bar(x, max(abs(r['close'] - r['open']), 1e-3 * r['close']), bottom=min(r['open'], r['close']),
                        color=col, width=0.7)
            ax1.plot(xs, [run.usd(r['price_echo']) for r in rows], color='#2b5fd9', linewidth=0.9, alpha=0.8,
                     label='price echoed by the FPGA')
            b = [(x, r) for x, r in zip(xs, rows) if r['hw_dec'] == 1]
            s = [(x, r) for x, r in zip(xs, rows) if r['hw_dec'] == 2]
            if b:
                ax1.scatter([x for x, _ in b], [r['low'] for _, r in b], marker='^', color='#00b050', s=60, zorder=5,
                            label='BUY (hardware)')
            if s:
                ax1.scatter([x for x, _ in s], [r['high'] for _, r in s], marker='v', color='#c000c0', s=60, zorder=5,
                            label='SELL (hardware)')
            lo, hi = run.usd(run.cfg[2]), run.usd(run.cfg[1])
            ymin, ymax = min(r['low'] for r in rows), max(r['high'] for r in rows)
            for lvl, name in ((hi, 'BRK_HIGH'), (lo, 'BRK_LOW')):
                if ymin - (ymax - ymin) * 0.3 <= lvl <= ymax + (ymax - ymin) * 0.3:
                    ax1.axhline(lvl, color='gray', linestyle=':', linewidth=1)
                    ax1.text(0, lvl, ' ' + name, fontsize=8, color='gray', va='bottom')
            ax1.legend(loc='upper left', fontsize=8)

            ax2.plot(xs, [r['hw_pos'] for r in rows], color='#7030a0')
            ax2.set_ylabel('position (lots)' if run.lot > 1 else 'position')

            # ---- returns (mark-to-market, % of the starting cash)
            rets = [r['return_pct'] for r in rows]
            ax4.axhline(0, color='gray', linewidth=0.8)
            ax4.fill_between(xs, rets, 0, where=[v >= 0 for v in rets], interpolate=True, color='#1a9850', alpha=0.25)
            ax4.fill_between(xs, rets, 0, where=[v < 0 for v in rets], interpolate=True, color='#d73027', alpha=0.25)
            ax4.plot(xs, rets, color='#1f4e9c', linewidth=1.6,
                     label='return on starting cash (mark-to-market): now %+.3f%%, best %+.3f%%, worst %+.3f%%'
                           % (rets[-1], max(rets), min(rets)))
            ax4.plot([xs[-1]], [rets[-1]], 'o', color='#1f4e9c')
            rspan = (max(rets) - min(rets)) or abs(rets[-1]) or 1.0
            ax4.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=1 if rspan >= 2 else 2 if rspan >= 0.2 else 3))
            ax4.set_ylabel('return')
            ax4.legend(loc='best', fontsize=8)
            if not b and not s:
                ax4.text(0.5, 0.75, 'no trades executed%s' % (' - BUYs refused for lack of cash: raise --starting-cash'
                                                              if blocked_cash else ''),
                         ha='center', va='center', transform=ax4.transAxes, fontsize=10, color='#c00000',
                         bbox=dict(facecolor='white', edgecolor='#c00000', boxstyle='round,pad=0.3'))

            ax3.plot(xs, [r['sw_lat'] for r in rows], color='#2b5fd9', label='RISC-V software (cycles)')
            ax3.plot(xs, [r['hw_lat'] for r in rows], color='#e07b00', linewidth=2, label='hardware accelerator (cycles)')
            ax3.legend(loc='center right', fontsize=8)
            for ax in (ax1, ax2, ax4, ax3):
                time_ticks(ax, rows)

            last = rows[-1]
            cash, value = last['cash_usd'], last['equity_usd']
            holdings_value = value - cash
            net_cash_flow = cash - start_cash
            profit = value - start_cash
            sw = [r['sw_lat'] for r in rows]
            txt = ('ticks: %d\nHW = SW: %d / %d\nHW = model: %d / %d\nprice echo errors: %d\n\n'
                   'HW latency: %d cycles\nSW latency: %.1f avg (%d-%d)\nspeed-up: %.1fx\n\n'
                   'trades: %d BUY, %d SELL\nBUYs refused (cash): %d\n'
                   'position: %d %s\nstarting cash: %s\ncash balance: %s\n'
                   'net cash flow: %s\nholdings value: %s\n'
                   'mark-to-market: %s\nprofit: %s\nreturn: %+.3f%%\n\n%s'
                   % (n, n - hs, n, n - mb, n, eb, last['hw_lat'], sum(sw) / len(sw), min(sw), max(sw),
                      (sum(sw) / len(sw)) / max(1, last['hw_lat']), len(b), len(s), blocked_cash,
                      last['hw_pos'], 'lots' if run.lot > 1 else '',
                      money(start_cash), money(cash), money(net_cash_flow), money(holdings_value), money(value),
                      money(profit), last['return_pct'], run.status))
            ok = hs == 0 and mb == 0 and eb == 0
            fig.text(0.755, 0.95, txt, fontsize=9.5, family='monospace', va='top',
                     bbox=dict(facecolor='#e8f7e8' if ok else '#fde2e2', edgecolor='black', boxstyle='round,pad=0.8'))
        ax1.set_title(run.title, fontsize=10, loc='left')
        ax1.set_ylabel('price (USD)' if run.scale > 1 else 'price')
        ax2.set_title('Hardware position', fontsize=10)
        ax4.set_title('Return on the starting cash: (cash + holdings at the bar close - starting cash) / starting cash',
                      fontsize=10)
        ax3.set_title('Decision latency: RISC-V software vs hardware accelerator', fontsize=10)
        ax3.set_xlabel('New York time (one 1-minute bar per tick)' if run.scale > 1 else 'tick')
        plt.subplots_adjust(left=0.075, right=0.74, hspace=0.42, top=0.95, bottom=0.05)

    if snapshot:
        update(0)
        fig.savefig(snapshot, dpi=110)
        plt.close(fig)
        print('dashboard picture:', snapshot)
        return
    _ani = FuncAnimation(fig, update, interval=700, cache_frame_data=False)
    plt.show()


# --------------------------------------------------------------------------- sessions
def real_session(a, symbol, day=None, bars=None):
    """One session of real 1-minute bars of `symbol`, with the breakout levels from the session
    before it.  bars: already downloaded bars (several days) or bars from a CSV.
    Returns (day, bars, cfg) with cfg = (pos_limit, brk_high, brk_low, starting_cash_units)."""
    import market_feed
    day, bars, hi, lo = market_feed.replay_session(symbol, a.lot, day, bars=bars)
    hi = market_feed.to_cents(a.brk_high) if a.brk_high else hi
    lo = market_feed.to_cents(a.brk_low) if a.brk_low else lo
    cash = DEFAULT_CASH_REAL if a.starting_cash is None else a.starting_cash
    return day, bars, (a.limit or 5000, hi, lo, cash_units(cash, 100, a.lot))


def write_cfg(log_path, cfg, scale, lot, source, symbol):
    # the configuration of a run, for verify_run.py
    with open(log_path + '.cfg', 'w') as f:
        f.write('pos_limit=%d\nbrk_high=%d\nbrk_low=%d\nstarting_cash_units=%d\nscale=%d\nlot=%d\nsource=%s\nsymbol=%s\n'
                % (cfg + (scale, lot, source, symbol)))


def make_board(a):
    if a.port.lower() == 'none':
        return SimBoard((1000, 150, 50, DEFAULT_CASH_UNITS))   # reconfigured by the commands of every run
    return Board(a.port)


def run_once(a, board, ticks, cfg, scale, lot, title, log_path, symbol, quiet=False, snapshot=None, window=False):
    """Send one session through the board (RESET + configuration first) and log it."""
    if a.port.lower() == 'none':
        title += '  [SIMULATION: Python model, no board]'
    run = Run(a, cfg, scale, lot, title)
    run.quiet, run.log = quiet, log_path
    run.symbol = symbol
    logf = open(log_path, 'w', newline='')
    logw = csv.DictWriter(logf, fieldnames=LOG_FIELDS)
    logw.writeheader()
    write_cfg(log_path, cfg, scale, lot, a.source, symbol)
    th = threading.Thread(target=worker, args=(run, board, ticks, logw, logf), daemon=True)
    th.start()
    if window:
        plot_loop(run)
    else:
        th.join()
        if snapshot and run.rows:
            plot_loop(run, snapshot=snapshot)
    logf.close()
    return run


def result_row(run, symbol, day):
    """One line of the several-company summary."""
    import market_feed
    rows = run.rows
    row = dict(company=market_feed.company_name(symbol), symbol=symbol, day=day, bars=len(rows), buys=0, sells=0,
               refused_cash=run.model.blocked_cash, final_position_lots='', strategy_return_pct='',
               buy_hold_return_pct='', best_return_pct='', worst_return_pct='',
               hw_sw_mismatches=run.hw_sw_bad, model_mismatches=run.model_bad, echo_errors=run.echo_bad,
               missing_reports=run.no_report, verified='', log=os.path.basename(run.log or ''), error='')
    if not rows:
        row.update(verified='FAIL', error=run.status)
        return row
    rets = [r['return_pct'] for r in rows]
    row.update(buys=sum(r['hw_dec'] == 1 for r in rows), sells=sum(r['hw_dec'] == 2 for r in rows),
               final_position_lots=rows[-1]['hw_pos'], strategy_return_pct=round(rets[-1], 4),
               buy_hold_return_pct=round(100.0 * (rows[-1]['price_sent'] / rows[0]['price_sent'] - 1.0), 4),
               best_return_pct=round(max(rets), 4), worst_return_pct=round(min(rets), 4))
    ok = run.hw_sw_bad == run.model_bad == run.echo_bad == run.no_report == 0
    row['verified'] = 'PASS' if ok else 'FAIL'
    return row


SUMMARY_FIELDS = ['company', 'symbol', 'day', 'bars', 'buys', 'sells', 'refused_cash', 'final_position_lots',
                  'strategy_return_pct', 'buy_hold_return_pct', 'best_return_pct', 'worst_return_pct',
                  'hw_sw_mismatches', 'model_mismatches', 'echo_errors', 'missing_reports', 'verified', 'log', 'error']


def per_company(results):
    """Average the runs of each company (in the order the companies were run)."""
    order, groups = [], {}
    for r in results:
        if r['symbol'] not in groups:
            order.append(r['symbol'])
            groups[r['symbol']] = []
        groups[r['symbol']].append(r)
    out = []
    for sym in order:
        ok = [r for r in groups[sym] if r['strategy_return_pct'] != '']
        out.append(dict(symbol=sym, company=groups[sym][0]['company'], runs=len(ok),
                        days=', '.join(r['day'] for r in ok),
                        strategy=sum(r['strategy_return_pct'] for r in ok) / len(ok) if ok else None,
                        buy_hold=sum(r['buy_hold_return_pct'] for r in ok) / len(ok) if ok else None,
                        trades=sum(r['buys'] + r['sells'] for r in ok),
                        verified=all(r['verified'] == 'PASS' for r in groups[sym]) and bool(ok),
                        error='; '.join(r['error'] for r in groups[sym] if r['error'])))
    return out


def plot_comparison(results, path, subtitle):
    """Horizontal bars per company: strategy return (blue) next to buy-and-hold (gray context),
    averaged over the sessions that were run.  One axis, zero baseline, values labelled."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    INK, INK2, MUTED, GRID, BASE, SURF = '#0b0b0b', '#52514e', '#898781', '#e1e0d9', '#c3c2b7', '#fcfcfb'
    STRAT, BH = '#2a78d6', '#898781'
    comp = [c for c in per_company(results) if c['strategy'] is not None]
    if not comp:
        print('no run produced a result: no comparison chart')
        return None
    comp.sort(key=lambda c: c['strategy'])                       # best strategy return at the top
    n = len(comp)
    fig, ax = plt.subplots(figsize=(11, 1.0 + 0.62 * n + 1.4))
    fig.patch.set_facecolor(SURF)
    ax.set_facecolor(SURF)
    h, gap = 0.36, 0.04
    ys = list(range(n))
    strat = [c['strategy'] for c in comp]
    bh = [c['buy_hold'] for c in comp]
    ax.barh([y + (h + gap) / 2 for y in ys], strat, height=h, color=STRAT, label='Strategy (FPGA decisions)', zorder=3)
    ax.barh([y - (h + gap) / 2 for y in ys], bh, height=h, color=BH, label='Buy and hold (first to last bar)', zorder=3)
    lo, hi = min(strat + bh + [0.0]), max(strat + bh + [0.0])
    span = (hi - lo) or 1.0
    ax.set_xlim(lo - 0.22 * span, hi + 0.22 * span)
    for y, v, w in [(y + (h + gap) / 2, v, 'bold') for y, v in zip(ys, strat)] + \
                   [(y - (h + gap) / 2, v, 'normal') for y, v in zip(ys, bh)]:
        ax.text(v + (0.012 * span if v >= 0 else -0.012 * span), y, pct(v), va='center',
                ha='left' if v >= 0 else 'right', fontsize=9, color=INK if w == 'bold' else INK2, fontweight=w)
    labels = []
    for c in comp:
        extra = ' - %d sessions' % c['runs'] if c['runs'] > 1 else ''
        if not c['verified']:
            extra += '  [FPGA check FAILED]'
        labels.append('%s%s\n%d trades' % (c['company'], extra, c['trades']))
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=9, color=INK)
    ax.axvline(0, color=BASE, linewidth=1.2, zorder=2)
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=1 if span < 20 else 0))
    ax.grid(axis='x', color=GRID, linewidth=0.8, zorder=0)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(BASE)
    ax.tick_params(axis='x', colors=MUTED, labelsize=9)
    ax.tick_params(axis='y', length=0)
    avg_s, avg_b = sum(strat) / n, sum(bh) / n
    beat = sum(1 for s_, b_ in zip(strat, bh) if s_ > b_)
    fig.suptitle('Strategy return vs buy-and-hold, per company', x=0.02, ha='left', fontsize=13, color=INK)
    per = ' (average return per session)' if any(c['runs'] > 1 for c in comp) else ''
    ax.set_title('%s\naverage over %d companies%s: strategy %s, buy-and-hold %s; strategy ahead on %d of %d'
                 % (subtitle, n, per, pct(avg_s), pct(avg_b), beat, n), loc='left', fontsize=9, color=INK2, wrap=True)
    ax.legend(loc='lower right', fontsize=9, frameon=False)
    ax.set_xlabel('return on the starting cash (mark-to-market at the last bar of the session)', color=INK2, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=SURF)
    plt.close(fig)
    return path


def pct(v):
    """+1.23% / -0.45% (a tiny negative that rounds to zero is shown as +0.00%)"""
    v = round(v, 2)
    return '%+.2f%%' % (v if v != 0 else 0.0)


def write_summary(results, out_dir, subtitle):
    csv_path = os.path.join(out_dir, 'summary.csv')
    with open(csv_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        w.writeheader()
        w.writerows(results)
    comp = per_company(results)
    fmt = lambda v: '-' if v is None or v == '' else pct(v)               # noqa: E731
    lines = ['# Strategy vs buy-and-hold', '', subtitle, '',
             '| Company | Sessions | Trades | Strategy return | Buy-and-hold | FPGA check |',
             '|---|---|---|---|---|---|']
    for c in comp:
        lines.append('| %s | %s | %d | %s | %s | %s |' % (c['company'], c['days'] or '-', c['trades'], fmt(c['strategy']),
                                                         fmt(c['buy_hold']), 'PASS' if c['verified'] else
                                                         'FAIL' + (' (%s)' % c['error'] if c['error'] else '')))
    lines += ['', 'Per session: summary.csv.  Per run: <TICKER>_<day>.csv (check with verify_run.py) and .png.',
              'Returns are mark-to-market on the starting cash, whole-bar notional, no fees or slippage.', '']
    md_path = os.path.join(out_dir, 'summary.md')
    with open(md_path, 'w') as f:
        f.write('\n'.join(lines))
    print()
    print('%-18s %-12s %7s %10s %13s  %s' % ('company', 'sessions', 'trades', 'strategy', 'buy-and-hold', 'FPGA check'))
    for c in comp:
        days = c['days'] if c['runs'] == 1 else '%d sessions' % c['runs'] if c['runs'] else '-'
        print('%-18s %-12s %7d %10s %13s  %s' % (c['company'], days, c['trades'], fmt(c['strategy']),
                                                fmt(c['buy_hold']), 'PASS' if c['verified'] else 'FAIL ' + c['error']))
    if any(c['runs'] > 1 for c in comp):
        print('(several sessions: the average return per session)')
    return csv_path, md_path


def run_batch(a, symbols):
    """Several companies (and/or several sessions): one run per company and session."""
    import market_feed
    out_dir = a.out_dir or 'results_%s' % datetime.now().strftime('%Y%m%d_%H%M%S')
    os.makedirs(out_dir, exist_ok=True)
    board = make_board(a)
    results = []
    for sym in symbols:
        name = market_feed.company_name(sym)
        try:
            all_bars = market_feed.fetch_minute_bars(sym, '7d', a.lot)
            days = market_feed.replayable_days(all_bars)
            if a.day:
                if a.day not in days:
                    raise RuntimeError('no replayable session %s (available: %s)' % (a.day, ', '.join(days)))
                chosen = [a.day]
            else:
                chosen = days[-a.days:]
            if not chosen:
                raise RuntimeError('not enough sessions of data')
        except Exception as e:                  # no data for this company: report it, carry on
            print('%s: %s' % (name, e))
            results.append(dict({k: '' for k in SUMMARY_FIELDS}, company=name, symbol=sym, verified='FAIL', error=str(e)))
            continue
        if len(chosen) < a.days and not a.day:
            print('%s: only %d replayable sessions available' % (name, len(chosen)))
        for day in chosen:
            day, bars, cfg = real_session(a, sym, day, all_bars)
            ticks = list(bars_to_ticks(bars))
            title = '%s 1-minute bars, %s (New York time), replayed through the FPGA' % (name, day)
            log_path = os.path.join(out_dir, '%s_%s.csv' % (sym, day))
            print('== %s %s: %d bars, previous-session high/low %.2f / %.2f USD' % (name, day, len(bars), cfg[1] / 100, cfg[2] / 100))
            run = run_once(a, board, ticks, cfg, 100, a.lot, title, log_path, sym, quiet=True,
                           snapshot=os.path.join(out_dir, '%s_%s.png' % (sym, day)))
            if run.status.startswith('board did not answer'):
                sys.exit('stopped: ' + run.status)
            results.append(result_row(run, sym, day))
    cash = DEFAULT_CASH_REAL if a.starting_cash is None else a.starting_cash
    all_days = sorted({r['day'] for r in results if r['day']})
    subtitle = ('1-minute bars, sessions %s; each run: %s starting cash, position limit %d lots, trades = whole bar volume, '
                'no fees%s' % (', '.join(all_days) if len(all_days) <= 4 else '%s to %s' % (all_days[0], all_days[-1]) if all_days else '-',
                               money(cash), a.limit or 5000, '; SIMULATION (Python model, no board)' if a.port.lower() == 'none' else ''))
    csv_path, md_path = write_summary(results, out_dir, subtitle)
    chart = plot_comparison(results, os.path.join(out_dir, 'comparison.png'), subtitle)
    print('\nsummary: %s and %s%s' % (csv_path, md_path, ('\ncomparison chart: ' + chart) if chart else ''))
    return results


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', default='replay', choices=['replay', 'live', 'csv', 'random', 'apple-replay', 'apple-live'])
    ap.add_argument('--company', default='apple',
                    help="company name or ticker, a comma list, or 'all' (apple, nvidia, google, microsoft, amazon, "
                         "walmart, meta, tesla); default apple")
    ap.add_argument('--port', default='COM6', help="serial port, or 'none' for the Python model")
    ap.add_argument('--file', default=None, help='CSV for --source csv (default <TICKER>_ticks.csv)')
    ap.add_argument('--day', help='session to replay, YYYY-MM-DD (default: latest)')
    ap.add_argument('--days', type=int, default=1, help='several-company mode: replay the last N sessions of each company')
    ap.add_argument('--out-dir', help='several-company mode: folder for the logs, pictures and summary')
    ap.add_argument('--speed', type=float, default=None,
                    help='replay ticks per second (default 10 with the window; 0 = as fast as the board answers)')
    ap.add_argument('--lot', type=int, default=1000, help='shares per lot (real data)')
    ap.add_argument('--limit', type=int, default=None, help='position limit (lots for real data)')
    ap.add_argument('--starting-cash', type=float, default=None,
                    help='cash available at the start, in displayed currency (default: %s for real market '
                         'data, %s for --source random and old Price,Volume CSV files)'
                         % (format(DEFAULT_CASH_REAL, ','), format(DEFAULT_CASH_UNITS, ',')))
    ap.add_argument('--brk-high', type=float, help='breakout high in USD (default: previous session high)')
    ap.add_argument('--brk-low', type=float, help='breakout low in USD (default: previous session low)')
    ap.add_argument('--max-ticks', type=int, default=0)
    ap.add_argument('--log', default=None)
    ap.add_argument('--no-plot', action='store_true')
    ap.add_argument('--save-png', help='with --no-plot: save the final dashboard picture to this file')
    ap.add_argument('--classic', action='store_true', help='the older plain window instead of the trading terminal')
    ap.add_argument('--util-report', help='Vivado utilization report (.rpt) for the FPGA resource panel '
                                          '(default: newest *utilization_placed.rpt in the project)')
    ap.add_argument('--timing-report', help='Vivado timing summary (.rpt) for the WNS / WHS line '
                                            '(default: newest *timing_summary_routed.rpt in the project)')
    ap.add_argument('--together', action='store_true',
                    help='trade the listed companies at the same time from ONE shared cash account '
                         '(automatic for --source csv with several companies)')
    ap.add_argument('--cap-pct', type=float, default=0,
                    help='with --strategy independent: each company may invest at most this %% of the starting cash '
                         '(0 = no cap)')
    g = ap.add_argument_group('several companies together (--together): the hardware portfolio allocator')
    g.add_argument('--strategy', default='hybrid', choices=['hybrid', 'independent'],
                   help='hybrid (default): rank + rotate + reweight in hardware (hft_alloc.v), one decision per '
                        'minute for the whole portfolio; independent: every engine trades on its own (v10)')
    g.add_argument('--no-rank', action='store_true', help='serve BUYs in company order instead of strongest first')
    g.add_argument('--no-rotate', action='store_true', help='never sell a weak holding to fund a stronger BUY')
    g.add_argument('--no-reweight', action='store_true', help='fixed equal weights and no per-company cap')
    g.add_argument('--max-lots', type=int, default=0, help='lots per BUY at most (0 = the whole bar volume)')
    g.add_argument('--margin-pct', type=float, default=0.1,
                   help='rotation only if the buyer\'s momentum beats the holder\'s by more than this (%%, default 0.1)')
    g.add_argument('--min-hold', type=int, default=5, help='minutes a position is held before it may be rotated out')
    g.add_argument('--weight-step', type=int, default=3,
                   help='k: a closed position moves 1/2^k of the weights (default 3 = 12.5%%)')
    g.add_argument('--floor-pct', type=float, default=None,
                   help='no company drops below this weight (%%; default half of an equal share: 25 with 2 '
                        'companies, 12.5 with 4, 6.25 with 8)')
    g.add_argument('--capshift', type=int, default=14,
                   help='cap of a company = starting cash x weight / 2^capshift x 2^15: 14 -> caps add up to 200%% '
                        'of the cash (default), 15 -> 100%%, 13 -> 400%%')
    g.add_argument('--save-png-focus', action='store_true',
                   help='with --no-plot --save-png: also save the whole-day page of every company')
    a = ap.parse_args()
    if a.source.startswith('apple-'):              # old names: same as replay / live (default company apple)
        a.source = a.source[len('apple-'):]
    if a.days < 1:
        ap.error('--days must be at least 1')

    import market_feed
    try:
        symbols = market_feed.company_list(a.company)
    except ValueError as e:
        ap.error(str(e))

    # ---- several companies at the same time, one shared cash account
    if a.together or (a.source == 'csv' and len(symbols) > 1):
        if len(symbols) < 2:
            ap.error('--together needs at least two companies, e.g. --company apple,nvidia')
        if a.source not in ('replay', 'csv'):
            ap.error('--together works with --source replay or --source csv')
        if a.speed is None:
            a.speed = 0 if a.no_plot else 10
        if a.strategy == 'independent':
            import hft_portfolio
            hft_portfolio.run_portfolio(a, symbols, real_session, cash_units, DEFAULT_CASH_REAL, make_board)
        else:
            import hft_hybrid
            hft_hybrid.run_hybrid(a, symbols, real_session, cash_units, DEFAULT_CASH_REAL, make_board)
        return

    # ---- several companies and/or several sessions: batch mode
    if a.source == 'replay' and (len(symbols) > 1 or a.days > 1):
        if a.speed is None:
            a.speed = 0
        if a.log or a.save_png:
            print('note: --log / --save-png are ignored with several runs (everything goes to the --out-dir folder)')
        run_batch(a, symbols)
        return
    if len(symbols) > 1:
        ap.error('--source %s works with one company; several companies need --source replay' % a.source)
    if a.speed is None:
        a.speed = 10
    symbol = symbols[0]
    name = market_feed.company_name(symbol)

    stamp = datetime.now().strftime('%H%M%S')
    if a.source == 'replay':
        day, bars, cfg = real_session(a, symbol, a.day)
        ticks, title = bars_to_ticks(bars), '%s 1-minute bars, %s (New York time), replayed through the FPGA' % (name, day)
        print('%s %s: %d bars, previous-session high/low %.2f / %.2f USD' % (name, day, len(bars), cfg[1] / 100, cfg[2] / 100))
        scale, lot = 100, a.lot
        default_log = 'run_%s_%s_%s.csv' % (symbol, day, stamp)
    elif a.source == 'live':
        day, so_far, hi, lo, new = market_feed.live_session(symbol, lot=a.lot)
        import itertools
        ticks = bars_to_ticks(itertools.chain(so_far, new))
        title = '%s live, %s (New York time): 1-minute bars through the FPGA' % (name, day)
        print('%s live %s: %d bars so far, then one per minute' % (name, day, len(so_far)))
        hi = market_feed.to_cents(a.brk_high) if a.brk_high else hi
        lo = market_feed.to_cents(a.brk_low) if a.brk_low else lo
        cash = DEFAULT_CASH_REAL if a.starting_cash is None else a.starting_cash
        cfg, scale, lot = (a.limit or 5000, hi, lo, cash_units(cash, 100, a.lot)), 100, a.lot
        default_log = 'run_%s_%s_%s.csv' % (symbol, day, stamp)
    elif a.source == 'csv':
        path = a.file or '%s_ticks.csv' % symbol
        with open(path) as f:
            header = f.readline().lower()
        if 'close' in header:                   # real bars from download_market_data.py
            day, bars, cfg = real_session(a, symbol, a.day, bars=market_feed.bars_from_csv(path, a.lot))
            ticks, scale, lot = bars_to_ticks(bars), 100, a.lot
            title = '%s 1-minute bars, %s (New York time), from %s' % (name, day, os.path.basename(path))
            print('%s: %s session %s, %d bars, previous-session high/low %.2f / %.2f USD'
                  % (path, name, day, len(bars), cfg[1] / 100, cfg[2] / 100))
            default_log = 'run_%s_%s_%s.csv' % (symbol, day, stamp)
        else:                                   # old Price,Volume format: values used as they are
            ticks = source_csv(path, a.lot)
            cash = DEFAULT_CASH_UNITS if a.starting_cash is None else a.starting_cash
            cfg = (a.limit or 1000, int(a.brk_high or 150), int(a.brk_low or 50), cash_units(cash, 1, 1))
            scale, lot, title = 1, 1, 'Ticks from %s through the FPGA' % os.path.basename(path)
            symbol = ''
            default_log = 'run_csv_%s.csv' % stamp
    else:
        cash = DEFAULT_CASH_UNITS if a.starting_cash is None else a.starting_cash
        ticks, cfg, scale, lot = source_random(a.max_ticks or 100000), (a.limit or 1000, 150, 50, cash_units(cash, 1, 1)), 1, 1
        title, default_log, symbol = 'Random-walk ticks through the FPGA', 'run_random_%s.csv' % stamp, ''
    log_path = a.log or default_log
    board = make_board(a)
    run_once(a, board, ticks, cfg, scale, lot, title, log_path, symbol,
             snapshot=a.save_png if a.no_plot else None, window=not a.no_plot)


if __name__ == '__main__':
    main()
