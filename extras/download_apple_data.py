"""download_apple_data.py - kept for older instructions; same as download_market_data.py
(which works for any company):  python download_apple_data.py [--company nvidia] [--out file.csv]
Without --out it now writes <TICKER>_ticks.csv (AAPL_ticks.csv for Apple)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import download_market_data  # noqa: E402

if __name__ == '__main__':
    download_market_data.main(default_company='apple')
