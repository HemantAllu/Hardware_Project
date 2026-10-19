// hft_firmware.c : software trading model + hardware/software comparison
//
//   For every tick received on the UART the core
//     1. reads the tick latched by the hardware
//     2. runs the same strategy as hft_accelerator.v in software, timed with
//        the cycle counter
//     3. waits for the hardware result (HW_DONE) and reads it
//     4. clears TICK_READY and HW_DONE in ONE write, so the next packet can only be
//        accepted after this tick is completely finished (clearing TICK_READY first
//        let a packet that arrived during steps 2-3 have its HW_DONE wiped by the
//        later clear, and every report after it was shifted by one tick)
//     5. sends a 40-byte report to the PC dashboard
//
//   The software decision must equal the hardware decision on every tick (the
//   dashboard and tools/check_hft.py compare them), so both use exactly the
//   same rules: MA(4) with a 3-tick warm-up (exact compare 4*price vs the sum of
//   4 prices), VWAP, breakout, 2-of-3 vote, kill switch, zero-volume ticks never
//   trade, position limit, cash availability, no short selling, whole-tick quantities.
//
//   The PC must wait for each report before it sends the next tick.  A packet that
//   arrives while the previous one is unread is dropped by the hardware for the CPU
//   AND the accelerator (hft_mmio.v), so they cannot drift apart; HFT_OVERRUN counts
//   the drops and LED3 lights.
//
//   Several companies (hft_multi.v): a tick's company is id[30:28].  Each company has its
//   own strategy state, position and configuration; the cash account is shared.  With
//   NUM_SYMBOLS = 1 (the default) everything behaves exactly like the single-company
//   firmware.  Same-cycle priority never arises here: the PC sends one packet at a time.
//
//   Portfolio mode (PORT_MODE bit0, hft_alloc.v): the engines only give each company's
//   SIGNAL (the 2-of-3 vote) and SCORE per tick; at the end of every minute the PC sends
//   ALLOCATE, the hardware allocator trades (sell, rank, buy, rotate, reweight) and this
//   firmware runs the SAME allocator in C (port_allocate, a copy of hft_model.PortfolioModel)
//   and compares codes, cash and every company's position, invested amount, weight and
//   holding time.  Reports in portfolio mode:
//     tick     : hw dec = hw vote, sw dec = sw vote, position slot = hw score
//     ALLOCATE : price = hw cash low, vol = hw cash high, hw dec = hw codes (bit16 kill,
//                bit31 = any HW/SW difference), hw lat = allocation cycles, sw dec = sw codes,
//                sw lat = sw allocation cycles, position slot = state checksum
//                sum((pos_i + (weight_i << 16)) * (2i+1)) mod 2^32 of the hardware
//
//   build: extras/sw/build.sh extras/hft_firmware.c build_hft
//   board image: extras/tools/make_board_image.sh   (rebuilds and copies to src/mem/imem.mem)
#include <stdint.h>

#define MMIO_BASE        0x20000000u
#define MMIO_LED         (*(volatile uint32_t *)(MMIO_BASE + 0x00))
#define MMIO_SEG         (*(volatile uint32_t *)(MMIO_BASE + 0x04))
#define MMIO_SWITCH      (*(volatile uint32_t *)(MMIO_BASE + 0x08))
#define MMIO_CYCLE       (*(volatile uint32_t *)(MMIO_BASE + 0x10))

#define HFT_BASE         0x30000000u
#define HFT_POS_LIMIT    (*(volatile uint32_t *)(HFT_BASE + 0x00))
#define HFT_BRK_HIGH     (*(volatile uint32_t *)(HFT_BASE + 0x04))
#define HFT_BRK_LOW      (*(volatile uint32_t *)(HFT_BASE + 0x08))
#define HFT_TICK_ID      (*(volatile uint32_t *)(HFT_BASE + 0x0C))
#define HFT_TICK_PRICE   (*(volatile uint32_t *)(HFT_BASE + 0x10))
#define HFT_TICK_VOL     (*(volatile uint32_t *)(HFT_BASE + 0x14))
#define HFT_HW_DECISION  (*(volatile uint32_t *)(HFT_BASE + 0x18))
#define HFT_HW_LATENCY   (*(volatile uint32_t *)(HFT_BASE + 0x1C))
#define HFT_HW_POSITION  (*(volatile uint32_t *)(HFT_BASE + 0x20))
#define HFT_STATUS       (*(volatile uint32_t *)(HFT_BASE + 0x24))
#define HFT_UART_TX      (*(volatile uint32_t *)(HFT_BASE + 0x28))
#define HFT_OVERRUN      (*(volatile uint32_t *)(HFT_BASE + 0x2C))
#define HFT_CTRL         (*(volatile uint32_t *)(HFT_BASE + 0x30))
#define HFT_CASH_LO      (*(volatile uint32_t *)(HFT_BASE + 0x34))
#define HFT_CASH_HI      (*(volatile uint32_t *)(HFT_BASE + 0x38))
#define HFT_SYMBOL_SEL   (*(volatile uint32_t *)(HFT_BASE + 0x40))
#define HFT_NUM_SYMBOLS  (*(volatile uint32_t *)(HFT_BASE + 0x44))
#define HFT_CAP_LO       (*(volatile uint32_t *)(HFT_BASE + 0x48))
#define HFT_CAP_HI       (*(volatile uint32_t *)(HFT_BASE + 0x4C))
#define HFT_N_MAX        (*(volatile uint32_t *)(HFT_BASE + 0x58))
#define HFT_HW_CASH_LO   (*(volatile uint32_t *)(HFT_BASE + 0x3C))
#define HFT_HW_CASH_HI   (*(volatile uint32_t *)(HFT_BASE + 0x50))
#define HFT_INV_LO       (*(volatile uint32_t *)(HFT_BASE + 0x5C))
#define HFT_INV_HI       (*(volatile uint32_t *)(HFT_BASE + 0x60))
#define HFT_PORT_MODE    (*(volatile uint32_t *)(HFT_BASE + 0x64))
#define HFT_MAX_LOTS     (*(volatile uint32_t *)(HFT_BASE + 0x68))
#define HFT_MARGIN       (*(volatile uint32_t *)(HFT_BASE + 0x6C))
#define HFT_ALLOC_PARAM  (*(volatile uint32_t *)(HFT_BASE + 0x70))
#define HFT_W_FLOOR      (*(volatile uint32_t *)(HFT_BASE + 0x74))
#define HFT_ALLOC_CODES  (*(volatile uint32_t *)(HFT_BASE + 0x78))
#define HFT_ALLOC_LAT    (*(volatile uint32_t *)(HFT_BASE + 0x7C))
#define HFT_SCORE        (*(volatile uint32_t *)(HFT_BASE + 0x84))
#define HFT_WEIGHT       (*(volatile uint32_t *)(HFT_BASE + 0x88))

#define CMD_RESET     0x80000000u
#define CMD_CFG_BRK   0x80000001u
#define CMD_CFG_LIMIT 0x80000002u
#define CMD_CFG_CASH  0x80000003u
#define CMD_CFG_NSYM  0x80000004u     // price = number of companies traded
#define CMD_CFG_CAP   0x80000005u     // price/vol = this company's cash cap low/high (0 = no cap)
#define CMD_ALLOCATE  0x80000006u     // end of a minute (portfolio mode), price = minute number
#define CMD_CFG_MODE  0x80000007u     // price = mode bits (on the next RESET), vol = MAX_LOTS
#define CMD_CFG_ROT   0x80000008u     // price = MARGIN, vol = MIN_HOLD
#define CMD_CFG_W     0x80000009u     // price = K | CAPSHIFT << 8 (CAPSHIFT on RESET), vol = FLOOR
#define MODE_PORT     1u
#define MODE_RANK     2u
#define MODE_ROTATE   4u
#define MODE_REWEIGHT 8u
#define W_TOTAL       32768u
#define SYM_MASK      0x70000000u     // company index in id[30:28] (ticks and commands)
#define MAX_SYM       8

#define STATUS_TICK_READY  (1u << 0)
#define STATUS_HW_DONE     (1u << 1)
#define STATUS_UART_TX_RDY (1u << 2)
#define STATUS_ALLOC_DONE  (1u << 3)
#define STATUS_SCORES_RDY  (1u << 5)
#define STATUS_KILL        (1u << 6)     // kill switch as applied by the hardware to this packet

// busy-wait limits: the hardware answers within a few cycles (a tick: 5; an allocation: at most
// 8 + 12*8 cycles); a poll loop iteration takes about 6 cycles.  A loop that runs out reports a
// fault instead of hanging the board (e.g. a tick lost while the allocator was busy).
#define SPIN_LIMIT    200000u
#define HW_TIMEOUT    0xFFFFFFFFu        // hw decision field of a report whose result never came

// default configuration (the PC can change it with CFG commands)
#define CFG_POS_LIMIT 1000u
#define CFG_BRK_HIGH  150u
#define CFG_BRK_LOW   50u
#define START_CAPITAL 1000000ull

static uint32_t cfg_pos_limit[MAX_SYM], cfg_brk_high[MAX_SYM], cfg_brk_low[MAX_SYM];
static uint64_t cfg_cap[MAX_SYM];
static uint64_t cfg_starting_cash;
static uint32_t hw_nmax;          // engines in the bitstream (HFT_N_MAX register)
static uint32_t nsym;             // companies traded now (1..hw_nmax)

enum { NO_ACTION = 0, BUY = 1, SELL = 2, ROT = 3 };

// portfolio allocator settings and state.  NO initialisers: .data is only loaded by the bitstream,
// so after the CPU RESET button an initialised variable would keep the value the PC last wrote,
// while the hardware registers are back at their reset values.  main() sets the defaults (the
// same reset values as hft_mmio.v) after crt0 has zeroed .bss.
static uint32_t p_mode_cfg, p_mode;        // written / in force since the last RESET
static uint32_t p_max_lots, p_margin, p_min_hold, p_wshift, p_capshift, p_wfloor;
static uint64_t p_cap_start;               // starting cash and CAPSHIFT latched at RESET
static uint32_t p_cap_shift;
static uint32_t p_pos[MAX_SYM], p_hold[MAX_SYM], p_w[MAX_SYM];
static uint64_t p_inv[MAX_SYM];
static uint32_t p_lastp[MAX_SYM], p_vol[MAX_SYM], p_sig[MAX_SYM], p_fresh[MAX_SYM];
static int32_t  p_score[MAX_SYM];

// software model state, one set per company (zeroed by crt0 at every reset, like the hardware)
static uint32_t sw_hist[MAX_SYM][3];
static uint32_t sw_warm[MAX_SYM];          // earlier ticks seen (MA needs 3)
static uint64_t sw_acc_pv[MAX_SYM];
static uint32_t sw_acc_v[MAX_SYM];         // 32 bits, same as the hardware
static uint32_t sw_vsat[MAX_SYM];          // VWAP sums would have overflowed: VWAP rule off (as the hardware)
static uint32_t sw_position[MAX_SYM];
static int64_t  sw_invested[MAX_SYM];      // BUY cost minus SELL proceeds (for the cap)
static uint64_t sw_capital;                // shared by every company

// sticky: a hardware result never arrived (a poll timed out) since the last RESET (LED2)
static uint32_t fw_fault;

// wait until (STATUS & mask) != 0; returns 0 if the hardware did not answer in time
static uint32_t wait_status(uint32_t mask) {
    for (uint32_t spin = 0; spin < SPIN_LIMIT; spin++)
        if (HFT_STATUS & mask)
            return 1;
    fw_fault = 1;
    return 0;
}

static void uart_send_byte(uint32_t b) {
    // no timeout needed here: the transmitter always becomes free again within one byte time
    // (about 87 us at 115200 baud), whatever the PC or the trading hardware do
    while (!(HFT_STATUS & STATUS_UART_TX_RDY))
        ;
    HFT_UART_TX = b & 0xFF;
}

static void uart_send_u32(uint32_t v) {
    uart_send_byte(v);
    uart_send_byte(v >> 8);
    uart_send_byte(v >> 16);
    uart_send_byte(v >> 24);
}

// the strategy's signal (2-of-3 vote) for one tick; also gives the MA sum S = this price + the
// 3 before it and whether the MA is warm (for the score)
static uint32_t sw_signal(uint32_t c, uint32_t price, uint32_t vol, uint64_t *ma_sum, uint32_t *ma_ok) {
    uint32_t buy = 0, sell = 0;
    uint32_t *h = sw_hist[c];

    // moving average of the last 4 prices, after a 3-tick warm-up.  Exact compare:
    // 4*price against the sum of the four prices (no rounding of the average).
    uint64_t sum = (uint64_t)price + h[0] + h[1] + h[2];
    *ma_sum = sum;
    *ma_ok  = sw_warm[c] >= 3;
    if (sw_warm[c] >= 3) {
        uint64_t p4  = (uint64_t)price << 2;
        buy  += p4 > sum;
        sell += p4 < sum;
    } else {
        sw_warm[c]++;
    }
    h[2] = h[1];
    h[1] = h[0];
    h[0] = price;

    // VWAP including this tick; if a sum would overflow, the VWAP rule is off until RESET
    uint64_t npv = sw_acc_pv[c] + (uint64_t)price * vol;
    uint64_t nv  = (uint64_t)sw_acc_v[c] + vol;
    if (sw_vsat[c] || npv < sw_acc_pv[c] || (nv >> 32) != 0) {
        sw_vsat[c] = 1;
    } else {
        sw_acc_pv[c] = npv;
        sw_acc_v[c]  = (uint32_t)nv;
        uint64_t p_x_v = (uint64_t)price * sw_acc_v[c];
        buy  += p_x_v > sw_acc_pv[c];
        sell += p_x_v < sw_acc_pv[c];
    }

    // breakout
    buy  += price > cfg_brk_high[c];
    sell += price < cfg_brk_low[c];

    return (buy >= 2) ? BUY : (sell >= 2) ? SELL : NO_ACTION;
}

static uint32_t sw_decide(uint32_t c, uint32_t price, uint32_t vol, uint32_t kill) {
    uint64_t ma_sum;
    uint32_t ma_ok;
    uint32_t d = sw_signal(c, price, vol, &ma_sum, &ma_ok);
    uint64_t cost = (uint64_t)price * vol;

    // risk interlock (same order as hft_model.MultiModel)
    if (kill)
        d = NO_ACTION;
    else if (vol == 0)                                      // a zero-volume tick never trades
        d = NO_ACTION;
    else if (d == BUY && (uint64_t)sw_position[c] + vol > cfg_pos_limit[c])
        d = NO_ACTION;
    else if (d == BUY && sw_capital < cost)                 // shared cash
        d = NO_ACTION;
    else if (d == BUY && cfg_cap[c] != 0 && sw_invested[c] + (int64_t)cost > (int64_t)cfg_cap[c])
        d = NO_ACTION;
    else if (d == SELL && sw_position[c] < vol)
        d = NO_ACTION;

    if (d == BUY) {
        sw_position[c] += vol;
        sw_capital     -= cost;
        sw_invested[c] += (int64_t)cost;
    } else if (d == SELL) {
        sw_position[c] -= vol;
        uint64_t n = sw_capital + cost;                     // saturates like the hardware
        sw_capital     = (n < sw_capital) ? ~0ull : n;
        sw_invested[c] -= (int64_t)cost;
    }
    return d;
}

// ------------------------------------------------------------------ portfolio allocator (C copy)
// 64-bit unsigned division, bit by bit (the core's divider is 32-bit, and there is no libgcc:
// only shifts by a constant are used, the compiler inlines those)
static uint64_t udiv64(uint64_t n, uint64_t d) {
    uint64_t q = 0, r = 0;
    for (int i = 0; i < 64; i++) {
        r = (r << 1) | (n >> 63);
        n <<= 1;
        q <<= 1;
        if (r >= d) {
            r -= d;
            q |= 1u;
        }
    }
    return q;
}

// momentum score (4*price - S) / S in units of 2^-20, truncated toward zero; 0 while warming up
static int32_t sw_score(uint32_t price, uint64_t ma_sum, uint32_t ma_ok) {
    if (!ma_ok || ma_sum == 0)
        return 0;
    uint64_t p4 = (uint64_t)price << 2;
    uint32_t neg = p4 < ma_sum;
    uint64_t mag = neg ? ma_sum - p4 : p4 - ma_sum;
    int32_t q = (int32_t)udiv64(mag << 20, ma_sum);
    return neg ? -q : q;
}

static void port_reset(void) {
    uint32_t n = nsym;
    uint32_t base = W_TOTAL / n;
    for (uint32_t c = 0; c < MAX_SYM; c++) {
        p_pos[c] = p_hold[c] = 0;
        p_inv[c] = 0;
        p_lastp[c] = p_vol[c] = p_sig[c] = p_fresh[c] = 0;
        p_score[c] = 0;
        p_w[c] = (c < n) ? base : 0;
    }
    p_w[0] += W_TOTAL - base * n;
    p_mode = p_mode_cfg;
    p_cap_start = cfg_starting_cash;
    p_cap_shift = p_capshift;
}

static void port_tick(uint32_t c, uint32_t price, uint32_t vol, uint32_t sig, uint64_t ma_sum, uint32_t ma_ok) {
    p_sig[c] = sig;
    p_lastp[c] = price;
    p_vol[c] = vol;
    p_fresh[c] = 1;
    p_score[c] = sw_score(price, ma_sum, ma_ok);
}

// invested + cost <= (start * weight) >> CAPSHIFT, exact (the product has up to 80 bits)
static uint32_t cap_ok(uint32_t c, uint64_t cost) {
    uint64_t lo = (uint64_t)(uint32_t)p_cap_start * p_w[c];
    uint64_t hi = (p_cap_start >> 32) * p_w[c];
    uint64_t p_lo = lo + (hi << 32);
    uint64_t p_hi = (hi >> 32) + (p_lo < lo);
    uint64_t cap_lo = p_lo, cap_hi = p_hi;
    for (uint32_t s = p_cap_shift; s; s--) {          // >> CAPSHIFT, one bit at a time
        cap_lo = (cap_lo >> 1) | (cap_hi << 63);
        cap_hi >>= 1;
    }
    uint64_t a_lo = p_inv[c] + cost;
    uint64_t a_hi = a_lo < cost;
    return (a_hi < cap_hi) || (a_hi == cap_hi && a_lo <= cap_lo);
}

static uint32_t share_shift(uint32_t n) {         // ceil(log2(n-1))
    return n <= 2 ? 0 : n == 3 ? 1 : n <= 5 ? 2 : 3;
}

static uint32_t floor_take(uint32_t w) {           // w >> K, but never below FLOOR
    uint32_t t = w >> p_wshift;
    if (w - t < p_wfloor)
        t = (w > p_wfloor) ? w - p_wfloor : 0;
    return t;
}

// one end-of-minute allocation; returns the codes, 2 bits per company
static uint32_t port_allocate(uint32_t kill) {
    uint32_t n = nsym;
    uint32_t rank = p_mode & MODE_RANK, rot = p_mode & MODE_ROTATE, rw = p_mode & MODE_REWEIGHT;
    uint32_t code[MAX_SYM], closed[MAX_SYM], cand[MAX_SYM], used[MAX_SYM], qty[MAX_SYM];
    for (uint32_t i = 0; i < MAX_SYM; i++)
        code[i] = closed[i] = cand[i] = used[i] = qty[i] = 0;     // closed: 1 win, 2 loss

    if (!kill) {
        for (uint32_t i = 0; i < n; i++) {                        // 1. SELL whole positions
            if (p_fresh[i] && p_sig[i] == SELL && p_vol[i] > 0 && p_pos[i] > 0) {
                uint64_t proceeds = (uint64_t)p_pos[i] * p_lastp[i];
                uint64_t n = sw_capital + proceeds;           // saturates like the hardware
                sw_capital = (n < sw_capital) ? ~0ull : n;
                closed[i] = proceeds > p_inv[i] ? 1 : proceeds < p_inv[i] ? 2 : 0;
                code[i] = SELL;
                p_pos[i] = p_hold[i] = 0;
                p_inv[i] = 0;
            }
        }
        for (uint32_t i = 0; i < n; i++) {                        // 2. BUY candidates
            if (p_fresh[i] && p_sig[i] == BUY) {
                uint32_t q = (p_max_lots == 0 || p_vol[i] < p_max_lots) ? p_vol[i] : p_max_lots;
                if (q > 0 && (uint64_t)p_pos[i] + q <= cfg_pos_limit[i]) {
                    cand[i] = 1;
                    qty[i] = q;
                }
            }
        }
        uint32_t rotated = 0;
        for (;;) {
            int32_t best = -1;                                    // 3. strongest first
            for (uint32_t j = 0; j < n; j++)
                if (cand[j] && !used[j] && (best < 0 || (rank && p_score[j] > p_score[best])))
                    best = (int32_t)j;
            if (best < 0)
                break;
            uint32_t i = (uint32_t)best;
            used[i] = 1;
            uint64_t cost = (uint64_t)p_lastp[i] * qty[i];
            uint32_t ok = !rw || cap_ok(i, cost);
            uint32_t bought = 0;
            if (sw_capital >= cost && ok) {
                sw_capital -= cost;
                bought = 1;
            } else if (rot && !rotated && ok) {                   // 4. rotation
                int32_t v = -1;
                for (uint32_t j = 0; j < n; j++) {
                    int64_t diff = (int64_t)p_score[i] - p_score[j];
                    if (p_pos[j] > 0 && !cand[j] && p_hold[j] >= p_min_hold && diff > (int64_t)p_margin &&
                        (v < 0 || p_score[j] < p_score[v]))
                        v = (int32_t)j;
                }
                if (v >= 0) {
                    uint64_t proceeds = (uint64_t)p_pos[v] * p_lastp[v];
                    uint64_t sum = sw_capital + proceeds;
                    if (sum < sw_capital || sum >= cost) {        // 65-bit compare
                        closed[v] = proceeds > p_inv[v] ? 1 : proceeds < p_inv[v] ? 2 : 0;
                        code[v] = ROT;
                        p_pos[v] = p_hold[v] = 0;
                        p_inv[v] = 0;
                        // cash + proceeds - cost, saturated at 2^64 - 1 like the hardware
                        sw_capital = (sum < sw_capital && cost <= sum) ? ~0ull : sum - cost;
                        rotated = bought = 1;
                    }
                }
            }
            if (bought) {
                if (p_pos[i] == 0)
                    p_hold[i] = 0;
                p_pos[i] += qty[i];
                p_inv[i] += cost;
                code[i] = BUY;
            }
        }
    }
    for (uint32_t i = 0; i < MAX_SYM; i++)                         // 5. holding time
        if (p_pos[i] > 0 && p_hold[i] < 255)
            p_hold[i]++;
    if (rw) {                                                      // 6. reweight, company order
        for (uint32_t i = 0; i < n; i++) {
            if (closed[i] == 1) {
                for (uint32_t j = 0; j < n; j++) {
                    if (j != i) {
                        uint32_t t = floor_take(p_w[j]);
                        p_w[j] -= t;
                        p_w[i] += t;
                    }
                }
            } else if (closed[i] == 2) {
                uint32_t share = floor_take(p_w[i]) >> share_shift(n);
                for (uint32_t j = 0; j < n; j++) {
                    if (j != i) {
                        p_w[j] += share;
                        p_w[i] -= share;
                    }
                }
            }
        }
    }
    uint32_t codes = 0;
    for (uint32_t i = 0; i < MAX_SYM; i++) {
        p_fresh[i] = 0;
        codes |= code[i] << (2 * i);
    }
    return codes;
}

static void write_port_config(void) {
    HFT_PORT_MODE   = p_mode_cfg;
    HFT_MAX_LOTS    = p_max_lots;
    HFT_MARGIN      = p_margin;
    HFT_ALLOC_PARAM = (p_min_hold & 0xFFu) | ((p_wshift & 31u) << 8) | ((p_capshift & 31u) << 16);
    HFT_W_FLOOR     = p_wfloor;
}

static void write_config(void) {
    for (uint32_t c = 0; c < hw_nmax; c++) {
        HFT_SYMBOL_SEL = c;
        HFT_POS_LIMIT  = cfg_pos_limit[c];
        HFT_BRK_HIGH   = cfg_brk_high[c];
        HFT_BRK_LOW    = cfg_brk_low[c];
        HFT_CAP_LO     = (uint32_t)cfg_cap[c];
        HFT_CAP_HI     = (uint32_t)(cfg_cap[c] >> 32);
    }
    HFT_SYMBOL_SEL  = 0;
    HFT_NUM_SYMBOLS = nsym;
    HFT_CASH_LO     = (uint32_t)cfg_starting_cash;
    HFT_CASH_HI     = (uint32_t)(cfg_starting_cash >> 32);
}

static void reset_model(void) {
    for (uint32_t c = 0; c < MAX_SYM; c++) {
        sw_hist[c][0] = sw_hist[c][1] = sw_hist[c][2] = 0;
        sw_warm[c] = 0;
        sw_acc_pv[c] = 0;
        sw_acc_v[c] = 0;
        sw_vsat[c] = 0;
        sw_position[c] = 0;
        sw_invested[c] = 0;
    }
    sw_capital = cfg_starting_cash;
    port_reset();
    HFT_CTRL = 1;                                           // clear the accelerator too
}

// position of company c as the hardware sees it (0 for a company that is not built)
static uint32_t hw_position(uint32_t c) {
    if (c >= hw_nmax)
        return 0;
    HFT_SYMBOL_SEL = c;
    return HFT_HW_POSITION;
}

// 8 decimal digits for the 7-segment display (uses the RV32M divider)
static uint32_t to_bcd(uint32_t v) {
    uint32_t out = 0;
    for (int i = 0; i < 8; i++) {
        out |= (v % 10u) << (4 * i);
        v /= 10u;
    }
    return out;
}

static void send_report(uint32_t id, uint32_t price, uint32_t vol, uint32_t hw_dec, uint32_t hw_lat,
                        uint32_t sw_dec, uint32_t sw_lat, uint32_t hw_pos) {
    // 40 bytes: header, id, price, vol, hw dec, hw lat, sw dec, sw lat, hw position, footer
    uart_send_u32(0xAA55AA55u);
    uart_send_u32(id);
    uart_send_u32(price);
    uart_send_u32(vol);
    uart_send_u32(hw_dec);
    uart_send_u32(hw_lat);
    uart_send_u32(sw_dec);
    uart_send_u32(sw_lat);
    uart_send_u32(hw_pos);
    uart_send_u32(0x55AA55AAu);
}

// ------------------------------------------------------------------ portfolio mode packets
static uint32_t port_mismatch;          // sticky: any HW/SW difference since the last RESET (LED2)

static void port_signal(uint32_t id, uint32_t c, uint32_t price, uint32_t vol) {
    uint64_t ma_sum;
    uint32_t ma_ok;
    uint32_t t0 = MMIO_CYCLE;
    uint32_t sw_dec = sw_signal(c, price, vol, &ma_sum, &ma_ok);
    port_tick(c, price, vol, sw_dec, ma_sum, ma_ok);
    uint32_t sw_lat = MMIO_CYCLE - t0;

    uint32_t ok = wait_status(STATUS_HW_DONE);
    ok = wait_status(STATUS_SCORES_RDY) && ok;         // the score divider runs in the background
    HFT_SYMBOL_SEL = c;
    uint32_t hw_dec = ok ? HFT_HW_DECISION : HW_TIMEOUT;
    uint32_t hw_lat = ok ? HFT_HW_LATENCY : 0;
    uint32_t hw_score = HFT_SCORE;
    HFT_STATUS = STATUS_TICK_READY | STATUS_HW_DONE;

    send_report(id, price, vol, hw_dec, hw_lat, sw_dec, sw_lat, hw_score);

    if (hw_dec != sw_dec || hw_score != (uint32_t)p_score[c])
        port_mismatch = 1;
    uint32_t led = 0;
    if (hw_dec == BUY)  led |= 1u << 0;
    if (hw_dec == SELL) led |= 1u << 1;
    if (port_mismatch || fw_fault) led |= 1u << 2;
    if (HFT_OVERRUN != 0) led |= 1u << 3;
    if (MMIO_SWITCH & 1u) led |= 1u << 14;
    MMIO_LED = led;
}

static void port_minute(uint32_t minute) {
    uint32_t hw_codes = 0, hw_lat = 0, kill = 0, timeout = 0;
    if (p_mode & MODE_PORT) {
        // the hardware started allocating the cycle this packet arrived
        if (!wait_status(STATUS_ALLOC_DONE))              // never seen: allocator did not finish
            timeout = 1;
        uint32_t r = HFT_ALLOC_CODES;
        hw_codes = r & 0xFFFFu;
        kill = (r >> 16) & 1u;                            // the kill switch as the allocator sampled it
        hw_lat = HFT_ALLOC_LAT;
    }
    uint32_t t0 = MMIO_CYCLE;
    uint32_t sw_codes = (p_mode & MODE_PORT) ? port_allocate(kill) : 0;
    uint32_t sw_lat = MMIO_CYCLE - t0;

    uint32_t cash_lo = HFT_HW_CASH_LO, cash_hi = HFT_HW_CASH_HI;
    uint32_t bad = timeout || hw_codes != sw_codes;
    if ((p_mode & MODE_PORT) && (cash_lo != (uint32_t)sw_capital || cash_hi != (uint32_t)(sw_capital >> 32)))
        bad = 1;
    uint32_t sum = 0;
    for (uint32_t c = 0; c < nsym; c++) {
        HFT_SYMBOL_SEL = c;
        uint32_t pos = HFT_HW_POSITION;
        uint32_t wh  = HFT_WEIGHT;                        // [15:0] weight, [23:16] minutes held
        uint32_t ilo = HFT_INV_LO, ihi = HFT_INV_HI;
        sum += (pos + ((wh & 0xFFFFu) << 16)) * (2 * c + 1);
        if ((p_mode & MODE_PORT) && (pos != p_pos[c] || (wh & 0xFFFFu) != p_w[c] || ((wh >> 16) & 0xFFu) != p_hold[c] ||
                                     ilo != (uint32_t)p_inv[c] || ihi != (uint32_t)(p_inv[c] >> 32)))
            bad = 1;
    }
    HFT_STATUS = STATUS_TICK_READY | STATUS_HW_DONE | STATUS_ALLOC_DONE;
    if (bad)
        port_mismatch = 1;
    send_report(CMD_ALLOCATE, cash_lo, cash_hi, hw_codes | (kill << 16) | (bad << 31), hw_lat, sw_codes, sw_lat, sum);

    // LED4.. LED11: BUY / SELL / ROT of companies 0..3 (2 bits each); 7-segment: cash (decimal)
    uint32_t led = (hw_codes & 0xFFu) << 4;
    if (port_mismatch || fw_fault) led |= 1u << 2;
    if (HFT_OVERRUN != 0) led |= 1u << 3;
    if (kill) led |= 1u << 14;
    MMIO_LED = led;
    MMIO_SEG = to_bcd(cash_lo % 100000000u);
    (void)minute;
}

int main(void) {
    // allocator defaults (= hft_mmio.v reset values); see the note at the declarations
    p_mode_cfg = 0; p_mode = 0; p_max_lots = 0;
    p_margin = 1049; p_min_hold = 5; p_wshift = 3; p_capshift = 14; p_wfloor = 4096;
    hw_nmax = HFT_N_MAX;
    if (hw_nmax == 0 || hw_nmax > MAX_SYM)
        hw_nmax = 1;
    nsym = 1;
    for (uint32_t c = 0; c < MAX_SYM; c++) {
        cfg_pos_limit[c] = CFG_POS_LIMIT;
        cfg_brk_high[c]  = CFG_BRK_HIGH;
        cfg_brk_low[c]   = CFG_BRK_LOW;
        cfg_cap[c]       = 0;
    }
    cfg_starting_cash = START_CAPITAL;
    write_config();
    write_port_config();
    port_reset();
    HFT_STATUS    = STATUS_TICK_READY | STATUS_HW_DONE;   // drop anything stale
    sw_capital    = cfg_starting_cash;
    MMIO_SEG      = 0;

    for (;;) {
        while (!(HFT_STATUS & STATUS_TICK_READY))
            ;
        uint32_t id    = HFT_TICK_ID;
        uint32_t price = HFT_TICK_PRICE;
        uint32_t vol   = HFT_TICK_VOL;
        uint32_t c     = (id & SYM_MASK) >> 28;            // company
        uint32_t cmd   = id & ~SYM_MASK;
        // TICK_READY stays set until this packet is finished: a packet that arrives
        // meanwhile is dropped for the hardware and the software alike (OVERRUN)

        if (id & 0x80000000u) {                            // command from the PC
            if (cmd == CMD_RESET) {
                reset_model();
                port_mismatch = 0;
                fw_fault = 0;
            } else if (cmd == CMD_CFG_CASH) {
                cfg_starting_cash = (uint64_t)price | ((uint64_t)vol << 32);
                write_config();
            } else if (cmd == CMD_CFG_NSYM) {
                nsym = (price == 0) ? 1 : (price > hw_nmax) ? hw_nmax : price;
                write_config();
            } else if (id == CMD_ALLOCATE) {
                port_minute(price);
                continue;
            } else if (cmd == CMD_CFG_MODE) {
                p_mode_cfg = price & 15u;
                p_max_lots = vol;
                write_port_config();
            } else if (cmd == CMD_CFG_ROT) {
                p_margin   = price;
                p_min_hold = vol & 255u;
                write_port_config();
            } else if (cmd == CMD_CFG_W) {
                p_wshift   = price & 31u;
                p_capshift = (price >> 8) & 31u;
                p_wfloor   = vol & 0xFFFFu;
                write_port_config();
            } else if (cmd == CMD_ALLOCATE) {
                // ALLOCATE with a company number: ignored (the hardware only starts on 0x80000006;
                // CFG_MODE / CFG_ROT / CFG_W are global and are handled above with or without one)
            } else if (c < hw_nmax) {                      // per-company configuration
                if (cmd == CMD_CFG_BRK) {
                    cfg_brk_high[c] = price;
                    cfg_brk_low[c]  = vol;
                } else if (cmd == CMD_CFG_LIMIT) {
                    cfg_pos_limit[c] = price;
                } else if (cmd == CMD_CFG_CAP) {
                    cfg_cap[c] = (uint64_t)price | ((uint64_t)vol << 32);
                }
                write_config();
            }
            // report: that company's position; for CFG_NSYM the number of companies now
            // traded (lets the PC see that the bitstream has fewer engines than it asked for)
            uint32_t pos = (cmd == CMD_CFG_NSYM) ? nsym : (cmd == CMD_CFG_MODE) ? (HFT_PORT_MODE & 0xFFu)
                                                                  : hw_position(c);
            HFT_STATUS = STATUS_TICK_READY | STATUS_HW_DONE;
            MMIO_LED = 0;
            MMIO_SEG = 0;
            send_report(id, price, vol, 0, 0, 0, 0, pos);
            continue;
        }

        if (c >= nsym) {                                   // company not traded: hardware ignores it too
            HFT_STATUS = STATUS_TICK_READY;
            send_report(id, price, vol, 0, 0, 0, 0, 0);
            continue;
        }

        if (p_mode & MODE_PORT) {                          // portfolio mode: signal + score only
            port_signal(id, c, price, vol);
            continue;
        }

        // the kill state the hardware latched with THIS packet (not a fresh read of SW0, which
        // could differ if the switch moved since the tick arrived)
        uint32_t kill  = (HFT_STATUS & STATUS_KILL) ? 1u : 0u;
        uint32_t t0    = MMIO_CYCLE;
        uint32_t sw_dec = sw_decide(c, price, vol, kill);
        uint32_t sw_lat = MMIO_CYCLE - t0;

        uint32_t ok = wait_status(STATUS_HW_DONE);
        HFT_SYMBOL_SEL = c;
        uint32_t hw_dec = ok ? HFT_HW_DECISION : HW_TIMEOUT;
        uint32_t hw_lat = ok ? HFT_HW_LATENCY : 0;
        uint32_t hw_pos = HFT_HW_POSITION;
        HFT_STATUS = STATUS_TICK_READY | STATUS_HW_DONE;   // this packet is finished

        send_report(id, price, vol, hw_dec, hw_lat, sw_dec, sw_lat, hw_pos);

        // board display: that company's hardware position (decimal) on the 7-segment display,
        // with the company number in the leftmost digit when several companies are traded;
        // LED0 BUY, LED1 SELL, LED2 HW/SW mismatch, LED3 packets were dropped (the PC sent
        // faster than the board answers), LED14 kill switch, LED15 halted
        uint32_t led = 0;
        if (hw_dec == BUY)  led |= 1u << 0;
        if (hw_dec == SELL) led |= 1u << 1;
        if (hw_dec != sw_dec || hw_pos != sw_position[c] || fw_fault) led |= 1u << 2;
        if (HFT_OVERRUN != 0) led |= 1u << 3;
        if (kill) led |= 1u << 14;
        MMIO_LED = led;
        uint32_t seg = to_bcd(hw_pos);
        if (nsym > 1)
            seg = (seg & 0x0FFFFFFFu) | (c << 28);
        MMIO_SEG = seg;
    }
    return 0;
}
