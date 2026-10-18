#!/usr/bin/env python3
"""check_hft.py - reference model for the trading accelerator + checker for tb_hft.

  python3 check_hft.py gen ticks.txt            write the system-test tick stream
  python3 check_hft.py check ticks.txt log      compare a tb_hft log with the model
  python3 check_hft.py genrand rand.txt         random ticks for the accelerator unit test
  python3 check_hft.py unit rand.txt log        compare a tb_hft_unit log with the model
  python3 check_hft.py genburst burst.txt       5 setup commands + 14 back-to-back ticks
  python3 check_hft.py checkburst burst.txt log compare a tb_hft +NOWAIT=5 log (packets must be
                                                dropped for hardware AND software alike)
  python3 check_hft.py genmulti multi.txt       2-company system-test stream (shared cash, caps,
                                                per-company config, a tick for an untraded company)
  python3 check_hft.py fromlog run.csv ticks.txt  turn a dashboard log (+ its .cfg) into a tb_hft tick
                                                file: the same RESET/config commands and the same ticks,
                                                so a real-data run (any company) can be replayed in the
                                                RTL simulation and checked with 'check' ('checkport' for
                                                a --together run with the hardware allocator)
  python3 check_hft.py genport port.txt         portfolio-mode system test (ticks + ALLOCATE every minute)
  python3 check_hft.py checkport port.txt log   compare a tb_hft log of it with hft_model.PortfolioModel

Model (what hft_accelerator.v and hft_firmware.c must both do, per tick):
  MA(4)    : sum = p + p[-1] + p[-2] + p[-3], only after 3 earlier ticks
             BUY vote if 4*p > sum, SELL vote if 4*p < sum (exact, no rounding)
  VWAP     : running sums including this tick; BUY if p*sumV > sumPV, SELL if <
  Breakout : BUY if p > BRK_HIGH, SELL if p < BRK_LOW
  Vote     : BUY if >= 2 buy votes, else SELL if >= 2 sell votes, else NONE
  Risk     : kill switch -> NONE; volume 0 -> NONE; BUY blocked if pos + vol > POS_LIMIT;
             BUY also blocked when cash < price*vol; SELL blocked if pos < vol
             (no shorting); cash and position never become negative
  Latency  : hardware reports 5 cycles (data_valid to decision)
"""
import os
import random
import sys

POS_LIMIT, BRK_HIGH, BRK_LOW = 1000, 150, 50
HW_LATENCY = 5
M32 = (1 << 32) - 1

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from hft_model import (HFTModel, MultiModel, PortfolioModel, CMD_RESET, CMD_CFG_BRK, CMD_CFG_LIMIT,  # noqa: E402
                       CMD_CFG_CASH, CMD_CFG_NSYM, CMD_CFG_CAP, CMD_ALLOCATE, CMD_CFG_MODE, CMD_CFG_ROT, CMD_CFG_W,
                       MODE_PORTFOLIO, ROT, sym_of, cmd_of, with_sym)

# engines built into the simulated soc_top (HFT_N_MAX); the model clamps NUM_SYMBOLS to it
HW_NMAX = int(os.environ.get('HFT_N_MAX', '2'))

COUNTERS = ('blocked_limit', 'blocked_cash', 'blocked_nostock', 'zero_vol')


def model(ticks, stats=None):
    """Expected (decision, reported position) per line; decision None for a command and
    'skip' for a tick of a company that is not traded (the firmware reports zeros).
    Ticks: (id, price, vol, kill).  Uses MultiModel; with one company (the default) it is
    exactly the single-company model.  stats: optional dict that receives how often each
    kind of signal was blocked (summed over all runs)."""
    m, out = MultiModel(HW_NMAX), []
    tot = dict.fromkeys(COUNTERS + ('blocked_cap',), 0)

    def flush():
        for k in COUNTERS:
            tot[k] += sum(getattr(e, k) for e in m.engines)
        tot['blocked_cap'] += m.blocked_cap

    for tid, p, v, kill in ticks:
        c = sym_of(tid)
        if tid & 0x80000000:
            if tid == CMD_RESET:
                flush()                          # reset() clears the counters
            m.command(tid, p, v)
            # the report of CFG_NSYM carries the number of companies now traded
            out.append((None, m.nsym if cmd_of(tid) == CMD_CFG_NSYM else m.pos(c)))
        elif c >= m.nsym:
            out.append(('skip', 0))
        else:
            out.append((m.step(c, p, v, kill), m.pos(c)))
    flush()
    if stats is not None:
        stats.update(tot)
    return out


def gen(path, seed=19):
    """Tick stream for tb_hft: reset + config, a run, a re-config + reset, a second run
    (AAPL scale, default cash), then three runs with explicit starting cash:
    small cash (large buys must be refused), cash that needs the HIGH 32-bit word, and
    AAPL scale with enough cash.  Some ticks have volume 0."""
    rnd = random.Random(seed)
    ticks, p = [(CMD_RESET, 0, 0, 0), (CMD_CFG_BRK, 150, 50, 0), (CMD_CFG_LIMIT, 1000, 0, 0)], 100
    plan = ([+3] * 12 + [+6] * 8 + [0] * 4 + [-12] * 10 + [-4] * 6 + [+5] * 12 + [rnd.randint(-8, 8) for _ in range(28)])
    for i, step in enumerate(plan):
        p = max(5, p + step + rnd.randint(-2, 2))
        ticks.append((i + 1, p, rnd.randint(20, 160), 1 if 22 <= i <= 25 else 0))
    # second run with AAPL-like prices in cents and volumes in lots, after a reset
    ticks += [(CMD_CFG_BRK, 25400, 24800, 0), (CMD_CFG_LIMIT, 5000, 0, 0), (CMD_RESET, 0, 0, 0)]
    p = 25100
    for i in range(40):
        p += rnd.randint(-60, 60)
        ticks.append((1000 + i, p, rnd.randint(50, 900), 0))

    nid = [3000]

    def run(cash, hi, lo, limit, n, p0, step, vmax, zero_every=0):
        ticks.append((CMD_CFG_BRK, hi, lo, 0))
        ticks.append((CMD_CFG_LIMIT, limit, 0, 0))
        ticks.append((CMD_CFG_CASH, cash & M32, cash >> 32, 0))
        ticks.append((CMD_RESET, 0, 0, 0))
        q = p0
        for i in range(n):
            q = max(5, q + rnd.choice([-3, -2, -1, 0, 1, 2, 3, 6]) * step)
            v = 0 if (zero_every and i % zero_every == zero_every - 1) else rnd.randint(1, vmax)
            nid[0] += 1
            ticks.append((nid[0], q, v, 0))

    run(30000, 120, 80, 1000, 70, 100, 1, 160, zero_every=17)             # small cash: big buys refused
    run((1 << 32) + 500, 120, 80, 1000, 60, 100, 1, 160)                   # cash needs the HIGH word
    run(2000000, 25400, 24800, 5000, 60, 25100, 60, 900, zero_every=23)    # AAPL scale, cash for ~80 lots
    # v12: VWAP volume sum overflow - hardware and firmware must both switch the VWAP rule off
    ticks += [(CMD_CFG_BRK, 110, 90, 0), (CMD_CFG_LIMIT, 0xFFFFFFFF, 0, 0),
              (CMD_CFG_CASH, 0, 1 << 30, 0), (CMD_RESET, 0, 0, 0)]
    q = 100
    for i in range(45):
        q = max(5, q + rnd.choice([-6, -3, -1, 0, 1, 3, 6]))
        nid[0] += 1
        ticks.append((nid[0], q, 0x60000000 if 3 <= i <= 5 else rnd.randint(1, 200), 0))
    with open(path, 'w') as f:
        for t in ticks:
            f.write('%08x %d %d %d\n' % t)
    st = {}
    exp = model(ticks, st)
    ds = [d for d, _ in exp if d is not None]
    print('wrote %d lines to %s (model: %d BUY, %d SELL; blocked: cash %d, limit %d, nostock %d, zero-volume %d)'
          % (len(ticks), path, ds.count(1), ds.count(2), st['blocked_cash'], st['blocked_limit'],
             st['blocked_nostock'], st['zero_vol']))


def gen_multi(path, seed=23):
    """2-company system test: NUM_SYMBOLS = 2, per-company breakout/limit/cap, one shared cash
    account that runs out, ticks of the two companies interleaved minute by minute (company 0
    first), a tick for company 2 (not traded: zeros), a CFG for company 5 (not built: ignored),
    then back to NUM_SYMBOLS = 1 for a few single-company ticks."""
    rnd = random.Random(seed)
    L = [(CMD_RESET, 0, 0, 0), (CMD_CFG_NSYM, 3, 0, 0), (CMD_CFG_NSYM, 2, 0, 0)]   # 3 > N_MAX = 2: clamped
    cfg = {0: (25150, 25050, 400, 0), 1: (12930, 12870, 400, 900000)}     # AAPL-like, NVDA-like (cap on 1)
    for c, (hi, lo, lim, cap) in cfg.items():
        L += [(with_sym(CMD_CFG_BRK, c), hi, lo, 0), (with_sym(CMD_CFG_LIMIT, c), lim, 0, 0),
              (with_sym(CMD_CFG_CAP, c), cap & M32, cap >> 32, 0)]
    L += [(with_sym(CMD_CFG_BRK, 5), 1, 1, 0)]                               # company 5 is not built
    cash = 4000000
    L += [(CMD_CFG_CASH, cash & M32, cash >> 32, 0), (CMD_RESET, 0, 0, 0)]
    p = [25100, 12900]
    for i in range(70):
        for c in (0, 1):
            p[c] += rnd.randint(-70, 70) if c == 0 else rnd.randint(-40, 40)
            v = 0 if i % 29 == 28 else rnd.randint(5, 60)
            L.append((with_sym(i + 1, c), p[c], v, 1 if 40 <= i <= 42 else 0))
        if i == 35:
            L.append((with_sym(9999, 2), 100, 10, 0))                      # company 2: NUM_SYMBOLS is 2
    L += [(CMD_CFG_NSYM, 1, 0, 0)]
    for i in range(10):
        p[0] += rnd.randint(-70, 70)
        L.append((500 + i, p[0], rnd.randint(5, 60), 0))
    L.append((with_sym(600, 1), p[1], 50, 0))                                 # company 1 now untraded
    with open(path, 'w') as f:
        for t in L:
            f.write('%08x %d %d %d\n' % t)
    st = {}
    ds = [d for d, _ in model(L, st)]
    print('wrote %d lines to %s (model: %d BUY, %d SELL; blocked: cash %d, cap %d, limit %d, nostock %d)'
          % (len(L), path, ds.count(1), ds.count(2), st['blocked_cash'], st['blocked_cap'],
             st['blocked_limit'], st['blocked_nostock']))


def gen_burst(path):
    """5 setup commands (sent one at a time) + 14 rising-price ticks that the test sends back to
    back.  Every accepted tick is a BUY of 10 lots, so a lost tick is visible in the position."""
    L = [(CMD_RESET, 0, 0, 0), (CMD_CFG_BRK, 150, 50, 0), (CMD_CFG_LIMIT, 1000, 0, 0),
         (CMD_CFG_CASH, 10 ** 9 & M32, 10 ** 9 >> 32, 0), (CMD_RESET, 0, 0, 0)]
    for i in range(14):
        L.append((i + 1, 200 + 3 * i, 10, 0))
    with open(path, 'w') as f:
        for t in L:
            f.write('%08x %d %d %d\n' % t)
    print('wrote %d lines to %s' % (len(L), path))


def from_log(log_path, out_path):
    import csv
    cfg = dict(ln.strip().split('=', 1) for ln in open(log_path + '.cfg') if '=' in ln)
    cash = int(cfg['starting_cash_units'])
    if cfg.get('mode') == 'hybrid':                  # hardware portfolio allocator (hft_hybrid.py log)
        n = int(cfg['nsym'])
        L = [(CMD_RESET, 0, 0, 0), (CMD_CFG_NSYM, n, 0, 0)]
        for c in range(n):
            L += [(with_sym(CMD_CFG_BRK, c), int(cfg['brk_high_%d' % c]), int(cfg['brk_low_%d' % c]), 0),
                  (with_sym(CMD_CFG_LIMIT, c), int(cfg['pos_limit_%d' % c]), 0, 0)]
        L += [(CMD_CFG_MODE, int(cfg['port_mode']), int(cfg['max_lots']), 0),
              (CMD_CFG_ROT, int(cfg['margin']), int(cfg['min_hold']), 0),
              (CMD_CFG_W, int(cfg['wshift']) | (int(cfg['capshift']) << 8), int(cfg['wfloor']), 0),
              (CMD_CFG_CASH, cash & M32, cash >> 32, 0), (CMD_RESET, 0, 0, 0)]
        for r in csv.DictReader(open(log_path)):
            if r['kind'] == 'tick':
                L.append((int(r['tick_id'], 16), int(r['price_sent']), int(r['vol_sent']), 0))
            else:
                L.append((CMD_ALLOCATE, int(r['minute']) + 1, 0, int(r['kill'])))
        label = cfg.get('symbols', '')
    elif cfg.get('mode') == 'portfolio':               # several companies traded --together
        n = int(cfg['nsym'])
        L = [(CMD_RESET, 0, 0, 0), (CMD_CFG_NSYM, n, 0, 0)]
        for c in range(n):
            cap = int(cfg.get('cap_units_%d' % c, 0))
            L += [(with_sym(CMD_CFG_BRK, c), int(cfg['brk_high_%d' % c]), int(cfg['brk_low_%d' % c]), 0),
                  (with_sym(CMD_CFG_LIMIT, c), int(cfg['pos_limit_%d' % c]), 0, 0),
                  (with_sym(CMD_CFG_CAP, c), cap & M32, cap >> 32, 0)]
        L += [(CMD_CFG_CASH, cash & M32, cash >> 32, 0), (CMD_RESET, 0, 0, 0)]
        for r in csv.DictReader(open(log_path)):
            L.append((int(r['tick_id'], 16), int(r['price_sent']), int(r['vol_sent']), 0))
        label = cfg.get('symbols', '')
    else:
        L = [(CMD_RESET, 0, 0, 0), (CMD_CFG_BRK, int(cfg['brk_high']), int(cfg['brk_low']), 0),
             (CMD_CFG_LIMIT, int(cfg['pos_limit']), 0, 0), (CMD_CFG_CASH, cash & M32, cash >> 32, 0), (CMD_RESET, 0, 0, 0)]
        for r in csv.DictReader(open(log_path)):
            L.append((int(r['tick']), int(r['price_sent']), int(r['vol_sent']), 0))
        label = cfg.get('symbol', '')
    with open(out_path, 'w') as f:
        for t in L:
            f.write('%08x %d %d %d\n' % t)
    print('wrote %d lines (%s %s) to %s' % (len(L), label, os.path.basename(log_path), out_path))


# ----------------------------------------------------------------------------- portfolio mode
class SysModel:
    """What the whole board (hardware + firmware) must report, in both modes: MultiModel while
    PORT_MODE bit0 is off (the reset state), PortfolioModel after a RESET with it on."""

    def __init__(self, n_max=HW_NMAX):
        self.ind = MultiModel(n_max)
        self.port = PortfolioModel(n_max)
        self.port.mode_cfg = self.port.mode = 0          # hardware reset value: independent engines
        self.n_max = n_max

    @property
    def port_on(self):
        return bool(self.port.mode & MODE_PORTFOLIO)

    def line(self, tid, p, v, kill):
        """Returns (kind, expected fields): kind 'cmd' (position slot), 'skip', 'tick'
        (independent: decision, position), 'ptick' (vote, score), 'alloc' (codes, kill, cash,
        checksum)."""
        c = sym_of(tid)
        if tid & 0x80000000:
            if tid == CMD_ALLOCATE:
                if not self.port_on:
                    return 'alloc_off', None
                codes = self.port.allocate(kill)
                packed = sum(x << (2 * i) for i, x in enumerate(codes))
                return 'alloc', (packed, kill, self.port.cash, self.port.checksum())
            self.ind.command(tid, p, v)
            self.port.command(tid, p, v)
            cmd = cmd_of(tid)
            if cmd == CMD_CFG_NSYM:
                return 'cmd', self.ind.nsym
            if cmd == CMD_CFG_MODE:
                return 'cmd', (self.port.mode << 4) | self.port.mode_cfg
            if self.port_on:
                return 'cmd', self.port.pos[c] if c < self.n_max else 0
            return 'cmd', self.ind.pos(c)
        if c >= self.ind.nsym:
            return 'skip', None
        if self.port_on:
            sig, score = self.port.tick(c, p, v)
            return 'ptick', (sig, score)
        return 'tick', (self.ind.step(c, p, v, kill), self.ind.pos(c))


def gen_port(path, seed=33):
    """Portfolio-mode system test.  Run 1: 2 companies, full mode (rank + rotate + reweight),
    cash for about two buys, MIN_HOLD 2, MARGIN 500, 90 minutes incl. 3 kill minutes, a minute
    without company 1, a tick for company 2 (not traded).  Run 2: rank only, MAX_LOTS 20,
    K 2, CAPSHIFT 15, FLOOR 6000, cash above 2^32.  Run 3: back to the independent engines."""
    rnd = random.Random(seed)
    L = [(CMD_RESET, 0, 0, 0), (CMD_CFG_NSYM, 2, 0, 0)]
    cfg = {0: (25150, 25050, 100), 1: (12930, 12870, 200)}
    for c, (hi, lo, lim) in cfg.items():
        L += [(with_sym(CMD_CFG_BRK, c), hi, lo, 0), (with_sym(CMD_CFG_LIMIT, c), lim, 0, 0)]
    L += [(CMD_CFG_MODE, 15, 0, 0), (CMD_CFG_ROT, 500, 2, 0), (CMD_CFG_W, 3 | (14 << 8), 4096, 0)]
    cash = 1500000
    L += [(CMD_CFG_CASH, cash & M32, cash >> 32, 0), (CMD_RESET, 0, 0, 0)]
    p = [25100, 12900]
    drift = [0, 0]
    for i in range(90):
        if i % 15 == 0:
            drift = [rnd.choice([-30, 0, 30]), rnd.choice([-20, 0, 20])]
        for c in (0, 1):
            if c == 1 and i == 20:
                continue                                                # company 1 has no bar
            p[c] += drift[c] + (rnd.randint(-70, 70) if c == 0 else rnd.randint(-40, 40))
            v = 0 if i % 29 == 28 else rnd.randint(5, 60)
            L.append((with_sym(i + 1, c), p[c], v, 0))
        if i == 35:
            L.append((with_sym(9999, 2), 100, 10, 0))                  # company 2 is not traded
        L.append((CMD_ALLOCATE, i + 1, 0, 1 if 40 <= i <= 42 else 0))
    big = (1 << 32) + 777
    L += [(CMD_CFG_MODE, 3, 20, 0), (CMD_CFG_W, 2 | (15 << 8), 6000, 0), (CMD_CFG_CASH, big & M32, big >> 32, 0),
          (CMD_RESET, 0, 0, 0)]
    for i in range(40):
        for c in (1, 0):                                               # order of arrival does not matter
            p[c] += rnd.randint(-60, 60)
            L.append((with_sym(200 + i, c), p[c], rnd.randint(1, 90), 0))
        L.append((CMD_ALLOCATE, 200 + i, 0, 0))
    L += [(CMD_CFG_MODE, 0, 0, 0), (CMD_RESET, 0, 0, 0)]
    for i in range(12):
        for c in (0, 1):
            p[c] += rnd.randint(-60, 60)
            L.append((with_sym(400 + i, c), p[c], rnd.randint(5, 60), 0))
    with open(path, 'w') as f:
        for t in L:
            f.write('%08x %d %d %d\n' % t)
    m, tot = SysModel(), {}
    for t in L:
        if t[0] == CMD_RESET:
            for k, v in m.port.stats.items():
                tot[k] = tot.get(k, 0) + v
        m.line(*t)
    for k, v in m.port.stats.items():
        tot[k] = tot.get(k, 0) + v
    print('wrote %d lines to %s (model: %d BUY, %d SELL, %d ROT, %d wins + %d losses reweighted, %d refused for cash, '
          '%d for the cap)' % (len(L), path, tot['buys'], tot['sells'], tot['rotations'], tot['wins'], tot['losses'],
                               tot['refused_cash'], tot['refused_cap']))


def check_port_sys(tick_path, log_path):
    ticks = read_ticks(tick_path)
    lines = open(log_path).read().splitlines()
    reps = [ln.split()[1:] for ln in lines if ln.startswith('REPORT')]
    errs = sum(1 for ln in lines if ln.startswith('TICK'))
    if len(reps) != len(ticks):
        print('  %d reports for %d lines' % (len(reps), len(ticks)))
        errs += 1
    ov = [ln.split() for ln in lines if ln.startswith('OVERRUN')]
    if not ov or int(ov[0][1]) != 0:
        print('  OVERRUN missing or not 0')
        errs += 1
    elif int(ov[0][3], 16) & 0x4:
        print('  LED2 (HW/SW mismatch) is on at the end')
        errs += 1
    m = SysModel()
    n = dict(alloc=0, ptick=0, tick=0, rot=0)
    alat, slat, tlat = [], [], []

    def s32(x):
        return x - (1 << 32) if x >= 1 << 31 else x

    for (tid, p, v, kill), r in zip(ticks, reps):
        kind, e = m.line(tid, p, v, kill)
        rid, rp, rv, hwd, hwl, swd, swl, hwp = int(r[0], 16), *[int(x) for x in r[1:]]
        bad = []
        if kind == 'alloc':
            codes, k, cash, chk = e
            n['alloc'] += 1
            n['rot'] += sum(1 for i in range(8) if (codes >> (2 * i)) & 3 == ROT)
            alat.append(hwl)
            slat.append(swl)
            # proven bound of hft_alloc.v (v12) when no score division is pending, which is always
            # the case here: the firmware answers a tick only after its score is done
            lat_bound = 8 + 12 * m.port.nsym
            if hwl > lat_bound:
                bad.append('allocation took %d cycles, bound 8 + 12*%d = %d' % (hwl, m.port.nsym, lat_bound))
            if rid != CMD_ALLOCATE:
                bad.append('id %08x' % rid)
            if hwd & (1 << 31):
                bad.append('firmware flags a HW/SW difference')
            if hwd & 0xFFFF != codes or (hwd >> 16) & 1 != k:
                bad.append('HW codes %x kill %d, model %x kill %d' % (hwd & 0xFFFF, (hwd >> 16) & 1, codes, k))
            if swd != codes:
                bad.append('SW codes %x, model %x' % (swd, codes))
            if rp | (rv << 32) != cash:
                bad.append('cash %d, model %d' % (rp | (rv << 32), cash))
            if hwp != chk:
                bad.append('checksum %08x, model %08x' % (hwp, chk))
        else:
            if (rid, rp, rv) != (tid, p, v):
                bad.append('echo %x/%d/%d' % (rid, rp, rv))
            if kind == 'cmd' or kind == 'skip':
                exp_pos = e if kind == 'cmd' else 0
                if (hwd, hwl, swd, swl) != (0, 0, 0, 0) or hwp != exp_pos:
                    bad.append('report %d %d %d %d pos %d, expected zeros pos %d' % (hwd, hwl, swd, swl, hwp, exp_pos))
            elif kind == 'ptick':
                n['ptick'] += 1
                sig, score = e
                tlat.append(swl)
                if hwd != sig or swd != sig or hwl != HW_LATENCY or s32(hwp) != score:
                    bad.append('vote HW %d SW %d lat %d score %d, model vote %d score %d' % (hwd, swd, hwl, s32(hwp), sig, score))
            elif kind == 'tick':
                n['tick'] += 1
                d, pos = e
                if hwd != d or swd != d or hwl != HW_LATENCY or hwp != pos:
                    bad.append('HW %d SW %d lat %d pos %d, model %d pos %d' % (hwd, swd, hwl, hwp, d, pos))
            else:
                bad.append('ALLOCATE outside portfolio mode')
        if bad:
            errs += 1
            if errs <= 25:
                print('  line %08x %d %d: %s' % (tid, p, v, '; '.join(bad)))
    print('portfolio system test: %d reports for %d lines | %d allocations (%d ROT), %d portfolio ticks, %d independent '
          'ticks | allocation HW %s cycles, SW %s cycles; tick SW (signal + score) %s cycles'
          % (len(reps), len(ticks), n['alloc'], n['rot'], n['ptick'], n['tick'],
             '%d..%d' % (min(alat), max(alat)) if alat else '-', '%d..%d' % (min(slat), max(slat)) if slat else '-',
             '%d..%d' % (min(tlat), max(tlat)) if tlat else '-'))
    ok = errs == 0 and n['alloc'] > 0
    print('RESULT', 'PASS' if ok else 'FAIL (%d problems)' % errs)
    return ok


def read_ticks(path):
    out = []
    for ln in open(path):
        if ln.strip():
            a = ln.split()
            out.append((int(a[0], 16), int(a[1]), int(a[2]), int(a[3])))
    return out


def check(tick_path, log_path):
    ticks = read_ticks(tick_path)
    exp = model(ticks)
    lines = open(log_path).read().splitlines()
    reps = [ln.split()[1:] for ln in lines if ln.startswith('REPORT')]
    problems = [ln.strip() for ln in lines if ln.startswith('TICK')]
    errs = len(problems)
    for p in problems:
        print('  ', p)
    names = {0: 'NONE', 1: 'BUY', 2: 'SELL'}
    n_trade = hw_ok = sw_ok = lat_ok = pos_ok = 0
    sw_lat = []
    if len(reps) != len(ticks):
        print('  %d reports for %d lines' % (len(reps), len(ticks)))
        errs += 1
    ov = [ln.split() for ln in lines if ln.startswith('OVERRUN')]
    if not ov:
        print('  no OVERRUN line in the log')
        errs += 1
    elif int(ov[0][1]) != 0:
        print('  OVERRUN counter is %s: packets were dropped although the test waits for every report' % ov[0][1])
        errs += 1
    for (tid, p, v, kill), (d, pos), r in zip(ticks, exp, reps):
        rid, rp, rv, hwd, hwl, swd, swl, hwp = int(r[0], 16), *[int(x) for x in r[1:]]
        line = []
        if (rid, rp, rv) != (tid, p, v):
            line.append('echo %x/%d/%d != %x/%d/%d' % (rid, rp, rv, tid, p, v))
        if hwp != pos:
            line.append('HW position %d, expected %d' % (hwp, pos))
        else:
            pos_ok += 1
        if d is None or d == 'skip':           # command / untraded company: decisions must be 0
            if (hwd, hwl, swd, swl) != (0, 0, 0, 0):
                line.append('command report not zero' if d is None else 'untraded-company report not zero')
        else:
            n_trade += 1
            sw_lat.append(swl)
            if hwd != d:
                line.append('HW %s, expected %s' % (names.get(hwd, hwd), names[d]))
            else:
                hw_ok += 1
            if swd != d:
                line.append('SW %s, expected %s' % (names.get(swd, swd), names[d]))
            else:
                sw_ok += 1
            if hwl == HW_LATENCY:
                lat_ok += 1
            else:
                line.append('HW latency %d' % hwl)
        if line:
            errs += 1
            if errs <= 25:
                print('  line %08x price %d vol %d: %s' % (tid, p, v, '; '.join(line)))
    print('reports %d/%d | ticks %d: HW ok %d, SW ok %d, latency ok %d | position ok %d/%d | SW latency %s..%s'
          % (len(reps), len(ticks), n_trade, hw_ok, sw_ok, lat_ok, pos_ok, len(ticks),
             min(sw_lat) if sw_lat else '-', max(sw_lat) if sw_lat else '-'))
    st = {}
    ds = [d for d, _ in model(ticks, st) if d is not None]
    print('model: %d BUY, %d SELL, %d NONE | signals blocked: cash %d, position limit %d, nothing to sell %d, zero volume %d%s'
          % (ds.count(1), ds.count(2), ds.count(0), st['blocked_cash'], st['blocked_limit'],
             st['blocked_nostock'], st['zero_vol'],
             (', cash cap %d' % st['blocked_cap']) if st['blocked_cap'] else ''))
    syms = sorted({sym_of(t[0]) for t in ticks if not t[0] & 0x80000000})
    if len(syms) > 1:
        print('companies in the stream: %s; untraded-company ticks: %d' % (syms, ds.count('skip')))
    ok = errs == 0
    print('RESULT', 'PASS' if ok else 'FAIL (%d problems)' % errs)
    return ok


def check_burst(tick_path, log_path, nwait=5):
    """The first nwait lines were sent one at a time, the rest back to back (no waiting).
    Packets that arrive while the previous one is unread are dropped.  Required:
      * reports + dropped packets == packets sent        (nothing is lost silently)
      * the reports that did arrive match the model replayed over exactly those ticks
        (hardware decision == software decision == model, hardware position == model position),
        i.e. a dropped packet is dropped for the accelerator too
      * OVERRUN > 0 (the test really exercises the drop path) and LED3 on, LED2 (HW/SW mismatch) off"""
    ticks = read_ticks(tick_path)
    lines = open(log_path).read().splitlines()
    reps = [ln.split()[1:] for ln in lines if ln.startswith('REPORT')]
    errs = 0
    for ln in lines:
        if ln.startswith('TICK'):
            print('  ', ln.strip())
            errs += 1
    ov = [ln.split() for ln in lines if ln.startswith('OVERRUN')]
    if not ov:
        print('  no OVERRUN line in the log')
        return False
    overrun, led, sent = int(ov[0][1]), int(ov[0][3], 16), int(ov[0][5])
    burst = ticks[nwait:]
    if sent != len(ticks):
        print('  testbench sent %d lines, file has %d' % (sent, len(ticks)))
        errs += 1
    if len(reps) < nwait:
        print('  only %d reports for the %d setup commands' % (len(reps), nwait))
        return False
    got = [(int(r[0], 16), *[int(x) for x in r[1:]]) for r in reps[nwait:]]
    if len(got) + overrun != len(burst):
        print('  %d reports + %d dropped != %d packets sent' % (len(got), overrun, len(burst)))
        errs += 1
    if overrun == 0:
        print('  no packet was dropped: the burst did not exercise the drop path')
        errs += 1
    if not led & 0x8:
        print('  LED3 (packets dropped) is off, LED=%04x' % led)
        errs += 1
    if led & 0x4:
        print('  LED2 (HW/SW mismatch) is on, LED=%04x' % led)
        errs += 1
    by_id = {t[0]: t for t in burst}
    m = HFTModel(POS_LIMIT, BRK_HIGH, BRK_LOW)
    for t in ticks[:nwait]:
        m.command(t[0], t[1], t[2])
    last_id, hw_ok = 0, 0
    for rid, rp, rv, hwd, hwl, swd, swl, hwp in got:
        t = by_id.get(rid)
        if t is None or rid <= last_id:
            print('  report id %x is unknown or out of order' % rid)
            errs += 1
            continue
        last_id = rid
        _, p, v, kill = t
        d = m.step(p, v, kill)
        problems = []
        if (rp, rv) != (p, v):
            problems.append('echo %d/%d != %d/%d' % (rp, rv, p, v))
        if hwd != d:
            problems.append('HW decision %d, model %d' % (hwd, d))
        if swd != hwd:
            problems.append('SW decision %d != HW decision %d' % (swd, hwd))
        if hwp != m.pos:
            problems.append('HW position %d, model %d' % (hwp, m.pos))
        if problems:
            errs += 1
            print('  tick %d: %s' % (rid, '; '.join(problems)))
        else:
            hw_ok += 1
    print('burst: %d packets sent back to back -> %d reported, %d dropped (OVERRUN=%d, LED=%04x) | %d/%d reports match the model'
          % (len(burst), len(got), overrun, overrun, led, hw_ok, len(got)))
    ok = errs == 0 and len(got) >= 2
    print('RESULT', 'PASS' if ok else 'FAIL (%d problems)' % errs)
    return ok


def gen_random(path, n=3000, seed=7):
    rnd, p, ticks = random.Random(seed), 100, []
    for i in range(n):
        p = min(260, max(10, p + rnd.choice([-9, -4, -2, -1, 0, 1, 2, 4, 9])))
        v = 0 if rnd.random() < 0.02 else rnd.randint(1, 300)       # a few zero-volume ticks
        ticks.append((i + 1, p, v, 1 if rnd.random() < 0.03 else 0))
    # v12: three huge-volume ticks overflow the 32-bit VWAP volume sum; from then on the VWAP rule
    # must stay silent (only MA + breakout vote) in the hardware exactly as in the model
    for j in range(3):
        ticks.append((n + 1 + j, p, 0x60000000, 0))
    for i in range(400):
        p = min(260, max(10, p + rnd.choice([-9, -4, -2, -1, 0, 1, 2, 4, 9])))
        ticks.append((n + 4 + i, p, rnd.randint(1, 300), 0))
    with open(path, 'w') as f:
        for t in ticks:
            f.write('%d %d %d %d\n' % t)


def check_unit(tick_path, log_path):
    ticks = [tuple(int(x) for x in ln.split()) for ln in open(tick_path) if ln.strip()]
    exp = [d for d, _ in model(ticks)]
    decs = [tuple(int(x) for x in ln.split()[1:]) for ln in open(log_path) if ln.startswith('DEC')]
    bad = 0
    lat5 = sum(1 for d in decs if d[2] == HW_LATENCY)
    for (tid, p, v, k), e, d in zip(ticks, exp, decs):
        if d[0] != tid or d[1] != e or not (HW_LATENCY <= d[2] <= 2 * HW_LATENCY):
            bad += 1
            if bad < 10:
                print('  tick', tid, 'got', d, 'expected decision', e)
    ok = bad == 0 and len(decs) == len(ticks)
    print('unit: %d/%d decided, %d mismatches, %d at exactly 5 cycles, max latency %d (buffered ticks wait)'
          % (len(decs), len(ticks), bad, lat5, max(d[2] for d in decs) if decs else -1))
    print('model: %d BUY, %d SELL, %d NONE' % (exp.count(1), exp.count(2), exp.count(0)))
    print('RESULT', 'PASS' if ok else 'FAIL')
    return ok


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'gen':
        gen(sys.argv[2])
    elif mode == 'genrand':
        gen_random(sys.argv[2])
    elif mode == 'genburst':
        gen_burst(sys.argv[2])
    elif mode == 'genmulti':
        gen_multi(sys.argv[2])
    elif mode == 'genport':
        gen_port(sys.argv[2])
    elif mode == 'checkport':
        sys.exit(0 if check_port_sys(sys.argv[2], sys.argv[3]) else 1)
    elif mode == 'unit':
        sys.exit(0 if check_unit(sys.argv[2], sys.argv[3]) else 1)
    elif mode == 'checkburst':
        sys.exit(0 if check_burst(sys.argv[2], sys.argv[3]) else 1)
    elif mode == 'fromlog':
        from_log(sys.argv[2], sys.argv[3])
    elif mode == 'check':
        sys.exit(0 if check(sys.argv[2], sys.argv[3]) else 1)
    else:
        sys.exit('unknown mode %r (gen | check | genrand | unit | genburst | checkburst | fromlog)' % mode)
