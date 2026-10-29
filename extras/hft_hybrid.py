"""hft_hybrid.py - several companies, ONE cash account, the hybrid portfolio allocator in HARDWARE.

Used by hft_dashboard.py (the default with --together):
  python hft_dashboard.py --company apple,nvidia --together               latest common session, on the board
  python hft_dashboard.py --company apple,nvidia,google,microsoft --together --port none   Python model, no board
  python hft_dashboard.py --source csv --file AAPL_ticks.csv,NVDA_ticks.csv --company apple,nvidia
  ... --strategy independent       the v10 behaviour instead (every engine trades on its own)
  ... --no-rank / --no-rotate / --no-reweight   switch one part of the hybrid off (ablation)

Per minute the PC sends every company's 1-minute bar, then ALLOCATE:
  tick     -> the engine of that company computes its SIGNAL (2-of-3 vote, 5 cycles) and its momentum
              SCORE (background divider); report: hw vote, sw vote (RISC-V), hw score
  ALLOCATE -> hft_alloc.v trades for the whole portfolio: SELL whole positions, RANK the BUY candidates
              by score, BUY strongest first (shared cash, per-company cap from the weights), ROTATE at
              most once per minute (sell the weakest holding to fund a stronger BUY), REWEIGHT after
              every closed position (winners get more of the cap budget, losers less).
              Report: hw codes, sw codes (the firmware's C copy of the allocator), shared cash, state
              checksum (positions + weights).  The firmware itself also compares every register.
Every report is checked against hft_model.PortfolioModel as it arrives.

The window fits ONE screen whatever the number of companies:
  overview (default): every company's price over the LAST 60 MINUTES with the hardware's BUY / SELL /
                      ROT marks, and the portfolio (equity and cash, weights, allocation latency) over
                      the same hour.
  click a company   : that company over the WHOLE DAY so far: price and trades, score and signal,
                      position, weight and profit.  Click again, or press Esc, to go back.
                      Keys 1..8 open company 1..8 directly.
"""
import csv
import os
import random
import threading
import time

from hft_model import (LOST_SYNC, PortfolioModel, CMD_RESET, CMD_CFG_BRK, CMD_CFG_LIMIT, CMD_CFG_CASH, CMD_CFG_NSYM,
                       CMD_ALLOCATE, CMD_CFG_MODE, CMD_CFG_ROT, CMD_CFG_W, MODE_PORTFOLIO, MODE_RANK, MODE_ROTATE,
                       MODE_REWEIGHT, NONE, BUY, SELL, ROT, CODE_NAMES, W_TOTAL, SCORE_FRAC, M32, with_sym)

COLORS = ['#2b5fd9', '#e07b00', '#1a9850', '#c000c0', '#7030a0', '#c00000', '#008080', '#806000']
WINDOW = 60                      # minutes shown in the overview
LOG_FIELDS = ['kind', 'minute', 'time', 'company', 'sym', 'tick_id', 'open', 'high', 'low', 'close', 'volume',
              'price_sent', 'vol_sent', 'price_echo', 'vol_echo', 'hw_vote', 'sw_vote', 'model_vote', 'hw_lat', 'sw_lat', 'hw_score',
              'model_score', 'kill', 'hw_codes', 'sw_codes', 'model_codes', 'hw_cash_units', 'model_cash_units',
              'hw_checksum', 'model_checksum', 'positions', 'weights', 'cash_usd', 'equity_usd', 'return_pct', 'ok']


def s32(x):
    return x - (1 << 32) if x >= 1 << 31 else x


def unpack_codes(v, n):
    return [(v >> (2 * i)) & 3 for i in range(n)]


def merge_by_minute(per_company):
    """[[bars of company 0], [bars of company 1], ...] -> [(time, [(company, bar), ...])] in time order,
    companies in the user's order inside a minute."""
    slots = {}
    for c, bars in enumerate(per_company):
        for b in bars:
            slots.setdefault(b.time, []).append((c, b))
    return [(t, sorted(v, key=lambda x: x[0])) for t, v in sorted(slots.items())]


class Settings:
    """The allocator settings and how they are sent (CFG_MODE / CFG_ROT / CFG_W)."""

    def __init__(self, rank=True, rotate=True, reweight=True, max_lots=0, margin_pct=0.1, min_hold=5, k=3,
                 floor_pct=12.5, capshift=14, n=None):
        if floor_pct is None:                         # default: half of an equal share
            floor_pct = 50.0 / max(n or 4, 1)
        self.mode = MODE_PORTFOLIO | (MODE_RANK if rank else 0) | (MODE_ROTATE if rotate else 0) | \
            (MODE_REWEIGHT if reweight else 0)
        self.max_lots = int(max_lots)
        self.margin = int(round(margin_pct / 100.0 * (1 << SCORE_FRAC)))
        self.min_hold = int(min_hold) & 255
        self.k = int(k) & 31
        self.wfloor = min(0xFFFF, int(round(floor_pct / 100.0 * W_TOTAL)))
        self.capshift = int(capshift) & 31

    @classmethod
    def from_args(cls, a, n):
        return cls(rank=not a.no_rank, rotate=not a.no_rotate, reweight=not a.no_reweight, max_lots=a.max_lots,
                   margin_pct=a.margin_pct, min_hold=a.min_hold, k=a.weight_step, floor_pct=a.floor_pct,
                   capshift=a.capshift, n=n)

    def describe(self):
        parts = [nm for bit, nm in ((MODE_RANK, 'rank'), (MODE_ROTATE, 'rotate'), (MODE_REWEIGHT, 'reweight'))
                 if self.mode & bit]
        return ('hybrid: %s | MARGIN %.3f%% | MIN_HOLD %d min | weight step 1/%d | floor %.1f%% | caps %d%% of the '
                'cash | MAX_LOTS %s' % (' + '.join(parts) or 'no rank / rotate / reweight', self.margin * 100.0 / (1 << SCORE_FRAC),
                                        self.min_hold, 1 << self.k, self.wfloor * 100.0 / W_TOTAL,
                                        (100 << 15) >> self.capshift, self.max_lots or 'whole bar'))

    def commands(self):
        return [(CMD_CFG_MODE, self.mode, self.max_lots), (CMD_CFG_ROT, self.margin, self.min_hold),
                (CMD_CFG_W, self.k | (self.capshift << 8), self.wfloor)]

    def apply(self, m):
        """Put the same settings into a PortfolioModel (before its reset)."""
        m.mode_cfg, m.max_lots, m.margin, m.min_hold = self.mode, self.max_lots, self.margin, self.min_hold
        m.wshift, m.capshift, m.wfloor = self.k, self.capshift, self.wfloor


class SimHybridBoard:
    """No hardware: answers like the firmware in portfolio mode (PortfolioModel; latencies are placeholders)."""

    def __init__(self, n_max=8):
        self.m = PortfolioModel(n_max)
        self.m.mode_cfg = self.m.mode = 0

    def exchange(self, tid, price, vol):
        m, c = self.m, (tid >> 28) & 7
        if tid == CMD_ALLOCATE:
            codes = m.allocate(0)
            packed = sum(x << (2 * i) for i, x in enumerate(codes))
            return (tid, m.cash & M32, m.cash >> 32, packed, random.randint(7, 30), packed,
                    random.randint(300, 1300), m.checksum())
        if tid & 0x80000000:
            m.command(tid, price, vol)
            cmd = tid & ~0x70000000
            pos = m.nsym if cmd == CMD_CFG_NSYM else ((m.mode << 4) | m.mode_cfg) if cmd == CMD_CFG_MODE else \
                (m.pos[c] if c < m.n_max else 0)
            return (tid, price, vol, 0, 0, 0, 0, pos)
        r = m.tick(c, price, vol)
        if r is None:
            return (tid, price, vol, 0, 0, 0, 0, 0)
        sig, score = r
        return (tid, price, vol, sig, 5, sig, random.randint(150, 1700), score & M32)


class HybridRun:
    def __init__(self, args, symbols, names, cfgs, starting_cash, settings, scale, lot, title, slots):
        self.args, self.symbols, self.names, self.cfgs = args, symbols, names, cfgs
        self.n = len(symbols)
        self.settings, self.scale, self.lot, self.title = settings, scale, lot, title
        self.slots = slots                                          # every minute of the session ('YYYY-MM-DD HH:MM')
        self.start_units = starting_cash
        self.start_cash = self.units_usd(starting_cash)
        self.lock = threading.Lock()
        m = self.model = PortfolioModel(max(self.n, 1))
        m.nsym = self.n
        for c, (lim, hi, lo) in enumerate(cfgs):
            e = m.engines[c]
            e.pos_limit, e.brk_high, e.brk_low = lim, hi, lo
        settings.apply(m)
        m.starting_cash = starting_cash
        m.reset()
        # what the window shows (all verified against the model before it is stored)
        self.minutes = []                    # one dict per allocation
        self.ticks_of = [[] for _ in range(self.n)]   # per company: dict(minute, price, vote, score)
        self.marks = [[] for _ in range(self.n)]      # per company: (minute, price, code)
        self.realized = [0] * self.n                  # profit of closed positions (units)
        self.trades = [dict(buy=0, sell=0, rot=0) for _ in range(self.n)]
        self.last_price = [0] * self.n
        self.cash_units = starting_cash
        self.ticks = self.bad_ticks = self.bad_allocs = self.no_report = self.fw_flags = 0
        self.status = 'starting'
        self.done = False
        self.log = None
        self.fills = []              # every execution: dict(x, lane, time, sym, side, qty, price, notional)
        self.rtt = []                # PC -> FPGA -> PC round trip of every packet (ms)
        self.t_start = self.t_end = None

    def units_usd(self, units):
        return units * self.lot / self.scale

    def usd(self, price):
        return price / self.scale

    # ---- one tick report
    def record_tick(self, minute, tid, c, bar, rep):
        rid, rp, rv, hwd, hwl, swd, swl, hwp = rep
        sig, score = self.model.tick(c, bar.price, bar.vol)
        ok = (rid, rp, rv) == (tid, bar.price, bar.vol) and hwd == swd == sig and s32(hwp) == score
        with self.lock:
            self.ticks += 1
            self.bad_ticks += not ok
            self.last_price[c] = bar.price
            self.ticks_of[c].append(dict(minute=minute, price=bar.price, vote=hwd, score=s32(hwp), open=bar.open,
                                         high=bar.high, low=bar.low, close=bar.close, volume=bar.volume, vol=bar.vol,
                                         hw_lat=hwl, sw_lat=swl))
        return dict(kind='tick', minute=minute, time=bar.time, company=self.symbols[c], sym=c, tick_id='%08x' % tid,
                    open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume,
                    price_sent=bar.price, vol_sent=bar.vol, price_echo=rp, vol_echo=rv, hw_vote=hwd, sw_vote=swd, model_vote=sig, hw_lat=hwl,
                    sw_lat=swl, hw_score=s32(hwp), model_score=score, ok=int(ok))

    # ---- one ALLOCATE report
    def record_alloc(self, minute, tm, rep):
        rid, cash_lo, cash_hi, hwd, hwl, swd, swl, chk = rep
        m, n = self.model, self.n
        kill = (hwd >> 16) & 1
        before = [(m.pos[c], m.inv[c], m.lastp[c]) for c in range(n)]
        codes = m.allocate(kill)[:n]
        packed = sum(x << (2 * i) for i, x in enumerate(codes))
        hw_cash = cash_lo | (cash_hi << 32)
        fw_flag = (hwd >> 31) & 1
        ok = rid == CMD_ALLOCATE and (hwd & 0xFFFF) == packed and swd == packed and hw_cash == m.cash and \
            chk == m.checksum() and not fw_flag
        with self.lock:
            self.bad_allocs += not ok
            self.fw_flags += fw_flag
            self.cash_units = hw_cash
            for c, code in enumerate(codes):
                pos0, inv0, lp = before[c]
                if code == BUY:
                    self.trades[c]['buy'] += 1
                elif code in (SELL, ROT):
                    self.trades[c]['sell' if code == SELL else 'rot'] += 1
                    self.realized[c] += pos0 * lp - inv0
                if code != NONE:
                    self.marks[c].append((minute, m.lastp[c], code))
                    qty = (m.pos[c] - pos0) if code == BUY else pos0
                    self.fills.append(dict(x=minute, lane=c, time=tm[-5:], sym=self.symbols[c], side=code, qty=qty,
                                           price=m.lastp[c] / self.scale,
                                           notional=self.units_usd(qty * m.lastp[c])))
            eq = hw_cash + sum(m.pos[c] * self.last_price[c] for c in range(n))
            ret = 100.0 * (eq - self.start_units) / self.start_units if self.start_units else 0.0
            self.minutes.append(dict(minute=minute, time=tm, cash=hw_cash, equity=eq, ret=ret, codes=codes,
                                     pos=m.pos[:n], w=m.w[:n], hold=m.hold[:n], inv=m.inv[:n],
                                     hw_lat=hwl, sw_lat=swl, kill=kill, ok=ok))
        return dict(kind='alloc', minute=minute, time=tm, kill=kill, hw_codes=hwd & 0xFFFF, sw_codes=swd,
                    model_codes=packed, hw_lat=hwl, sw_lat=swl, hw_cash_units=hw_cash, model_cash_units=m.cash,
                    hw_checksum=chk, model_checksum=m.checksum(), positions=' '.join(map(str, m.pos[:n])),
                    weights=' '.join(map(str, m.w[:n])), cash_usd=self.units_usd(hw_cash),
                    equity_usd=self.units_usd(eq), return_pct=ret, ok=int(ok))


def configure(run, board):
    """RESET, NUM_SYMBOLS, per-company breakout / limit, allocator settings, cash, RESET (the mode takes
    effect on that RESET).  Returns an error text or None."""
    cmds = [(CMD_RESET, 0, 0), (CMD_CFG_NSYM, run.n, 0)]
    for c, (lim, hi, lo) in enumerate(run.cfgs):
        cmds += [(with_sym(CMD_CFG_BRK, c), hi, lo), (with_sym(CMD_CFG_LIMIT, c), lim, 0)]
    cmds += run.settings.commands()
    cmds += [(CMD_CFG_CASH, run.start_units & M32, run.start_units >> 32), (CMD_RESET, 0, 0)]
    for cmd, p, v in cmds:
        rep = board.exchange(cmd, p, v)
        if rep is None or rep[0] != cmd:
            return 'board did not answer the %s command (check COM port / bitstream)' % hex(cmd)
        if cmd == CMD_CFG_NSYM and rep[7] != run.n:
            return ('the board trades at most %d companies at once (this bitstream has %d engines), %d were asked: '
                    'rebuild with a larger HFT_N_MAX in soc_top.v or use fewer companies' % (rep[7], rep[7], run.n))
        if cmd == CMD_CFG_MODE and (rep[7] & 15) != run.settings.mode:
            return ('the board did not accept the portfolio mode (answer %#x): this bitstream / board image has no '
                    'hardware allocator (v10 or older).  Program the v11 bitstream, or use --strategy independent'
                    % rep[7])
    return None


def worker(run, board, minutes, logw, logf):
    a = run.args
    err = configure(run, board)
    if err:
        run.status = err
        print(err)
        run.done = True
        return
    print('board reset and configured: %d companies, shared starting cash %d units' % (run.n, run.start_units))
    print(run.settings.describe())
    run.status = 'running'
    run.t_start = time.perf_counter()
    t_next = time.time()
    k = 0
    for mi, (tm, bars) in enumerate(minutes):
        if a.max_ticks and k >= a.max_ticks:
            break
        for c, bar in bars:
            k += 1
            tid = with_sym(k, c)
            t_tx = time.perf_counter()
            rep = board.exchange(tid, bar.price, bar.vol)
            with run.lock:
                run.rtt.append(1000.0 * (time.perf_counter() - t_tx))
            if rep is None:
                # v11 stepped the model anyway and went on, but the board may or may not have
                # processed this tick, so the comparison could no longer be trusted
                run.no_report += 1
                print('%s %s: no report from the board; %s' % (tm, run.symbols[c], LOST_SYNC))
                break
            row = run.record_tick(mi, tid, c, bar, rep)
            logw.writerow(row)
            if not row['ok']:
                print('%s %-5s tick MISMATCH: HW vote %d SW vote %d score %d | model vote %d score %d'
                      % (tm, run.symbols[c], row['hw_vote'], row['sw_vote'], row['hw_score'], row['model_vote'],
                         row['model_score']))
        if run.no_report:
            break
        rep = board.exchange(CMD_ALLOCATE, mi + 1, 0)
        if rep is None:
            run.no_report += 1
            print('%s ALLOCATE: no report from the board; %s' % (tm, LOST_SYNC))
            break
        row = run.record_alloc(mi, tm, rep)
        logw.writerow(row)
        logf.flush()
        codes = run.minutes[-1]['codes']
        if any(codes) or not row['ok']:
            print('%s | %s | cash %s | HW %d cyc, SW %d cyc%s'
                  % (tm, ' '.join('%s:%s' % (s, CODE_NAMES[x]) for s, x in zip(run.symbols, codes) if x),
                     money(run.units_usd(row['hw_cash_units'])), row['hw_lat'], row['sw_lat'],
                     '' if row['ok'] else '   <-- MISMATCH (HW codes %x, SW codes %x, model %x)'
                     % (row['hw_codes'], row['sw_codes'], row['model_codes'])))
        if a.speed:
            t_next += 1.0 / a.speed
            time.sleep(max(0.0, t_next - time.time()))
    run.t_end = time.perf_counter()
    run.status = 'finished' if not run.no_report else 'stopped: a report from the board was missing'
    run.done = True
    print('done: %d ticks, %d allocations | tick mismatches %d | allocation mismatches %d (firmware flagged %d) | '
          'missing reports %d' % (run.ticks, len(run.minutes), run.bad_ticks, run.bad_allocs, run.fw_flags,
                                  run.no_report))
    for line in summary(run):
        print(line)
    print('log written to', run.log, ' -> check it with: python verify_run.py', run.log)


def money(v):
    return ('-' if v < 0 else '') + '$' + format(abs(int(round(v))), ',')


def summary(run):
    if not run.minutes:
        return []
    m, last = run.model, run.minutes[-1]
    out = ['%-8s %5s %5s %5s %9s %8s %14s %11s' % ('company', 'BUY', 'SELL', 'ROT', 'position', 'weight',
                                                   'realized P&L', 'buy & hold')]
    for c, sym in enumerate(run.symbols):
        tc = run.ticks_of[c]
        bh = 100.0 * (tc[-1]['price'] / tc[0]['price'] - 1.0) if tc else 0.0
        t = run.trades[c]
        out.append('%-8s %5d %5d %5d %9d %7.1f%% %14s %+10.3f%%' % (sym, t['buy'], t['sell'], t['rot'], m.pos[c],
                                                                    100.0 * m.w[c] / W_TOTAL,
                                                                    money(run.units_usd(run.realized[c])), bh))
    out.append('portfolio: starting cash %s, cash now %s, equity %s, return %+.4f%%'
               % (money(run.start_cash), money(run.units_usd(last['cash'])), money(run.units_usd(last['equity'])),
                  last['ret']))
    st = m.stats
    out.append('allocator: %d minutes where the ranking changed the order, %d rotations, %d wins + %d losses '
               'reweighted; BUY refused: %d cash, %d cap, %d position limit'
               % (st['ranked'], st['rotations'], st['wins'], st['losses'], st['refused_cash'], st['refused_cap'],
                  st['refused_limit']))
    hl = [x['hw_lat'] for x in run.minutes]
    sl = [x['sw_lat'] for x in run.minutes]
    out.append('allocation latency: hardware %d..%d cycles, RISC-V software %d..%d cycles'
               % (min(hl), max(hl), min(sl), max(sl)))
    if not any(any(x['codes']) for x in run.minutes):
        out.append('WARNING: no trade was executed in this run.')
    return out


def write_cfg(path, run, source):
    s = run.settings
    with open(path + '.cfg', 'w') as f:
        f.write('mode=hybrid\nsymbols=%s\nnsym=%d\nstarting_cash_units=%d\nscale=%d\nlot=%d\nsource=%s\n'
                'port_mode=%d\nmax_lots=%d\nmargin=%d\nmin_hold=%d\nwshift=%d\ncapshift=%d\nwfloor=%d\n'
                % (','.join(run.symbols), run.n, run.start_units, run.scale, run.lot, source, s.mode, s.max_lots,
                   s.margin, s.min_hold, s.k, s.capshift, s.wfloor))
        for c, (lim, hi, lo) in enumerate(run.cfgs):
            f.write('pos_limit_%d=%d\nbrk_high_%d=%d\nbrk_low_%d=%d\n' % (c, lim, c, hi, c, lo))


# ----------------------------------------------------------------------------- the window
class View:
    """Which page is shown: overview (focus None) or one company's whole day (focus = company)."""

    def __init__(self, focus=None):
        self.focus = focus
        self.axes_company = {}           # axes of the overview -> company (for the click)
        self.dirty = True


def plot_loop(run, snapshot=None, focus=None):
    """the live window: the trading-terminal view (dash_pro.py), or the v12 window with --classic"""
    a = run.args
    if getattr(a, 'classic', False):
        return plot_loop_classic(run, snapshot, focus)
    import dash_pro
    return dash_pro.run_portfolio(run, snapshot, focus, util=getattr(a, 'util_report', None),
                                  timing=getattr(a, 'timing_report', None), window=WINDOW)


def plot_loop_classic(run, snapshot=None, focus=None):
    import matplotlib
    if snapshot:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.ticker import FuncFormatter, PercentFormatter

    usd_axis = FuncFormatter(lambda v, _: ('$%.2fB' % (v / 1e9)) if abs(v) >= 1e9 else ('$%.1fM' % (v / 1e6))
                             if abs(v) >= 1e6 else ('$%.0f' % v))
    n = run.n
    view = View(focus)
    fig = plt.figure(figsize=(16, 8.6), dpi=100)
    try:
        fig.canvas.manager.set_window_title(run.title)
    except AttributeError:
        pass
    mark_style = {BUY: ('^', '#00b050', 'BUY'), SELL: ('v', '#c000c0', 'SELL'), ROT: ('X', '#d00000', 'ROT (sold to fund a stronger BUY)')}

    def time_axis(ax, lo, hi, nlab=8):
        """x = minute index; labels HH:MM."""
        hi = max(hi, lo + 1)
        step = max(1, (hi - lo) // nlab)
        xs = list(range(lo, hi + 1, step))
        ax.set_xticks(xs)
        ax.set_xticklabels([run.slots[x][-5:] if x < len(run.slots) else '' for x in xs], fontsize=7)
        ax.set_xlim(lo - 0.5, hi + 0.5)
        ax.tick_params(axis='y', labelsize=7)

    def draw_marks(ax, c, lo, hi, size=46):
        done = set()
        for mi, p, code in run.marks[c]:
            if lo <= mi <= hi:
                mk, col, lab = mark_style[code]
                ax.scatter([mi], [run.usd(p)], marker=mk, s=size, color=col, edgecolors='black', linewidths=0.4,
                           zorder=5, label=lab if code not in done else None)
                done.add(code)

    def status_lines(minutes, compact=True):
        last = minutes[-1]
        nt = run.ticks
        lines = ['%s  %s' % (last['time'][-5:], run.status),
                 'ticks  %d/%d ok' % (nt - run.bad_ticks, nt),
                 'minutes %d/%d ok' % (len(minutes) - run.bad_allocs, len(minutes)),
                 'no report: %d' % run.no_report] + (['KILL SWITCH ON'] if last['kill'] else []) + [
                 '', 'start  %s' % money(run.start_cash), 'cash   %s' % money(run.units_usd(last['cash'])),
                 'equity %s' % money(run.units_usd(last['equity'])), 'return %+.3f%%' % last['ret']]
        if not compact:
            st = run.model.stats
            lines += ['', 'rank changed order: %d min' % st['ranked'], 'rotations: %d' % st['rotations'],
                      'reweighted: %d wins, %d losses' % (st['wins'], st['losses'])]
        return lines

    def status_box(ax, minutes, compact=True):
        ax.axis('off')
        ok = run.bad_ticks == 0 and run.bad_allocs == 0 and run.no_report == 0
        ax.text(0.04, 1.0, '\n'.join(status_lines(minutes, compact)), fontsize=8, family='monospace', va='top',
                transform=ax.transAxes,
                bbox=dict(facecolor='#e8f7e8' if ok else '#fde2e2', edgecolor='black', boxstyle='round,pad=0.6'))

    # ---------------------------------------------------------------- overview: all companies, last hour
    def short_money(units):
        v = run.units_usd(units)
        return ('-' if v < 0 else '+') + ('$%.2fB' % (abs(v) / 1e9) if abs(v) >= 1e9 else '$%.1fM' % (abs(v) / 1e6)
                                          if abs(v) >= 1e6 else '$%.0fk' % (abs(v) / 1e3) if abs(v) >= 1e3 else
                                          '$%.0f' % abs(v))

    def mark_legend():
        from matplotlib.lines import Line2D
        hs = [Line2D([], [], marker=mk, color='w', markerfacecolor=col, markeredgecolor='black', markersize=8, label=lab)
              for mk, col, lab in mark_style.values()]
        fig.legend(handles=hs, loc='lower left', ncol=3, fontsize=8, frameon=False, bbox_to_anchor=(0.04, 0.0))

    def draw_overview(minutes):
        from matplotlib.gridspec import GridSpecFromSubplotSpec
        cols = 1 if n <= 3 else 2
        rows = (n + cols - 1) // cols
        outer = fig.add_gridspec(1, 2, width_ratios=[1.0 * cols + 0.15, 1.75], left=0.045, right=0.99, top=0.9,
                                 bottom=0.075, wspace=0.13)
        left = GridSpecFromSubplotSpec(rows, cols, subplot_spec=outer[0], hspace=0.62, wspace=0.22)
        right = GridSpecFromSubplotSpec(3, 2, subplot_spec=outer[1], width_ratios=[1.55, 1.0], hspace=0.55,
                                        wspace=0.42)
        hi = minutes[-1]['minute']
        lo = max(0, hi - WINDOW + 1)
        last = minutes[-1]
        view.axes_company = {}
        for c in range(n):
            r, k = divmod(c, cols)
            ax = fig.add_subplot(left[r, k])
            view.axes_company[ax] = c
            col = COLORS[c % len(COLORS)]
            pts = [t for t in run.ticks_of[c] if lo <= t['minute'] <= hi]
            if pts:
                ax.plot([t['minute'] for t in pts], [run.usd(t['price']) for t in pts], color=col, linewidth=1.1)
            draw_marks(ax, c, lo, hi)
            sc = run.ticks_of[c][-1]['score'] if run.ticks_of[c] else 0
            ax.set_title('%d  %s\npos %d lots | weight %.1f%% | score %+.3f%% | closed P&L %s'
                         % (c + 1, run.names[c], last['pos'][c], 100.0 * last['w'][c] / W_TOTAL,
                            100.0 * sc / (1 << SCORE_FRAC), short_money(run.realized[c])),
                         fontsize=8, loc='left', color=col)
            time_axis(ax, lo, hi, 6)
            for sp in ax.spines.values():
                sp.set_edgecolor(col)
                sp.set_linewidth(1.2)
        win = [x for x in minutes if lo <= x['minute'] <= hi]
        xs = [x['minute'] for x in win]
        ax_e = fig.add_subplot(right[0, 0])
        ax_e.plot(xs, [x['ret'] for x in win], color='#1f4e9c', linewidth=1.4)
        ax_e.axhline(0, color='gray', linewidth=0.7)
        ax_e.yaxis.set_major_formatter(PercentFormatter(decimals=2))
        ax_c = ax_e.twinx()
        ax_c.plot(xs, [run.units_usd(x['cash']) for x in win], color='#898781', linewidth=1.0, linestyle='--')
        ax_c.yaxis.set_major_formatter(usd_axis)
        ax_c.tick_params(axis='y', labelsize=6.5, colors='#696761')
        ax_e.set_title('Portfolio return (blue) and shared cash (grey)', fontsize=8.5, loc='left')
        time_axis(ax_e, lo, hi, 4)
        ax_w = fig.add_subplot(right[1, 0])
        ax_w.stackplot(xs, *[[100.0 * x['w'][c] / W_TOTAL for x in win] for c in range(n)],
                       colors=[COLORS[c % len(COLORS)] for c in range(n)], alpha=0.75,
                       labels=[run.symbols[c] for c in range(n)])
        ax_w.set_ylim(0, 100)
        ax_w.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        ax_w.legend(loc='lower left', fontsize=6, ncol=min(n, 4), framealpha=0.7)
        ax_w.set_title('Weights (share of the cap budget)', fontsize=8.5, loc='left')
        time_axis(ax_w, lo, hi, 4)
        ax_l = fig.add_subplot(right[2, 0])
        ax_l.plot(xs, [x['sw_lat'] for x in win], color='#e07b00', linewidth=1.0, label='RISC-V software')
        ax_l.plot(xs, [x['hw_lat'] for x in win], color='black', linewidth=1.8, label='hardware')
        ax_l.set_yscale('log')
        ax_l.legend(loc='center left', fontsize=6.5)
        ax_l.set_title('Allocation latency (cycles)', fontsize=8.5, loc='left')
        time_axis(ax_l, lo, hi, 4)
        ax_s = fig.add_subplot(right[0, 1])
        status_box(ax_s, minutes)
        ax_t = fig.add_subplot(right[1:, 1])
        ax_t.axis('off')
        recent = []
        for x in reversed(minutes):
            for c, code in enumerate(x['codes']):
                if code:
                    recent.append('%s %-5s %s' % (x['time'][-5:], run.symbols[c], CODE_NAMES[code]))
            if len(recent) >= 24:
                break
        ax_t.text(0.04, 1.0, 'latest trades\n' + ('\n'.join(recent[:24]) if recent else '(none yet)'), fontsize=7.5,
                  family='monospace', va='top', transform=ax_t.transAxes)
        mark_legend()
        fig.suptitle('%s   |   last %d minutes   |   click a company (or press 1-%d) for its whole day'
                     % (run.title, WINDOW, n), x=0.01, ha='left', fontsize=10)

    # ---------------------------------------------------------------- one company, the whole day
    def draw_focus(minutes, c):
        col = COLORS[c % len(COLORS)]
        gs = fig.add_gridspec(4, 2, width_ratios=[3.2, 1.0], height_ratios=[2.4, 1.0, 1.0, 1.0],
                              left=0.055, right=0.985, top=0.9, bottom=0.06, wspace=0.12, hspace=0.45)
        hi = minutes[-1]['minute']
        lo = 0
        tc = run.ticks_of[c]
        ax_p = fig.add_subplot(gs[0, 0])
        if tc:
            ax_p.plot([t['minute'] for t in tc], [run.usd(t['price']) for t in tc], color=col, linewidth=1.1,
                      label='%s price echoed by the FPGA' % run.names[c])
        draw_marks(ax_p, c, lo, hi, size=70)          # (labels: legend below)
        lim, bh, bl = run.cfgs[c]
        if tc:
            ys = [run.usd(t['price']) for t in tc]
            span = (max(ys) - min(ys)) or 1.0
            for lvl, nm in ((run.usd(bh), 'BRK_HIGH'), (run.usd(bl), 'BRK_LOW')):
                if min(ys) - 0.3 * span <= lvl <= max(ys) + 0.3 * span:
                    ax_p.axhline(lvl, color='gray', linestyle=':', linewidth=1)
                    ax_p.text(lo, lvl, ' ' + nm, fontsize=7, color='gray', va='bottom')
        ax_p.legend(loc='best', fontsize=7.5)
        ax_p.set_ylabel('USD', fontsize=8)
        ax_p.set_title('%s (company %d): the whole day so far' % (run.names[c], c + 1), fontsize=10, loc='left',
                       color=col)
        time_axis(ax_p, lo, hi, 12)
        ax_sc = fig.add_subplot(gs[1, 0], sharex=ax_p)
        if tc:
            vcol = {BUY: '#00b050', SELL: '#c000c0', NONE: '#b0b0b0'}
            ax_sc.bar([t['minute'] for t in tc], [100.0 * t['score'] / (1 << SCORE_FRAC) for t in tc], width=0.9,
                      color=[vcol.get(t['vote'], '#b0b0b0') for t in tc])
        ax_sc.axhline(0, color='gray', linewidth=0.7)
        ax_sc.yaxis.set_major_formatter(PercentFormatter(decimals=2))
        ax_sc.set_title('momentum score (bars coloured by the signal: green BUY, purple SELL, grey none)',
                        fontsize=8.5, loc='left')
        time_axis(ax_sc, lo, hi, 12)
        xs = [x['minute'] for x in minutes]
        ax_q = fig.add_subplot(gs[2, 0], sharex=ax_p)
        ax_q.step(xs, [x['pos'][c] for x in minutes], where='post', color=col, linewidth=1.3)
        ax_q.set_title('position (lots)', fontsize=8.5, loc='left')
        time_axis(ax_q, lo, hi, 12)
        ax_w = fig.add_subplot(gs[3, 0], sharex=ax_p)
        ax_w.plot(xs, [100.0 * x['w'][c] / W_TOTAL for x in minutes], color=col, linewidth=1.3,
                  label='weight of %s' % run.symbols[c])
        ax_w.axhline(100.0 * W_TOTAL / max(n, 1) / W_TOTAL, color='gray', linestyle=':', linewidth=0.8,
                     label='equal weight')
        ax_w.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        ax_w.legend(loc='best', fontsize=7)
        ax_w.set_title('weight (share of the cap budget)', fontsize=8.5, loc='left')
        time_axis(ax_w, lo, hi, 12)
        ax_i = fig.add_subplot(gs[:, 1])
        ax_i.axis('off')
        t = run.trades[c]
        last = minutes[-1]
        value = last['pos'][c] * run.last_price[c]
        lines = [run.names[c], '',
                 'BUY   %d' % t['buy'], 'SELL  %d' % t['sell'], 'ROT   %d  (sold to fund others)' % t['rot'], '',
                 'position   %d lots' % last['pos'][c], 'held for   %d min' % last['hold'][c],
                 'invested   %s' % money(run.units_usd(last['inv'][c])),
                 'value now  %s' % money(run.units_usd(value)),
                 'open P&L   %s' % money(run.units_usd(value - last['inv'][c])),
                 'closed P&L %s' % money(run.units_usd(run.realized[c])),
                 'weight     %.1f%%' % (100.0 * last['w'][c] / W_TOTAL), '']
        if tc:
            lines.append('buy & hold %+.3f%%' % (100.0 * (tc[-1]['price'] / tc[0]['price'] - 1.0)))
        lines += ['', '-' * 30] + status_lines(minutes, compact=False)
        ax_i.text(0.0, 1.0, '\n'.join(lines), fontsize=8.5, family='monospace', va='top', transform=ax_i.transAxes)
        fig.suptitle('%s   |   %s: the whole day   |   click anywhere or press Esc for all companies'
                     % (run.title, run.names[c]), x=0.01, ha='left', fontsize=10)

    def update(_=None):
        with run.lock:
            minutes = list(run.minutes)
        fig.clf()
        if not minutes:
            fig.text(0.5, 0.5, run.status, ha='center', fontsize=12)
            return
        if view.focus is None or view.focus >= n:
            draw_overview(minutes)
        else:
            draw_focus(minutes, view.focus)

    def on_click(ev):
        if view.focus is None:
            c = view.axes_company.get(ev.inaxes)
            if c is None:
                return
            view.focus = c
        else:
            view.focus = None
        update()
        fig.canvas.draw_idle()

    def on_key(ev):
        if ev.key == 'escape' or ev.key == 'backspace':
            view.focus = None
        elif ev.key and ev.key.isdigit() and 1 <= int(ev.key) <= n:
            view.focus = int(ev.key) - 1
        else:
            return
        update()
        fig.canvas.draw_idle()

    if snapshot:
        update()
        fig.savefig(snapshot, dpi=100)
        plt.close(fig)
        print('dashboard picture:', snapshot)
        return
    fig.canvas.mpl_connect('button_press_event', on_click)
    fig.canvas.mpl_connect('key_press_event', on_key)
    try:                                   # fill the screen (TkAgg / Qt); the layout also fits 1600 x 860
        mng = plt.get_current_fig_manager()
        if hasattr(mng, 'window') and hasattr(mng.window, 'state'):
            mng.window.state('zoomed')
        elif hasattr(mng, 'window') and hasattr(mng.window, 'showMaximized'):
            mng.window.showMaximized()
    except Exception:
        pass
    _ani = FuncAnimation(fig, update, interval=900, cache_frame_data=False)
    plt.show()


def run_hybrid(a, symbols, real_session, cash_units_fn, default_cash, make_board):
    """Entry point from hft_dashboard.main() (same session / cash / board rules as the other modes)."""
    import market_feed
    from datetime import datetime
    names = [market_feed.company_name(s) for s in symbols]
    if a.source == 'csv':
        files = (a.file.split(',') if a.file else ['%s_ticks.csv' % s for s in symbols])
        if len(files) != len(symbols):
            raise SystemExit('--file needs one CSV per company (%d given, %d companies)' % (len(files), len(symbols)))
        all_bars = [market_feed.bars_from_csv(f, a.lot) for f in files]
        src = 'from ' + ', '.join(os.path.basename(f) for f in files)
    else:
        all_bars = [market_feed.fetch_minute_bars(s, '7d', a.lot) for s in symbols]
        src = 'replayed through the FPGA'
    common = None
    for bars in all_bars:
        d = set(market_feed.replayable_days(bars))
        common = d if common is None else common & d
    if not common:
        raise SystemExit('the companies have no replayable session in common')
    day = a.day or max(common)
    if day not in common:
        raise SystemExit('no session %s for every company (common sessions: %s)' % (day, ', '.join(sorted(common))))
    sess, cfgs = [], []
    for s, bars in zip(symbols, all_bars):
        _, b, cfg = real_session(a, s, day, bars)
        sess.append(b)
        cfgs.append(cfg[:3])
        print('%s %s: %d bars, previous-session high/low %.2f / %.2f USD' % (market_feed.company_name(s), day,
                                                                            len(b), cfg[1] / 100, cfg[2] / 100))
    cash = default_cash if a.starting_cash is None else a.starting_cash
    start_units = cash_units_fn(cash, 100, a.lot)
    minutes = merge_by_minute(sess)
    settings = Settings.from_args(a, len(symbols))
    title = '%s  %s  (hardware allocator, one cash account)' % (' + '.join(symbols), day)
    if a.port.lower() == 'none':
        title += '  [SIMULATION, no board]'
    print('%s, %s' % (title, src))
    run = HybridRun(a, symbols, names, cfgs, start_units, settings, 100, a.lot, title, [t for t, _ in minutes])
    log_path = a.log or 'run_%s_%s_%s.csv' % ('-'.join(symbols), day, datetime.now().strftime('%H%M%S'))
    run.log = log_path
    logf = open(log_path, 'w', newline='')
    logw = csv.DictWriter(logf, fieldnames=LOG_FIELDS)
    logw.writeheader()
    write_cfg(log_path, run, a.source)
    board = SimHybridBoard() if a.port.lower() == 'none' else make_board(a)
    th = threading.Thread(target=worker, args=(run, board, minutes, logw, logf), daemon=True)
    th.start()
    if a.no_plot:
        th.join()
        if a.save_png and run.minutes:
            plot_loop(run, snapshot=a.save_png)
            if a.save_png_focus:
                base, ext = os.path.splitext(a.save_png)
                for c in range(run.n):
                    plot_loop(run, snapshot='%s_%s%s' % (base, run.symbols[c], ext), focus=c)
    else:
        plot_loop(run)
    logf.close()
    return run
