"""hft_model.py - bit-exact Python model of hft_accelerator.v / hft_firmware.c.

Used by the dashboard (simulation mode), tools/check_hft.py (RTL tests) and
verify_run.py (checking a real board run).

Per tick:
  MA(4)    : sum = p + p[-1] + p[-2] + p[-3], only after 3 earlier ticks
             BUY vote if 4*p > sum, SELL vote if 4*p < sum   (exact: no rounding of the average)
  VWAP     : running sums including this tick (volume sum 32 bits, price*volume sum 64 bits);
             BUY if p*sumV > sumPV, SELL if p*sumV < sumPV.  If either sum would overflow, the
             VWAP rule is switched off (vsat, until RESET): no VWAP vote, sums frozen (v12)
  Breakout : BUY if p > brk_high, SELL if p < brk_low
  Vote     : BUY with >= 2 buy votes, else SELL with >= 2 sell votes, else NONE
  Risk     : kill switch -> NONE; volume 0 -> NONE; BUY blocked if it exceeds the
             position limit or costs more cash than is available; SELL blocked if
             pos < vol (no short selling).  Cash and position are never negative.

Units: price x volume ("units") is what the accelerator calls cash.  For the real-data
dashboard price is in cents and volume in lots, so one unit = 1 cent x 1 lot.

Several companies (MultiModel, hft_multi.v): one HFTModel strategy per company and ONE
shared cash account.  A tick's company is tick_id[30:28]; command ids carry it in the
same bits (RESET and CFG_CASH are global).  BUY needs shared cash >= price*vol and, when
that company's cap is not 0, invested + price*vol <= cap (invested = BUY cost minus SELL
proceeds of that company).  Ticks are applied one at a time; ticks that the hardware
commits in the same cycle are applied in company order (lower index first), which is
exactly the hardware's fixed-priority rule.  A tick for a company >= NUM_SYMBOLS is not
traded (decision NONE, nothing changes).

Besides the decision, the model counts the signals the risk interlock blocked
(blocked_limit / blocked_cash / blocked_nostock / zero_vol).  They never change a
decision; the dashboard and verify_run.py use them to warn when a run barely trades
(for example because the starting cash cannot pay for one bar of volume).
"""

NONE, BUY, SELL = 0, 1, 2
NAMES = {NONE: 'NONE', BUY: 'BUY', SELL: 'SELL'}

CMD_RESET = 0x80000000      # clear strategy state (hardware and software)
CMD_CFG_BRK = 0x80000001    # price field = BRK_HIGH, vol field = BRK_LOW
CMD_CFG_LIMIT = 0x80000002  # price field = POS_LIMIT
CMD_CFG_CASH = 0x80000003   # price/vol fields = starting cash low/high words
CMD_CFG_NSYM = 0x80000004   # price field = NUM_SYMBOLS (companies traded at once)
CMD_CFG_CAP = 0x80000005    # price/vol fields = this company's cash cap low/high (0 = no cap)
CMD_ALLOCATE = 0x80000006   # portfolio mode: end of minute, run the allocator (price field = minute number)
CMD_CFG_MODE = 0x80000007   # price = mode bits (MODE_*), vol = MAX_LOTS (0 = whole bar volume); applies at RESET
CMD_CFG_ROT = 0x80000008    # price = rotation MARGIN (score units), vol = MIN_HOLD (minutes)
CMD_CFG_W = 0x80000009      # price = k | capshift << 8 (weight step 1/2^k, cap = (cash * w) >> capshift), vol = FLOOR
MODE_PORTFOLIO, MODE_RANK, MODE_ROTATE, MODE_REWEIGHT = 1, 2, 4, 8
ROT = 3                     # allocation code: position sold to fund a stronger company
CODE_NAMES = {NONE: '-', BUY: 'BUY', SELL: 'SELL', ROT: 'ROT'}
W_TOTAL = 1 << 15           # the weights always add up to this (Q15)
SCORE_FRAC = 20             # score = (4*price - sum of last 4 prices) / that sum, in units of 2^-20
DEFAULTS = dict(max_lots=0, margin=1049, min_hold=5, wshift=3, wfloor=4096, capshift=14)
M32, M64 = (1 << 32) - 1, (1 << 64) - 1
SYM_SHIFT, SYM_MASK = 28, 0x70000000
# printed by the PC tools when a report from the board never arrives: the run stops, because the
# board may or may not have processed that packet
LOST_SYNC = ('stopping: without this report the board and the Python model may no longer be in step '
             '(check the cable / COM port, press CPU RESET and start the run again)')


def sym_of(tick_id):
    """Company index carried in tick_id[30:28] (ticks and commands)."""
    return (tick_id >> SYM_SHIFT) & 7


def cmd_of(tick_id):
    """Command code without the company bits."""
    return tick_id & ~SYM_MASK & M32


def with_sym(tick_id, sym):
    return (tick_id & ~SYM_MASK & M32) | (sym << SYM_SHIFT)


class HFTModel:
    def __init__(self, pos_limit=1000, brk_high=150, brk_low=50, starting_cash=1000000):
        self.pos_limit, self.brk_high, self.brk_low = pos_limit, brk_high, brk_low
        self.starting_cash = starting_cash
        self.reset()

    def reset(self):
        self.hist = [0, 0, 0]
        self.warm = 0
        self.spv = 0
        self.sv = 0
        self.vsat = False           # VWAP sums would have overflowed: VWAP rule off until reset
        self.pos = 0
        self.cash = self.starting_cash
        # statistics of blocked signals (not part of the hardware state)
        self.blocked_limit = 0      # BUY signals refused: position limit
        self.blocked_cash = 0       # BUY signals refused: not enough cash
        self.blocked_nostock = 0    # SELL signals refused: nothing (or too little) held
        self.zero_vol = 0           # BUY/SELL signals on a zero-volume tick

    def command(self, cmd, price, vol):
        if cmd == CMD_RESET:
            self.reset()
        elif cmd == CMD_CFG_BRK:
            self.brk_high, self.brk_low = price, vol
        elif cmd == CMD_CFG_LIMIT:
            self.pos_limit = price
        elif cmd == CMD_CFG_CASH:
            self.starting_cash = price | (vol << 32)

    def equity(self, price):
        """Cash plus holdings valued at `price`, in units (price x lots)."""
        return self.cash + self.pos * price

    def signal(self, price, vol):
        """Update the price history and VWAP sums and return the 2-of-3 vote (no risk check)."""
        buy = sell = 0
        if self.warm >= 3:
            total = price + self.hist[0] + self.hist[1] + self.hist[2]
            buy += 4 * price > total
            sell += 4 * price < total
        else:
            self.warm += 1
        self.hist = [price, self.hist[0], self.hist[1]]
        nspv, nsv = self.spv + price * vol, self.sv + vol
        if self.vsat or nsv > M32 or nspv > M64:
            self.vsat = True                        # like hft_accelerator.v: no VWAP vote any more
        else:
            self.spv, self.sv = nspv, nsv
            pxv = price * self.sv
            buy += pxv > self.spv
            sell += pxv < self.spv
        buy += price > self.brk_high
        sell += price < self.brk_low
        return BUY if buy >= 2 else SELL if sell >= 2 else NONE

    def step(self, price, vol, kill=0):
        d = self.signal(price, vol)
        if kill:
            d = NONE
        elif d != NONE and vol == 0:
            self.zero_vol += 1
            d = NONE
        elif d == BUY and self.pos + vol > self.pos_limit:
            self.blocked_limit += 1
            d = NONE
        elif d == BUY and self.cash < price * vol:
            self.blocked_cash += 1
            d = NONE
        elif d == SELL and self.pos < vol:
            self.blocked_nostock += 1
            d = NONE
        if d == BUY:
            self.pos += vol
            self.cash -= price * vol
        elif d == SELL:
            self.pos -= vol
            self.cash = min(self.cash + price * vol, M64)     # saturates like the hardware (v12)
        return d


class MultiModel:
    """N_MAX independent strategies (one HFTModel each) sharing one cash account."""

    def __init__(self, n_max=8, starting_cash=1000000):
        self.n_max = n_max
        self.engines = [HFTModel() for _ in range(n_max)]
        self.caps = [0] * n_max
        self.nsym = 1
        self.starting_cash = starting_cash
        self.reset()

    def reset(self):
        for e in self.engines:
            e.reset()
        self.cash = self.starting_cash
        self.invested = [0] * self.n_max
        self.blocked_cap = 0

    def pos(self, sym):
        return self.engines[sym].pos if sym < self.n_max else 0

    def command(self, tick_id, price, vol):
        cmd, sym = cmd_of(tick_id), sym_of(tick_id)
        if cmd == CMD_RESET:
            self.reset()
        elif cmd == CMD_CFG_CASH:
            self.starting_cash = price | (vol << 32)
        elif cmd == CMD_CFG_NSYM:
            self.nsym = 1 if price == 0 else min(price, self.n_max)
        elif sym < self.n_max:
            if cmd == CMD_CFG_BRK:
                self.engines[sym].brk_high, self.engines[sym].brk_low = price, vol
            elif cmd == CMD_CFG_LIMIT:
                self.engines[sym].pos_limit = price
            elif cmd == CMD_CFG_CAP:
                self.caps[sym] = price | (vol << 32)

    def step(self, sym, price, vol, kill=0):
        if sym >= self.nsym or sym >= self.n_max:
            return NONE                         # not traded (counted as BAD_SYMBOL by the hardware)
        e = self.engines[sym]
        d = e.signal(price, vol)
        cost = price * vol
        if kill:
            d = NONE
        elif d != NONE and vol == 0:
            e.zero_vol += 1
            d = NONE
        elif d == BUY and e.pos + vol > e.pos_limit:
            e.blocked_limit += 1
            d = NONE
        elif d == BUY and self.cash < cost:
            e.blocked_cash += 1
            d = NONE
        elif d == BUY and self.caps[sym] and self.invested[sym] + cost > self.caps[sym]:
            self.blocked_cap += 1
            d = NONE
        elif d == SELL and e.pos < vol:
            e.blocked_nostock += 1
            d = NONE
        if d == BUY:
            e.pos += vol
            self.cash -= cost
            self.invested[sym] += cost
        elif d == SELL:
            e.pos -= vol
            self.cash = min(self.cash + cost, M64)            # saturates like the hardware (v12)
            self.invested[sym] -= cost
        return d

    def equity(self, prices):
        """Shared cash plus every holding valued at prices[sym] (units)."""
        return self.cash + sum(self.engines[i].pos * prices[i] for i in range(min(len(prices), self.n_max)))


# ----------------------------------------------------------------------------- portfolio mode
def weight_init(n):
    """Equal weights for n companies that add up to W_TOTAL exactly (remainder to company 0)."""
    base = W_TOTAL // n
    w = [base] * n
    w[0] += W_TOTAL - base * n
    return w


# shift that spreads a loser's weight over the other n-1 companies: ceil(log2(n-1))
SHARE_SHIFT = {1: 0, 2: 0, 3: 1, 4: 2, 5: 2, 6: 3, 7: 3, 8: 3}


def score_of(price, ma_sum, ma_ok):
    """Momentum score: (4*price - S) / S in units of 2^-20, S = this price + the 3 before it.
    Truncated toward zero (division of the magnitude), 0 while the MA is warming up."""
    if not ma_ok or ma_sum == 0:
        return 0
    num = 4 * price - ma_sum
    q = (abs(num) << SCORE_FRAC) // ma_sum
    return -q if num < 0 else q


class PortfolioModel:
    """Hybrid allocator of hft_alloc.v (bit-exact).  Per minute: every company's tick gives a
    SIGNAL (the 2-of-3 vote, no risk check) and a SCORE; the ALLOCATE command then trades:
      1. SELLs: a company with a SELL signal (volume > 0) sells its WHOLE position.
      2. RANK : the BUY candidates (BUY signal, qty = min(volume, MAX_LOTS) > 0, position + qty
               <= its limit) are served strongest score first (ties: lower company number);
               without MODE_RANK in company order.
      3. BUY  : qty lots for price*qty if the shared cash covers it and, with MODE_REWEIGHT,
               invested + cost <= cap = (starting cash * weight) >> CAPSHIFT (CAPSHIFT 14: the caps
               add up to 200 % of the cash, so the companies still compete for the shared cash;
               15: 100 %).
      4. ROTATE (MODE_ROTATE, at most once per minute): a BUY refused ONLY for cash may sell the
               held company with the LOWEST score among those with no BUY signal this minute,
               held for >= MIN_HOLD minutes and scoring more than MARGIN below the buyer, if that
               sale makes the BUY affordable.  Code ROT for the sold company.
      5. HOLD : every company still holding counts one more minute (saturates at 255).
      6. REWEIGHT (MODE_REWEIGHT): each position closed this minute (SELL or ROT), in company
               order, moves weight: a win (proceeds > invested) takes w_j >> k from every other
               company j; a loss gives w_i >> k away, split as (w_i >> k) >> SHARE_SHIFT[n] to each
               other company; nobody goes below FLOOR.  The weights always add up to W_TOTAL.
    The kill switch blocks every trade of that minute (holding times still count).
    Without MODE_PORTFOLIO the board runs the independent engines (MultiModel)."""

    def __init__(self, n_max=8, starting_cash=1000000):
        self.n_max = n_max
        self.engines = [HFTModel() for _ in range(n_max)]
        self.nsym = 1
        self.starting_cash = starting_cash
        self.mode = MODE_PORTFOLIO | MODE_RANK | MODE_ROTATE | MODE_REWEIGHT
        self.mode_cfg = self.mode
        for k, v in DEFAULTS.items():
            setattr(self, k, v)
        self.reset()

    # ---- configuration / commands (same encoding as the firmware) ----
    def reset(self):
        n = self.n_max
        for e in self.engines:
            e.reset()
        self.mode = self.mode_cfg
        self.cash = self.starting_cash
        self.cap_start, self.cap_shift = self.starting_cash, self.capshift   # latched at reset, like the hardware
        self.pos, self.inv, self.hold = [0] * n, [0] * n, [0] * n
        self.lastp, self.vol, self.score, self.sig = [0] * n, [0] * n, [0] * n, [0] * n
        self.fresh = [False] * n
        w = weight_init(self.nsym)
        self.w = w + [0] * (n - len(w))
        self.allocations = 0
        self.stats = dict(buys=0, sells=0, rotations=0, wins=0, losses=0, refused_cash=0, refused_cap=0,
                          refused_limit=0, ranked=0)

    def command(self, tick_id, price, vol):
        cmd, sym = cmd_of(tick_id), sym_of(tick_id)
        if cmd == CMD_RESET:
            self.reset()
        elif cmd == CMD_CFG_CASH:
            self.starting_cash = price | (vol << 32)
        elif cmd == CMD_CFG_NSYM:
            self.nsym = 1 if price == 0 else min(price, self.n_max)
        elif cmd == CMD_CFG_MODE:
            self.mode_cfg, self.max_lots = price & 15, vol
        elif cmd == CMD_CFG_ROT:
            self.margin, self.min_hold = price, vol & 255
        elif cmd == CMD_CFG_W:
            self.wshift, self.capshift, self.wfloor = price & 31, (price >> 8) & 31, vol & 0xFFFF
        elif cmd == CMD_ALLOCATE:
            # like the hardware (hft_mmio.v starts only on exactly 0x80000006) and the firmware:
            # an ALLOCATE id that carries company bits is ignored
            return self.allocate() if tick_id == CMD_ALLOCATE else None
        elif sym < self.n_max:
            if cmd == CMD_CFG_BRK:
                self.engines[sym].brk_high, self.engines[sym].brk_low = price, vol
            elif cmd == CMD_CFG_LIMIT:
                self.engines[sym].pos_limit = price
        return None

    # ---- one tick: signal + score, no trade ----
    def tick(self, sym, price, vol):
        if sym >= self.nsym or sym >= self.n_max:
            return None
        e = self.engines[sym]
        ma_ok = e.warm >= 3
        ma_sum = price + e.hist[0] + e.hist[1] + e.hist[2]
        sig = e.signal(price, vol)
        self.sig[sym], self.lastp[sym], self.vol[sym], self.fresh[sym] = sig, price, vol, True
        self.score[sym] = score_of(price, ma_sum, ma_ok)
        return sig, self.score[sym]

    # ---- end of minute ----
    def allocate(self, kill=0):
        n, N = self.nsym, self.n_max
        rank, rot, rw = self.mode & MODE_RANK, self.mode & MODE_ROTATE, self.mode & MODE_REWEIGHT
        codes, closed = [NONE] * N, [None] * N
        st = self.stats

        def close(i, proceeds, code):
            closed[i] = 'win' if proceeds > self.inv[i] else 'loss' if proceeds < self.inv[i] else None
            codes[i] = code
            self.pos[i] = self.inv[i] = self.hold[i] = 0

        def buy(i, qty, cost):
            if self.pos[i] == 0:
                self.hold[i] = 0
            self.pos[i] += qty
            self.inv[i] += cost
            codes[i] = BUY
            st['buys'] += 1

        if not kill:
            for i in range(n):                                       # 1. SELL whole positions
                if self.fresh[i] and self.sig[i] == SELL and self.vol[i] > 0 and self.pos[i] > 0:
                    proceeds = self.pos[i] * self.lastp[i]
                    self.cash = min(self.cash + proceeds, M64)    # saturates like the hardware (v12)
                    close(i, proceeds, SELL)
                    st['sells'] += 1
            cand, qty = [False] * N, [0] * N                        # 2. BUY candidates
            for i in range(n):
                if self.fresh[i] and self.sig[i] == BUY:
                    q = self.vol[i] if self.max_lots == 0 else min(self.vol[i], self.max_lots)
                    if q > 0 and self.pos[i] + q <= self.engines[i].pos_limit:
                        cand[i], qty[i] = True, q
                    elif q > 0:
                        st['refused_limit'] += 1
            used, rotated = [False] * N, False
            order = []
            while True:
                best = None
                for j in range(N):                                   # 3. strongest first
                    if cand[j] and not used[j]:
                        if best is None or (rank and self.score[j] > self.score[best]):
                            best = j
                if best is None:
                    break
                used[best] = True
                order.append(best)
                i = best
                cost = self.lastp[i] * qty[i]
                cap_ok = (not rw) or (self.inv[i] + cost <= (self.cap_start * self.w[i]) >> self.cap_shift)
                if self.cash >= cost and cap_ok:
                    self.cash -= cost
                    buy(i, qty[i], cost)
                elif rot and not rotated and cap_ok:                   # 4. rotation
                    v = None
                    for j in range(N):
                        if (j < n and self.pos[j] > 0 and not cand[j] and self.hold[j] >= self.min_hold
                                and self.score[i] - self.score[j] > self.margin):
                            if v is None or self.score[j] < self.score[v]:
                                v = j
                    done = False
                    if v is not None:
                        proceeds = self.pos[v] * self.lastp[v]
                        if self.cash + proceeds >= cost:
                            close(v, proceeds, ROT)
                            self.cash = min(self.cash + proceeds - cost, M64)
                            buy(i, qty[i], cost)
                            rotated = done = True
                            st['rotations'] += 1
                    if not done:
                        st['refused_cash'] += 1
                elif not cap_ok:
                    st['refused_cap'] += 1
                else:
                    st['refused_cash'] += 1
            if len(order) > 1 and rank and order != sorted(order):
                st['ranked'] += 1                                    # rank changed the order this minute
        for i in range(N):                                           # 5. holding time
            if self.pos[i] > 0 and self.hold[i] < 255:
                self.hold[i] += 1
        if rw:                                                       # 6. reweight, company order
            k, floor = self.wshift, self.wfloor
            for i in range(n):
                if closed[i] == 'win':
                    st['wins'] += 1
                    for j in range(n):
                        if j != i:
                            t = self.w[j] >> k
                            if self.w[j] - t < floor:
                                t = self.w[j] - floor if self.w[j] > floor else 0
                            self.w[j] -= t
                            self.w[i] += t
                elif closed[i] == 'loss':
                    st['losses'] += 1
                    t = self.w[i] >> k
                    if self.w[i] - t < floor:
                        t = self.w[i] - floor if self.w[i] > floor else 0
                    share = t >> SHARE_SHIFT[n]
                    for j in range(n):
                        if j != i:
                            self.w[j] += share
                            self.w[i] -= share
        self.fresh = [False] * N
        self.allocations += 1
        return codes

    def checksum(self):
        """The 32-bit state signature the firmware reports after every allocation."""
        return sum((self.pos[i] + (self.w[i] << 16)) * (2 * i + 1) for i in range(self.nsym)) & M32

    def equity(self, prices):
        return self.cash + sum(self.pos[i] * prices[i] for i in range(min(len(prices), self.n_max)))


def pack_codes(codes):
    return sum((c & 3) << (2 * i) for i, c in enumerate(codes)) & 0xFFFF
