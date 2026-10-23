#!/usr/bin/env python3
"""ablation.py - which part of the hybrid allocator earns its place?  (Python models, no board)

Replays the same sessions of several companies through:
  independent        v10: every engine trades on its own from the shared cash (MultiModel)
  rank               portfolio mode, BUYs strongest score first, nothing else
  rank+rotate        + sell the weakest holding to fund a stronger BUY
  rank+reweight      + winners get more of the cap budget, losers less (caps on)
  hybrid             rank + rotate + reweight (the default of the dashboard)
and prints return, worst drawdown, trades and rotations per session plus the average.
The models are bit-exact with the hardware (tested in run_hft_tests.sh), so this is what the board
would do.  Returns are on whole-bar notional, without fees or slippage.

  python3 tools/ablation.py --company apple,nvidia --file AAPL_ticks.csv,NVDA_ticks.csv
  python3 tools/ablation.py --company apple,nvidia,google,microsoft          (downloads 7 days from Yahoo)
  options: --starting-cash USD (default 1,000,000,000) --lot 1000 --limit 5000 --min-hold 5
           --margin-pct 0.1 --out ablation.md
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from hft_model import (MultiModel, PortfolioModel, MODE_PORTFOLIO, MODE_RANK, MODE_ROTATE, MODE_REWEIGHT,  # noqa: E402
                       BUY, SELL, ROT)

VARIANTS = [('independent', None), ('rank', MODE_RANK), ('rank+rotate', MODE_RANK | MODE_ROTATE),
            ('rank+reweight', MODE_RANK | MODE_REWEIGHT), ('hybrid', MODE_RANK | MODE_ROTATE | MODE_REWEIGHT)]


def run_variant(mode, minutes, cfgs, start, a):
    n = len(cfgs)
    last = [0] * n
    curve, trades, rots = [], 0, 0
    if mode is None:
        m = MultiModel(n)
        m.nsym = n
        for c, (lim, hi, lo) in enumerate(cfgs):
            e = m.engines[c]
            e.pos_limit, e.brk_high, e.brk_low = lim, hi, lo
        m.starting_cash = start
        m.reset()
        for _, bars in minutes:
            for c, b in bars:
                d = m.step(c, b.price, b.vol)
                trades += d in (BUY, SELL)
                last[c] = b.price
            curve.append(m.equity(last))
    else:
        import hft_hybrid
        s = hft_hybrid.Settings(rank=bool(mode & MODE_RANK), rotate=bool(mode & MODE_ROTATE),
                                reweight=bool(mode & MODE_REWEIGHT), max_lots=a.max_lots, margin_pct=a.margin_pct,
                                min_hold=a.min_hold, k=a.weight_step, floor_pct=a.floor_pct, capshift=a.capshift, n=n)
        m = PortfolioModel(n)
        m.nsym = n
        for c, (lim, hi, lo) in enumerate(cfgs):
            e = m.engines[c]
            e.pos_limit, e.brk_high, e.brk_low = lim, hi, lo
        s.apply(m)
        m.starting_cash = start
        m.reset()
        for _, bars in minutes:
            for c, b in bars:
                m.tick(c, b.price, b.vol)
                last[c] = b.price
            codes = m.allocate(0)
            trades += sum(1 for x in codes if x)
            rots += sum(1 for x in codes if x == ROT)
            curve.append(m.equity(last))
    peak, dd = start, 0.0
    for v in curve:
        peak = max(peak, v)
        dd = min(dd, (v - peak) / peak)
    ret = 100.0 * (curve[-1] - start) / start if curve else 0.0
    return dict(ret=ret, dd=100.0 * dd, trades=trades, rots=rots)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--company', required=True)
    ap.add_argument('--file', help='one CSV per company (download_market_data.py format); default: Yahoo')
    ap.add_argument('--starting-cash', type=float, default=1e9)
    ap.add_argument('--lot', type=int, default=1000)
    ap.add_argument('--limit', type=int, default=5000)
    ap.add_argument('--max-lots', type=int, default=0)
    ap.add_argument('--margin-pct', type=float, default=0.1)
    ap.add_argument('--min-hold', type=int, default=5)
    ap.add_argument('--weight-step', type=int, default=3)
    ap.add_argument('--floor-pct', type=float, default=None)
    ap.add_argument('--capshift', type=int, default=14)
    ap.add_argument('--out', help='also write the table as Markdown to this file')
    a = ap.parse_args()
    import market_feed
    import hft_hybrid
    symbols = market_feed.company_list(a.company)
    if a.file:
        files = a.file.split(',')
        if len(files) != len(symbols):
            raise SystemExit('--file needs one CSV per company')
        all_bars = [market_feed.bars_from_csv(f, a.lot) for f in files]
    else:
        all_bars = [market_feed.fetch_minute_bars(s, '7d', a.lot) for s in symbols]
    days = None
    for bars in all_bars:
        d = set(market_feed.replayable_days(bars))
        days = d if days is None else days & d
    days = sorted(days or [])
    if not days:
        raise SystemExit('no replayable session common to every company')
    start = int(round(a.starting_cash * 100 / a.lot))          # cents x lots, like the dashboard
    table = {name: [] for name, _ in VARIANTS}
    lines = ['| session | ' + ' | '.join(name for name, _ in VARIANTS) + ' |',
             '|---|' + '---|' * len(VARIANTS)]
    for day in days:
        sess, cfgs = [], []
        for bars in all_bars:
            _, b, hi, lo = market_feed.replay_session(lot=a.lot, day=day, bars=bars)
            sess.append(b)
            cfgs.append((a.limit, hi, lo))
        minutes = hft_hybrid.merge_by_minute(sess)
        cells = []
        for name, mode in VARIANTS:
            r = run_variant(mode, minutes, cfgs, start, a)
            table[name].append(r)
            cells.append('%+.3f%% (dd %.2f%%, %d trades%s)' % (r['ret'], r['dd'], r['trades'],
                                                                ', %d rot' % r['rots'] if r['rots'] else ''))
        lines.append('| %s | %s |' % (day, ' | '.join(cells)))
    avg = []
    for name, _ in VARIANTS:
        rs = table[name]
        avg.append('**%+.3f%%** (dd %.2f%%)' % (sum(r['ret'] for r in rs) / len(rs), min(r['dd'] for r in rs)))
    lines.append('| average (worst dd) | %s |' % ' | '.join(avg))
    head = ('%s, %d session(s), starting cash %s USD, position limit %d lots, whole-bar trades, no fees'
            % (' + '.join(symbols), len(days), format(int(a.starting_cash), ','), a.limit))
    print(head)
    print('\n'.join(lines))
    if a.out:
        with open(a.out, 'w') as f:
            f.write('# Ablation: %s\n\n%s\n\n%s\n' % (' + '.join(symbols), head, '\n'.join(lines)))
        print('written to', a.out)


if __name__ == '__main__':
    main()
