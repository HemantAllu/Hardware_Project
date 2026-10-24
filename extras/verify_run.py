"""verify_run.py - independent check of a dashboard run log.

  python verify_run.py run_NVDA_2026-10-09_193000.csv            (needs internet for check 5)
  python verify_run.py run_NVDA_2026-10-09_193000.csv --offline  (skip the Yahoo re-download)
  python verify_run.py results_x/*.csv --offline                    (several logs, e.g. a --company all run)
  python verify_run.py run_AAPL-NVDA_2026-10-13_101500.csv --offline (companies traded --together)

Checks
  1. Link      : every price and volume echoed by the board equals what the PC sent
  2. HW vs SW  : hardware decision == RISC-V software decision on every tick
  3. Model     : hardware decision and position == hft_model.py replayed from scratch
  4. Latency   : hardware latency is 5 cycles on every tick
  5. Market    : the company's 1-minute bars (ticker from the .cfg file; AAPL for old logs)
                 are downloaded again from Yahoo and compared with
                 what was sent (close in cents and volume in lots, bar by bar)
  6. Returns   : the return the dashboard logged for every tick == the return of the model
                 replay (cash + holdings at the bar close, exact integer cash), when the log has it
Logs of a --together run with the hardware portfolio allocator (mode=hybrid, the default) are
replayed through hft_model.PortfolioModel: every tick's signal and score, every minute's
allocation codes (hardware AND the firmware's C copy), shared cash and state checksum (positions +
weights), the 5-cycle signal latency, the logged returns, and the Yahoo bars (check 5).
Logs of a --together --strategy independent run (several companies, one shared cash account) get the
same checks per company plus: the shared cash logged on every tick == the MultiModel replay, and it never goes
negative; the portfolio return == cash + every holding at its last close.
It also prints how many signals the risk interlock refused and warns when the run barely
traded (a run without trades only shows that both sides agree on "do nothing").
Writes <log>_verify.png: market price vs FPGA price with the hardware's BUY/SELL marks,
the difference in cents (should be a flat zero line), the return on the starting cash,
and hardware vs model position.
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hft_model import HFTModel, MultiModel, PortfolioModel, W_TOTAL, CODE_NAMES  # noqa: E402


FLOAT_FIELDS = ('open', 'high', 'low', 'close', 'cash_usd', 'equity_usd', 'return_pct')


def load(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in r:
            if k not in ('time', 'company', 'tick_id'):
                r[k] = float(r[k]) if k in FLOAT_FIELDS else int(float(r[k]))
    cfg = {}
    if os.path.exists(path + '.cfg'):
        for ln in open(path + '.cfg'):
            if '=' not in ln:
                continue
            k, v = ln.strip().split('=', 1)
            cfg[k] = v if k in ('source', 'symbol', 'symbols', 'mode') else int(v)
    return rows, cfg


def market_check(rows, lot, symbol):
    import market_feed
    bars = {b.time: b for b in market_feed.fetch_minute_bars(symbol, period='7d', lot=lot, completed_only=True)}
    res = dict(compared=0, missing=0, price_bad=[], vol_bad=[], yahoo=bars)
    for r in rows:
        b = bars.get(r['time'])
        if b is None:
            res['missing'] += 1
            continue
        res['compared'] += 1
        if b.price != r['price_echo']:
            res['price_bad'].append((r['time'], r['price_echo'], b.price))
        if b.vol != r['vol_echo']:
            res['vol_bad'].append((r['time'], r['vol_echo'], b.vol))
    return res


REAL_SOURCES = ('replay', 'live', 'apple-replay', 'apple-live')


def verify_one(log, offline):
    if open(log).readline().startswith('kind,'):
        return verify_hybrid(log, offline)
    rows, cfg = load(log)
    if not rows:
        print('%s: log is empty' % log)
        return False
    if cfg.get('mode') == 'portfolio':
        return verify_portfolio(log, rows, cfg, offline)
    pos_limit, brk_high, brk_low = cfg.get('pos_limit', 1000), cfg.get('brk_high', 150), cfg.get('brk_low', 50)
    scale, lot = cfg.get('scale', 1), cfg.get('lot', 1)
    symbol = cfg.get('symbol') or 'AAPL'          # logs written before v6 have no symbol: they were AAPL
    real = cfg.get('source', '') in REAL_SOURCES or bool(cfg.get('symbol')) or bool(scale == 100 and rows[0]['time'])
    results = []

    def check(name, bad, total, detail=''):
        ok = bad == 0
        results.append(ok)
        print('%-4s %-10s %d / %d ok%s' % ('PASS' if ok else 'FAIL', name, total - bad, total, ('   ' + detail) if detail else ''))

    print('%s: %d ticks, POS_LIMIT=%d BRK_HIGH=%d BRK_LOW=%d (prices in %s)'
          % (log, len(rows), pos_limit, brk_high, brk_low, 'cents' if scale == 100 else 'units'))
    # 1 link
    echo_bad = [r for r in rows if (r['price_echo'], r['vol_echo']) != (r['price_sent'], r['vol_sent'])]
    check('link', len(echo_bad), len(rows))
    # 2 hw vs sw
    hs_bad = [r for r in rows if r['hw_dec'] != r['sw_dec']]
    check('HW vs SW', len(hs_bad), len(rows))
    # 3 model replay (tick ids must be contiguous from 1, i.e. no lost reports, for an exact replay)
    starting_cash = int(cfg.get('starting_cash_units', 1000000))
    m = HFTModel(pos_limit, brk_high, brk_low, starting_cash)
    exp_dec, exp_pos, exp_ret, mod_bad = [], [], [], []
    contiguous = [r['tick'] for r in rows] == list(range(1, len(rows) + 1))
    for r in rows:
        d = m.step(r['price_echo'], r['vol_echo'])
        exp_dec.append(d)
        exp_pos.append(m.pos)
        eq = m.equity(r['price_echo'])                  # exact integer units
        exp_ret.append(100.0 * (eq - starting_cash) / starting_cash if starting_cash else 0.0)
        if d != r['hw_dec'] or m.pos != r['hw_pos']:
            mod_bad.append((r['tick'], r['hw_dec'], d, r['hw_pos'], m.pos))
    check('model', len(mod_bad), len(rows), '' if contiguous else '(ticks missing from the log: replay may drift)')
    for t in mod_bad[:5]:
        print('       tick %d: HW dec %d pos %d, model dec %d pos %d' % (t[0], t[1], t[3], t[2], t[4]))
    # 4 latency
    lat_bad = [r for r in rows if r['hw_lat'] != 5]
    check('latency', len(lat_bad), len(rows), 'HW 5 cycles; SW %d-%d, avg %.1f' % (
        min(r['sw_lat'] for r in rows), max(r['sw_lat'] for r in rows), sum(r['sw_lat'] for r in rows) / len(rows)))
    # 5 market data
    mk = None
    if real and not offline:
        try:
            mk = market_check(rows, lot, symbol)
            bad = len(mk['price_bad']) + len(mk['vol_bad'])
            check('market', bad, mk['compared'], '%d bars compared with a fresh Yahoo download, %d not in Yahoo data'
                  % (mk['compared'], mk['missing']))
            for t in mk['price_bad'][:5]:
                print('       %s: sent %.2f, Yahoo now %.2f' % (t[0], t[1] / 100, t[2] / 100))
            for t in mk['vol_bad'][:5]:
                print('       %s: sent %d lots, Yahoo now %d lots' % t)
            if bad:
                print('       (Yahoo can revise the newest bars for a few minutes; old bars should match exactly)')
        except Exception as e:
            print('SKIP market     could not download from Yahoo: %s' % e)
    elif real:
        print('SKIP market     (--offline)')
    # 6 returns logged by the dashboard vs the model replay
    if 'return_pct' in rows[0]:
        ret_bad = [r['tick'] for r, e in zip(rows, exp_ret) if abs(r['return_pct'] - e) > 1e-6]
        check('returns', len(ret_bad), len(rows), 'final return %+.4f%% (model replay %+.4f%%)'
              % (rows[-1]['return_pct'], exp_ret[-1]))
    else:
        print('SKIP returns    (log written by an older dashboard without return columns)')
    trades = sum(1 for r in rows if r['hw_dec'])
    print('decisions: %d BUY, %d SELL, %d NONE' % (sum(r['hw_dec'] == 1 for r in rows), sum(r['hw_dec'] == 2 for r in rows),
                                                   len(rows) - trades))
    print('signals refused by the risk interlock: %d BUY (not enough cash), %d BUY (position limit), '
          '%d SELL (nothing held), %d on zero-volume ticks'
          % (m.blocked_cash, m.blocked_limit, m.blocked_nostock, m.zero_vol))
    if trades == 0:
        print('WARNING no trade was executed: the checks only show that hardware, software and model agree on '
              '"do nothing"%s' % ('; BUYs were refused for lack of cash, raise --starting-cash' if m.blocked_cash else ''))
    elif m.blocked_cash >= sum(r['hw_dec'] == 1 for r in rows):
        print('WARNING most BUY signals were refused for lack of cash; a larger --starting-cash tests more trades')
    verdict = all(results)
    print('RESULT', 'PASS' if verdict else 'FAIL')

    # ------------------------------------------------------------------ figure
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    xs = list(range(len(rows)))
    usd = (lambda p: p / scale)
    fig, (a1, a2, a4, a3) = plt.subplots(4, 1, figsize=(14, 12.5), sharex=True,
                                         gridspec_kw=dict(height_ratios=[3, 1, 1.3, 1.3]))
    if mk:
        ycl = [mk['yahoo'][r['time']].close if r['time'] in mk['yahoo'] else float('nan') for r in rows]
        a1.plot(xs, ycl, color='black', linewidth=1.4, label='Yahoo Finance %s close (downloaded again now)' % symbol)
        diff = [(r['price_echo'] - mk['yahoo'][r['time']].price) if r['time'] in mk['yahoo'] else float('nan') for r in rows]
        a2.plot(xs, diff, color='#c00000')
        a2.set_ylabel('cents')
        a2.set_title('FPGA price minus Yahoo price (0 everywhere = the graph matches the market)', fontsize=10)
    elif real:
        a1.plot(xs, [r['close'] for r in rows], color='black', linewidth=1.4, label='market close sent by the PC')
        a2.text(0.5, 0.5, 'market re-download skipped', ha='center', va='center', transform=a2.transAxes)
    else:
        a2.text(0.5, 0.5, 'not real market data', ha='center', va='center', transform=a2.transAxes)
    a1.scatter(xs, [usd(r['price_echo']) for r in rows], s=8, color='#2b5fd9', zorder=3, label='price echoed by the FPGA')
    for dec, mk_, col, key, lab in ((1, '^', '#00b050', 'low', 'BUY (hardware)'), (2, 'v', '#c000c0', 'high', 'SELL (hardware)')):
        pts = [(x, r) for x, r in zip(xs, rows) if r['hw_dec'] == dec]
        if pts:
            a1.scatter([x for x, _ in pts], [usd(r['price_echo']) for _, r in pts], marker=mk_, s=70, color=col, zorder=4,
                       label=lab, edgecolors='black', linewidths=0.4)
    a1.axhline(usd(brk_high), color='gray', linestyle=':', linewidth=1)
    a1.axhline(usd(brk_low), color='gray', linestyle=':', linewidth=1)
    a1.legend(loc='best', fontsize=8)
    a1.set_ylabel('USD' if scale == 100 else 'price')
    a1.set_title('%s  -  verification %s' % (os.path.basename(log), 'PASS' if verdict else 'FAIL'))
    from matplotlib.ticker import PercentFormatter
    a4.axhline(0, color='gray', linewidth=0.8)
    a4.fill_between(xs, exp_ret, 0, where=[v >= 0 for v in exp_ret], interpolate=True, color='#1a9850', alpha=0.25)
    a4.fill_between(xs, exp_ret, 0, where=[v < 0 for v in exp_ret], interpolate=True, color='#d73027', alpha=0.25)
    a4.plot(xs, exp_ret, color='#1f4e9c', linewidth=1.6,
            label='return on starting cash, model replay (final %+.3f%%)' % exp_ret[-1])
    if 'return_pct' in rows[0]:
        a4.plot(xs, [r['return_pct'] for r in rows], color='#f0a000', linewidth=1, linestyle='--',
                label='return logged by the dashboard')
    a4.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    a4.set_ylabel('return')
    a4.set_title('Return on the starting cash (cash + holdings at the bar close, mark-to-market)', fontsize=10)
    a4.legend(loc='upper left', fontsize=8)
    a3.plot(xs, [r['hw_pos'] for r in rows], color='#7030a0', linewidth=2.2, label='hardware position (from the board)')
    a3.plot(xs, exp_pos, color='#f0a000', linewidth=1, linestyle='--', label='reference model position (replayed)')
    a3.legend(loc='best', fontsize=8)
    a3.set_ylabel('lots' if lot > 1 else 'units')
    step = max(1, len(rows) // 12)
    a3.set_xticks(xs[::step])
    a3.set_xticklabels([r['time'][-5:] if r['time'] else str(r['tick']) for r in rows][::step], fontsize=8)
    a3.set_xlabel('New York time' if real else 'tick')
    plt.tight_layout()
    out = os.path.splitext(log)[0] + '_verify.png'
    plt.savefig(out, dpi=130)
    print('figure:', out)
    plt.close(fig)
    return verdict


def verify_portfolio(log, rows, cfg, offline):
    """Several companies traded together from one cash account (hft_portfolio.py log)."""
    syms = cfg['symbols'].split(',')
    n, scale, lot = len(syms), cfg.get('scale', 100), cfg.get('lot', 1)
    start = int(cfg['starting_cash_units'])
    results = []

    def check(name, bad, total, detail=''):
        ok = bad == 0
        results.append(ok)
        print('%-4s %-10s %d / %d ok%s' % ('PASS' if ok else 'FAIL', name, total - bad, total, ('   ' + detail) if detail else ''))

    print('%s: %d ticks, %d companies together (%s), one shared cash account of %d units'
          % (log, len(rows), n, ', '.join(syms), start))
    m = MultiModel(n)
    m.nsym = n
    for c in range(n):
        e = m.engines[c]
        e.pos_limit, e.brk_high, e.brk_low = cfg['pos_limit_%d' % c], cfg['brk_high_%d' % c], cfg['brk_low_%d' % c]
        m.caps[c] = cfg.get('cap_units_%d' % c, 0)
        print('  company %d %-5s POS_LIMIT=%d BRK_HIGH=%d BRK_LOW=%d CAP=%s' % (c, syms[c], e.pos_limit, e.brk_high,
                                                                          e.brk_low, m.caps[c] or 'none'))
    m.starting_cash = start
    m.reset()
    check('link', sum((r['price_echo'], r['vol_echo']) != (r['price_sent'], r['vol_sent']) for r in rows), len(rows))
    check('HW vs SW', sum(r['hw_dec'] != r['sw_dec'] for r in rows), len(rows))
    mod_bad, cash_bad, neg, ret_bad = [], [], 0, 0
    last = [0] * n
    exp_ret, exp_cash = [], []
    for r in rows:
        c = r['sym']
        d = m.step(c, r['price_echo'], r['vol_echo'])
        last[c] = r['price_echo']
        if d != r['hw_dec'] or m.pos(c) != r['hw_pos']:
            mod_bad.append((r['tick'], syms[c], r['hw_dec'], d, r['hw_pos'], m.pos(c)))
        if r['cash_units'] != m.cash:
            cash_bad.append((r['tick'], r['cash_units'], m.cash))
        neg += r['cash_units'] < 0
        eq = m.equity(last)
        er = 100.0 * (eq - start) / start if start else 0.0
        exp_ret.append(er)
        exp_cash.append(m.cash)
        ret_bad += abs(r['return_pct'] - er) > 1e-6
    contiguous = [r['tick'] for r in rows] == list(range(1, len(rows) + 1))
    check('model', len(mod_bad), len(rows), '' if contiguous else '(ticks missing from the log: replay may drift)')
    for t in mod_bad[:5]:
        print('       tick %d %s: HW dec %d, model %d; HW pos %d, model %d' % t)
    check('cash', len(cash_bad) + neg, len(rows), 'shared cash == model on every tick, never negative (final %d units)'
          % m.cash)
    for t in cash_bad[:5]:
        print('       tick %d: logged cash %d, model %d' % t)
    check('latency', sum(r['hw_lat'] != 5 for r in rows), len(rows), 'HW 5 cycles on every company')
    check('returns', ret_bad, len(rows), 'final portfolio return %+.4f%%' % exp_ret[-1])
    real = cfg.get('source', '') in REAL_SOURCES or (scale == 100 and bool(rows[0]['time']))
    if real and not offline:
        for c, sym in enumerate(syms):
            rc = [r for r in rows if r['sym'] == c]
            try:
                mk = market_check(rc, lot, sym)
                bad = len(mk['price_bad']) + len(mk['vol_bad'])
                check('market', bad, mk['compared'], '%s: %d bars compared with Yahoo, %d not in Yahoo data'
                      % (sym, mk['compared'], mk['missing']))
            except Exception as e:
                print('SKIP market     %s: could not download from Yahoo: %s' % (sym, e))
    elif real:
        print('SKIP market     (--offline)')
    for c, sym in enumerate(syms):
        rc = [r for r in rows if r['sym'] == c]
        e = m.engines[c]
        print('  %-5s %d BUY, %d SELL, final position %d | refused: cash %d, position limit %d, nothing held %d'
              % (sym, sum(r['hw_dec'] == 1 for r in rc), sum(r['hw_dec'] == 2 for r in rc), m.pos(c),
                 e.blocked_cash, e.blocked_limit, e.blocked_nostock))
    print('  BUYs refused by a company cap: %d' % m.blocked_cap)
    verdict = all(results)
    print('RESULT', 'PASS' if verdict else 'FAIL')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    fig, axes = plt.subplots(n + 2, 1, figsize=(14, 2.6 * n + 6), sharex=True)
    xs = list(range(len(rows)))
    for c, sym in enumerate(syms):
        ax = axes[c]
        pts = [(x, r) for x, r in zip(xs, rows) if r['sym'] == c]
        ax.plot([x for x, _ in pts], [r['price_echo'] / scale for _, r in pts], color='#2b5fd9', linewidth=1)
        for dec, mk_, col in ((1, '^', '#00b050'), (2, 'v', '#c000c0')):
            q = [(x, r) for x, r in pts if r['hw_dec'] == dec]
            if q:
                ax.scatter([x for x, _ in q], [r['price_echo'] / scale for _, r in q], marker=mk_, s=50, color=col,
                           zorder=4, edgecolors='black', linewidths=0.4)
        ax.set_title('%s: price echoed by the FPGA with the hardware BUY/SELL marks' % sym, fontsize=10, loc='left')
    axes[n].plot(xs, [r['cash_units'] * lot / scale for r in rows], color='#e07b00', linewidth=2, label='shared cash (log)')
    axes[n].plot(xs, [v * lot / scale for v in exp_cash], color='black', linewidth=1, linestyle='--', label='model replay')
    axes[n].legend(loc='best', fontsize=8)
    axes[n].set_title('Shared cash, USD', fontsize=10, loc='left')
    axes[n + 1].plot(xs, exp_ret, color='#1f4e9c', linewidth=1.6, label='model replay')
    axes[n + 1].plot(xs, [r['return_pct'] for r in rows], color='#f0a000', linewidth=1, linestyle='--', label='dashboard log')
    axes[n + 1].yaxis.set_major_formatter(PercentFormatter(xmax=100))
    axes[n + 1].legend(loc='best', fontsize=8)
    axes[n + 1].set_title('Portfolio return on the starting cash', fontsize=10, loc='left')
    fig.suptitle('%s  -  verification %s' % (os.path.basename(log), 'PASS' if verdict else 'FAIL'), x=0.02, ha='left')
    plt.tight_layout()
    out = os.path.splitext(log)[0] + '_verify.png'
    plt.savefig(out, dpi=110)
    plt.close(fig)
    print('figure:', out)
    return verdict


def verify_hybrid(log, offline):
    """Several companies with the hardware portfolio allocator (hft_hybrid.py log)."""
    with open(log) as f:
        raw = list(csv.DictReader(f))
    cfg = {}
    for ln in open(log + '.cfg'):
        if '=' in ln:
            k, v = ln.strip().split('=', 1)
            cfg[k] = v if k in ('source', 'symbols', 'mode') else int(v)
    syms = cfg['symbols'].split(',')
    n, scale, lot, start = len(syms), cfg.get('scale', 100), cfg.get('lot', 1), cfg['starting_cash_units']
    m = PortfolioModel(n)
    m.nsym = n
    for c in range(n):
        e = m.engines[c]
        e.pos_limit, e.brk_high, e.brk_low = cfg['pos_limit_%d' % c], cfg['brk_high_%d' % c], cfg['brk_low_%d' % c]
    m.mode_cfg, m.max_lots, m.margin, m.min_hold = cfg['port_mode'], cfg['max_lots'], cfg['margin'], cfg['min_hold']
    m.wshift, m.capshift, m.wfloor = cfg['wshift'], cfg['capshift'], cfg['wfloor']
    m.starting_cash = start
    m.reset()
    results = []

    def check(name, bad, total, detail=''):
        ok = bad == 0
        results.append(ok)
        print('%-4s %-10s %d / %d ok%s' % ('PASS' if ok else 'FAIL', name, total - bad, total, ('   ' + detail) if detail else ''))

    def num(r, k):
        return int(float(r[k]))

    ticks = [r for r in raw if r['kind'] == 'tick']
    allocs = [r for r in raw if r['kind'] == 'alloc']
    print('%s: %d companies with the hardware portfolio allocator (%s), %d ticks, %d allocations, cash %d units'
          % (log, n, ', '.join(syms), len(ticks), len(allocs), start))
    check('link', sum((num(r, 'price_echo'), num(r, 'vol_echo')) != (num(r, 'price_sent'), num(r, 'vol_sent'))
                      for r in ticks), len(ticks))
    check('HW vs SW', sum(num(r, 'hw_vote') != num(r, 'sw_vote') for r in ticks) +
          sum(num(r, 'hw_codes') != num(r, 'sw_codes') for r in allocs), len(ticks) + len(allocs),
          'signals and allocation codes')
    sig_bad, alloc_bad, ret_bad = [], [], 0
    last = [0] * n
    exp_ret, xs_ret, cash_hist, w_hist = [], [], [], []
    marks = [[] for _ in range(n)]
    for i, r in enumerate(raw):
        if r['kind'] == 'tick':
            c = num(r, 'sym')
            sig, score = m.tick(c, num(r, 'price_echo'), num(r, 'vol_echo'))
            last[c] = num(r, 'price_echo')
            if (sig, score) != (num(r, 'hw_vote'), num(r, 'hw_score')):
                sig_bad.append((r['time'], syms[c], num(r, 'hw_vote'), sig, num(r, 'hw_score'), score))
        else:
            codes = m.allocate(num(r, 'kill'))[:n]
            packed = sum(x << (2 * k) for k, x in enumerate(codes))
            got = (num(r, 'hw_codes'), num(r, 'hw_cash_units'), num(r, 'hw_checksum'))
            if got != (packed, m.cash, m.checksum()):
                alloc_bad.append((r['time'], got, (packed, m.cash, m.checksum())))
            for c, x in enumerate(codes):
                if x:
                    marks[c].append((i, m.lastp[c], x))
            eq = m.equity(last)
            er = 100.0 * (eq - start) / start if start else 0.0
            exp_ret.append(er)
            xs_ret.append(i)
            cash_hist.append(m.cash)
            w_hist.append(m.w[:n])
            ret_bad += abs(float(r['return_pct']) - er) > 1e-6
    check('model', len(sig_bad) + len(alloc_bad), len(raw), 'signal + score of every tick; codes, cash and '
          'checksum of every minute (PortfolioModel replay)')
    for t in sig_bad[:5]:
        print('       %s %s: HW vote %d (model %d), score %d (model %d)' % t)
    for t in alloc_bad[:5]:
        print('       %s: HW codes/cash/checksum %s, model %s' % t)
    check('latency', sum(num(r, 'hw_lat') != 5 for r in ticks), len(ticks), 'signal in 5 cycles on every tick')
    check('returns', ret_bad, len(allocs), 'final portfolio return %+.4f%%' % (exp_ret[-1] if exp_ret else 0))
    real = cfg.get('source', '') in REAL_SOURCES
    if real and not offline:
        for c, sym in enumerate(syms):
            rc = [dict(time=r['time'], price_echo=num(r, 'price_echo'), vol_echo=num(r, 'vol_echo'))
                  for r in ticks if num(r, 'sym') == c]
            try:
                mk = market_check(rc, lot, sym)
                check('market', len(mk['price_bad']) + len(mk['vol_bad']), mk['compared'],
                      '%s: %d bars compared with Yahoo, %d not in Yahoo data' % (sym, mk['compared'], mk['missing']))
            except Exception as e:
                print('SKIP market     %s: could not download from Yahoo: %s' % (sym, e))
    elif real:
        print('SKIP market     (--offline)')
    st = m.stats
    print('  allocator: %d BUY, %d SELL, %d ROT; ranking changed the order in %d minutes; %d wins + %d losses '
          'reweighted; BUY refused: cash %d, cap %d, position limit %d'
          % (st['buys'], st['sells'], st['rotations'], st['ranked'], st['wins'], st['losses'], st['refused_cash'],
             st['refused_cap'], st['refused_limit']))
    if not st['buys']:
        print('WARNING no trade was executed: the checks only show that hardware, software and model agree on '
              '"do nothing"')
    verdict = all(results)
    print('RESULT', 'PASS' if verdict else 'FAIL')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    fig, axes = plt.subplots(n + 2, 1, figsize=(14, 2.4 * n + 5.5), sharex=True)
    for c, sym in enumerate(syms):
        ax = axes[c]
        pts = [(i, num(r, 'price_echo')) for i, r in enumerate(raw) if r['kind'] == 'tick' and num(r, 'sym') == c]
        ax.plot([x for x, _ in pts], [p / scale for _, p in pts], color='#2b5fd9', linewidth=1)
        for code, mk_, col in ((1, '^', '#00b050'), (2, 'v', '#c000c0'), (3, 'X', '#d00000')):
            q = [(x, p) for x, p, k in marks[c] if k == code]
            if q:
                ax.scatter([x for x, _ in q], [p / scale for _, p in q], marker=mk_, s=50, color=col, zorder=4,
                           edgecolors='black', linewidths=0.4, label=CODE_NAMES[code])
        ax.legend(loc='best', fontsize=7)
        ax.set_title('%s: price echoed by the FPGA, allocations of the hardware' % sym, fontsize=10, loc='left')
    axes[n].plot(xs_ret, exp_ret, color='#1f4e9c', linewidth=1.6, label='return, model replay')
    axes[n].plot([i for i, r in enumerate(raw) if r['kind'] == 'alloc'], [float(r['return_pct']) for r in allocs],
                 color='#f0a000', linewidth=1, linestyle='--', label='return, dashboard log')
    axes[n].yaxis.set_major_formatter(PercentFormatter(xmax=100))
    axes[n].legend(loc='best', fontsize=8)
    axes[n].set_title('Portfolio return on the starting cash', fontsize=10, loc='left')
    if w_hist:
        axes[n + 1].stackplot(xs_ret, *[[100.0 * w[c] / W_TOTAL for w in w_hist] for c in range(n)], labels=syms, alpha=0.75)
        axes[n + 1].legend(loc='upper left', fontsize=7, ncol=n)
    axes[n + 1].set_title('Weights (model replay)', fontsize=10, loc='left')
    fig.suptitle('%s  -  verification %s' % (os.path.basename(log), 'PASS' if verdict else 'FAIL'), x=0.02, ha='left')
    plt.tight_layout()
    out = os.path.splitext(log)[0] + '_verify.png'
    plt.savefig(out, dpi=100)
    plt.close(fig)
    print('figure:', out)
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('log', nargs='+', help='one or more dashboard logs (run_*.csv, or the <TICKER>_<day>.csv of a '
                                           '--company all run)')
    ap.add_argument('--offline', action='store_true', help='skip the Yahoo re-download')
    a = ap.parse_args()
    logs = [p for p in a.log if not p.endswith('summary.csv')]
    verdicts = []
    for i, log in enumerate(logs):
        if len(logs) > 1:
            print('%s%s' % ('\n' if i else '', '=' * 78))
        verdicts.append((log, verify_one(log, a.offline)))
    if len(logs) > 1:
        print('\n%d logs: %d PASS, %d FAIL' % (len(verdicts), sum(v for _, v in verdicts), sum(not v for _, v in verdicts)))
        for log, v in verdicts:
            if not v:
                print('  FAIL', log)
    sys.exit(0 if all(v for _, v in verdicts) else 1)


if __name__ == '__main__':
    main()
