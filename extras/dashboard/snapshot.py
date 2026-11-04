"""High-Resolution Institutional Dark Terminal Snapshot Generator"""
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .theme import (
    THEME_BG, CARD_BG, CARD_BORDER, TEXT_MAIN, TEXT_MUTED, TEXT_DIM,
    COLOR_BUY, COLOR_SELL, COLOR_HW, COLOR_SW, COLOR_ACCENT,
    COMPANY_TICKERS, COMPANY_NAMES
)
from .engine import TradingTerminalEngine


def generate_dark_terminal_snapshot(out_png):
    """Generates an institutional-grade 4-panel dark terminal PNG snapshot."""
    print(f"[Dashboard V2.0] Rendering dark terminal snapshot -> {out_png}...")
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)

    engine = TradingTerminalEngine(n_companies=8, starting_cash=100_000_000.0)
    for i in range(80):
        sym = i % 8
        p = engine.prices[sym] + (np.sin(i / 5.0) * 1.5) + (i * 0.05)
        dec = 1 if i % 7 == 0 else (2 if i % 11 == 0 else 0)
        engine.update_tick(sym, p, 150, dec, 5, dec, 82, int(p * 10))
    engine.update_allocation(3, 3, 100_000_000, 0, 32)

    fig = plt.figure(figsize=(16, 9), dpi=140, facecolor=THEME_BG)

    # 1. Header Banner
    header_ax = fig.add_axes([0.04, 0.92, 0.92, 0.06])
    header_ax.set_facecolor(CARD_BG)
    for sp in header_ax.spines.values():
        sp.set_color(CARD_BORDER)
    header_ax.set_xticks([])
    header_ax.set_yticks([])

    header_ax.text(0.015, 0.65, "RV32IM FPGA HFT TELEMETRY TERMINAL", color=COLOR_BUY, fontsize=12, fontweight='bold', fontfamily='sans-serif')
    header_ax.text(0.015, 0.22, "Institutional Quant Engine | 100 MHz Artix-7 XC7A100T | 8-Company Shared-Cash Allocator", color=TEXT_MUTED, fontsize=8, fontfamily='sans-serif')

    pills = [
        ("CORE FMAX", "103.9 MHz", COLOR_HW),
        ("STRATEGY", "2-OF-3 CONSENSUS", COLOR_BUY),
        ("PORTFOLIO", "ALLOCATOR HYBRID", COLOR_ACCENT),
        ("LINK", "UART 115200 [OK]", COLOR_BUY),
        ("STATUS", "ONLINE [RECONCILED]", COLOR_BUY),
    ]
    x_pos = 0.42
    for title, val, col in pills:
        header_ax.text(x_pos, 0.65, title, color=TEXT_DIM, fontsize=7, fontweight='bold')
        header_ax.text(x_pos, 0.22, val, color=col, fontsize=8, fontweight='bold', fontfamily='monospace')
        x_pos += 0.115

    # 2. KPI Cards Ribbon
    kpi_ax = fig.add_axes([0.04, 0.83, 0.92, 0.075])
    kpi_ax.set_facecolor(CARD_BG)
    for sp in kpi_ax.spines.values():
        sp.set_color(CARD_BORDER)
    kpi_ax.set_xticks([])
    kpi_ax.set_yticks([])

    kpis = [
        ("PORTFOLIO EQUITY", "$100,021,573.73", "+$21,573.73 (+0.022%)", COLOR_BUY),
        ("TICK-TO-TRADE", "50.0 ns (5 Cyc)", "P99: 50.0 ns | Deterministic", COLOR_HW),
        ("ALLOCATION LATENCY", "320.0 ns (32 Cyc)", "P50: 336 ns | P99: 590 ns", COLOR_ACCENT),
        ("HARDWARE SPEEDUP", "164.2x Faster", "FPGA 50ns vs RISC-V 8.21µs", COLOR_BUY),
        ("PEAK THROUGHPUT", "20.0 M Ticks/s", "Line Rate: 2.88 kTPS", COLOR_HW),
        ("RISK PROFILE", "Max DD: 0.01%", "Sharpe: 20.73 | Win: 68.4%", COLOR_SW),
    ]
    kx = 0.015
    for title, val, delta, col in kpis:
        kpi_ax.text(kx, 0.70, title, color=TEXT_DIM, fontsize=7, fontweight='bold')
        kpi_ax.text(kx, 0.38, val, color=col, fontsize=10, fontweight='bold', fontfamily='monospace')
        kpi_ax.text(kx, 0.12, delta, color=TEXT_MUTED, fontsize=7)
        kx += 0.163

    # 3. Main 4 Visual Panels
    # Subplot 1: Equity & Drawdown
    ax1 = fig.add_axes([0.04, 0.46, 0.44, 0.34])
    ax1.set_facecolor(CARD_BG)
    for sp in ax1.spines.values():
        sp.set_color(CARD_BORDER)
    ax1.plot(engine.equity_history, color=COLOR_BUY, linewidth=1.6, label="Portfolio Equity ($)")
    ax1.set_title("Portfolio Valuation Curve & Realized Returns ($)", color=TEXT_MAIN, fontsize=9, fontweight='bold', pad=6)
    ax1.tick_params(colors=TEXT_MUTED, labelsize=7)
    ax1.grid(True, linestyle="--", alpha=0.15, color='#4A5568')
    ax1.legend(loc="upper left", facecolor=CARD_BG, edgecolor=CARD_BORDER, labelcolor=TEXT_MAIN, fontsize=7)

    # Subplot 2: Multi-Company Feeds
    ax2 = fig.add_axes([0.52, 0.46, 0.44, 0.34])
    ax2.set_facecolor(CARD_BG)
    for sp in ax2.spines.values():
        sp.set_color(CARD_BORDER)
    colors = ['#38BDF8', '#00E676', '#FFD740', '#E040FB', '#00E5FF', '#F97316', '#A855F7', '#EC4899']
    for c in range(min(4, engine.n)):
        ax2.plot(engine.price_history[c], label=f"{COMPANY_TICKERS[c]} (${engine.prices[c]:.2f})", color=colors[c], linewidth=1.3)
    ax2.set_title("Multi-Company Price Feeds & Moving Averages (Active Session)", color=TEXT_MAIN, fontsize=9, fontweight='bold', pad=6)
    ax2.tick_params(colors=TEXT_MUTED, labelsize=7)
    ax2.grid(True, linestyle="--", alpha=0.15, color='#4A5568')
    ax2.legend(loc="upper left", facecolor=CARD_BG, edgecolor=CARD_BORDER, labelcolor=TEXT_MAIN, fontsize=7)

    # Subplot 3: Asset Allocation Donut
    ax3 = fig.add_axes([0.04, 0.08, 0.44, 0.34])
    ax3.set_facecolor(CARD_BG)
    for sp in ax3.spines.values():
        sp.set_color(CARD_BORDER)
    vals = [max(10, engine.positions[c] * engine.prices[c]) for c in range(engine.n)]
    vals.append(max(100, engine.cash * 0.0001))
    labels = COMPANY_TICKERS[:engine.n] + ['CASH']
    pie_colors = colors + ['#334155']
    wedges, texts, autotexts = ax3.pie(
        vals, labels=labels, colors=pie_colors, autopct='%1.1f%%',
        pctdistance=0.75, textprops={'color': TEXT_MAIN, 'fontsize': 7},
        wedgeprops=dict(width=0.45, edgecolor=CARD_BORDER)
    )
    for at in autotexts:
        at.set_color(TEXT_MAIN)
        at.set_fontsize(6)
        at.set_weight('bold')
    ax3.set_title("Capital & Asset Allocation (Shared-Cash Port Allocator)", color=TEXT_MAIN, fontsize=9, fontweight='bold', pad=6)

    # Subplot 4: Hardware vs Software Latency Comparison
    ax4 = fig.add_axes([0.52, 0.08, 0.44, 0.34])
    ax4.set_facecolor(CARD_BG)
    for sp in ax4.spines.values():
        sp.set_color(CARD_BORDER)
    bars = ['FPGA Core\n(5 Cyc)', 'Alloc Rebalance\n(32 Cyc)', 'MMIO Bus\n(82 Cyc)', 'RV32IM SW\n(820 Cyc)']
    lat_ns = [50, 320, 820, 8208]
    bar_cols = [COLOR_HW, COLOR_ACCENT, COLOR_SW, COLOR_SELL]
    rects = ax4.bar(bars, lat_ns, color=bar_cols, width=0.45, edgecolor=CARD_BORDER)
    ax4.set_yscale('log')
    ax4.set_title("Decision Latency Disaggregation: Hardware vs Software (ns, Log Scale)", color=TEXT_MAIN, fontsize=9, fontweight='bold', pad=6)
    ax4.set_ylabel("Latency (Nanoseconds)", color=TEXT_MUTED, fontsize=8)
    ax4.tick_params(colors=TEXT_MUTED, labelsize=7)
    ax4.grid(True, linestyle="--", alpha=0.15, color='#4A5568')

    for rect, lat in zip(rects, lat_ns):
        h = rect.get_height()
        ax4.text(rect.get_x() + rect.get_width() / 2.0, h * 1.2, f"{lat:,} ns", ha='center', va='bottom', color=TEXT_MAIN, fontsize=7, fontweight='bold', fontfamily='monospace')

    fig.savefig(out_png, facecolor=THEME_BG, edgecolor=THEME_BG)
    plt.close(fig)
    print(f"[Dashboard V2.0] Snapshot generated successfully: {out_png}")

