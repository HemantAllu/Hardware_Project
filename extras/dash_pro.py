"""dash_pro.py - the live "trading terminal" window of hft_dashboard.py (one company) and of the
several-company portfolio mode (hft_hybrid.py).  Dark theme, redrawn about once a second while the
board answers.

What is on screen
  * KPI tiles: equity / return, cash, positions, trades, ticks and allocations verified
    (hardware = RISC-V software = Python model), decision latency, throughput, run status
  * candlestick charts (1-minute bars) with the engine's own indicators: the 4-bar moving average
    and the running VWAP it compares against, the breakout levels, and every BUY / SELL / ROT the
    hardware executed
  * latency histogram (RISC-V software cycles vs the 5-cycle hardware decision) with percentiles
  * FPGA resource utilisation (LUT / FF / BRAM / DSP gauges and the timing slack) read from
    Vivado's own reports - nothing is estimated: without a report the panel says so
  * trade execution timeline (one lane per company) and a blotter of the latest fills
  * throughput and processing statistics (ticks per second, PC <-> FPGA round trip, UART load,
    hardware capacity, software speed-up, allocation cycles)

Vivado reports: by default the newest
    <project>/rv32im.runs/impl_1/*utilization_placed.rpt   and   *timing_summary_routed.rpt
are used; point at others with  --util-report FILE  and  --timing-report FILE.
"""
import glob
import os
import re
import time

# ----------------------------------------------------------------------------- theme
BG, PANEL, GRID, EDGE = '#0d1117', '#151b23', '#262d36', '#30363d'
TEXT, MUTED, DIM = '#e6edf3', '#8b949e', '#5c6670'
UP, DOWN, ACCENT, AMBER, VIOLET, CYAN = '#26a69a', '#ef5350', '#58a6ff', '#f0b429', '#bc8cff', '#39d0d8'
MA_COL, VWAP_COL = '#f0b429', '#bc8cff'
COMPANY_COLORS = ['#58a6ff', '#f0883e', '#3fb950', '#db61a2', '#a371f7', '#ff7b72', '#39d0d8', '#d29922']
NONE_, BUY_, SELL_, ROT_ = 0, 1, 2, 3
SIDE = {BUY_: ('BUY', UP, '^'), SELL_: ('SELL', DOWN, 'v'), ROT_: ('ROT', AMBER, 'X')}

XC7A100T = {'LUT': 63400, 'FF': 126800, 'BRAM': 135, 'DSP': 240}
UART_BYTES_PER_S = 115200 / 10.0          # 8N1: 10 bits per byte
CLOCK_HZ = 100e6


def _rc():
    import matplotlib as mpl
    mpl.rcParams.update({
        'figure.facecolor': BG, 'axes.facecolor': PANEL, 'savefig.facecolor': BG,
        'axes.edgecolor': EDGE, 'axes.labelcolor': MUTED, 'axes.titlecolor': TEXT,
        'xtick.color': MUTED, 'ytick.color': MUTED, 'text.color': TEXT,
        'grid.color': GRID, 'grid.linewidth': 0.6, 'axes.grid': True, 'axes.axisbelow': True,
        'font.size': 8, 'axes.titlesize': 9, 'axes.titleweight': 'bold', 'axes.titlelocation': 'left',
        'axes.titlepad': 5, 'xtick.labelsize': 7, 'ytick.labelsize': 7, 'legend.fontsize': 7,
        'legend.facecolor': PANEL, 'legend.edgecolor': EDGE, 'legend.framealpha': 0.85,
        'font.family': ['DejaVu Sans'], 'axes.spines.top': False, 'axes.spines.right': False,
    })


# ----------------------------------------------------------------------------- formatting
def money(v, sign=False):
    s = '-' if v < 0 else ('+' if sign else '')
    a = abs(v)
    if a >= 1e9:
        return '%s$%.3fB' % (s, a / 1e9)
    if a >= 1e6:
        return '%s$%.2fM' % (s, a / 1e6)
    if a >= 1e4:
        return '%s$%.1fk' % (s, a / 1e3)
    return '%s$%.2f' % (s, a)


def pct(v, d=2):
    return '%+.*f%%' % (d, v)


def percentile(xs, p):
    if not xs:
        return 0
    s = sorted(xs)
    k = min(len(s) - 1, max(0, int(round(p / 100.0 * (len(s) - 1)))))
    return s[k]


# ----------------------------------------------------------------------------- Vivado reports
def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _newest(pattern):
    files = glob.glob(pattern, recursive=True)
    return max(files, key=os.path.getmtime) if files else None


def find_reports(util=None, timing=None):
    root = _project_root()
    util = util or _newest(os.path.join(root, '**', '*utilization_placed.rpt')) or \
        _newest(os.path.join(root, '**', '*utilization_synth.rpt'))
    timing = timing or _newest(os.path.join(root, '**', '*timing_summary_routed.rpt'))
    return util, timing


def parse_utilization(path):
    """{'LUT': (used, available, pct), ...} from a Vivado report_utilization file."""
    rows = {'LUT': ('Slice LUTs', 'CLB LUTs'), 'FF': ('Slice Registers', 'CLB Registers'),
            'BRAM': ('Block RAM Tile',), 'DSP': ('DSPs',)}
    out = {}
    try:
        with open(path, errors='replace') as f:
            lines = f.readlines()
    except OSError:
        return out
    for line in lines:
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if not cells:
            continue
        name = cells[0].rstrip('*').strip()
        for key, names in rows.items():
            if key in out or name not in names:
                continue
            nums = []
            for c in cells[1:]:
                try:
                    nums.append(float(c.replace('<', '').strip()))
                except ValueError:
                    pass
            if len(nums) >= 3:
                used, avail, util = nums[0], nums[-2], nums[-1]
                out[key] = (used, avail, util)
    return out


def parse_timing(path):
    """(WNS, WHS) in ns from report_timing_summary, or None."""
    try:
        with open(path, errors='replace') as f:
            lines = f.readlines()
    except OSError:
        return None
    for i, line in enumerate(lines):
        if 'WNS(ns)' in line and 'WHS(ns)' in line:
            hdr = re.split(r'\s{2,}', line.strip())          # 'TNS Failing Endpoints' is ONE column
            for v in lines[i + 1:i + 4]:
                parts = v.split()
                if len(parts) == len(hdr) and re.match(r'^-?\d', parts[0]):
                    try:
                        return float(parts[hdr.index('WNS(ns)')]), float(parts[hdr.index('WHS(ns)')])
                    except (ValueError, IndexError):
                        return None
    return None


class Resources:
    def __init__(self, util=None, timing=None):
        self.util_path, self.timing_path = find_reports(util, timing)
        self.util = parse_utilization(self.util_path) if self.util_path else {}
        self.timing = parse_timing(self.timing_path) if self.timing_path else None


# ----------------------------------------------------------------------------- drawing helpers
def style_ax(ax, title=None, sub=None):
    ax.set_facecolor(PANEL)
    for sp in ax.spines.values():
        sp.set_color(EDGE)
    if title:
        ax.set_title(title, color=TEXT, fontsize=9, fontweight='bold', loc='left')
    if sub:
        ax.text(1.0, 1.015, sub, transform=ax.transAxes, ha='right', va='bottom', fontsize=7, color=MUTED)


def panel_box(fig, rect, title=None):
    """an axes used as a text panel (no ticks)"""
    ax = fig.add_axes(rect)
    ax.set_facecolor(PANEL)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(True)
        sp.set_color(EDGE)
    if title:
        ax.set_title(title, color=TEXT, fontsize=9, fontweight='bold', loc='left')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    return ax


def candles(ax, xs, o, h, l, c, width=0.62):
    if not xs:
        return
    cols = [UP if cc >= oo else DOWN for oo, cc in zip(o, c)]
    ax.vlines(xs, l, h, colors=cols, linewidth=0.8, zorder=2)
    span = (max(h) - min(l)) or max(abs(h[0]), 1.0)
    body = [max(abs(cc - oo), span * 0.004) for oo, cc in zip(o, c)]
    ax.bar(xs, body, bottom=[min(oo, cc) for oo, cc in zip(o, c)], width=width, color=cols, edgecolor=cols,
           linewidth=0.4, zorder=3)


def indicators(prices, vols):
    """the engine's own references: 4-bar moving average of the price (the engine compares 4 x price
    with the sum of the last 4) and the running VWAP since the start of the run."""
    ma, vw, spv, sv = [], [], 0.0, 0.0
    for i, (p, v) in enumerate(zip(prices, vols)):
        ma.append(sum(prices[i - 3:i + 1]) / 4.0 if i >= 3 else None)
        spv += p * v
        sv += v
        vw.append(spv / sv if sv else None)
    return ma, vw


def plot_line(ax, xs, ys, **kw):
    pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
    if pts:
        ax.plot([p[0] for p in pts], [p[1] for p in pts], **kw)


def time_axis(ax, labels, lo, hi, n=7):
    hi = max(hi, lo + 1)
    step = max(1, (hi - lo) // n)
    xs = list(range(lo, hi + 1, step))
    ax.set_xticks(xs)
    ax.set_xticklabels([labels[x][-5:] if 0 <= x < len(labels) else '' for x in xs])
    ax.set_xlim(lo - 0.7, hi + 0.7)


def tiles(fig, items, y=0.885, h=0.075, left=0.008, right=0.992, gap=0.006):
    """KPI tiles across the top: items = [(label, value, sub, color)]"""
    from matplotlib.patches import FancyBboxPatch
    ax = fig.add_axes([0, y, 1, h])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    n = len(items)
    w = (right - left - gap * (n - 1)) / n
    for i, (label, value, sub, col) in enumerate(items):
        x = left + i * (w + gap)
        ax.add_patch(FancyBboxPatch((x, 0.04), w, 0.92, boxstyle='round,pad=0,rounding_size=0.012',
                                    transform=ax.transAxes, facecolor=PANEL, edgecolor=EDGE, linewidth=1))
        ax.add_patch(FancyBboxPatch((x, 0.04), 0.0025, 0.92, boxstyle='square,pad=0', transform=ax.transAxes,
                                    facecolor=col, edgecolor='none'))
        ax.text(x + 0.008, 0.80, label.upper(), fontsize=6.8, color=MUTED, va='center', fontweight='bold')
        ax.text(x + 0.008, 0.47, value, fontsize=12.5, color=col if col != MUTED else TEXT, va='center',
                fontweight='bold')
        if sub:
            ax.text(x + 0.008, 0.16, sub, fontsize=6.6, color=MUTED, va='center')
    return ax


def header(fig, title, status, ok, clock=''):
    ax = fig.add_axes([0, 0.965, 1, 0.035])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0.008, 0.45, 'FPGA HFT TERMINAL', fontsize=11, fontweight='bold', color=ACCENT, va='center')
    ax.text(0.118, 0.45, title, fontsize=9, color=TEXT, va='center')
    live = status == 'running'
    col = UP if live and ok else (DOWN if not ok or status.startswith(('stopped', 'board')) else MUTED)
    txt = ('LIVE' if live else 'FINISHED' if status == 'finished' else status.upper()[:40])
    ax.text(0.992, 0.45, '● ' + txt, fontsize=9.5, fontweight='bold', color=col, va='center', ha='right')
    if clock:
        ax.text(0.90, 0.45, clock, fontsize=9, color=MUTED, va='center', ha='right')


def latency_hist(ax, sw, hw, title='DECISION LATENCY', what='per tick'):
    import numpy as np
    style_ax(ax, title, 'cycles @ 100 MHz')
    if not sw:
        return
    hwv = hw[-1] if hw else 5
    lo = max(1, min(min(sw), min(hw or [5])) * 0.6)
    hi = max(sw) * 1.6
    bins = np.logspace(np.log10(lo), np.log10(hi), 36)
    ax.hist(sw, bins=bins, color=AMBER, alpha=0.85, edgecolor=PANEL, linewidth=0.4,
            label='RISC-V software (C on the soft CPU)')
    ax.hist(hw, bins=bins, color=CYAN, alpha=0.95, edgecolor=PANEL, linewidth=0.4,
            label='FPGA accelerator')
    ax.set_xscale('log')
    ax.set_yscale('log')
    p50, p99 = percentile(sw, 50), percentile(sw, 99)
    for v in (p50, p99):
        ax.axvline(v, color=AMBER, linestyle='--', linewidth=0.8, alpha=0.8)
    ax.axvline(hwv, color=CYAN, linestyle='-', linewidth=1.2)
    ax.text(hwv, 0.55, ' HW\n %d cyc\n %d ns' % (hwv, hwv * 10), transform=ax.get_xaxis_transform(), color=CYAN,
            fontsize=6.8, va='top', fontweight='bold')
    counts = np.histogram(sw, bins=bins)[0].max()
    ax.set_ylim(0.8, max(counts, 2) * 40)
    ax.text(0.5, 0.90, 'FPGA %.0fx faster' % (sum(sw) / len(sw) / max(1, hwv)), transform=ax.transAxes,
            ha='center', color=TEXT, fontsize=10, fontweight='bold')
    ax.text(0.5, 0.79, 'software p50 %d  ·  p99 %d cycles' % (p50, p99), transform=ax.transAxes, ha='center',
            color=AMBER, fontsize=7)
    ax.text(0.5, 0.70, 'cyan FPGA  ·  amber RISC-V C code  ·  %d %s' % (len(sw), what), transform=ax.transAxes,
            ha='center', color=MUTED, fontsize=6.3)


def fpga_panel(fig, rect, res, engines=None):
    ax = panel_box(fig, rect, 'FPGA RESOURCES')
    ax.text(0.97, 0.96, 'XC7A100T', transform=ax.transAxes, ha='right', va='top', fontsize=6.5, color=MUTED)
    rows = [('LUT', 'Slice LUTs'), ('FF', 'Registers'), ('BRAM', 'Block RAM'), ('DSP', 'DSP48 slices')]
    top, step = 0.86, 0.165
    have = bool(res.util)
    for i, (key, name) in enumerate(rows):
        y = top - i * step
        ax.text(0.03, y, key, fontsize=8.5, fontweight='bold', color=TEXT, va='center')
        ax.text(0.03, y - 0.065, name, fontsize=6.3, color=MUTED, va='center')
        ax.add_patch(_rect(0.24, y - 0.035, 0.42, 0.07, GRID))
        if have and key in res.util:
            used, avail, u = res.util[key]
            col = UP if u < 50 else AMBER if u < 80 else DOWN
            ax.add_patch(_rect(0.24, y - 0.035, 0.42 * min(u, 100) / 100.0, 0.07, col))
            ax.text(0.69, y + 0.005, '%.1f%%' % u, fontsize=9, fontweight='bold', color=col, va='center')
            ax.text(0.69, y - 0.065, '%s / %s' % (format(int(used), ','), format(int(avail), ',')), fontsize=6.3,
                    color=MUTED, va='center')
        else:
            ax.text(0.69, y + 0.005, '--', fontsize=9, color=DIM, va='center')
            ax.text(0.69, y - 0.065, 'of %s' % format(XC7A100T[key], ','), fontsize=6.3, color=MUTED, va='center')
    y = top - 4 * step + 0.02
    if res.timing:
        wns, whs = res.timing
        col = UP if wns >= 0 else DOWN
        ax.text(0.03, y, '100 MHz timing %s:  WNS %+.3f ns  ·  WHS %+.3f ns'
                % ('met' if wns >= 0 and whs >= 0 else 'FAILED', wns, whs),
                fontsize=7, color=col, va='center', fontweight='bold')
    if have:
        src = os.path.basename(res.util_path)
        ax.text(0.03, 0.035, 'source: Vivado %s%s' % (src, ('   |   %d engines' % engines) if engines else ''),
                fontsize=6, color=DIM, va='bottom')
    else:
        ax.text(0.03, 0.035, 'no Vivado report yet: run implementation\nor pass --util-report <file>.rpt',
                fontsize=6.3, color=AMBER, va='bottom')


def _rect(x, y, w, h, col):
    from matplotlib.patches import FancyBboxPatch
    return FancyBboxPatch((x, y), max(w, 0.0001), h, boxstyle='round,pad=0,rounding_size=0.01', facecolor=col,
                          edgecolor='none')


def stats_panel(fig, rect, rows, title='THROUGHPUT & PROCESSING'):
    ax = panel_box(fig, rect, title)
    n = len(rows)
    step = 0.9 / max(n, 1)
    for i, (k, v, col) in enumerate(rows):
        y = 0.93 - (i + 0.5) * step
        if k is None:
            ax.axhline(y, xmin=0.03, xmax=0.97, color=EDGE, linewidth=0.8)
            continue
        ax.text(0.03, y, k, fontsize=7.4, color=MUTED, va='center')
        ax.text(0.97, y, v, fontsize=7.8, color=col or TEXT, va='center', ha='right', fontweight='bold')
    return ax


def blotter(fig, rect, fills, title='TRADE BLOTTER', max_rows=12):
    ax = panel_box(fig, rect, title)
    cols = (0.03, 0.18, 0.33, 0.46, 0.62, 0.80)
    hdr = ('TIME', 'SYM', 'SIDE', 'QTY', 'PRICE', 'NOTIONAL')
    for x, t in zip(cols, hdr):
        ax.text(x, 0.93, t, fontsize=6.5, color=MUTED, fontweight='bold', va='center')
    ax.axhline(0.885, xmin=0.02, xmax=0.98, color=EDGE, linewidth=0.8)
    if not fills:
        ax.text(0.5, 0.5, 'no executions yet', ha='center', color=DIM, fontsize=8)
        return
    step = 0.85 / max_rows
    for i, f in enumerate(reversed(fills[-max_rows:])):
        y = 0.85 - (i + 0.5) * step
        name, col, _ = SIDE[f['side']]
        if i % 2 == 0:
            ax.add_patch(_rect(0.015, y - step / 2, 0.97, step, '#1a212b'))
        vals = (f['time'], f['sym'], name, '%d' % f['qty'], '%.2f' % f['price'], money(f['notional']))
        for k, (x, v) in enumerate(zip(cols, vals)):
            ax.text(x, y, v, fontsize=7, va='center', color=col if k == 2 else TEXT,
                    fontweight='bold' if k == 2 else 'normal', family='DejaVu Sans Mono')


def timeline(ax, fills, lanes, labels, lo, hi, lane_colors):
    style_ax(ax, 'TRADE EXECUTION TIMELINE', '▲ BUY   ▼ SELL   ✖ rotation   (size = quantity)')
    n = len(lanes)
    for i in range(n):
        ax.axhspan(i - 0.42, i + 0.42, color=lane_colors[i % len(lane_colors)], alpha=0.06, linewidth=0)
    qs = [f['qty'] for f in fills] or [1]
    qmax = max(qs) or 1
    for side in (BUY_, SELL_, ROT_):
        pts = [f for f in fills if f['side'] == side and lo <= f['x'] <= hi]
        if pts:
            name, col, mk = SIDE[side]
            ax.scatter([f['x'] for f in pts], [f['lane'] for f in pts], marker=mk, color=col,
                       s=[28 + 110 * f['qty'] / qmax for f in pts], edgecolors='black', linewidths=0.4, zorder=4,
                       label=name)
    ax.set_yticks(range(n))
    ax.set_yticklabels(lanes)
    for t, i in zip(ax.get_yticklabels(), range(n)):
        t.set_color(lane_colors[i % len(lane_colors)])
        t.set_fontweight('bold')
    ax.set_ylim(n - 0.5, -0.5)
    ax.grid(axis='y', visible=False)
    time_axis(ax, labels, lo, hi, 6)


# ============================================================================= one company
def run_single(run, snapshot=None, util=None, timing=None):
    import matplotlib
    if snapshot:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.ticker import FuncFormatter, PercentFormatter
    _rc()
    res = Resources(util, timing)
    fig = plt.figure(figsize=(17, 9.6), dpi=100)
    try:
        fig.canvas.manager.set_window_title('FPGA HFT terminal - ' + run.title)
    except AttributeError:
        pass
    usd_fmt = FuncFormatter(lambda v, _: '%.2f' % v)

    def update(_=None):
        with run.lock:
            rows = list(run.rows)
            n, hs, mb, eb = run.n, run.hw_sw_bad, run.model_bad, run.echo_bad
            rtt = list(getattr(run, 'rtt', []))
            t0, t1 = getattr(run, 't_start', None), getattr(run, 't_end', None)
            status = run.status
        fig.clf()
        ok = hs == 0 and mb == 0 and eb == 0 and not run.no_report
        header(fig, run.title, status, ok, rows[-1]['time'][-5:] + ' NY' if rows and rows[-1]['time'] else '')
        if not rows:
            fig.text(0.5, 0.5, 'waiting for the board ... (%s)' % status, ha='center', color=MUTED, fontsize=13)
            return
        last = rows[-1]
        buys = [r for r in rows if r['hw_dec'] == 1]
        sells = [r for r in rows if r['hw_dec'] == 2]
        sw = [r['sw_lat'] for r in rows if r['sw_lat']]
        hw = [r['hw_lat'] for r in rows if r['hw_lat']]
        elapsed = ((t1 or time.perf_counter()) - t0) if t0 else 0.0
        tps = n / elapsed if elapsed > 0 else 0.0
        profit = last['equity_usd'] - run.start_cash
        tiles(fig, [
            ('Equity (mark-to-market)', money(last['equity_usd']), 'start ' + money(run.start_cash), TEXT),
            ('Return', pct(last['return_pct'], 3), 'P&L ' + money(profit, True), UP if profit >= 0 else DOWN),
            ('Cash', money(last['cash_usd']), 'shared account', TEXT),
            ('Position', '%d %s' % (last['hw_pos'], 'lots' if run.lot > 1 else ''),
             'limit %d' % run.cfg[0], ACCENT),
            ('Trades executed', '%d B  /  %d S' % (len(buys), len(sells)),
             'refused (cash) %d' % run.model.blocked_cash, TEXT),
            ('HW = SW = Model', '%d / %d' % (n - max(hs, mb), n),
             ('✔ all decisions verified' if ok else '✖ %d mismatches' % max(hs, mb, eb)), UP if ok else DOWN),
            ('HW decision latency', '%d cyc = %d ns' % (hw[-1] if hw else 5, 10 * (hw[-1] if hw else 5)),
             'SW avg %.0f cyc' % (sum(sw) / len(sw) if sw else 0), CYAN),
            ('Throughput', '%.1f ticks/s' % tps, 'round trip p50 %.1f ms' % percentile(rtt, 50) if rtt else '', AMBER),
        ])
        # ---------------- left: price, volume, position, return
        L, R = 0.045, 0.655
        xs = list(range(len(rows)))
        labels = [r['time'][-5:] if r['time'] else str(r['tick']) for r in rows]
        o, h, l, c = ([r[k] for r in rows] for k in ('open', 'high', 'low', 'close'))
        ax_p = fig.add_axes([L, 0.43, R - L, 0.425])
        style_ax(ax_p, 'PRICE  ·  ' + ('1-minute candles' if run.scale > 1 else 'ticks'), 'MA(4) and VWAP = the references the engine compares against')
        candles(ax_p, xs, o, h, l, c, width=0.66 if len(xs) < 200 else 0.8)
        prices = [r['price_sent'] / run.scale for r in rows]
        ma, vw = indicators(prices, [r['vol_sent'] for r in rows])
        plot_line(ax_p, xs, ma, color=MA_COL, linewidth=1.0, label='MA(4)')
        plot_line(ax_p, xs, vw, color=VWAP_COL, linewidth=1.2, linestyle='--', label='VWAP')
        ymin, ymax = min(l), max(h)
        span = (ymax - ymin) or 1.0
        for lvl, name in ((run.usd(run.cfg[1]), 'BRK HIGH'), (run.usd(run.cfg[2]), 'BRK LOW')):
            if ymin - 0.25 * span <= lvl <= ymax + 0.25 * span:
                ax_p.axhline(lvl, color=MUTED, linestyle=':', linewidth=0.9)
                ax_p.text(xs[-1] + 0.5, lvl, ' ' + name, color=MUTED, fontsize=6.5, va='center')
        bx = [(x, r) for x, r in zip(xs, rows) if r['hw_dec'] == 1]
        sx = [(x, r) for x, r in zip(xs, rows) if r['hw_dec'] == 2]
        if bx:
            ax_p.scatter([x for x, _ in bx], [r['low'] - 0.06 * span for _, r in bx], marker='^', s=58,
                         color=UP, edgecolors='white', linewidths=0.5, zorder=6, label='BUY (FPGA)')
        if sx:
            ax_p.scatter([x for x, _ in sx], [r['high'] + 0.06 * span for _, r in sx], marker='v',
                         s=58, color=DOWN, edgecolors='white', linewidths=0.5, zorder=6, label='SELL (FPGA)')
        ax_p.axhline(c[-1], color=UP if c[-1] >= o[-1] else DOWN, linewidth=0.6, alpha=0.7)
        ax_p.text(1.002, c[-1], ' %.2f ' % c[-1], transform=ax_p.get_yaxis_transform(), fontsize=7.5,
                  color='black', va='center', fontweight='bold',
                  bbox=dict(boxstyle='square,pad=0.2', facecolor=UP if c[-1] >= o[-1] else DOWN, edgecolor='none'))
        ax_p.yaxis.set_major_formatter(usd_fmt)
        ax_p.legend(loc='upper left', ncol=4)
        ax_p.set_ylim(ymin - 0.15 * span, ymax + 0.15 * span)
        time_axis(ax_p, labels, 0, len(xs) - 1, 10)
        ax_p.tick_params(labelbottom=False)

        ax_v = fig.add_axes([L, 0.335, R - L, 0.085], sharex=ax_p)
        style_ax(ax_v)
        ax_v.bar(xs, [r['volume'] for r in rows], color=[UP if cc >= oo else DOWN for oo, cc in zip(o, c)],
                 alpha=0.55, width=0.8)
        ax_v.set_ylabel('volume', color=MUTED)
        ax_v.yaxis.set_major_formatter(FuncFormatter(lambda v, _: '%.0fk' % (v / 1e3) if v >= 1e3 else '%d' % v))
        ax_v.tick_params(labelbottom=False)

        ax_q = fig.add_axes([L, 0.225, R - L, 0.085], sharex=ax_p)
        style_ax(ax_q, 'POSITION (lots)' if run.lot > 1 else 'POSITION')
        ax_q.step(xs, [r['hw_pos'] for r in rows], where='post', color=ACCENT, linewidth=1.3)
        ax_q.fill_between(xs, [r['hw_pos'] for r in rows], step='post', color=ACCENT, alpha=0.15)
        ax_q.tick_params(labelbottom=False)

        ax_r = fig.add_axes([L, 0.045, R - L, 0.15], sharex=ax_p)
        style_ax(ax_r, 'RETURN ON STARTING CASH (mark-to-market)')
        rets = [r['return_pct'] for r in rows]
        ax_r.plot(xs, rets, color=TEXT, linewidth=1.1)
        ax_r.fill_between(xs, rets, 0, where=[v >= 0 for v in rets], interpolate=True, color=UP, alpha=0.3)
        ax_r.fill_between(xs, rets, 0, where=[v < 0 for v in rets], interpolate=True, color=DOWN, alpha=0.3)
        ax_r.axhline(0, color=MUTED, linewidth=0.7)
        peak, dd = -1e18, 0.0
        for v in rets:
            peak = max(peak, v)
            dd = min(dd, v - peak)
        ax_r.text(1.0, 1.015, 'now %s   best %s   max drawdown %.3f pt' % (pct(rets[-1], 3), pct(max(rets), 3), dd),
                  transform=ax_r.transAxes, ha='right', va='bottom', fontsize=7, color=MUTED)
        ax_r.yaxis.set_major_formatter(PercentFormatter(decimals=2))
        time_axis(ax_r, labels, 0, len(xs) - 1, 10)

        # ---------------- right column
        X, W = 0.685, 0.307
        ax_h = fig.add_axes([X, 0.655, W, 0.2])
        latency_hist(ax_h, sw, hw, what='ticks')
        fpga_panel(fig, [X, 0.43, W, 0.19], res)
        rows_s = [
            ('ticks processed', '%d in %.1f s' % (n, elapsed), None),
            ('ticks per second (PC <-> FPGA link)', '%.1f /s' % tps, AMBER),
            ('round trip PC -> FPGA -> PC  p50 / p99',
             '%.1f / %.1f ms' % (percentile(rtt, 50), percentile(rtt, 99)) if rtt else '--', None),
            ('UART load (12 B out + 40 B back per tick)',
             'no board (simulation)' if _sim(run) else '%.0f%%' % (100.0 * tps * 40 / UART_BYTES_PER_S), None),
            (None, None, None),
            ('FPGA decision', '%d cycles = %d ns' % (hw[-1] if hw else 5, 10 * (hw[-1] if hw else 5)), CYAN),
            ('engine capacity (1 tick / 5 cycles)', '%.0f M ticks/s' % (CLOCK_HZ / max(1, hw[-1] if hw else 5) / 1e6), CYAN),
            ('RISC-V software  avg / p99', '%.0f / %d cycles' % (sum(sw) / len(sw), percentile(sw, 99)) if sw else '--',
             AMBER),
            ('price echo errors / missing reports', '%d / %d' % (eb, run.no_report), UP if not eb and not run.no_report else DOWN),
        ]
        stats_panel(fig, [X, 0.235, W, 0.165], rows_s)
        fills = [dict(time=r['time'][-5:] if r['time'] else str(r['tick']), sym=getattr(run, 'symbol', '') or 'TICK',
                      side=r['hw_dec'], qty=r['vol_sent'], price=r['price_sent'] / run.scale,
                      notional=run.units_usd(r['price_sent'] * r['vol_sent'])) for r in rows if r['hw_dec'] in (1, 2)]
        blotter(fig, [X, 0.045, W, 0.16], fills, 'TRADE EXECUTIONS (latest first)', max_rows=7)

    if snapshot:
        update()
        fig.savefig(snapshot, dpi=110)
        plt.close(fig)
        print('dashboard picture:', snapshot)
        return
    _maximize(plt)
    _ani = FuncAnimation(fig, update, interval=800, cache_frame_data=False)
    plt.show()


def _sim(run):
    return str(getattr(run.args, 'port', '')).lower() == 'none'


def _maximize(plt):
    try:
        mng = plt.get_current_fig_manager()
        if hasattr(mng, 'window') and hasattr(mng.window, 'state'):
            mng.window.state('zoomed')
        elif hasattr(mng, 'window') and hasattr(mng.window, 'showMaximized'):
            mng.window.showMaximized()
    except Exception:
        pass


# ============================================================================= several companies
def run_portfolio(run, snapshot=None, focus=None, util=None, timing=None, window=60):
    import matplotlib
    if snapshot:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.ticker import FuncFormatter, PercentFormatter
    from hft_model import W_TOTAL, SCORE_FRAC
    _rc()
    res = Resources(util, timing)
    n = run.n
    state = dict(focus=focus, axes={})
    fig = plt.figure(figsize=(17, 9.6), dpi=100)
    try:
        fig.canvas.manager.set_window_title('FPGA HFT terminal - ' + run.title)
    except AttributeError:
        pass
    ccol = [COMPANY_COLORS[c % len(COMPANY_COLORS)] for c in range(n)]
    big_usd = FuncFormatter(lambda v, _: money(v))

    def snap():
        with run.lock:
            return dict(minutes=list(run.minutes), ticks_of=[list(t) for t in run.ticks_of],
                        fills=list(getattr(run, 'fills', [])), rtt=list(getattr(run, 'rtt', [])),
                        t0=getattr(run, 't_start', None), t1=getattr(run, 't_end', None), status=run.status,
                        ticks=run.ticks, bad_ticks=run.bad_ticks, bad_allocs=run.bad_allocs,
                        no_report=run.no_report, realized=list(run.realized), trades=[dict(t) for t in run.trades])

    def kpis(s):
        mins, last = s['minutes'], s['minutes'][-1]
        nt, na = s['ticks'], len(mins)
        ok = s['bad_ticks'] == 0 and s['bad_allocs'] == 0 and s['no_report'] == 0
        eq = run.units_usd(last['equity'])
        profit = eq - run.start_cash
        nb = sum(t['buy'] for t in s['trades'])
        ns = sum(t['sell'] for t in s['trades'])
        nr = sum(t['rot'] for t in s['trades'])
        held = sum(1 for p in last['pos'] if p)
        invested = sum(last['pos'][c] * (s['ticks_of'][c][-1]['price'] if s['ticks_of'][c] else 0) for c in range(n))
        elapsed = ((s['t1'] or time.perf_counter()) - s['t0']) if s['t0'] else 0.0
        tps = nt / elapsed if elapsed > 0 else 0.0
        hl = [m['hw_lat'] for m in mins]
        tiles(fig, [
            ('Portfolio equity', money(eq), 'start ' + money(run.start_cash), TEXT),
            ('Return', pct(last['ret'], 3), 'P&L ' + money(profit, True), UP if profit >= 0 else DOWN),
            ('Shared cash', money(run.units_usd(last['cash'])),
             'invested %s' % money(run.units_usd(invested)), TEXT),
            ('Open positions', '%d / %d' % (held, n), 'companies held', ACCENT),
            ('Executions', '%d B  %d S  %d R' % (nb, ns, nr), 'BUY / SELL / rotation', TEXT),
            ('Ticks: HW = SW = Model', '%d / %d' % (nt - s['bad_ticks'], nt),
             '✔ every signal verified' if s['bad_ticks'] == 0 else '✖ %d mismatches' % s['bad_ticks'],
             UP if s['bad_ticks'] == 0 else DOWN),
            ('Allocations verified', '%d / %d' % (na - s['bad_allocs'], na),
             'HW alloc %d-%d cycles' % (min(hl), max(hl)), UP if s['bad_allocs'] == 0 else DOWN),
            ('Throughput', '%.1f ticks/s' % tps,
             'Python model, no board' if _sim(run) else 'through the FPGA, %d companies' % n, AMBER),
        ])
        return ok, tps, elapsed

    def company_panel(ax, c, s, lo, hi, compact=True):
        tc = [t for t in s['ticks_of'][c] if lo <= t['minute'] <= hi]
        allp = [t['price'] / run.scale for t in s['ticks_of'][c]]
        ma, vw = indicators(allp, [t.get('vol', 0) for t in s['ticks_of'][c]])
        idx = {t['minute']: i for i, t in enumerate(s['ticks_of'][c])}
        style_ax(ax)
        for sp in ax.spines.values():
            sp.set_color(ccol[c])
            sp.set_linewidth(1.0)
        if not tc:
            return
        xs = [t['minute'] for t in tc]
        o = [t.get('open', t['price'] / run.scale) for t in tc]
        h = [t.get('high', t['price'] / run.scale) for t in tc]
        l = [t.get('low', t['price'] / run.scale) for t in tc]
        cl = [t.get('close', t['price'] / run.scale) for t in tc]
        candles(ax, xs, o, h, l, cl, width=0.62)
        plot_line(ax, xs, [ma[idx[x]] for x in xs], color=MA_COL, linewidth=0.9, label='MA(4)')
        plot_line(ax, xs, [vw[idx[x]] for x in xs], color=VWAP_COL, linewidth=1.0, linestyle='--', label='VWAP')
        span = (max(h) - min(l)) or 1.0
        for f in s['fills']:
            if f['lane'] == c and lo <= f['x'] <= hi:
                name, col, mk = SIDE[f['side']]
                y = f['price'] - 0.08 * span if f['side'] == BUY_ else f['price'] + 0.08 * span
                ax.scatter([f['x']], [y], marker=mk, s=46 if compact else 80, color=col, edgecolors='white',
                           linewidths=0.5, zorder=6)
        ax.set_ylim(min(l) - 0.18 * span, max(h) + 0.18 * span)
        first = s['ticks_of'][c][0]['price'] / run.scale
        chg = 100.0 * (cl[-1] / first - 1.0) if first else 0.0
        last = s['minutes'][-1]
        sc = s['ticks_of'][c][-1]['score'] * 100.0 / (1 << SCORE_FRAC)
        nm = run.names[c] if run.names[c].upper() != run.symbols[c].upper() else ''
        ax.text(0.01, 1.03, '%s   %s' % (run.symbols[c], nm[:26]), transform=ax.transAxes, color=ccol[c],
                fontsize=10, fontweight='bold', va='bottom')
        ax.text(0.99, 1.03, '%.2f  %s' % (cl[-1], pct(chg)), transform=ax.transAxes, ha='right',
                color=UP if chg >= 0 else DOWN, fontsize=9, fontweight='bold', va='bottom')
        info = 'pos %d  ·  wt %.0f%%  ·  score %+.3f%%  ·  P&L %s' % (
            last['pos'][c], 100.0 * last['w'][c] / W_TOTAL, sc, money(run.units_usd(s['realized'][c]), True))
        ax.text(0.01, 0.97, info, transform=ax.transAxes, color=TEXT, fontsize=6.6, va='top',
                bbox=dict(boxstyle='round,pad=0.25', facecolor=BG, edgecolor='none', alpha=0.75))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: '%.2f' % v))

    def draw_overview(s):
        mins = s['minutes']
        hi = mins[-1]['minute']
        lo = max(0, hi - window + 1)
        ok, tps, elapsed = kpis(s)
        header(fig, run.title, s['status'], ok, mins[-1]['time'][-5:] + ' NY')
        # company grid (left)
        cols = 1 if n <= 2 else 2
        rws = (n + cols - 1) // cols
        L, R, B, T = 0.04, 0.565, 0.05, 0.855
        gw = (R - L - 0.035 * (cols - 1)) / cols
        gh = (T - B - 0.05 * (rws - 1)) / rws
        state['axes'] = {}
        for c in range(n):
            r, k = divmod(c, cols)
            ax = fig.add_axes([L + k * (gw + 0.035), T - (r + 1) * gh - r * 0.05, gw, gh - 0.025])
            state['axes'][ax] = c
            company_panel(ax, c, s, lo, hi)
            time_axis(ax, run.slots, lo, hi, 5)
        fig.text(L, 0.012, 'candles: last %d minutes  |  ▲ BUY  ▼ SELL  ✖ rotation  |  amber MA(4), '
                 'violet VWAP  |  click a company (or press 1-%d) for its whole day' % (window, n),
                 color=MUTED, fontsize=7)
        # right column
        X, W = 0.60, 0.392
        ax_e = fig.add_axes([X, 0.69, W, 0.165])
        style_ax(ax_e, 'PORTFOLIO EQUITY  ·  whole session', 'mark-to-market; grey line = starting cash')
        xs = [m['minute'] for m in mins]
        eqs = [run.units_usd(m['equity']) for m in mins]
        col = UP if eqs[-1] >= run.start_cash else DOWN
        base = min(eqs + [run.start_cash])
        top = max(eqs + [run.start_cash])
        pad = (top - base) * 0.12 or abs(top) * 0.001 or 1.0
        ax_e.plot(xs, eqs, color=col, linewidth=1.5)
        ax_e.fill_between(xs, eqs, base - pad, color=col, alpha=0.18)
        ax_e.axhline(run.start_cash, color=MUTED, linewidth=0.8, linestyle=':')
        ax_e.set_ylim(base - pad, top + pad)
        ax_e.yaxis.set_major_formatter(big_usd)
        ax_e.axvspan(lo - 0.5, hi + 0.5, color=ACCENT, alpha=0.05)
        time_axis(ax_e, run.slots, 0, hi, 7)
        ax_t = fig.add_axes([X, 0.485, W, 0.16])
        timeline(ax_t, s['fills'], run.symbols, run.slots, 0, hi, ccol)
        ax_h = fig.add_axes([X + 0.035, 0.255, W * 0.52 - 0.035, 0.18])
        latency_hist(ax_h, [t['sw_lat'] for tc in s['ticks_of'] for t in tc if t.get('sw_lat')],
                     [t['hw_lat'] for tc in s['ticks_of'] for t in tc if t.get('hw_lat')], 'SIGNAL LATENCY', 'ticks')
        fpga_panel(fig, [X + W * 0.54, 0.255, W * 0.46, 0.18], res, engines=None)
        hl = [m['hw_lat'] for m in mins]
        sl = [m['sw_lat'] for m in mins]
        rtt = s['rtt']
        swt = [t['sw_lat'] for tc in s['ticks_of'] for t in tc if t.get('sw_lat')]
        rows = [
            ('ticks / allocations', '%d / %d in %.1f s' % (s['ticks'], len(mins), elapsed), None),
            ('ticks per second (PC <-> FPGA)', '%.1f /s' % tps, AMBER),
            ('round trip p50 / p99', '%.1f / %.1f ms' % (percentile(rtt, 50), percentile(rtt, 99)) if rtt else '--',
             None),
            ('UART load', 'simulation' if _sim(run) else '%.0f%%' % (100.0 * tps * 40 / UART_BYTES_PER_S), None),
            (None, None, None),
            ('signal: FPGA / RISC-V', '5 / %.0f cyc' % (sum(swt) / len(swt)) if swt else '--', CYAN),
            ('allocation: FPGA avg', '%.1f cyc = %.0f ns' % (sum(hl) / len(hl), 10 * sum(hl) / len(hl)), CYAN),
            ('allocation: RISC-V avg', '%.0f cyc  (%.0fx)' % (sum(sl) / len(sl), (sum(sl) / max(1, sum(hl)))), AMBER),
            ('engine capacity', '%d x 20 M ticks/s' % n, CYAN),
        ]
        stats_panel(fig, [X, 0.05, W * 0.46, 0.165], rows)
        blotter(fig, [X + W * 0.48, 0.05, W * 0.52, 0.165], s['fills'], 'TRADE BLOTTER (latest first)', max_rows=7)

    def draw_focus(s, c):
        mins = s['minutes']
        hi = mins[-1]['minute']
        ok, tps, elapsed = kpis(s)
        header(fig, '%s  -  %s, whole day  (click or Esc: all companies)' % (run.title, run.names[c]), s['status'], ok,
               mins[-1]['time'][-5:] + ' NY')
        L, R = 0.045, 0.68
        ax_p = fig.add_axes([L, 0.43, R - L, 0.40])
        company_panel(ax_p, c, s, 0, hi, compact=False)
        lim, bh, bl = run.cfgs[c]
        tc = s['ticks_of'][c]
        if tc:
            lo_, hi_ = ax_p.get_ylim()
            for lvl, name in ((bh / run.scale, 'BRK HIGH'), (bl / run.scale, 'BRK LOW')):
                if lo_ <= lvl <= hi_:
                    ax_p.axhline(lvl, color=MUTED, linestyle=':', linewidth=0.9)
                    ax_p.text(hi + 0.5, lvl, ' ' + name, color=MUTED, fontsize=6.5, va='center')
        ax_p.legend(loc='lower left', fontsize=6.5)
        time_axis(ax_p, run.slots, 0, hi, 12)
        ax_p.tick_params(labelbottom=False)
        ax_v = fig.add_axes([L, 0.335, R - L, 0.08], sharex=ax_p)
        style_ax(ax_v)
        if tc:
            ax_v.bar([t['minute'] for t in tc], [t.get('volume', 0) for t in tc], width=0.8, alpha=0.55,
                     color=[UP if t.get('close', 0) >= t.get('open', 0) else DOWN for t in tc])
        ax_v.set_ylabel('volume', color=MUTED)
        ax_v.yaxis.set_major_formatter(FuncFormatter(lambda v, _: '%.0fk' % (v / 1e3) if v >= 1e3 else '%d' % v))
        ax_v.tick_params(labelbottom=False)
        ax_s = fig.add_axes([L, 0.2, R - L, 0.11], sharex=ax_p)
        style_ax(ax_s, 'MOMENTUM SCORE (computed by the FPGA divider)', 'green BUY signal, red SELL, grey none')
        if tc:
            vc = {1: UP, 2: DOWN}
            ax_s.bar([t['minute'] for t in tc], [100.0 * t['score'] / (1 << SCORE_FRAC) for t in tc], width=0.8,
                     color=[vc.get(t['vote'], DIM) for t in tc])
        ax_s.axhline(0, color=MUTED, linewidth=0.6)
        ax_s.yaxis.set_major_formatter(PercentFormatter(decimals=2))
        ax_s.tick_params(labelbottom=False)
        ax_q = fig.add_axes([L, 0.05, R - L, 0.12], sharex=ax_p)
        style_ax(ax_q, 'POSITION (lots) AND WEIGHT')
        xs = [m['minute'] for m in mins]
        ax_q.step(xs, [m['pos'][c] for m in mins], where='post', color=ccol[c], linewidth=1.3)
        ax_q.fill_between(xs, [m['pos'][c] for m in mins], step='post', color=ccol[c], alpha=0.15)
        ax_w = ax_q.twinx()
        ax_w.plot(xs, [100.0 * m['w'][c] / W_TOTAL for m in mins], color=AMBER, linewidth=1.0, linestyle='--')
        ax_w.yaxis.set_major_formatter(PercentFormatter(decimals=0))
        ax_w.tick_params(axis='y', colors=AMBER)
        ax_w.grid(False)
        time_axis(ax_q, run.slots, 0, hi, 12)
        X, W = 0.715, 0.277
        last = mins[-1]
        t = s['trades'][c]
        lp = tc[-1]['price'] if tc else 0
        value = last['pos'][c] * lp
        bh_ret = 100.0 * (tc[-1]['price'] / tc[0]['price'] - 1.0) if tc else 0.0
        rows = [
            ('executions  BUY / SELL / ROT', '%d / %d / %d' % (t['buy'], t['sell'], t['rot']), None),
            ('position', '%d lots, held %d min' % (last['pos'][c], last['hold'][c]), ACCENT),
            ('invested', money(run.units_usd(last['inv'][c])), None),
            ('value now', money(run.units_usd(value)), None),
            ('open P&L', money(run.units_usd(value - last['inv'][c]), True),
             UP if value >= last['inv'][c] else DOWN),
            ('closed P&L', money(run.units_usd(s['realized'][c]), True), UP if s['realized'][c] >= 0 else DOWN),
            ('weight (share of cap budget)', '%.1f%%' % (100.0 * last['w'][c] / W_TOTAL), AMBER),
            ('buy & hold today', pct(bh_ret, 3), UP if bh_ret >= 0 else DOWN),
            (None, None, None),
            ('limit / breakout', '%d lots / %.2f - %.2f' % (lim, bl / run.scale, bh / run.scale), None),
        ]
        stats_panel(fig, [X, 0.6, W, 0.23], rows, 'POSITION & P&L  -  ' + run.symbols[c])
        ax_h = fig.add_axes([X + 0.02, 0.36, W - 0.02, 0.18])
        latency_hist(ax_h, [x['sw_lat'] for x in tc if x.get('sw_lat')], [x['hw_lat'] for x in tc if x.get('hw_lat')],
                     'SIGNAL LATENCY - ' + run.symbols[c], 'ticks')
        blotter(fig, [X, 0.05, W, 0.25], [f for f in s['fills'] if f['lane'] == c],
                'EXECUTIONS - ' + run.symbols[c], max_rows=10)

    def update(_=None):
        s = snap()
        fig.clf()
        if not s['minutes']:
            header(fig, run.title, s['status'], True)
            fig.text(0.5, 0.5, 'waiting for the board ... (%s)' % s['status'], ha='center', color=MUTED, fontsize=13)
            return
        f = state['focus']
        if f is None or f >= n:
            draw_overview(s)
        else:
            draw_focus(s, f)

    def on_click(ev):
        if state['focus'] is None:
            c = state['axes'].get(ev.inaxes)
            if c is None:
                return
            state['focus'] = c
        else:
            state['focus'] = None
        update()
        fig.canvas.draw_idle()

    def on_key(ev):
        if ev.key in ('escape', 'backspace'):
            state['focus'] = None
        elif ev.key and ev.key.isdigit() and 1 <= int(ev.key) <= n:
            state['focus'] = int(ev.key) - 1
        else:
            return
        update()
        fig.canvas.draw_idle()

    if snapshot:
        update()
        fig.savefig(snapshot, dpi=110)
        plt.close(fig)
        print('dashboard picture:', snapshot)
        return
    fig.canvas.mpl_connect('button_press_event', on_click)
    fig.canvas.mpl_connect('key_press_event', on_key)
    _maximize(plt)
    _ani = FuncAnimation(fig, update, interval=900, cache_frame_data=False)
    plt.show()
