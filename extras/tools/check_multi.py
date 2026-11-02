#!/usr/bin/env python3
"""check_multi.py - random stimulus for tb_hft_multi.v and checker against MultiModel.

  python3 check_multi.py gen ops.txt [seed] [n_max] [groups_per_run]
  python3 check_multi.py check log.txt [n_max]

The stimulus covers: several companies ticking in the SAME clock cycle (fixed priority on the
shared cash), ticks offset by 1..4 cycles (one engine in S4 while another is mid-flight),
shared cash running out, per-company cash caps, position limits, SELL without holdings,
zero-volume ticks, the kill switch, and `clear` with new starting cash (incl. 64-bit values).

The checker walks the log in time order: TICK lines queue a tick for its engine, DEC lines
(printed in commit order) pop it and step the model, CASH lines compare the shared cash after
that cycle.  The shared cash unit serves one engine per cycle (lowest index first); an engine
that has to wait for it reports `held` > 0, and every engine must report latency 5 + held
(exactly 5 when it did not wait).  At most one engine may change the cash in one cycle.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from hft_model import MultiModel, BUY, SELL, NONE  # noqa: E402

LAT = 5


def directed():
    """Two cases where the same-cycle priority decides the outcome (companies 0 and 1)."""
    L = []
    # A: two BUYs of 1,100 in the same cycle, cash 1,500 -> company 0 buys, company 1 is refused
    L.append((1, 0, 1500, 0, 0))
    for s in (0, 1):
        L += [(2, s, 1000, 50, 10), (4, s, 0, 0, 0)]
    L += [(0, 0, 100, 10, 0), (0, 1, 100, 10, 0), (3, 6, 0, 0, 0),
          (0, 0, 110, 10, 0), (0, 1, 110, 10, 0), (3, 8, 0, 0, 0)]
    # B: company 0 SELLs (+900) in the same cycle as company 1 BUYs for 840 with 0 cash left:
    #    the BUY is only possible because the lower-index SELL is credited first
    L.append((1, 0, 1100, 0, 0))
    L += [(2, 0, 1000, 50, 10), (2, 1, 1000, 1000, 10)]
    L += [(0, 0, 100, 10, 0), (0, 1, 100, 10, 0), (3, 6, 0, 0, 0),
          (0, 0, 110, 10, 0), (0, 1, 110, 10, 0), (3, 8, 0, 0, 0)]          # company 0 buys 10 for 1,100
    L += [(2, 0, 1000, 1000, 200), (2, 1, 1000, 50, 10)]
    L += [(0, 0, 90, 10, 0), (0, 1, 120, 7, 0), (3, 8, 0, 0, 0)]
    # C (v12): shared cash at 2^64 - 1: buy 10 at 110, the price rises, sell 10 at 150 -> the
    #    proceeds exceed what was spent, so the credit must SATURATE at 2^64 - 1 (not wrap)
    L.append((1, 0xFFFFFFFF, 0xFFFFFFFF, 0, 0))
    L += [(2, 0, 1000, 5000, 1000), (4, 0, 0, 0, 0)]
    for p, v in [(100, 10)] * 3 + [(110, 10)] + [(200, 0)] * 3 + [(150, 10)]:
        L += [(0, 0, p, v, 0), (3, 8, 0, 0, 0)]
    return L


def gen(path, seed=1, n_max=2, groups=120, runs=6):
    rnd = random.Random(seed)
    L = directed()
    # v12: the last two runs start just below 2^64 so SELL credits must saturate, not wrap
    for r in range(runs + 2):
        # shared starting cash: small (runs out), medium, or one that needs the high word
        cash = rnd.choice([rnd.randint(20000, 120000), rnd.randint(200000, 900000),
                           (1 << 32) + rnd.randint(0, 5000)])
        if r >= runs:
            cash = (1 << 64) - rnd.randint(1, 5000)
        L.append((1, cash >> 32, cash & 0xFFFFFFFF, 0, 0))
        for s in range(n_max):
            L.append((2, s, rnd.choice([300, 600, 1000, 2500]), rnd.randint(120, 170), rnd.randint(40, 80)))
            cap = 0 if rnd.random() < 0.4 else rnd.randint(5000, 200000)
            L.append((4, s, cap >> 32, cap & 0xFFFFFFFF, 0))
        prices = [rnd.randint(60, 200) for _ in range(n_max)]
        T, busy, kill, last_wait = 0, [0] * n_max, 0, 99
        for _ in range(groups):
            free = [s for s in range(n_max) if busy[s] <= T]
            if not free:
                L.append((3, 1, 0, 0, 0)); T += 2; last_wait = 1
                continue
            if rnd.random() < 0.4:
                group = free                               # everyone that can, in the same cycle
            else:
                group = sorted(rnd.sample(free, rnd.randint(1, len(free))))
            if last_wait >= 8 and rnd.random() < 0.06:     # kill changes only when nothing is in flight
                kill ^= 1
            for s in group:
                prices[s] = min(260, max(10, prices[s] + rnd.choice([-9, -4, -2, -1, 0, 1, 2, 4, 9])))
                v = 0 if rnd.random() < 0.03 else rnd.randint(1, 300)
                L.append((0, s, prices[s], v, kill))
                busy[s] = T + LAT + 2 * (n_max - 1)    # room for waiting on the cash unit
            wait = rnd.choice([0, 1, 2, 3, 4]) if rnd.random() < 0.3 else rnd.randint(5, 10)
            L.append((3, wait, 0, 0, 0))
            T += 1 + wait
            last_wait = wait
        L.append((3, 12, 0, 0, 0))
    with open(path, 'w') as f:
        for t in L:
            f.write('%d %d %d %d %d\n' % t)
    print('wrote %d ops (%d ticks) to %s' % (len(L), sum(1 for t in L if t[0] == 0), path))


def check(log_path, n_max=2):
    m = MultiModel(n_max)
    m.nsym = n_max
    queues = [[] for _ in range(n_max)]
    errs = ndec = ncash = trades = 0
    lat_bad = 0
    same = 0
    held_dec = 0                   # decisions that waited for the cash unit
    cash_changes = 0               # engines that changed the cash in the current cycle
    done = None
    tot = dict(cash=0, cap=0, limit=0, nostock=0, zero=0)
    prio = 0                       # BUYs refused only because an engine served just before (while this one waited) spent the cash
    cash_before_last = m.cash      # shared cash before the most recent cash change

    def add_totals():
        tot['cash'] += sum(e.blocked_cash for e in m.engines)
        tot['limit'] += sum(e.blocked_limit for e in m.engines)
        tot['nostock'] += sum(e.blocked_nostock for e in m.engines)
        tot['zero'] += sum(e.zero_vol for e in m.engines)
        tot['cap'] += m.blocked_cap
    for ln in open(log_path):
        a = ln.split()
        if not a:
            continue
        if a[0] == 'TICK':
            queues[int(a[1])].append(tuple(int(x) for x in a[2:5]))
        elif a[0] == 'OP':
            if a[1] == 'CASH':
                add_totals()
                m.starting_cash = int(a[2]); m.reset()
                cash_before_last = m.cash
            elif a[1] == 'CFG':
                s = int(a[2]); e = m.engines[s]
                e.pos_limit, e.brk_high, e.brk_low = int(a[3]), int(a[4]), int(a[5])
            elif a[1] == 'CAP':
                m.caps[int(a[2])] = int(a[3])
        elif a[0] == 'DEC':
            s, d, lat, pos, inv, held = (int(x) for x in a[1:7])
            held_dec += held > 0
            if not queues[s]:
                print('  DEC for engine %d with no tick queued' % s); errs += 1; continue
            p, v, k = queues[s].pop(0)
            before = m.engines[s].blocked_cash
            cash_before = m.cash
            md = m.step(s, p, v, k)
            cash_changes += m.cash != cash_before
            if m.engines[s].blocked_cash > before and held > 0 and cash_before_last >= p * v:
                prio += 1
            if m.cash != cash_before:
                cash_before_last = cash_before
            ndec += 1
            trades += md != NONE
            prob = []
            if d != md:
                prob.append('decision %d, model %d' % (d, md))
            if lat != LAT + held:
                prob.append('latency %d, expected %d (5 + %d held)' % (lat, LAT + held, held)); lat_bad += 1
            if pos != m.pos(s):
                prob.append('position %d, model %d' % (pos, m.pos(s)))
            if inv != m.invested[s]:
                prob.append('invested %d, model %d' % (inv, m.invested[s]))
            if prob:
                errs += 1
                if errs <= 20:
                    print('  engine %d tick p=%d v=%d k=%d: %s' % (s, p, v, k, '; '.join(prob)))
        elif a[0] == 'CASH':
            ncash += 1
            if cash_changes > 1:
                errs += 1
                print('  %d engines changed the cash in one cycle' % cash_changes)
            cash_changes = 0
            c = int(a[1])
            if c != m.cash:
                errs += 1
                if errs <= 20:
                    print('  shared cash %d, model %d' % (c, m.cash))
            if m.cash < 0:
                errs += 1; print('  model cash negative')
        elif a[0] == 'DONE':
            done = a
            same = int(a[2].split('=')[1])
            held_cycles = int(a[3].split('=')[1])
    left = sum(len(q) for q in queues)
    if left:
        print('  %d ticks never decided' % left); errs += 1
    if done is None:
        print('  no DONE line'); errs += 1
    add_totals()
    print('multi (N=%d): %d decisions, %d trades, %d cash checks, %d cycles with 2+ engines deciding together, '
          '%d decisions waited for the cash unit (%d cycles), latency != 5 + held: %d, mismatches: %d'
          % (n_max, ndec, trades, ncash, same, held_dec, held_cycles if done else 0, lat_bad, errs))
    print('  signals blocked: cash %d (of which %d only because a lower-index engine took the cash first), '
          'cap %d, position limit %d, nothing to sell %d, zero volume %d'
          % (tot['cash'], prio, tot['cap'], tot['limit'], tot['nostock'], tot['zero']))
    ok = errs == 0 and ndec > 0 and same > 0 and held_dec > 0 and prio > 0
    print('RESULT', 'PASS' if ok else 'FAIL')
    return ok


if __name__ == '__main__':
    if sys.argv[1] == 'gen':
        gen(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1,
            int(sys.argv[4]) if len(sys.argv) > 4 else 2, int(sys.argv[5]) if len(sys.argv) > 5 else 120)
    else:
        sys.exit(0 if check(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2) else 1)
