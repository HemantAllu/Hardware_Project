"""hft_portfolio.py - trade several companies AT THE SAME TIME from ONE cash account.

Used by hft_dashboard.py:
  python hft_dashboard.py --company apple,nvidia --together              replay the latest common session
  python hft_dashboard.py --source csv --file AAPL_ticks.csv,NVDA_ticks.csv --company apple,nvidia
  python hft_dashboard.py --company apple,nvidia --together --cap-pct 50 every company may invest at
                                                                         most 50 % of the starting cash
  ... --port none                                                        Python model instead of a board

Each company runs its own engine on the FPGA (hft_multi.v): own price history, VWAP, breakout
levels (that company's previous session), position limit and position.  Only the cash is shared.
The 1-minute bars of all companies are merged by time; inside one minute the companies are sent in
the order given on the command line (the hardware, the firmware and the model all apply the trades
in that order, so the shared cash always agrees).  A tick for company k carries k in id[30:28].

The window: one price panel per company with the hardware's BUY/SELL marks, then the portfolio:
shared cash and total equity (cash + every holding at its last close), the return on the starting
cash, and the decision latency (RISC-V software vs hardware).  Every report is checked as it
arrives (echo, HW == SW, HW decision and position == hft_model.MultiModel) and logged to a CSV;
check it afterwards with verify_run.py.
"""
import csv
import os
import random
import threading
import time

from hft_model import (LOST_SYNC, MultiModel, NAMES, CMD_RESET, CMD_CFG_BRK, CMD_CFG_LIMIT, CMD_CFG_CASH,
                       CMD_CFG_NSYM, CMD_CFG_CAP, with_sym)

LOG_FIELDS = ['tick', 'tick_id', 'company', 'sym', 'time', 'open', 'high', 'low', 'close', 'volume',
              'price_sent', 'vol_sent', 'price_echo', 'vol_echo', 'hw_dec', 'hw_lat', 'sw_dec', 'sw_lat',
              'hw_pos', 'model_dec', 'model_pos', 'cash_units', 'cash_usd', 'equity_usd', 'return_pct']
COLORS = ['#2b5fd9', '#e07b00', '#1a9850', '#c000c0', '#7030a0', '#c00000', '#008080', '#806000']


def merge(per_company):
    """per_company: list of bar lists (index = company number, in the user's order).
    Returns [(time, company, bar)] ordered by bar time, then company order."""
    out = []
    for c, bars in enumerate(per_company):
        out += [(b.time, c, b) for b in bars]
    out.sort(key=lambda t: (t[0], t[1]))
    return out


class SimPortfolioBoard:
    """No hardware: answers like the firmware, using MultiModel (latencies are placeholders)."""

    def __init__(self, n_max=8):
        self.m = MultiModel(n_max)

    def exchange(self, tid, price, vol):
        c = (tid >> 28) & 7
        if tid & 0x80000000:
            self.m.command(tid, price, vol)
            return (tid, price, vol, 0, 0, 0, 0,
                    self.m.nsym if (tid & ~0x70000000) == CMD_CFG_NSYM else self.m.pos(c))
        if c >= self.m.nsym:
            return (tid, price, vol, 0, 0, 0, 0, 0)
        d = self.m.step(c, price, vol)
        return (tid, price, vol, d, 5, d, random.randint(80, 100), self.m.pos(c))


class PortfolioRun:
    def __init__(self, args, symbols, names, cfgs, starting_cash, caps, scale, lot, title):
        self.args, self.symbols, self.names = args, symbols, names
        self.cfgs, self.caps = cfgs, caps                       # cfgs[c] = (pos_limit, brk_high, brk_low)
        self.n = len(symbols)
        self.scale, self.lot, self.title = scale, lot, title
        self.start_units = starting_cash
        self.start_cash = self.units_usd(starting_cash)
        self.lock = threading.Lock()
        self.rows = []
        self.model = MultiModel(max(self.n, 1))
        self.model.nsym = self.n
        for c, (lim, hi, lo) in enumerate(cfgs):
            e = self.model.engines[c]
            e.pos_limit, e.brk_high, e.brk_low = lim, hi, lo
            self.model.caps[c] = caps[c]
        self.model.starting_cash = starting_cash
        self.model.reset()
        self.cash_units = starting_cash                 # follows the HARDWARE decisions
        self.pos = [0] * self.n
        self.last_price = [0] * self.n
        self.ticks = self.hw_sw_bad = self.model_bad = self.echo_bad = self.no_report = 0
        self.status = 'starting'
        self.done = False
        self.log = None

    def units_usd(self, units):
        return units * self.lot / self.scale

    def usd(self, price):
        return price / self.scale

    def record(self, i, tid, c, t, rep):
        rid, rp, rv, hwd, hwl, swd, swl, hwp = rep
        md = self.model.step(c, t.price, t.vol)
        with self.lock:
            self.ticks += 1
            if (rid, rp, rv) != (tid, t.price, t.vol):
                self.echo_bad += 1
            if hwd != swd:
                self.hw_sw_bad += 1
            if hwd != md or hwp != self.model.pos(c):
                self.model_bad += 1
            if hwd == 1:
                self.cash_units -= t.price * t.vol
            elif hwd == 2:
                self.cash_units += t.price * t.vol
            self.pos[c], self.last_price[c] = hwp, rp
            eq_units = self.cash_units + sum(p * q for p, q in zip(self.pos, self.last_price))
            equity = self.units_usd(eq_units)
            ret = 100.0 * (eq_units - self.start_units) / self.start_units if self.start_units else 0.0
            self.rows.append(dict(tick=i, tick_id='%08x' % tid, company=self.symbols[c], sym=c, time=t.time,
                                  open=t.open, high=t.high, low=t.low, close=t.close, volume=t.volume,
                                  price_sent=t.price, vol_sent=t.vol, price_echo=rp, vol_echo=rv,
                                  hw_dec=hwd, hw_lat=hwl, sw_dec=swd, sw_lat=swl, hw_pos=hwp,
                                  model_dec=md, model_pos=self.model.pos(c), cash_units=self.cash_units,
                                  cash_usd=self.units_usd(self.cash_units), equity_usd=equity, return_pct=ret))
        return md


def configure(run, board):
    """RESET, NUM_SYMBOLS, per-company breakout / limit / cap, shared cash, RESET.  Returns an error or None."""
    cmds = [(CMD_RESET, 0, 0), (CMD_CFG_NSYM, run.n, 0)]
    for c, (lim, hi, lo) in enumerate(run.cfgs):
        cmds += [(with_sym(CMD_CFG_BRK, c), hi, lo), (with_sym(CMD_CFG_LIMIT, c), lim, 0),
                 (with_sym(CMD_CFG_CAP, c), run.caps[c] & 0xFFFFFFFF, run.caps[c] >> 32)]
    cmds += [(CMD_CFG_CASH, run.start_units & 0xFFFFFFFF, run.start_units >> 32), (CMD_RESET, 0, 0)]
    for cmd, p, v in cmds:
        rep = board.exchange(cmd, p, v)
        if rep is None or rep[0] != cmd:
            return 'board did not answer the %s command (check COM port / bitstream)' % hex(cmd)
        if cmd == CMD_CFG_NSYM and rep[7] != run.n:
            return ('the board trades at most %d companies at once (this bitstream has %d engines), %d were asked: '
                    'rebuild with a larger HFT_N_MAX in soc_top.v or use fewer companies' % (rep[7], rep[7], run.n))
    return None


def worker(run, board, merged, logw, logf):
    a = run.args
    err = configure(run, board)
    if err:
        run.status = err
        print(err)
        run.done = True
        return
    print('board reset and configured: %d companies, shared starting cash %d units%s'
          % (run.n, run.start_units, '' if not any(run.caps) else ', caps %s' % run.caps))
    run.status = 'running'
    t_next = time.time()
    for i, (_, c, t) in enumerate(merged, start=1):
        if a.max_ticks and i > a.max_ticks:
            break
        tid = with_sym(i, c)
        rep = board.exchange(tid, t.price, t.vol)
        if rep is None:
            run.no_report += 1
            print('tick %d (%s): no report from the board; %s' % (i, run.symbols[c], LOST_SYNC))
            break
        md = run.record(i, tid, c, t, rep)
        logw.writerow(run.rows[-1])
        logf.flush()
        _, _, _, hwd, hwl, swd, swl, hwp = rep
        bad = not (hwd == swd == md and hwp == run.model.pos(c))
        if bad or hwd:
            print('tick %4d %s %-5s | price %8.2f | HW %-4s %d cyc | SW %-4s %d cyc | pos %d | cash %s%s'
                  % (i, t.time, run.symbols[c], run.usd(t.price), NAMES.get(hwd, hwd), hwl, NAMES.get(swd, swd), swl,
                     hwp, money(run.units_usd(run.cash_units)), '   <-- MISMATCH' if bad else ''))
        if a.speed:
            t_next += 1.0 / a.speed
            time.sleep(max(0.0, t_next - time.time()))
    run.status = 'finished' if not run.no_report else 'stopped: a report from the board was missing'
    run.done = True
    print('done: %d ticks | HW/SW mismatches %d | model mismatches %d | echo errors %d | missing reports %d'
          % (run.ticks, run.hw_sw_bad, run.model_bad, run.echo_bad, run.no_report))
    for line in summary(run):
        print(line)
    print('log written to', run.log, ' -> check it with: python verify_run.py', run.log)


def money(v):
    return ('-' if v < 0 else '') + '$' + format(abs(int(round(v))), ',')


def summary(run):
    rows, m = run.rows, run.model
    if not rows:
        return []
    out = ['%-10s %6s %6s %10s %14s %12s' % ('company', 'BUY', 'SELL', 'position', 'invested now', 'buy & hold')]
    for c, sym in enumerate(run.symbols):
        rc = [r for r in rows if r['sym'] == c]
        bh = 100.0 * (rc[-1]['price_sent'] / rc[0]['price_sent'] - 1.0) if rc else 0.0
        out.append('%-10s %6d %6d %10d %14s %+11.3f%%' % (sym, sum(r['hw_dec'] == 1 for r in rc),
                                                          sum(r['hw_dec'] == 2 for r in rc), run.pos[c],
                                                          money(run.units_usd(m.invested[c])), bh))
    last = rows[-1]
    out.append('portfolio: starting cash %s, cash now %s, equity %s, return %+.4f%%'
               % (money(run.start_cash), money(last['cash_usd']), money(last['equity_usd']), last['return_pct']))
    bc = sum(e.blocked_cash for e in m.engines)
    out.append('signals refused: %d BUY (shared cash), %d BUY (company cap), %d BUY (position limit), %d SELL (nothing held)'
               % (bc, m.blocked_cap, sum(e.blocked_limit for e in m.engines), sum(e.blocked_nostock for e in m.engines)))
    if not any(r['hw_dec'] for r in rows):
        out.append('WARNING: no trade was executed in this run.')
    return out


def write_cfg(path, run, source):
    with open(path + '.cfg', 'w') as f:
        f.write('mode=portfolio\nsymbols=%s\nnsym=%d\nstarting_cash_units=%d\nscale=%d\nlot=%d\nsource=%s\n'
                % (','.join(run.symbols), run.n, run.start_units, run.scale, run.lot, source))
        for c, (lim, hi, lo) in enumerate(run.cfgs):
            f.write('pos_limit_%d=%d\nbrk_high_%d=%d\nbrk_low_%d=%d\ncap_units_%d=%d\n' % (c, lim, c, hi, c, lo, c, run.caps[c]))


def plot_loop(run, merged, snapshot=None):
    import matplotlib
    if snapshot:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.ticker import PercentFormatter, FuncFormatter
    usd_axis = FuncFormatter(lambda v, _: ('$%.1fB' % (v / 1e9)) if abs(v) >= 1e9 else ('$%.1fM' % (v / 1e6))
                             if abs(v) >= 1e6 else ('$%.0f' % v))
    slots = sorted({tm for tm, _, _ in merged})
    slot_of = {tm: k for k, tm in enumerate(slots)}
    n = run.n
    ratios = [2.2] * n + [1.6, 1.4, 1.2]
    fig, axes = plt.subplots(n + 3, 1, figsize=(15, 3.0 * n + 8.5), gridspec_kw=dict(height_ratios=ratios))
    fig.canvas.manager.set_window_title(run.title)
    price_axes, ax_eq, ax_ret, ax_lat = axes[:n], axes[n], axes[n + 1], axes[n + 2]

    def x_labels(ax):
        step = max(1, len(slots) // 10)
        ax.set_xticks(list(range(0, len(slots), step)))
        ax.set_xticklabels([s[-5:] for s in slots][::step], fontsize=8)
        ax.set_xlim(-1, max(len(slots), 1))

    def update(_):
        with run.lock:
            rows = list(run.rows)
            stats = (run.ticks, run.hw_sw_bad, run.model_bad, run.echo_bad, run.no_report)
        for ax in axes:
            ax.clear()
        for t in list(fig.texts):
            t.remove()
        for c, ax in enumerate(price_axes):
            rc = [r for r in rows if r['sym'] == c]
            col = COLORS[c % len(COLORS)]
            if rc:
                xs = [slot_of[r['time']] for r in rc]
                ax.plot(xs, [run.usd(r['price_echo']) for r in rc], color=col, linewidth=1.1,
                        label='%s price echoed by the FPGA' % run.names[c])
                for dec, mk, colm, lab in ((1, '^', '#00b050', 'BUY'), (2, 'v', '#c000c0', 'SELL')):
                    pts = [(x, r) for x, r in zip(xs, rc) if r['hw_dec'] == dec]
                    if pts:
                        ax.scatter([x for x, _ in pts], [run.usd(r['price_echo']) for _, r in pts], marker=mk, s=60,
                                   color=colm, zorder=5, edgecolors='black', linewidths=0.4, label='%s (hardware)' % lab)
                lim, hi, lo = run.cfgs[c]
                ymin, ymax = min(run.usd(r['price_echo']) for r in rc), max(run.usd(r['price_echo']) for r in rc)
                for lvl, nm in ((run.usd(hi), 'BRK_HIGH'), (run.usd(lo), 'BRK_LOW')):
                    if ymin - (ymax - ymin) * 0.3 <= lvl <= ymax + (ymax - ymin) * 0.3:
                        ax.axhline(lvl, color='gray', linestyle=':', linewidth=1)
                        ax.text(0, lvl, ' ' + nm, fontsize=8, color='gray', va='bottom')
                ax.legend(loc='best', fontsize=8, framealpha=0.85)
            ax.set_title('%s  (company %d)  -  position %d lots' % (run.names[c], c, run.pos[c]), fontsize=10, loc='left')
            ax.set_ylabel('USD')
            x_labels(ax)
        if rows:
            # one point per minute: the portfolio after every company of that minute
            per_slot = {}
            for r in rows:
                per_slot[slot_of[r['time']]] = r
            xs = sorted(per_slot)
            ax_eq.plot(xs, [per_slot[x]['equity_usd'] for x in xs], color='#1f4e9c', linewidth=1.6,
                       label='total equity: cash + holdings at their last close')
            ax_eq.plot(xs, [per_slot[x]['cash_usd'] for x in xs], color='#898781', linewidth=1.2, linestyle='--',
                       label='shared cash')
            ax_eq.axhline(run.start_cash, color='#c3c2b7', linewidth=0.8)
            ax_eq.legend(loc='best', fontsize=8, framealpha=0.85)
            ax_eq.yaxis.set_major_formatter(usd_axis)
            rets = [per_slot[x]['return_pct'] for x in xs]
            ax_ret.axhline(0, color='gray', linewidth=0.8)
            ax_ret.fill_between(xs, rets, 0, where=[v >= 0 for v in rets], interpolate=True, color='#1a9850', alpha=0.25)
            ax_ret.fill_between(xs, rets, 0, where=[v < 0 for v in rets], interpolate=True, color='#d73027', alpha=0.25)
            ax_ret.plot(xs, rets, color='#1f4e9c', linewidth=1.6,
                        label='portfolio return on the starting cash: now %+.3f%%' % rets[-1])
            span = (max(rets) - min(rets)) or abs(rets[-1]) or 1.0
            ax_ret.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=1 if span >= 2 else 2 if span >= 0.2 else 3))
            ax_ret.legend(loc='best', fontsize=8)
            for c in range(n):
                rc = [r for r in rows if r['sym'] == c]
                ax_lat.plot([slot_of[r['time']] for r in rc], [r['sw_lat'] for r in rc], color=COLORS[c % len(COLORS)],
                            linewidth=0.9, label='RISC-V software, %s (cycles)' % run.symbols[c])
            ax_lat.plot([slot_of[r['time']] for r in rows], [r['hw_lat'] for r in rows], color='black', linewidth=2,
                        label='hardware engine, every company (cycles)')
            ax_lat.legend(loc='center right', fontsize=8)
            last = rows[-1]
            nt, hs, mb, eb, nr = stats
            lines = ['ticks: %d (%d companies)' % (nt, n), 'HW = SW: %d / %d' % (nt - hs, nt),
                     'HW = model: %d / %d' % (nt - mb, nt), 'echo errors: %d' % eb, 'missing reports: %d' % nr, '']
            for c, sym in enumerate(run.symbols):
                rc = [r for r in rows if r['sym'] == c]
                lines.append('%-5s %d BUY %d SELL pos %d' % (sym, sum(r['hw_dec'] == 1 for r in rc),
                                                             sum(r['hw_dec'] == 2 for r in rc), run.pos[c]))
            lines += ['', 'starting cash: %s' % money(run.start_cash), 'shared cash:   %s' % money(last['cash_usd']),
                      'equity:        %s' % money(last['equity_usd']), 'return: %+.3f%%' % last['return_pct'],
                      'refused (cash): %d' % sum(e.blocked_cash for e in run.model.engines),
                      'refused (cap):  %d' % run.model.blocked_cap, '', run.status]
            ok = hs == 0 and mb == 0 and eb == 0 and nr == 0
            fig.text(0.765, 0.935, '\n'.join(lines), fontsize=9.5, family='monospace', va='top',
                     bbox=dict(facecolor='#e8f7e8' if ok else '#fde2e2', edgecolor='black', boxstyle='round,pad=0.8'))
        ax_eq.set_title('Portfolio: shared cash and total equity', fontsize=10, loc='left')
        ax_ret.set_title('Portfolio return: (equity - starting cash) / starting cash', fontsize=10, loc='left')
        ax_lat.set_title('Decision latency: RISC-V software vs hardware engines', fontsize=10, loc='left')
        ax_lat.set_xlabel('New York time (1-minute bars; inside a minute the companies go in the order given)')
        for ax in (ax_eq, ax_ret, ax_lat):
            x_labels(ax)
        fig.suptitle(run.title, x=0.02, ha='left', fontsize=12)
        plt.subplots_adjust(left=0.07, right=0.75, hspace=0.55, top=0.93, bottom=0.04)

    if snapshot:
        update(0)
        fig.savefig(snapshot, dpi=100)
        plt.close(fig)
        print('dashboard picture:', snapshot)
        return
    _ani = FuncAnimation(fig, update, interval=800, cache_frame_data=False)
    plt.show()


def run_portfolio(a, symbols, real_session, cash_units_fn, default_cash, make_board):
    """Entry point from hft_dashboard.main().  real_session / cash_units_fn / make_board come from the
    dashboard so the configuration rules (breakout = previous session, lot, cash) stay identical."""
    import market_feed
    from datetime import datetime
    names = [market_feed.company_name(s) for s in symbols]
    # ---- bars per company
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
    caps = [int(start_units * a.cap_pct / 100) if a.cap_pct else 0] * len(symbols)
    merged = merge(sess)
    title = '%s together, %s (New York time), one shared cash account, %s' % (' + '.join(names), day, src)
    if a.port.lower() == 'none':
        title += '  [SIMULATION: Python model, no board]'
    run = PortfolioRun(a, symbols, names, cfgs, start_units, caps, 100, a.lot, title)
    log_path = a.log or 'run_%s_%s_%s.csv' % ('-'.join(symbols), day, datetime.now().strftime('%H%M%S'))
    run.log = log_path
    logf = open(log_path, 'w', newline='')
    logw = csv.DictWriter(logf, fieldnames=LOG_FIELDS)
    logw.writeheader()
    write_cfg(log_path, run, a.source)
    board = SimPortfolioBoard() if a.port.lower() == 'none' else make_board(a)
    th = threading.Thread(target=worker, args=(run, board, merged, logw, logf), daemon=True)
    th.start()
    if a.no_plot:
        th.join()
        if a.save_png and run.rows:
            plot_loop(run, merged, snapshot=a.save_png)
    else:
        plot_loop(run, merged)
    logf.close()
    return run
