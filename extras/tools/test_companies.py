#!/usr/bin/env python3
"""test_companies.py - offline test of the company feature (no internet, no board needed).

Yahoo Finance is replaced by a stand-in that serves SYNTHETIC 1-minute bars in exactly the
format yfinance returns (tz-aware New York timestamps, Open/High/Low/Close/Volume, 5 sessions).
The numbers are made up - this tests the plumbing, not the strategy:
  * company names / tickers resolve (apple, nvidia, google, microsoft, amazon, walmart, meta, tesla)
  * a single-company replay writes a log + .cfg with the right ticker and a dashboard picture
  * --company all --days 2 runs 8 x 2 sessions, writes summary.csv / summary.md / comparison.png,
    and every run passes the HW = SW = model checks (Python model board, --port none)
  * buy-and-hold in the summary = last close / first close - 1 of that session
  * verify_run.py re-downloads the RIGHT company for its market check (a log checked against
    the wrong ticker must fail)
  * --company apple,nvidia --together --strategy independent: both companies from one cash account,
    bars merged by minute in the order given, tick ids carry the company in bits 30:28,
    verify_run.py PASS (incl. the shared-cash check and the market check of each company),
    --cap-pct refuses BUYs
  * --together (hybrid, the hardware portfolio allocator) with 2 and 4 companies: ticks + one
    ALLOCATE per minute, every report == PortfolioModel, verify_run.py PASS (model replay +
    market check of every company), the one-screen overview and every company's whole-day page
    are drawn, an ablation run (--no-rotate) passes too and never rotates, and a board without
    the allocator (v10 image) is refused with a clear message
Needs pandas and matplotlib (pip install pandas matplotlib).
  python3 extras/tools/test_companies.py
"""
import contextlib
import csv
import glob
import io
import os
import random
import shutil
import sys
import tempfile
import types
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRAS = os.path.dirname(HERE)
sys.path.insert(0, EXTRAS)

# synthetic price level (USD) and median volume per minute (shares) per ticker - test fixtures only
LEVELS = {'AAPL': (255, 120e3), 'NVDA': (185, 450e3), 'GOOGL': (245, 90e3), 'MSFT': (515, 55e3),
          'AMZN': (225, 110e3), 'WMT': (102, 45e3), 'META': (715, 35e3), 'TSLA': (435, 260e3)}
DAYS = ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09']


def fake_yfinance():
    import math
    import pandas as pd

    def frame(symbol, days):
        level, vol = LEVELS[symbol]
        rnd = random.Random(zlib.crc32(symbol.encode()))
        p, idx, rows = float(level), [], []
        for day in DAYS:
            drift = rnd.gauss(0, 0.00002)        # about +-0.8 % per day, like a normal session
            t0 = pd.Timestamp(day + ' 09:30', tz='America/New_York')
            for m in range(390):
                o = p
                p *= math.exp(drift + rnd.gauss(0, 0.0007))
                hi, lo = max(o, p) * (1 + abs(rnd.gauss(0, 0.0003))), min(o, p) * (1 - abs(rnd.gauss(0, 0.0003)))
                if day in days:
                    idx.append(t0 + pd.Timedelta(minutes=m))
                    rows.append((o, hi, lo, p, int(rnd.lognormvariate(math.log(vol), 0.6))))
        return pd.DataFrame(rows, index=pd.DatetimeIndex(idx), columns=['Open', 'High', 'Low', 'Close', 'Volume'])

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period='5d', interval='1m', prepost=False, auto_adjust=False):
            assert interval == '1m' and not prepost
            if self.symbol not in LEVELS:
                return pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume'])
            return frame(self.symbol, DAYS[-1:] if period == '1d' else DAYS)

    mod = types.ModuleType('yfinance')
    mod.Ticker = Ticker
    return mod


def run_main(module, argv):
    sys.argv = argv
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            module.main()
        except SystemExit as e:
            if e.code not in (0, None):
                return e.code, out.getvalue()
    return 0, out.getvalue()


def main():
    import matplotlib
    matplotlib.use('Agg')
    sys.modules['yfinance'] = fake_yfinance()
    import market_feed
    import hft_dashboard
    import verify_run

    # names
    want = {'apple': 'AAPL', 'nvidia': 'NVDA', 'NVDA': 'NVDA', 'google': 'GOOGL', 'Microsoft': 'MSFT',
            'amazon': 'AMZN', 'walmart': 'WMT', 'meta': 'META', 'tesla': 'TSLA'}
    for k, v in want.items():
        assert market_feed.resolve_symbol(k) == v, k
    assert market_feed.company_list('all') == list(LEVELS)
    print('names ok:', ', '.join(market_feed.company_name(s) for s in market_feed.company_list('all')))

    tmp = tempfile.mkdtemp(prefix='hft_companies_')
    try:
        # one company, like the live window but saved as a picture
        log = os.path.join(tmp, 'nvda.csv')
        rc, out = run_main(hft_dashboard, ['hft_dashboard.py', '--company', 'nvidia', '--port', 'none', '--no-plot',
                                           '--speed', '0', '--log', log, '--save-png', os.path.join(tmp, 'nvda.png')])
        assert rc == 0, out
        cfg = dict(ln.strip().split('=') for ln in open(log + '.cfg'))
        assert cfg['symbol'] == 'NVDA' and cfg['source'] == 'replay', cfg
        assert 'Nvidia (NVDA) 2026-10-09' in out and os.path.exists(os.path.join(tmp, 'nvda.png')), out[:300]
        rows = list(csv.DictReader(open(log)))
        assert len(rows) == 390
        print('single company ok: Nvidia 2026-10-09, %d ticks, log + .cfg (symbol=NVDA) + picture' % len(rows))

        # all eight companies, 2 sessions each
        out_dir = os.path.join(tmp, 'all')
        rc, out = run_main(hft_dashboard, ['hft_dashboard.py', '--company', 'all', '--days', '2', '--port', 'none',
                                           '--out-dir', out_dir])
        assert rc == 0, out
        summ = list(csv.DictReader(open(os.path.join(out_dir, 'summary.csv'))))
        assert len(summ) == 16, len(summ)
        assert [r['symbol'] for r in summ] == [s for s in LEVELS for _ in range(2)]
        assert {r['day'] for r in summ} == {'2026-10-08', '2026-10-09'}
        assert all(r['verified'] == 'PASS' for r in summ), [r for r in summ if r['verified'] != 'PASS']
        for r in summ:
            lg = list(csv.DictReader(open(os.path.join(out_dir, r['log']))))
            bh = 100.0 * (int(lg[-1]['price_sent']) / int(lg[0]['price_sent']) - 1.0)
            assert abs(float(r['buy_hold_return_pct']) - round(bh, 4)) < 1e-9, (r['symbol'], bh)
            assert abs(float(r['strategy_return_pct']) - round(float(lg[-1]['return_pct']), 4)) < 1e-9
            assert os.path.exists(os.path.join(out_dir, r['log'].replace('.csv', '.png')))
        for f in ('summary.md', 'comparison.png'):
            assert os.path.exists(os.path.join(out_dir, f)), f
        trades = sum(int(r['buys']) + int(r['sells']) for r in summ)
        assert trades > 0
        print('all companies ok: 16 runs (8 companies x 2 sessions), all FPGA checks PASS, %d trades, '
              'summary.csv/.md + comparison.png' % trades)

        # verify_run: market check re-downloads the right company
        logs = sorted(glob.glob(os.path.join(out_dir, '*_2026-10-09.csv')))
        assert len(logs) == 8
        with contextlib.redirect_stdout(io.StringIO()) as o:
            ok = [verify_run.verify_one(lg, offline=False) for lg in logs]
        assert all(ok), o.getvalue()[-2000:]
        assert 'PASS market' in o.getvalue()
        bad = os.path.join(tmp, 'wrong.csv')
        shutil.copy(os.path.join(out_dir, 'NVDA_2026-10-09.csv'), bad)
        txt = open(os.path.join(out_dir, 'NVDA_2026-10-09.csv.cfg')).read().replace('symbol=NVDA', 'symbol=AAPL')
        open(bad + '.cfg', 'w').write(txt)
        with contextlib.redirect_stdout(io.StringIO()) as o:
            assert verify_run.verify_one(bad, offline=False) is False
        assert 'FAIL market' in o.getvalue()
        print('verify_run ok: 8 logs PASS incl. the market re-download; a log checked against the wrong ticker FAILS')

        # two companies together, one shared cash account
        for cap in ('0', '30'):
            log = os.path.join(tmp, 'together_%s.csv' % cap)
            rc, out = run_main(hft_dashboard, ['hft_dashboard.py', '--company', 'apple,nvidia', '--together', '--port', 'none',
                                               '--no-plot', '--log', log, '--cap-pct', cap, '--starting-cash', '200000000',
                                               '--strategy', 'independent'])
            assert rc == 0, out
            rows = list(csv.DictReader(open(log)))
            assert len(rows) == 780, len(rows)
            assert [r['company'] for r in rows[:4]] == ['AAPL', 'NVDA', 'AAPL', 'NVDA']
            assert all(int(r['tick_id'], 16) >> 28 == int(r['sym']) for r in rows)
            assert all(r['hw_dec'] == r['model_dec'] for r in rows)
            with contextlib.redirect_stdout(io.StringIO()) as o:
                assert verify_run.verify_one(log, offline=False), o.getvalue()[-2000:]
            v = o.getvalue()
            assert 'PASS cash' in v and v.count('PASS market') == 2, v
            caps = int(v.split('BUYs refused by a company cap: ')[1].split()[0])
            assert (caps > 0) == (cap != '0'), caps
            trades = sum(r['hw_dec'] != '0' for r in rows)
            print('together ok (cap %s%%): 780 ticks AAPL+NVDA merged by minute, %d trades, %d BUYs refused by the cap, '
                  'verify_run PASS (shared cash + both market checks)' % (cap, trades, caps))

        # the hardware portfolio allocator (default of --together)
        import hft_hybrid
        import hft_portfolio
        for comps, extra in (('apple,nvidia', []), ('apple,nvidia,google,microsoft', []),
                             ('apple,nvidia,google,microsoft', ['--no-rotate'])):
            n = comps.count(',') + 1
            log = os.path.join(tmp, 'hybrid_%d%s.csv' % (n, '_norot' if extra else ''))
            png = os.path.join(tmp, 'hybrid_%d.png' % n)
            rc, out = run_main(hft_dashboard, ['hft_dashboard.py', '--company', comps, '--together', '--port', 'none',
                                               '--no-plot', '--log', log, '--save-png', png, '--save-png-focus',
                                               '--starting-cash', '300000000', '--min-hold', '2'] + extra)
            assert rc == 0, out
            rows = list(csv.DictReader(open(log)))
            ticks = [r for r in rows if r['kind'] == 'tick']
            allocs = [r for r in rows if r['kind'] == 'alloc']
            assert len(ticks) == 390 * n and len(allocs) == 390, (len(ticks), len(allocs))
            assert all(r['ok'] == '1' for r in rows)
            assert all(int(r['tick_id'], 16) >> 28 == int(r['sym']) for r in ticks)
            # every minute: the companies' ticks, then exactly one ALLOCATE
            kinds = ''.join('t' if r['kind'] == 'tick' else 'a' for r in rows)
            assert kinds == ('t' * n + 'a') * 390, kinds[:40]
            with contextlib.redirect_stdout(io.StringIO()) as o:
                assert verify_run.verify_one(log, offline=False), o.getvalue()[-2000:]
            v = o.getvalue()
            assert 'PASS model' in v and v.count('PASS market') == n, v
            syms = hft_dashboard_symbols(comps)
            pics = [png] + [os.path.splitext(png)[0] + '_%s.png' % t for t in syms]
            assert all(os.path.getsize(p) > 20000 for p in pics), pics
            rot = int(v.split(' ROT;')[0].split()[-1])
            buys = int(v.split(' BUY,')[0].split()[-1])
            assert buys > 0
            if extra:
                assert rot == 0, v
            print('hybrid ok (%d companies%s): %d ticks + 390 ALLOCATE, %d BUY, %d ROT, every report == PortfolioModel, '
                  'verify_run PASS (model + %d market checks), overview + %d whole-day pages drawn'
                  % (n, ', ' + ' '.join(extra) if extra else '', len(ticks), buys, rot, n, n))
        # a board without the allocator (v10 image) answers CFG_MODE with 0: refused with a clear message
        run = types.SimpleNamespace(n=2, cfgs=[(5000, 1, 1)] * 2, settings=hft_hybrid.Settings(), start_units=10 ** 8)
        err = hft_hybrid.configure(run, hft_portfolio.SimPortfolioBoard())
        assert err and 'no hardware allocator' in err, err
        print('hybrid ok: a v10 board (no allocator) is refused: "%s..."' % err[:70])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('PASS: company feature (offline, synthetic bars)')


def hft_dashboard_symbols(comps):
    import market_feed
    return market_feed.company_list(comps)


if __name__ == '__main__':
    main()
