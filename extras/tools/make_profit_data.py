"""make_profit_data.py - SYNTHETIC (made-up) market data on which our strategy makes a profit.

WHY THIS EXISTS
  On real data the MA + VWAP + breakout strategy wins on some days and loses on others.
  For a demo it is useful to also show data where it clearly wins.  This script makes
  8 fictional companies (SYN1 .. SYN8) whose prices follow patterns the strategy is
  built to catch: a price that breaks above yesterday's high and keeps trending up.

  THESE ARE NOT REAL COMPANIES AND NOT REAL PRICES.  The profit is designed in: it shows
  that the hardware follows the rules correctly, not that the strategy makes money in the
  real market.  Always say "synthetic data" when you show these results.

OUTPUT (same format as download_market_data.py, so every tool reads it unchanged)
  synthetic_data/SYN1_ticks.csv ... SYN8_ticks.csv
  columns: time,open,high,low,close,volume   (1-minute bars, 09:30-15:59, 390 bars a day)
  3 sessions per company: 2026-10-19 (sets the breakout levels), 2026-10-20, 2026-10-21

RUN (from the extras folder)
  python tools/make_profit_data.py                 # writes synthetic_data/
  python hft_dashboard.py --source csv --company SYN1 --file synthetic_data/SYN1_ticks.csv --port none
  python hft_dashboard.py --source csv --company SYN1,SYN2,SYN3,SYN4,SYN5,SYN6,SYN7,SYN8 \
      --file synthetic_data/SYN1_ticks.csv,...,synthetic_data/SYN8_ticks.csv --days 2 --port COM6

The data is the same every time (fixed random seeds), so results can be repeated.
"""
import argparse
import csv
import math
import os
import random

DAYS = ['2026-10-19', '2026-10-20', '2026-10-21']
BARS = 390                                   # 09:30 .. 15:59, one bar per minute

# name, start price (USD), typical volume (shares per minute), pattern per session, seed
# Patterns (what the price does during one session):
#   'range'    : moves sideways  (used for the first day: it only sets the breakout levels)
#   'trend'    : steady climb with small wiggles
#   'gapup'    : opens a little higher, rallies in the morning, then holds
#   'stairs'   : climbs in steps: rise, pause, rise, pause
#   'late'     : quiet morning, strong afternoon rally
#   'dipup'    : small dip after the open, then a long recovery and climb
COMPANIES = [
    ('SYN1', 'Synthetic Alpha',   182.0, 160000, ['range', 'trend',  'stairs'], 101),
    ('SYN2', 'Synthetic Beta',    455.0,  40000, ['range', 'gapup',  'trend'],  202),
    ('SYN3', 'Synthetic Gamma',   128.0, 210000, ['range', 'stairs', 'late'],   303),
    ('SYN4', 'Synthetic Delta',   312.0,  60000, ['range', 'late',   'gapup'],  404),
    ('SYN5', 'Synthetic Epsilon',  96.0, 260000, ['range', 'dipup',  'trend'],  505),
    ('SYN6', 'Synthetic Zeta',    238.0,  80000, ['range', 'trend',  'dipup'],  606),
    ('SYN7', 'Synthetic Eta',     521.0,  35000, ['range', 'gapup',  'stairs'], 727),
    ('SYN8', 'Synthetic Theta',   164.0, 180000, ['range', 'stairs', 'trend'],  808),
]


def drift_curve(pattern, n=BARS):
    """Expected move (as a fraction of price) for each minute of the session."""
    out = []
    for i in range(n):
        t = i / (n - 1)
        if pattern == 'range':
            d = 0.0012 * math.sin(2 * math.pi * 3 * t) / n * 20
        elif pattern == 'trend':
            d = 0.030 / n
        elif pattern == 'gapup':
            d = 0.050 / (0.35 * n) if t < 0.35 else 0.004 / n
        elif pattern == 'stairs':
            d = 0.060 / n if int(t * 6) % 2 == 0 else 0.0
        elif pattern == 'late':
            d = 0.0 if t < 0.45 else 0.040 / (0.55 * n)
        elif pattern == 'dipup':
            d = -0.010 / (0.1 * n) if t < 0.1 else 0.045 / (0.9 * n)
        else:
            raise ValueError(pattern)
        out.append(d)
    return out


def make_company(start, vol_typ, patterns, seed):
    rnd = random.Random(seed)
    rows = []
    price = start
    for day, pattern in zip(DAYS, patterns):
        if pattern == 'gapup':
            price *= 1.004                                       # small opening gap up
        drift = drift_curve(pattern)
        noise = 0.0006 if pattern != 'range' else 0.0009         # minute-to-minute wiggle
        for i in range(BARS):
            o = price
            c = o * (1 + drift[i] + rnd.gauss(0, noise))
            hi = max(o, c) * (1 + abs(rnd.gauss(0, noise / 2)))
            lo = min(o, c) * (1 - abs(rnd.gauss(0, noise / 2)))
            t = i / (BARS - 1)
            shape = 1.0 + 1.6 * (1 - t) ** 6 + 1.0 * t ** 8      # busy open and close, quiet midday
            if drift[i] > 0 and pattern != 'range':
                shape *= 1.3                                     # rallies come with more volume
            v = int(vol_typ * shape * rnd.lognormvariate(0, 0.35))
            hh, mm = divmod(9 * 60 + 30 + i, 60)
            rows.append(['%s %02d:%02d' % (day, hh, mm), '%.4f' % o, '%.4f' % hi, '%.4f' % lo, '%.4f' % c, max(v, 1000)])
            price = c
        price *= 1 + rnd.gauss(0, 0.001)                         # overnight move
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out-dir', default='synthetic_data')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    for sym, name, start, vol, patterns, seed in COMPANIES:
        rows = make_company(start, vol, patterns, seed)
        path = os.path.join(a.out_dir, '%s_ticks.csv' % sym)
        with open(path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['time', 'open', 'high', 'low', 'close', 'volume'])
            w.writerows(rows)
        print('%s (%s, SYNTHETIC): %d bars, %s -> %s USD  -> %s'
              % (sym, name, len(rows), rows[0][1], rows[-1][4], path))


if __name__ == '__main__':
    main()
