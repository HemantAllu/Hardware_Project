"""download_market_data.py - save the last ~7 days of 1-minute bars of one or more companies.

  pip install yfinance pandas
  python download_market_data.py --company nvidia              -> NVDA_ticks.csv
  python download_market_data.py --company all                 -> one CSV per company (8 files)
  python download_market_data.py --company apple --out my.csv

Columns: time (bar start, New York time), open, high, low, close, volume - the real
values, unscaled. The dashboard converts close to cents and volume to lots when it
sends a tick:  python hft_dashboard.py --source csv --file NVDA_ticks.csv --company nvidia
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_feed  # noqa: E402


def main(default_company='apple'):
    ap = argparse.ArgumentParser()
    ap.add_argument('--company', '--symbol', dest='company', default=default_company,
                    help="name or ticker, comma list, or 'all' (default: %s)" % default_company)
    ap.add_argument('--out', help='output CSV (only with one company; default <TICKER>_ticks.csv)')
    a = ap.parse_args()
    symbols = market_feed.company_list(a.company)
    if a.out and len(symbols) > 1:
        sys.exit('--out works with one company only')
    for sym in symbols:
        out = a.out or '%s_ticks.csv' % sym
        print('Downloading %s 1-minute bars (last 7 days) from Yahoo Finance...' % market_feed.company_name(sym))
        bars = market_feed.fetch_minute_bars(sym, '7d')
        with open(out, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['time', 'open', 'high', 'low', 'close', 'volume'])
            for b in bars:
                w.writerow([b.time, '%.4f' % b.open, '%.4f' % b.high, '%.4f' % b.low, '%.4f' % b.close, b.volume])
        for day, bs in market_feed.sessions(bars).items():
            print('  %s: %3d bars, %.2f - %.2f USD' % (day, len(bs), min(b.low for b in bs), max(b.high for b in bs)))
        print('saved %d bars to %s' % (len(bars), out))


if __name__ == '__main__':
    main()
