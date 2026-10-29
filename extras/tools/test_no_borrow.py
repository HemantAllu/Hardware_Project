#!/usr/bin/env python3
"""Focused regression for the trading rules of the Python reference model
(the same rules are implemented in hft_accelerator.v and hft_firmware.c):
  * cash interlock: an underfunded BUY and an unheld SELL are rejected, balances never go negative
  * exact moving-average compare (no rounding of the average)
  * a zero-volume tick never trades
  * the blocked-signal counters used by the dashboard warnings
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hft_model import BUY, NONE, SELL, HFTModel


def force_buy(model, price, vol):
    # Seed a prior VWAP below the price; it and breakout vote BUY.
    model.spv, model.sv = 1, 1
    return model.step(price, vol)


def force_sell(model, price, vol):
    # Seed a prior VWAP above the price; it and breakout vote SELL.
    model.spv, model.sv = 1000, 1
    return model.step(price, vol)


def test_cash_and_inventory():
    # $100 in model units: a 60-unit buy fills, then an 80-unit buy is rejected.
    m = HFTModel(pos_limit=1000, brk_high=0, brk_low=0, starting_cash=100)
    assert force_buy(m, 6, 10) == BUY
    assert (m.cash, m.pos) == (40, 10)
    assert force_buy(m, 8, 10) == NONE
    assert (m.cash, m.pos) == (40, 10)
    assert m.blocked_cash == 1

    # No holding means no sell.  A valid sale returns cash, never a negative position.
    s = HFTModel(pos_limit=1000, brk_high=999999, brk_low=100)
    assert force_sell(s, 10, 5) == NONE
    assert (s.cash, s.pos) == (1000000, 0)
    assert s.blocked_nostock == 1
    s.pos = 5
    assert force_sell(s, 10, 5) == SELL
    assert s.pos == 0 and s.cash == 1000050

    # position limit
    p = HFTModel(pos_limit=15, brk_high=0, brk_low=0, starting_cash=10 ** 9)
    assert force_buy(p, 6, 10) == BUY
    assert force_buy(p, 6, 10) == NONE and p.pos == 10 and p.blocked_limit == 1

    # equity = cash + holdings at the current price
    assert p.equity(7) == p.cash + 10 * 7


def test_exact_moving_average():
    # Earlier ticks 100, 100, 101 (most recent first: 101, 100, 100) and a new price of 100:
    # sum = 401, true average 100.25, so the price is BELOW the average -> MA votes SELL.
    # Breakout-low (100 < 200) votes SELL too; VWAP is neutral on the first tick of the sums.
    # Two SELL votes -> SELL.  With the old rounded-down average (100) the MA vote was
    # missing and the tick did not trade.
    g = HFTModel(pos_limit=10 ** 6, brk_high=10 ** 9, brk_low=200, starting_cash=10 ** 12)
    g.hist, g.warm, g.pos = [101, 100, 100], 3, 5
    assert g.step(100, 1) == SELL
    # mirror case: 101, 101, 100 then 101 -> sum 403, 4*101 = 404 > 403 -> MA votes BUY
    h = HFTModel(pos_limit=10 ** 6, brk_high=50, brk_low=0, starting_cash=10 ** 12)
    h.hist, h.warm = [100, 101, 101], 3
    assert h.step(101, 1) == BUY


def test_zero_volume():
    # BUY signal (VWAP + breakout) on a zero-volume tick: no trade, counted as zero_vol
    m = HFTModel(pos_limit=1000, brk_high=0, brk_low=0, starting_cash=1000)
    assert force_buy(m, 6, 0) == NONE
    assert (m.cash, m.pos, m.zero_vol) == (1000, 0, 1)
    # SELL signal (VWAP + breakout-low) on a zero-volume tick while holding: no trade either
    s = HFTModel(pos_limit=1000, brk_high=999999, brk_low=100, starting_cash=1000)
    s.pos = 3
    assert force_sell(s, 6, 0) == NONE
    assert (s.cash, s.pos, s.zero_vol) == (1000, 3, 1)


def main():
    test_cash_and_inventory()
    test_exact_moving_average()
    test_zero_volume()
    print('PASS: cash/inventory interlock, exact moving average, zero-volume rule, blocked-signal counters')


if __name__ == '__main__':
    main()
