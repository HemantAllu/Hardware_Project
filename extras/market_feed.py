"""market_feed.py - real 1-minute market data for the FPGA (Yahoo Finance via yfinance).

Pick the company by name or ticker (case-insensitive):
    apple AAPL | nvidia NVDA | google / alphabet GOOGL | microsoft MSFT | amazon AMZN
    walmart WMT | meta / facebook META | tesla TSLA        ('all' = these eight)
Any other Yahoo Finance ticker (e.g. JPM, NFLX) also works.

Each 1-minute bar becomes one tick:  price = close in cents,  vol = volume in lots.
  * cents keep the real price exactly (227.53 USD -> 22753)
  * a lot is LOT shares (default 1000), so the hardware position limit and trade
    size are in lots; VWAP is not affected by this scaling (it is a ratio)
Breakout levels default to the previous session's high and low (a classic
"break out of yesterday's range" rule), also in cents.

All eight companies fit the accelerator's number widths with room to spare: prices
up to about $42,000,000 fit in 32-bit cents, and a whole day's volume of the busiest
stock (about 300,000 lots for NVDA) is far below the 32-bit volume sum.

Free data is 1-minute bars, not exchange tick-by-tick data, and Yahoo can lag the
market by up to a minute or so. Yahoo keeps about 7 calendar days of 1-minute bars.
US market hours are 09:30-16:00 New York time (19:00-01:30 IST while the US is on
summer time, 20:00-02:30 IST after 1 Nov).
"""
import re
import time
from dataclasses import dataclass
from datetime import timedelta

LOT = 1000          # shares per lot
SYMBOL = 'AAPL'     # default company

# the eight companies of the comparison, in a fixed order (ticker -> display name)
COMPANIES = {
    'AAPL': 'Apple',
    'NVDA': 'Nvidia',
    'GOOGL': 'Google',
    'MSFT': 'Microsoft',
    'AMZN': 'Amazon',
    'WMT': 'Walmart',
    'META': 'Meta',
    'TSLA': 'Tesla',
}
ALIASES = {
    'apple': 'AAPL', 'nvidia': 'NVDA', 'nvdia': 'NVDA', 'google': 'GOOGL', 'alphabet': 'GOOGL',
    'microsoft': 'MSFT', 'amazon': 'AMZN', 'walmart': 'WMT', 'meta': 'META',
    'facebook': 'META', 'fb': 'META', 'tesla': 'TSLA',
}


def resolve_symbol(name):
    """'nvidia' / 'NVDA' / 'Nvidia' -> 'NVDA'.  Unknown names that look like a ticker are
    passed through (upper case), so any Yahoo Finance symbol can be used."""
    key = name.strip()
    if key.lower() in ALIASES:
        return ALIASES[key.lower()]
    if key.upper() in COMPANIES:
        return key.upper()
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9.\-^=]{0,9}', key):
        return key.upper()
    raise ValueError('unknown company %r; use a ticker or one of: %s'
                     % (name, ', '.join(sorted(set(ALIASES) - {'nvdia', 'fb'}))))


def company_list(spec):
    """'all' -> the eight companies; 'apple,nvidia, TSLA' -> ['AAPL', 'NVDA', 'TSLA'] (order kept, no repeats)."""
    if spec.strip().lower() == 'all':
        return list(COMPANIES)
    out = []
    for part in spec.split(','):
        if part.strip():
            s = resolve_symbol(part)
            if s not in out:
                out.append(s)
    if not out:
        raise ValueError('no company given')
    return out


def company_name(symbol):
    """'NVDA' -> 'Nvidia (NVDA)'; other tickers are shown as they are."""
    return '%s (%s)' % (COMPANIES[symbol], symbol) if symbol in COMPANIES else symbol


@dataclass
class Bar:
    time: str           # bar start, New York time, 'YYYY-MM-DD HH:MM'
    open: float
    high: float
    low: float
    close: float
    volume: int
    price: int          # sent to the FPGA: close in cents
    vol: int            # sent to the FPGA: volume in whole lots (0 for a bar under half a lot)


def to_cents(x):
    return int(round(float(x) * 100))


def to_lots(v, lot=LOT):
    """Shares -> whole lots, rounded to nearest.  A bar of less than half a lot (or with no
    volume at all) becomes 0 lots: it updates the moving average but adds nothing to VWAP and
    never trades (the 'zero volume never trades' rule).  v11 forced every bar to at least one
    lot, so an empty bar was sent as 1,000 traded shares."""
    return int(round(float(v) / lot))


def _frame_to_bars(df, lot):
    bars = []
    for ts, row in df.iterrows():
        if row['Volume'] != row['Volume'] or row['Close'] != row['Close']:   # NaN rows
            continue
        bars.append(Bar(ts.strftime('%Y-%m-%d %H:%M'), float(row['Open']), float(row['High']), float(row['Low']),
                        float(row['Close']), int(row['Volume']), to_cents(row['Close']), to_lots(row['Volume'], lot)))
    return bars


def fetch_minute_bars(symbol=SYMBOL, period='5d', lot=LOT, completed_only=True, retries=2):
    """All 1-minute bars of the last `period` (yfinance keeps about 7 days of 1-minute data)."""
    import yfinance as yf
    df = None
    for attempt in range(retries + 1):
        df = yf.Ticker(symbol).history(period=period, interval='1m', prepost=False, auto_adjust=False)
        if not df.empty:
            break
        if attempt < retries:
            time.sleep(2.0)                    # Yahoo sometimes answers empty when asked quickly
    if df is None or df.empty:
        raise RuntimeError('Yahoo returned no data for %s (no internet, rate limited, or unknown ticker)' % symbol)
    if completed_only and len(df):
        # the newest bar is still forming while the market is open: drop it
        import pandas as pd
        last = df.index[-1]
        if pd.Timestamp.now(tz=last.tz) < last + timedelta(minutes=1):
            df = df.iloc[:-1]
    return _frame_to_bars(df, lot)


def sessions(bars):
    """Group bars by trading day: {'YYYY-MM-DD': [bars]} in date order."""
    out = {}
    for b in bars:
        out.setdefault(b.time[:10], []).append(b)
    return dict(sorted(out.items()))


def breakout_levels(day_bars):
    """High and low of a session, in cents (used as the next session's breakout levels)."""
    return to_cents(max(b.high for b in day_bars)), to_cents(min(b.low for b in day_bars))


def bars_from_csv(path, lot=LOT):
    """Bars saved by download_market_data.py (time,open,high,low,close,volume)."""
    import csv
    out = []
    with open(path) as f:
        for r in csv.DictReader(f):
            out.append(Bar(r['time'], float(r['open']), float(r['high']), float(r['low']), float(r['close']),
                           int(float(r['volume'])), to_cents(r['close']), to_lots(r['volume'], lot)))
    return out


def replayable_days(bars):
    """Sessions that can be replayed: every session except the oldest (it has no previous
    session for the breakout levels)."""
    return list(sessions(bars))[1:]


def replay_session(symbol=SYMBOL, lot=LOT, day=None, bars=None):
    """Bars of one session plus breakout levels from the session before it.
    bars: use these (e.g. from a CSV, or downloaded once for several days) instead of downloading.
    Returns (day, bars, brk_high_cents, brk_low_cents)."""
    s = sessions(bars if bars is not None else fetch_minute_bars(symbol, '7d', lot))
    days = list(s)
    if len(days) < 2:
        raise RuntimeError('%s: need at least two sessions of data, got %s' % (symbol, days))
    day = day or days[-1]
    if day not in s:
        raise RuntimeError('%s: no data for %s; available: %s' % (symbol, day, ', '.join(days)))
    i = days.index(day)
    if i == 0:
        raise RuntimeError('%s: %s is the oldest session available; pick a later one' % (symbol, day))
    hi, lo = breakout_levels(s[days[i - 1]])
    return day, s[day], hi, lo


def live_bars(symbol=SYMBOL, lot=LOT, poll_s=15, start_after=None):
    """Yields each new completed 1-minute bar as it appears (runs until stopped)."""
    seen = start_after
    while True:
        try:
            bars = fetch_minute_bars(symbol, '1d', lot)
        except Exception as e:               # network hiccup: wait and retry
            print('feed:', e)
            bars = []
        for b in bars:
            if seen is None or b.time > seen:
                seen = b.time
                yield b
        time.sleep(poll_s)


def live_session(symbol=SYMBOL, lot=LOT):
    """For live mode: today's bars so far, breakout levels from the previous session,
    and a generator of the new bars that follow."""
    s = sessions(fetch_minute_bars(symbol, '7d', lot))
    days = list(s)
    today = days[-1]
    prev = days[-2] if len(days) > 1 else None
    hi, lo = breakout_levels(s[prev]) if prev else breakout_levels(s[today])
    so_far = s[today]
    return today, so_far, hi, lo, live_bars(symbol, lot, start_after=so_far[-1].time if so_far else None)
