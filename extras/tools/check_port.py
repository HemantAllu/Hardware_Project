#!/usr/bin/env python3
"""check_port.py - stimulus for tb_hft_port.v and checker against hft_model.PortfolioModel.

  python3 check_port.py gen ops.txt [seed] [n_max] [minutes_per_run]
  python3 check_port.py check log.txt [n_max]

The stimulus starts with directed cases (each proves one rule: ranking decides who buys,
rotation, rotation blocked by MIN_HOLD and by MARGIN, a win and a loss moving the weights, the
weight floor, the kill switch, the company cap, MAX_LOTS, an untraded company) and continues with
random runs that vary every setting: NUM_SYMBOLS, mode bits, MAX_LOTS, CAPSHIFT, cash, limits,
breakouts, MARGIN, MIN_HOLD, k, FLOOR, missing bars, zero volume, same-cycle ticks.

The checker replays the log in time order and compares after EVERY allocation: the codes, the
shared cash, and for every company the position, invested amount, weight, holding time and score;
for every tick the signal and the 5-cycle latency.  It also prints how often each rule fired so a
PASS cannot hide an untested path.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from hft_model import PortfolioModel, MODE_PORTFOLIO, NONE, BUY, SELL, ROT, W_TOTAL  # noqa: E402

LAT = 5


class Gen:
    def __init__(self):
        self.L = []

    def setup(self, n, mode, cash, max_lots=0, capshift=14, margin=1049, min_hold=5, wshift=3, wfloor=4096,
              limits=None, brks=None):
        self.L.append((4, n, mode, max_lots, capshift))
        for s in range(n):
            lim = limits[s] if limits else 1000
            hi, lo = brks[s] if brks else (150, 50)
            self.L.append((2, s, lim, hi, lo))
        self.L.append((5, margin, min_hold, wshift, wfloor))
        self.L.append((1, cash >> 32, cash & 0xFFFFFFFF, 0, 0))

    def minute(self, ticks, kill=0, same_cycle=True, dups=()):
        """ticks: list of (sym, price, vol).  dups: second ticks of a company in the same minute,
        sent 8 cycles after the first (its signal is out, its score division is still running)."""
        if same_cycle:
            for s, p, v in ticks:
                self.L.append((0, s, p, v, 0))
            self.L.append((3, 8, 0, 0, 0))
        else:
            for s, p, v in ticks:
                self.L.append((0, s, p, v, 0))
                self.L.append((3, 8, 0, 0, 0))
        for s, p, v in dups:
            self.L.append((0, s, p, v, 0))
            self.L.append((3, 8, 0, 0, 0))
        self.L.append((6, kill, 0, 0, 0))


FULL = 2 | 4 | 8          # rank + rotate + reweight (portfolio bit is implied by the testbench)


def directed(g, n_max):
    # Warm-up pattern: 4 rising prices make MA, VWAP and breakout (brk_high low) all vote BUY.
    # A: RANK. cash for one buy only; company 1 has the stronger momentum -> it buys, not company 0
    g.setup(2, 2, cash=1500, brks=[(50, 10), (50, 10)])
    for k in range(3):
        g.minute([(0, 100, 0), (1, 100, 0)])                  # volume 0: no trade, warms the MA
    g.minute([(0, 101, 10), (1, 110, 10)])                    # scores: company 1 >> company 0
    # B: ROTATION. company 0 holds (bought early), stalls; company 1 surges, cash short
    g.setup(2, 2 | 4, cash=1200, margin=1000, min_hold=2, brks=[(50, 10), (50, 10)])
    for k in range(3):
        g.minute([(0, 100, 0), (1, 100, 0)])
    g.minute([(0, 104, 10), (1, 100, 0)])                     # company 0 buys 10 for 1040
    g.minute([(0, 104, 0), (1, 100, 0)])
    g.minute([(0, 104, 0), (1, 100, 0)])                      # company 0 held 3 minutes, score ~0
    g.minute([(0, 104, 0), (1, 120, 9)])                      # company 1 BUY 1080 > cash 160 -> rotate 0
    # C: rotation BLOCKED by MIN_HOLD (same as B but MIN_HOLD 10)
    g.setup(2, 2 | 4, cash=1200, margin=1000, min_hold=10, brks=[(50, 10), (50, 10)])
    for k in range(3):
        g.minute([(0, 100, 0), (1, 100, 0)])
    g.minute([(0, 104, 10), (1, 100, 0)])
    g.minute([(0, 104, 0), (1, 100, 0)])
    g.minute([(0, 104, 0), (1, 120, 9)])
    # D: rotation BLOCKED by MARGIN (huge margin)
    g.setup(2, 2 | 4, cash=1200, margin=4000000, min_hold=0, brks=[(50, 10), (50, 10)])
    for k in range(3):
        g.minute([(0, 100, 0), (1, 100, 0)])
    g.minute([(0, 104, 10), (1, 100, 0)])
    g.minute([(0, 104, 0), (1, 120, 9)])
    # E: REWEIGHT win then loss, with the floor (k = 1 moves half a weight at a time)
    g.setup(2, FULL, cash=100000, wshift=1, wfloor=8192, brks=[(50, 10), (50, 10)])
    for k in range(3):
        g.minute([(0, 100, 0), (1, 100, 0)])
    g.minute([(0, 104, 10), (1, 104, 10)])                    # both buy
    g.minute([(0, 120, 5), (1, 90, 5)])                       # sell signals? (MA/VWAP) - may or may not
    for k in range(4):
        g.minute([(0, 120 + 8 * k, 0), (1, 90 - 8 * k, 0)])
    g.minute([(0, 40, 5), (1, 160, 5)])
    g.minute([(0, 30, 5), (1, 20, 5)])
    # F: KILL blocks everything
    g.setup(2, FULL, cash=100000, brks=[(50, 10), (50, 10)])
    for k in range(3):
        g.minute([(0, 100, 0), (1, 100, 0)])
    g.minute([(0, 104, 10), (1, 104, 10)], kill=1)
    g.minute([(0, 108, 10), (1, 108, 10)], kill=0)
    # G: CAP (capshift 15, cash 3000: each company may invest at most 1500) and MAX_LOTS 7
    g.setup(2, FULL, cash=3000, max_lots=7, capshift=15, brks=[(50, 10), (50, 10)])
    for k in range(3):
        g.minute([(0, 100, 0), (1, 100, 0)])
    for k in range(4):
        g.minute([(0, 104 + 4 * k, 20), (1, 104 + 4 * k, 20)])
    # I: holding time saturates at 255 (buy once, then 262 quiet minutes)
    g.setup(1, FULL, cash=100000, brks=[(50, 10)])
    for k in range(3):
        g.minute([(0, 100, 0)])
    g.minute([(0, 104, 10)])
    for k in range(262):
        g.minute([(0, 104, 0)])
    # J (N >= 4): two buyers short of cash, two possible victims -> only ONE rotation per minute
    if n_max >= 4:
        g.setup(4, 2 | 4, cash=2200, margin=0, min_hold=0, brks=[(50, 10)] * 4)
        for k in range(3):
            g.minute([(s, 100, 0) for s in range(4)])
        g.minute([(0, 104, 10), (1, 104, 10)] + [(s, 100, 0) for s in (2, 3)])   # 0 and 1 buy 1040 each
        g.minute([(0, 104, 0), (1, 104, 0), (2, 112, 10), (3, 106, 10)])          # 2 and 3 need 1120, 1060
    # I (v12): cash 2^64 - 1, buy 10 at 110, the price rises, SELL at 150: proceeds 1,500 > 1,100 spent,
    #    so the credit must saturate at 2^64 - 1 instead of wrapping
    g.setup(1, FULL, cash=(1 << 64) - 1, brks=[(5000, 1000)])
    for p, v in [(100, 10)] * 3 + [(110, 10)] + [(200, 0)] * 3 + [(150, 10)]:
        g.minute([(0, p, v)])
    # J (v12): score divider extremes - moving-average sum 0 (score must be 0), the largest
    #    positive score (1, 1, 1 then 0xFFFFFFFF: 4p - S = 3p - 3), the most negative one
    #    (three times 0xFFFFFFFF then 1), price 1 after them, and a second tick of the same
    #    company while its division is still running
    g.setup(1, FULL, cash=100000, brks=[(5000, 1000)])
    for p in [0, 0, 0, 0, 0, 1, 1, 1, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 1, 1, 2, 0xFFFFFFFE, 7]:
        g.minute([(0, p, 1)])
    g.minute([(0, 5, 1)], dups=[(0, 0xFFFFFFFF, 1)])
    g.minute([(0, 0xFFFFFFFF, 1)], dups=[(0, 3, 1)])
    # H: company 2.. not traded (NUM_SYMBOLS 1 while the ticks name company 1)
    g.setup(1, FULL, cash=100000, brks=[(50, 10)])
    for k in range(5):
        g.minute([(0, 100 + 3 * k, 5), (1, 100 + 3 * k, 5)] if n_max > 1 else [(0, 100 + 3 * k, 5)])


def boundary(g, rnd, n_max, runs=8, minutes=120):
    """Runs that sit ON the decision boundaries.  A copy of the model follows the stimulus, and
    before each ALLOCATE the live parameters are set to the exact value where a rule flips:
    MARGIN = the score gap between a holder and a buyer (rotation must NOT happen at equality),
    MIN_HOLD = the holder's holding time (rotation allowed at equality), FLOOR = a weight minus its
    transfer (allowed at equality).  Companies 0 and 1 often get identical prices (equal scores:
    the tie goes to the lower number), and one run per call makes a BUY cost EXACTLY the cap.
    Returns how many minutes each boundary actually decided (proved with a model copy)."""
    import copy
    hit = dict(margin=0, min_hold=0, floor=0, tie=0, cap=0)
    m = PortfolioModel(n_max)

    def setup(n, mode, cash, **kw):
        g.setup(n, mode, cash, **kw)
        m.nsym, m.mode_cfg, m.starting_cash = n, MODE_PORTFOLIO | mode, cash
        m.max_lots, m.capshift = kw.get('max_lots', 0), kw.get('capshift', 14)
        m.margin, m.min_hold, m.wshift, m.wfloor = (kw.get('margin', 1049), kw.get('min_hold', 5),
                                                     kw.get('wshift', 3), kw.get('wfloor', 4096))
        for s_ in range(n):
            e = m.engines[s_]
            e.pos_limit = kw['limits'][s_] if kw.get('limits') else 1000
            e.brk_high, e.brk_low = kw['brks'][s_] if kw.get('brks') else (150, 50)
        m.reset()

    def decides(attr, a, b):
        x, y = copy.deepcopy(m), copy.deepcopy(m)
        setattr(x, attr, a)
        setattr(y, attr, b)
        return x.allocate() != y.allocate() or x.w != y.w

    # cap equality: 2 companies, cap per company = (cash >> 14) * 16384 = cash; cost = 1024 * 1600
    cash = 16384 * 100
    setup(2, FULL, cash, limits=[5000, 5000], brks=[(50, 10), (50, 10)])
    for p_ in (1000, 1000, 1000):
        g.minute([(0, p_, 0), (1, p_, 0)])
        for s_ in (0, 1):
            m.tick(s_, p_, 0)
        m.allocate()
    g.minute([(0, 1024, 1600)])
    m.tick(0, 1024, 1600)
    if m.sig[0] == BUY:
        hit['cap'] += 1
    m.allocate()

    for r in range(runs):
        n = rnd.randint(2, n_max)
        p = [rnd.randint(80, 150) for _ in range(n)]
        brks = [(pp + rnd.randint(-10, 10), pp - rnd.randint(5, 30)) for pp in p]
        same = rnd.random() < 0.5
        if same:
            p[1], brks[1] = p[0], brks[0]
        setup(n, FULL, rnd.randint(1500, 5000), capshift=rnd.choice([13, 14]), margin=0, min_hold=0,
              wshift=rnd.choice([1, 2, 3]), wfloor=rnd.choice([0, 4096]), limits=[rnd.choice([40, 200])] * n, brks=brks)
        for t in range(minutes):
            ticks = []
            for s_ in range(n):
                p[s_] = min(300, max(10, p[s_] + rnd.randint(-5, 5)))
                ticks.append((s_, p[s_], rnd.randint(0, 20)))
            if same:
                ticks[1] = (1, ticks[0][1], ticks[0][2])
                p[1] = p[0]
            for s_, pp, vv in ticks:
                g.L.append((0, s_, pp, vv, 0))
                m.tick(s_, pp, vv)
            g.L.append((3, 8, 0, 0, 0))
            if same and m.sig[0] == BUY and m.score[0] == m.score[1] and m.vol[0] > 0:
                hit['tie'] += 1
            held = [j for j in range(n) if m.pos[j] > 0]
            buyers = [i for i in range(n) if m.fresh[i] and m.sig[i] == BUY]
            m.margin, m.min_hold = 0, 0
            # MARGIN is an unsigned 32-bit register: the boundary pair (d, d - 1) needs d >= 1
            # (v11 also tried d = 0, wrote MARGIN = -1 = 0xFFFFFFFF to the hardware and -1 to the
            # model, and failed for seeds other than 3)
            pairs = [(i, j) for i in buyers for j in held if m.score[i] - m.score[j] >= 1]
            rnd.shuffle(pairs)
            for i, j in pairs:                      # find the gap that decides this minute, if any
                d = m.score[i] - m.score[j]
                if decides('margin', d, d - 1):
                    hit['margin'] += 1
                    m.margin = d if rnd.random() < 0.5 else d - 1
                    break
            for j in held:
                if decides('min_hold', m.hold[j], m.hold[j] + 1):
                    hit['min_hold'] += 1
                    m.min_hold = m.hold[j] + rnd.randint(0, 1)
                    break
            m.wfloor = rnd.choice([0, 4096])
            for k in rnd.sample(range(n), n):
                f = m.w[k] - (m.w[k] >> m.wshift)
                if decides('wfloor', f, f + 1):
                    hit['floor'] += 1
                    m.wfloor = f + rnd.randint(0, 1)
                    break
            g.L.append((5, m.margin, m.min_hold, m.wshift, m.wfloor))
            g.L.append((6, 0, 0, 0, 0))
            m.allocate()
    return hit


def gen(path, seed=1, n_max=2, minutes=150, runs=6):
    rnd = random.Random(seed)
    g = Gen()
    directed(g, n_max)
    hit = boundary(g, rnd, n_max)
    print('boundaries that decided a minute:', hit)
    # v12: the last run starts just below 2^64, so SELL / rotation credits must saturate, not wrap
    for r in range(runs + 1):
        n = rnd.randint(1, n_max) if r % 3 else n_max
        mode = rnd.choice([FULL, FULL, 2, 2 | 4, 2 | 8, 4 | 8, 0])
        cash = rnd.choice([rnd.randint(1500, 6000), rnd.randint(8000, 40000), (1 << 32) + rnd.randint(0, 9999)])
        if r >= runs:
            cash, mode = (1 << 64) - rnd.randint(1, 5000), FULL
        lims = [rnd.choice([30, 60, 200, 1000]) for _ in range(n)]
        p = [rnd.randint(60, 200) for _ in range(n)]
        brks = [(pp + rnd.randint(-15, 15), pp - rnd.randint(10, 40)) for pp in p]
        g.setup(n, mode, cash, max_lots=rnd.choice([0, 0, 5, 12]), capshift=rnd.choice([13, 14, 14, 15]),
                margin=rnd.choice([0, 200, 1049, 5000]), min_hold=rnd.choice([0, 1, 2, 5]),
                wshift=rnd.choice([1, 2, 3, 4]), wfloor=rnd.choice([0, 2048, 4096, 9000]), limits=lims, brks=brks)
        drift = [rnd.choice([-1, 0, 1]) for _ in range(n)]
        for t in range(minutes):
            if t % 40 == 0:
                drift = [rnd.choice([-2, -1, 0, 1, 2]) for _ in range(n)]
            ticks = []
            for s in range(n_max):
                if s < n and rnd.random() < 0.9:
                    p[s] = min(400, max(5, p[s] + drift[s] + rnd.randint(-4, 4)))
                    ticks.append((s, p[s], 0 if rnd.random() < 0.04 else rnd.randint(1, 25)))
                elif s >= n and rnd.random() < 0.05:
                    ticks.append((s, 100, 5))                 # a company that is not traded
            dups = []
            if ticks and rnd.random() < 0.08:
                s, pp, vv = rnd.choice(ticks)
                if s < n:
                    p[s] = min(400, max(5, pp + rnd.randint(-6, 6)))
                    dups.append((s, p[s], rnd.randint(0, 25)))
            g.minute(ticks, kill=1 if rnd.random() < 0.02 else 0, same_cycle=rnd.random() < 0.7, dups=dups)
    with open(path, 'w') as f:
        for t in g.L:
            f.write('%d %d %d %d %d\n' % t)
    print('wrote %d ops (%d minutes) to %s' % (len(g.L), sum(1 for t in g.L if t[0] == 6), path))


def check(log_path, n_max=2):
    m = PortfolioModel(n_max)
    errs = 0
    n_alloc = n_sig = 0
    lat_bad = 0
    tot = dict(buys=0, sells=0, rotations=0, wins=0, losses=0, refused_cash=0, refused_cap=0, refused_limit=0,
               ranked=0)
    seen = dict(floor_hit=0, kill=0, untraded=0, codes_rot=0, nonzero_scores=0, alloc_lat=set())
    pending_sig = [None] * n_max
    last_alloc = None

    def fail(msg):
        nonlocal errs
        errs += 1
        if errs <= 25:
            print('  ' + msg)

    def flush_stats():
        for k in tot:
            tot[k] += m.stats.get(k, 0)

    for ln in open(log_path):
        a = ln.split()
        if not a:
            continue
        tag = a[0]
        if tag == 'CLEAR':
            flush_stats()
            cash, n, mode, ml, cs = (int(x) for x in a[1:6])
            m.nsym, m.mode_cfg, m.max_lots, m.capshift, m.starting_cash = n, MODE_PORTFOLIO | mode, ml, cs, cash
            m.reset()
        elif tag == 'CFG':
            s, lim, hi, lo = (int(x) for x in a[1:5])
            e = m.engines[s]
            e.pos_limit, e.brk_high, e.brk_low = lim, hi, lo
        elif tag == 'PARAM':
            # same widths as the hardware registers (MARGIN 32 bits, MIN_HOLD 8, K 5, FLOOR 16)
            mg, mh, ws, wf = (int(x) for x in a[1:5])
            m.margin, m.min_hold, m.wshift, m.wfloor = mg & 0xFFFFFFFF, mh & 0xFF, ws & 31, wf & 0xFFFF
        elif tag == 'TICK':
            s, p, v = (int(x) for x in a[1:4])
            p, v = p & 0xFFFFFFFF, v & 0xFFFFFFFF          # the testbench prints 32-bit values signed
            r = m.tick(s, p, v)
            pending_sig[s] = r
            if r is None:
                seen['untraded'] += 1
        elif tag == 'SIG':
            s, vote, lat = (int(x) for x in a[1:4])
            n_sig += 1
            if lat != LAT:
                lat_bad += 1
                fail('company %d: signal latency %d' % (s, lat))
            r = pending_sig[s]
            if r is not None and vote != r[0]:
                fail('company %d: signal %d, model %d' % (s, vote, r[0]))
        elif tag == 'ALLOC':
            kill, codes, cash, alat = (int(x) for x in a[1:5])
            n_alloc += 1
            seen['kill'] += kill
            seen['alloc_lat'].add(alat)
            mc = m.allocate(kill)
            exp = sum(c << (2 * i) for i, c in enumerate(mc))
            if codes != exp:
                fail('minute %d: codes %s, model %s' % (n_alloc, fmt(codes, n_max), fmt(exp, n_max)))
            if cash != m.cash:
                fail('minute %d: cash %d, model %d' % (n_alloc, cash, m.cash))
            seen['codes_rot'] += sum(1 for c in mc if c == ROT)
            last_alloc = n_alloc
        elif tag == 'ST':
            s, pos, inv, w, hold, sc = (int(x) for x in a[1:7])
            exp = (m.pos[s], m.inv[s], m.w[s], m.hold[s], m.score[s])
            if (pos, inv, w, hold, sc) != exp:
                fail('minute %d company %d: pos/inv/w/hold/score %s, model %s' % (last_alloc, s, (pos, inv, w, hold, sc), exp))
            if sc:
                seen['nonzero_scores'] += 1
            if s < m.nsym and m.nsym > 1 and w == m.wfloor and m.wfloor:
                seen['floor_hit'] += 1
            if s == m.nsym - 1 and sum(m.w[:m.nsym]) != W_TOTAL:
                fail('weights add up to %d' % sum(m.w[:m.nsym]))
    flush_stats()
    print('port (N=%d): %d minutes, %d signals, latency != 5: %d, mismatches: %d' % (n_max, n_alloc, n_sig, lat_bad, errs))
    print('  exercised: %d BUY, %d SELL, %d ROT, %d minutes where RANK changed the order, %d wins + %d losses '
          'reweighted, %d weight-floor hits, refused: cash %d, cap %d, limit %d; %d kill minutes, %d untraded '
          'ticks, %d nonzero scores, allocation latency %s cycles'
          % (tot['buys'], tot['sells'], tot['rotations'], tot['ranked'], tot['wins'], tot['losses'], seen['floor_hit'],
             tot['refused_cash'], tot['refused_cap'], tot['refused_limit'], seen['kill'], seen['untraded'],
             seen['nonzero_scores'], rng(seen['alloc_lat'])))
    ok = errs == 0 and n_alloc > 0 and tot['rotations'] > 0 and tot['ranked'] > 0 and tot['wins'] > 0 and tot['losses'] > 0
    if errs == 0 and not ok:
        print('  (the stimulus did not exercise every rule)')
    print('RESULT', 'PASS' if ok else 'FAIL')
    return ok


def fmt(codes, n):
    names = {NONE: '-', BUY: 'BUY', SELL: 'SELL', ROT: 'ROT'}
    return '[' + ' '.join(names[(codes >> (2 * i)) & 3] for i in range(n)) + ']'


def rng(s):
    return '%d..%d' % (min(s), max(s)) if s else '-'


if __name__ == '__main__':
    if sys.argv[1] == 'gen':
        gen(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1, int(sys.argv[4]) if len(sys.argv) > 4 else 2,
            int(sys.argv[5]) if len(sys.argv) > 5 else 150)
    else:
        sys.exit(0 if check(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2) else 1)
