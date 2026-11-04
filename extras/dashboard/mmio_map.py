"""MMIO Register Definitions and Live Decoders (0x3000_0000 Base)"""

MMIO_REGISTERS = [
    (0x00, 0, "POS_LIMIT", "RW(sel)", "Per-company max inventory limit (lots)"),
    (0x04, 1, "BRK_HIGH", "RW(sel)", "Breakout upper threshold (cents)"),
    (0x08, 2, "BRK_LOW", "RW(sel)", "Breakout lower threshold (cents)"),
    (0x0C, 3, "TICK_ID", "R", "Sequence ID & company bits [30:28]"),
    (0x10, 4, "TICK_PRICE", "R", "Ingress tick price in cents"),
    (0x14, 5, "TICK_VOL", "R", "Ingress tick volume in lots (1 lot = 1,000 shs)"),
    (0x18, 6, "HW_DECISION", "R(sel)", "HW Decision (0:NONE, 1:BUY, 2:SELL)"),
    (0x1C, 7, "HW_LATENCY", "R(sel)", "Hardware compute latency (clock cycles)"),
    (0x20, 8, "HW_POSITION", "R(sel)", "Current inventory position in lots"),
    (0x24, 9, "STATUS", "Mixed", "tick_rdy, hw_done, tx_rdy, alloc_done, alloc_busy, strat"),
    (0x28, 10, "UART_TX", "W", "Write data byte to UART TX buffer"),
    (0x2C, 11, "OVERRUN", "R", "Ingress tick buffer overrun drop counter"),
    (0x30, 12, "CTRL", "W", "Control: bit 0 clears engines & diagnostic counters"),
    (0x34, 13, "CASH_LO", "RW", "Shared portfolio cash balance [31:0] (cents)"),
    (0x38, 14, "CASH_HI", "RW", "Shared portfolio cash balance [63:32]"),
    (0x3C, 15, "HW_CASH_LO", "R", "Accelerator committed cash [31:0]"),
    (0x40, 16, "SYMBOL_SEL", "RW", "Active company selector index [2:0] (0..7)"),
    (0x44, 17, "NUM_SYMBOLS", "RW", "Active companies count N (1..8)"),
    (0x48, 18, "CASH_CAP_LO", "RW(sel)", "Per-company cash ceiling [31:0]"),
    (0x4C, 19, "CASH_CAP_HI", "RW(sel)", "Per-company cash ceiling [63:32]"),
    (0x50, 20, "HW_CASH_HI", "R", "Accelerator committed cash [63:32]"),
    (0x54, 21, "BAD_SYMBOL", "R", "Count of ticks with symbol >= NUM_SYMBOLS"),
    (0x58, 22, "N_MAX", "R", "Hardware max companies parameter (8)"),
    (0x5C, 23, "INVESTED_LO", "R(sel)", "Total capital invested in company [31:0]"),
    (0x60, 24, "INVESTED_HI", "R(sel)", "Total capital invested in company [63:32]"),
    (0x64, 25, "PORT_MODE", "RW", "Mode config: [0]=port, [1]=rank, [2]=rot, [3]=reweight"),
    (0x68, 26, "MAX_LOTS", "RW", "Max lots per BUY allocation (0 = full bar vol)"),
    (0x6C, 27, "MARGIN", "RW", "Rotation momentum threshold margin (2^-20)"),
    (0x70, 28, "ALLOC_PARAM", "RW", "min_hold[7:0], wshift[12:8], capshift[20:16]"),
    (0x74, 29, "W_FLOOR", "RW", "Minimum portfolio weight floor (Q15, default 4096)"),
    (0x78, 30, "ALLOC_CODES", "R", "2-bit allocation action codes per company [15:0]"),
    (0x7C, 31, "ALLOC_LAT", "R", "Allocator execution latency in clock cycles"),
    (0x80, 32, "ALLOC_COUNT", "R", "Total portfolio allocation rounds executed"),
    (0x84, 33, "SCORE", "R(sel)", "Momentum ranking score (signed Q20)"),
    (0x88, 34, "WEIGHT", "R(sel)", "[15:0] Weight of 32768, [23:16] hold minutes"),
    (0x8C, 35, "FRAME_ERR", "R", "UART receiver framing errors encountered"),
    (0x90, 36, "ENG_DROP", "R", "Engine busy dropped tick events"),
    (0x94, 37, "VWAP_OFF", "R", "VWAP overflow/saturation protection bitmask"),
    (0x98, 38, "PKT_ABORT", "R", "UART framing error packet abort counter"),
    (0x9C, 39, "PKT_TIMEOUT", "R", "UART inter-byte parser timeout counter (5ms)"),
    (0xA0, 40, "STRATEGY_CFG", "RW", "[0]=strat, [1]=override, [31:8]=sw_change_cnt"),
    (0xA4, 41, "STRAT_ORIG_DEC", "R", "Decisions under original 2-of-3 strategy"),
    (0xA8, 42, "STRAT_MA_DEC", "R", "Decisions under MA-only strategy"),
    (0xAC, 43, "AUDIT_TX_ID", "R", "Monotonic transaction audit sequence ID")
]


def decode_mmio_val(reg_name, raw_val):
    """Translates raw 32-bit register values to human-readable physical representations."""
    if reg_name in ("TICK_PRICE", "BRK_HIGH", "BRK_LOW"):
        return f"${raw_val / 100.0:.2f}"
    elif reg_name in ("CASH_LO", "HW_CASH_LO", "CASH_CAP_LO", "INVESTED_LO"):
        return f"${raw_val / 100.0:,.2f}"
    elif reg_name in ("POS_LIMIT", "TICK_VOL", "HW_POSITION"):
        return f"{raw_val:,} lots"
    elif reg_name == "HW_DECISION":
        names = {0: "NONE", 1: "BUY", 2: "SELL"}
        return f"{names.get(raw_val, 'UNKNOWN')} ({raw_val})"
    elif reg_name in ("HW_LATENCY", "ALLOC_LAT"):
        return f"{raw_val} cyc ({raw_val * 10} ns)"
    elif reg_name == "STATUS":
        strat = "MA-Only" if (raw_val & 0x80) else "2-of-3"
        kill = "KILL_ACT" if (raw_val & 0x40) else "NORMAL"
        return f"[{strat} | {kill} | rdy={raw_val & 1}]"
    elif reg_name == "STRATEGY_CFG":
        active = "MA-Only (SW0=1)" if (raw_val & 1) else "Original 2-of-3 (SW0=0)"
        switches = raw_val >> 8
        return f"{active} [switches: {switches}]"
    elif reg_name == "WEIGHT":
        w = raw_val & 0xFFFF
        hold = (raw_val >> 16) & 0xFF
        pct = (w / 32768.0) * 100.0
        return f"{pct:.2f}% (Hold: {hold}m)"
    elif reg_name == "SCORE":
        return f"{raw_val:+d}"
    elif reg_name == "PORT_MODE":
        modes = []
        if raw_val & 1: modes.append("Port")
        if raw_val & 2: modes.append("Rank")
        if raw_val & 4: modes.append("Rotate")
        if raw_val & 8: modes.append("Reweight")
        return "+".join(modes) if modes else "Independent"
    else:
        return f"{raw_val:,}"

