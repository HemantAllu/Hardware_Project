#!/usr/bin/env python3
"""check_cash.py - generator + checker for tb_hft_cash.v (accelerator risk-interlock test).

  python3 check_cash.py gen ops.txt [seed] [runs]     random runs with random cash / limit / breakout
  python3 check_cash.py check ops.txt log             compare decision, position AND cash of every
                                                      tick with the Python reference model
The generator mixes: starting cash from 0 to 2**40 (so cash refusals, 64-bit cash and the
HIGH word are exercised), position limits from 1 to 100000, zero-volume and huge-volume
ticks, kill switch ticks and back-to-back tick pairs (the accelerator's 1-entry buffer).
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from hft_model import HFTModel  # noqa: E402

CASHES = [0, 1, 5000, 30000, 100000, 1000000, (1 << 32) - 1, 1 << 32, (1 << 32) + 12345, (5 << 32) + 77, 2 ** 40]
LIMITS = [1, 50, 300, 1000, 5000, 100000]
BRKS = [(120, 80), (110, 90), (150, 50), (100, 100), (25400, 24800)]


def gen(path, seed=1, runs=60):
    rnd = random.Random(seed)
    ops = []

    def one_run(cash, lim, bh, bl):
        ops.append((1, cash >> 32, cash & 0xFFFFFFFF, lim, 0))
        ops.append((2, bh, bl, 0, 0))
        big = bh > 1000
        p = 25100 if big else 100
        n, i = rnd.randint(40, 120), 0
        while i < n:
            p = max(1, p + rnd.choice([-9, -4, -2, 0, 2, 4, 9]) * (20 if big else 1))
            v = rnd.choice([1, 2, 10, 50, 160, 300, 900, 5000]) if rnd.random() < 0.88 else rnd.choice([0, 0, 2 ** 31, 2 ** 32 - 1])
            kill = 1 if rnd.random() < 0.05 else 0
            if rnd.random() < 0.12 and i + 1 < n:
                # a back-to-back pair (second tick one cycle after the first); same kill value for both
                p2 = max(1, p + rnd.choice([-4, 0, 4]) * (20 if big else 1))
                v2 = rnd.choice([1, 10, 160, 900])
                ops.append((0, p, v, kill, 1))
                ops.append((0, p2, v2, kill, 0))
                p, i = p2, i + 2
            else:
                ops.append((0, p, v, kill, 0))
                i += 1

    for _ in range(runs):
        cash, lim, (bh, bl) = rnd.choice(CASHES), rnd.choice(LIMITS), rnd.choice(BRKS)
        one_run(cash, lim, bh, bl)
    # v12: runs that start just below 2^64 and where a SELL really pushes the balance past the top
    # (found with the model): the hardware must saturate at 2^64 - 1 instead of wrapping
    found, tries = 0, 0
    while found < 4 and tries < 2000:
        tries += 1
        start = len(ops)
        one_run((1 << 64) - rnd.randint(1, 2000), rnd.choice([300, 1000, 5000]), 120, 80)
        m = HFTModel()
        m.starting_cash, m.pos_limit = (ops[start][1] << 32) | ops[start][2], ops[start][3]
        m.brk_high, m.brk_low = ops[start + 1][1], ops[start + 1][2]
        m.reset()
        sat = False
        for o in ops[start + 2:]:
            before = m.cash
            if m.step(o[1], o[2], o[3]) == 2 and before + o[1] * o[2] > (1 << 64) - 1:
                sat = True
        if sat:
            found += 1
        else:
            del ops[start:]
    print('runs with a saturating SELL: %d' % found)
    with open(path, 'w') as f:
        for o in ops:
            f.write('%d %d %d %d %d\n' % o)
    print('wrote %d ops to %s' % (len(ops), path))


def check(ops_path, log_path):
    ops = [tuple(map(int, ln.split())) for ln in open(ops_path) if ln.strip()]
    decs = [tuple(map(int, ln.split()[1:])) for ln in open(log_path) if ln.startswith('DEC')]
    m = HFTModel()
    tot = dict(blocked_cash=0, blocked_limit=0, blocked_nostock=0, zero_vol=0)
    k = bad = nbuy = nsell = 0
    lat_bad = 0

    def flush():
        for key in tot:
            tot[key] += getattr(m, key)

    for o in ops:
        if o[0] == 1:
            flush()
            m.starting_cash, m.pos_limit = (o[1] << 32) | o[2], o[3]
            m.reset()
        elif o[0] == 2:
            m.brk_high, m.brk_low = o[1], o[2]
        else:
            _, p, v, kill, _burst = o
            d = m.step(p, v, kill)
            if k >= len(decs):
                bad += 1
                k += 1
                continue
            _seq, dec, lat, pos, cash = decs[k]
            if (dec, pos, cash) != (d, m.pos, m.cash):
                bad += 1
                if bad <= 10:
                    print('MISMATCH tick #%d price %d vol %d: RTL dec %d pos %d cash %d | model dec %d pos %d cash %d'
                          % (k, p, v, dec, pos, cash, d, m.pos, m.cash))
            if not 5 <= lat <= 10:
                lat_bad += 1
            nbuy += d == 1
            nsell += d == 2
            k += 1
    flush()
    print('ticks %d, decisions in log %d, mismatches %d, latency outside 5..10 cycles: %d' % (k, len(decs), bad, lat_bad))
    print('model: %d BUY, %d SELL | signals blocked: cash %d, position limit %d, nothing to sell %d, zero volume %d'
          % (nbuy, nsell, tot['blocked_cash'], tot['blocked_limit'], tot['blocked_nostock'], tot['zero_vol']))
    ok = bad == 0 and lat_bad == 0 and k == len(decs) and tot['blocked_cash'] > 0 and tot['zero_vol'] > 0 and nbuy > 0 and nsell > 0
    if ok is False and bad == 0 and k == len(decs):
        print('(the random stream did not cover every path: cash refusals, zero volume, BUY and SELL)')
    print('RESULT', 'PASS' if ok else 'FAIL')
    return ok


if __name__ == '__main__':
    if sys.argv[1] == 'gen':
        gen(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1, int(sys.argv[4]) if len(sys.argv) > 4 else 60)
    else:
        sys.exit(0 if check(sys.argv[2], sys.argv[3]) else 1)
