"""Modern Institutional Quant Trading Terminal GUI (Tkinter + Matplotlib)"""
import csv
import os
import random
import threading
import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import matplotlib
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import pandas as pd

from .theme import (
    THEME_BG, CARD_BG, CARD_BG_SECONDARY, CARD_BORDER, CARD_BORDER_ACCENT,
    TEXT_MAIN, TEXT_MUTED, TEXT_DIM,
    COLOR_BUY, COLOR_SELL, COLOR_HOLD, COLOR_ROT, COLOR_HW, COLOR_SW, COLOR_ACCENT, COLOR_WARN,
    FONT_HEADER, FONT_TITLE, FONT_SUB, FONT_BADGE, FONT_MONO, FONT_MONO_BOLD, FONT_HERO,
    COMPANY_TICKERS, COMPANY_NAMES, COMPANY_BASE_PRICES, apply_mpl_dark_theme
)
from .mmio_map import MMIO_REGISTERS, decode_mmio_val
from .engine import TradingTerminalEngine

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRAS = os.path.dirname(HERE)
ROOT = os.path.dirname(EXTRAS)


class HFTTradingTerminalGUI:
    """Institutional High-Frequency Trading & RV32IM Telemetry Terminal."""
    def __init__(self, root, engine=None, serial_if=None, mode="LIVE SIMULATION"):
        self.root = root
        self.engine = engine or TradingTerminalEngine(n_companies=8, starting_cash=100_000_000.0)
        self.serial_if = serial_if
        self.mode = mode

        # Execution Controls State
        self.is_running = True
        self.is_paused = False
        self.is_demo_mode = True
        self.replay_speed = 10.0
        self.selected_company_idx = 0
        self.search_query = ""

        # Window Configuration
        self.root.title("RV32IM FPGA HFT TELEMETRY TERMINAL — Institutional Quant Terminal V2.0")
        self.root.geometry("1560x940")
        self.root.minsize(1280, 800)
        self.root.configure(bg=THEME_BG)

        self.apply_ttk_styles()
        self.build_ui()
        self.start_worker_threads()
        self.root.after(100, self.periodic_ui_refresh)

    def apply_ttk_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('default')
        self.style.configure(".", background=THEME_BG, foreground=TEXT_MAIN, font=FONT_SUB)
        self.style.configure("TNotebook", background=THEME_BG, borderwidth=0)
        self.style.configure("TNotebook.Tab", background=CARD_BG, foreground=TEXT_MUTED, padding=[18, 9], font=FONT_TITLE)
        self.style.map("TNotebook.Tab", background=[("selected", CARD_BG_SECONDARY)], foreground=[("selected", COLOR_HW)])

        self.style.configure("Treeview", background="#0E121A", foreground=TEXT_MAIN, fieldbackground="#0E121A",
                             rowheight=26, font=FONT_MONO, borderwidth=0)
        self.style.configure("Treeview.Heading", background=CARD_BG, foreground=TEXT_MUTED, font=FONT_TITLE, borderwidth=1)
        self.style.map("Treeview", background=[('selected', '#1E3A8A')], foreground=[('selected', '#FFFFFF')])

    def build_ui(self):
        # 1. Top Control & System Status Bar (Header)
        self.build_header()

        # 2. KPI Hero Ribbon
        self.build_kpi_ribbon()

        # 3. Main Multi-Tab Workspace
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

        # Tab 1: Live Trading & 8-Company Monitor
        self.tab_trading = tk.Frame(self.notebook, bg=THEME_BG)
        self.notebook.add(self.tab_trading, text="  1. Live Trading & Multi-Stock Monitor  ")
        self.build_trading_tab()

        # Tab 2: Hardware Telemetry, Latencies & RV32IM Pipeline Inspector
        self.tab_hardware = tk.Frame(self.notebook, bg=THEME_BG)
        self.notebook.add(self.tab_hardware, text="  2. Hardware Telemetry & Pipeline Inspector  ")
        self.build_hardware_tab()

        # Tab 3: Scalability, Ablation & Benchmark Explorer
        self.tab_benchmarks = tk.Frame(self.notebook, bg=THEME_BG)
        self.notebook.add(self.tab_benchmarks, text="  3. Scalability, Ablation & Benchmarks  ")
        self.build_benchmarks_tab()

    # -----------------------------------------------------------------------
    # 1. Header & System Status
    # -----------------------------------------------------------------------
    def build_header(self):
        hdr = tk.Frame(self.root, bg=CARD_BG, height=54, bd=0, highlightthickness=1, highlightbackground=CARD_BORDER)
        hdr.pack(fill=tk.X, side=tk.TOP, padx=0, pady=0)

        # Title & Subtitle
        t_box = tk.Frame(hdr, bg=CARD_BG)
        t_box.pack(side=tk.LEFT, padx=14, pady=6)
        tk.Label(t_box, text="RV32IM HFT ACCELERATOR", fg=COLOR_HW, bg=CARD_BG, font=FONT_HEADER).pack(anchor="w")
        tk.Label(t_box, text="Institutional Terminal V2.0 | Nexys A7 FPGA", fg=TEXT_DIM, bg=CARD_BG, font=("Segoe UI", 7, "bold")).pack(anchor="w")

        # Source Selector
        s_box = tk.Frame(hdr, bg=CARD_BG)
        s_box.pack(side=tk.LEFT, padx=10)
        tk.Label(s_box, text="SOURCE:", fg=TEXT_DIM, bg=CARD_BG, font=("Segoe UI", 7, "bold")).pack(anchor="w")
        self.combo_source = ttk.Combobox(s_box, values=[
            "Live UART / Nexys A7 (COM6)",
            "RTL Simulation (Python Model)",
            "Real Market Feed (Yahoo 1-min)",
            "Synthetic Random Walk (SYN1-8)"
        ], width=26, state="readonly", font=FONT_SUB)
        self.combo_source.current(1)
        self.combo_source.pack()

        # Action Buttons
        btn_box = tk.Frame(hdr, bg=CARD_BG)
        btn_box.pack(side=tk.LEFT, padx=8)

        self.btn_run = tk.Button(btn_box, text="Pause", bg="#334155", fg=TEXT_MAIN, bd=1, font=FONT_SUB, padx=8, command=self.toggle_pause)
        self.btn_run.pack(side=tk.LEFT, padx=2)

        self.btn_step = tk.Button(btn_box, text="Step Tick", bg="#334155", fg=TEXT_MAIN, bd=1, font=FONT_SUB, padx=6, command=self.step_tick)
        self.btn_step.pack(side=tk.LEFT, padx=2)

        self.btn_reset = tk.Button(btn_box, text="Reset", bg="#334155", fg=TEXT_MAIN, bd=1, font=FONT_SUB, padx=6, command=self.reset_engine)
        self.btn_reset.pack(side=tk.LEFT, padx=2)

        # Strategy Switcher (SW0)
        self.btn_strat = tk.Button(btn_box, text="Strategy (SW0)", bg="#1E293B", fg=COLOR_BUY, bd=1, font=FONT_TITLE, padx=8, command=self.toggle_strategy)
        self.btn_strat.pack(side=tk.LEFT, padx=6)

        # System Health Status Pills
        pills_box = tk.Frame(hdr, bg=CARD_BG)
        pills_box.pack(side=tk.RIGHT, padx=12, pady=6)

        self.pill_fmax = self.create_status_pill(pills_box, "CLOCK", "100.0 MHz", COLOR_HW)
        self.pill_strat = self.create_status_pill(pills_box, "STRATEGY", "2-of-3 (SW0=0)", COLOR_BUY)
        self.pill_port = self.create_status_pill(pills_box, "PORTFOLIO", "Hybrid Alloc", COLOR_ACCENT)
        self.pill_link = self.create_status_pill(pills_box, "UART LINK", "115200 [OK]", COLOR_BUY)
        self.pill_health = self.create_status_pill(pills_box, "HEALTH", "HEALTHY", COLOR_BUY)

        # Export & Demo Toggle
        tk.Button(hdr, text="Export Snapshot", bg="#2563EB", fg="#FFFFFF", bd=0, font=FONT_TITLE, padx=10, pady=4,
                  command=self.export_snapshot_dialog).pack(side=tk.RIGHT, padx=8)

    def create_status_pill(self, parent, label, val, color):
        p = tk.Frame(parent, bg=CARD_BG_SECONDARY, padx=8, pady=2, highlightthickness=1, highlightbackground=CARD_BORDER)
        p.pack(side=tk.LEFT, padx=4)
        tk.Label(p, text=label, fg=TEXT_DIM, bg=CARD_BG_SECONDARY, font=("Segoe UI", 6, "bold")).pack(anchor="w")
        v = tk.Label(p, text=val, fg=color, bg=CARD_BG_SECONDARY, font=FONT_BADGE)
        v.pack(anchor="w")
        return v

    # -----------------------------------------------------------------------
    # 2. KPI Hero Ribbon
    # -----------------------------------------------------------------------
    def build_kpi_ribbon(self):
        ribbon = tk.Frame(self.root, bg=CARD_BG, height=68, bd=0, highlightthickness=1, highlightbackground=CARD_BORDER)
        ribbon.pack(fill=tk.X, padx=12, pady=8)

        self.kpi_equity, self.kpi_equity_sub = self.create_hero_card(
            ribbon, "PORTFOLIO EQUITY & NET PNL", "$100,021,573.73", "+$21,573.73 (+0.022%)", COLOR_BUY
        )
        self.kpi_core_lat, self.kpi_core_lat_sub = self.create_hero_card(
            ribbon, "TICK-TO-TRADE LATENCY", "50.0 ns (5 cyc)", "P50: 50ns | P99: 50ns", COLOR_HW
        )
        self.kpi_alloc_lat, self.kpi_alloc_lat_sub = self.create_hero_card(
            ribbon, "ALLOCATION REBALANCE", "320.0 ns (32 cyc)", "Min: 13c | Max: 64c", COLOR_ACCENT
        )
        self.kpi_speedup, self.kpi_speedup_sub = self.create_hero_card(
            ribbon, "HARDWARE SPEEDUP", "164.2x Faster", "FPGA 50ns vs RISC-V 8.21µs", COLOR_BUY
        )
        self.kpi_thru, self.kpi_thru_sub = self.create_hero_card(
            ribbon, "THROUGHPUT & LINK RATE", "20.0 M Ticks/s", "Line Rate: 2.88 kTPS", COLOR_HW
        )
        self.kpi_risk, self.kpi_risk_sub = self.create_hero_card(
            ribbon, "RISK & EXECUTION PROFILE", "Max DD: 0.01%", "Sharpe: 20.73 | Win: 68.4%", COLOR_SW
        )

    def create_hero_card(self, parent, title, main_val, sub_val, main_color):
        card = tk.Frame(parent, bg=CARD_BG, padx=12, pady=6)
        card.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        tk.Label(card, text=title, fg=TEXT_MUTED, bg=CARD_BG, font=("Segoe UI", 7, "bold")).pack(anchor="w")
        v = tk.Label(card, text=main_val, fg=main_color, bg=CARD_BG, font=FONT_HERO)
        v.pack(anchor="w")
        s = tk.Label(card, text=sub_val, fg=TEXT_DIM, bg=CARD_BG, font=("Consolas", 8))
        s.pack(anchor="w")
        return v, s

    # -----------------------------------------------------------------------
    # 3. Tab 1: Live Trading & 8-Company Monitor
    # -----------------------------------------------------------------------
    def build_trading_tab(self):
        # Left Panel (Quote Matrix & Order Tape)
        left = tk.Frame(self.tab_trading, bg=THEME_BG, width=780)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6), pady=6)

        # 8-Company Quote Table
        tbl_card = tk.Frame(left, bg=CARD_BG, bd=0, highlightthickness=1, highlightbackground=CARD_BORDER)
        tbl_card.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        th_bar = tk.Frame(tbl_card, bg=CARD_BG)
        th_bar.pack(fill=tk.X, padx=10, pady=6)
        tk.Label(th_bar, text="8-COMPANY REAL-TIME PORTFOLIO & TELEMETRY MATRIX", fg=TEXT_MAIN, bg=CARD_BG, font=FONT_TITLE).pack(side=tk.LEFT)
        tk.Label(th_bar, text="Double-click row to focus chart", fg=TEXT_DIM, bg=CARD_BG, font=FONT_SUB).pack(side=tk.RIGHT)

        cols = ("Ticker", "Price ($)", "Bid/Ask", "Volume", "4-MA ($)", "VWAP ($)", "Momentum", "Signal", "Holding", "Cap ($)", "Weight", "PnL ($)")
        self.quote_tree = ttk.Treeview(tbl_card, columns=cols, show='headings', height=8)
        for c in cols:
            self.quote_tree.heading(c, text=c)
            w = 85 if c in ("Price ($)", "Bid/Ask", "4-MA ($)", "VWAP ($)", "Cap ($)", "PnL ($)") else 65
            self.quote_tree.column(c, width=w, anchor="center")
        self.quote_tree.column("Ticker", width=70, anchor="w")
        self.quote_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.quote_tree.bind("<Double-1>", self.on_quote_selected)

        # Live Order & Signal Tape
        tape_card = tk.Frame(left, bg=CARD_BG, height=200, bd=0, highlightthickness=1, highlightbackground=CARD_BORDER)
        tape_card.pack(fill=tk.BOTH, expand=True)

        t_bar = tk.Frame(tape_card, bg=CARD_BG)
        t_bar.pack(fill=tk.X, padx=10, pady=6)
        tk.Label(t_bar, text="LIVE ORDER & SIGNAL TAPE (HARDWARE EXECUTION FEED)", fg=TEXT_MAIN, bg=CARD_BG, font=FONT_TITLE).pack(side=tk.LEFT)
        tk.Button(t_bar, text="Export CSV", bg="#334155", fg=TEXT_MAIN, bd=0, font=FONT_SUB, padx=6, command=self.export_tape_csv).pack(side=tk.RIGHT)

        tape_cols = ("Timestamp", "TID", "Ticker", "Signal", "Exec Action", "Price ($)", "Lots", "Latency", "Status")
        self.tape_tree = ttk.Treeview(tape_card, columns=tape_cols, show='headings', height=6)
        for c in tape_cols:
            self.tape_tree.heading(c, text=c)
            self.tape_tree.column(c, width=75, anchor="center")
        self.tape_tree.column("Timestamp", width=95, anchor="center")
        self.tape_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Right Panel (Interactive Equity & Technical Charts)
        right = tk.Frame(self.tab_trading, bg=THEME_BG, width=720)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(6, 0), pady=6)

        c_card = tk.Frame(right, bg=CARD_BG, bd=0, highlightthickness=1, highlightbackground=CARD_BORDER)
        c_card.pack(fill=tk.BOTH, expand=True)

        self.fig_trade = Figure(figsize=(6.5, 6), dpi=100)
        self.ax_equity = self.fig_trade.add_subplot(211)
        self.ax_stock = self.fig_trade.add_subplot(212)
        apply_mpl_dark_theme(self.fig_trade, [self.ax_equity, self.ax_stock])
        self.fig_trade.tight_layout(pad=2.2)

        self.canvas_trade = FigureCanvasTkAgg(self.fig_trade, master=c_card)
        self.canvas_trade.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    # -----------------------------------------------------------------------
    # 4. Tab 2: Hardware Telemetry, Latencies & RV32IM Inspector
    # -----------------------------------------------------------------------
    def build_hardware_tab(self):
        # Left Subpanel: Live Searchable MMIO Register Map Inspector
        left = tk.Frame(self.tab_hardware, bg=THEME_BG, width=760)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6), pady=6)

        mmio_card = tk.Frame(left, bg=CARD_BG, bd=0, highlightthickness=1, highlightbackground=CARD_BORDER)
        mmio_card.pack(fill=tk.BOTH, expand=True)

        m_bar = tk.Frame(mmio_card, bg=CARD_BG)
        m_bar.pack(fill=tk.X, padx=10, pady=8)
        tk.Label(m_bar, text="LIVE MMIO REGISTER MAP (0x3000_0000 BASE, 44 REGISTERS)", fg=COLOR_HW, bg=CARD_BG, font=FONT_TITLE).pack(side=tk.LEFT)

        # Search Bar
        tk.Label(m_bar, text="Filter:", fg=TEXT_MUTED, bg=CARD_BG, font=FONT_SUB).pack(side=tk.LEFT, padx=(16, 4))
        self.ent_search = tk.Entry(m_bar, width=18, bg="#0E121A", fg=TEXT_MAIN, insertbackground=TEXT_MAIN, font=FONT_MONO)
        self.ent_search.pack(side=tk.LEFT)
        self.ent_search.bind("<KeyRelease>", self.on_search_modified)

        m_cols = ("Offset", "Register Name", "Access", "Raw Hex", "Decoded Physical Value", "Description")
        self.mmio_tree = ttk.Treeview(mmio_card, columns=m_cols, show='headings', height=18)
        for c in m_cols:
            self.mmio_tree.heading(c, text=c)
        self.mmio_tree.column("Offset", width=55, anchor="center")
        self.mmio_tree.column("Register Name", width=125, anchor="w")
        self.mmio_tree.column("Access", width=65, anchor="center")
        self.mmio_tree.column("Raw Hex", width=95, anchor="center")
        self.mmio_tree.column("Decoded Physical Value", width=175, anchor="w")
        self.mmio_tree.column("Description", width=220, anchor="w")
        self.mmio_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Right Subpanel: Pipeline Counters & Latency Deep-Dive
        right = tk.Frame(self.tab_hardware, bg=THEME_BG, width=740)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(6, 0), pady=6)

        # Pipeline Profiling Counters Box
        pipe_card = tk.Frame(right, bg=CARD_BG, bd=0, highlightthickness=1, highlightbackground=CARD_BORDER, padx=12, pady=10)
        pipe_card.pack(fill=tk.X, pady=(0, 6))

        tk.Label(pipe_card, text="RV32IM 5-STAGE PIPELINE & CO-PROCESSOR COUNTERS", fg=COLOR_SW, bg=CARD_BG, font=FONT_TITLE).pack(anchor="w", pady=(0, 6))

        p_grid = tk.Frame(pipe_card, bg=CARD_BG)
        p_grid.pack(fill=tk.X)

        self.lbl_pipe_cycles = self.create_grid_metric(p_grid, "TOTAL CYCLES", "14,250,000", 0, 0)
        self.lbl_pipe_inst = self.create_grid_metric(p_grid, "INSTRUCTIONS", "12,391,300", 0, 1)
        self.lbl_pipe_cpi = self.create_grid_metric(p_grid, "AVERAGE CPI", "1.15", 0, 2)
        self.lbl_pipe_hazard = self.create_grid_metric(p_grid, "HAZARD STALLS", "1,820,400", 1, 0)
        self.lbl_pipe_branch = self.create_grid_metric(p_grid, "BRANCH PENALTY", "945,210", 1, 1)
        self.lbl_pipe_fwd = self.create_grid_metric(p_grid, "FORWARDING HITS", "14,610,560", 1, 2)

        # Fault Injection Triggers (P0-B)
        f_box = tk.Frame(pipe_card, bg=CARD_BG, pady=6)
        f_box.pack(fill=tk.X)
        tk.Label(f_box, text="FAULT SIMULATION:", fg=TEXT_DIM, bg=CARD_BG, font=("Segoe UI", 7, "bold")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(f_box, text="Frame Error", bg="#334155", fg="#FF8A80", font=("Segoe UI", 7), command=lambda: self.engine.inject_fault("FRAMING_ERROR")).pack(side=tk.LEFT, padx=2)
        tk.Button(f_box, text="Bad Symbol", bg="#334155", fg="#FF8A80", font=("Segoe UI", 7), command=lambda: self.engine.inject_fault("BAD_SYMBOL")).pack(side=tk.LEFT, padx=2)
        tk.Button(f_box, text="Burst Overrun", bg="#334155", fg="#FF8A80", font=("Segoe UI", 7), command=lambda: self.engine.inject_fault("BURST_OVERRUN")).pack(side=tk.LEFT, padx=2)
        tk.Button(f_box, text="Clear Faults", bg="#334155", fg=COLOR_BUY, font=("Segoe UI", 7), command=lambda: self.engine.inject_fault("RESET")).pack(side=tk.LEFT, padx=4)

        # Latency Charts
        lat_card = tk.Frame(right, bg=CARD_BG, bd=0, highlightthickness=1, highlightbackground=CARD_BORDER)
        lat_card.pack(fill=tk.BOTH, expand=True)

        self.fig_hw = Figure(figsize=(6.5, 4.5), dpi=100)
        self.ax_lat_bar = self.fig_hw.add_subplot(211)
        self.ax_lat_hist = self.fig_hw.add_subplot(212)
        apply_mpl_dark_theme(self.fig_hw, [self.ax_lat_bar, self.ax_lat_hist])
        self.fig_hw.tight_layout(pad=2.2)

        self.canvas_hw = FigureCanvasTkAgg(self.fig_hw, master=lat_card)
        self.canvas_hw.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def create_grid_metric(self, parent, label, val, r, c):
        f = tk.Frame(parent, bg=CARD_BG_SECONDARY, padx=8, pady=4, highlightthickness=1, highlightbackground=CARD_BORDER)
        f.grid(row=r, column=c, padx=4, pady=3, sticky="ew")
        tk.Label(f, text=label, fg=TEXT_MUTED, bg=CARD_BG_SECONDARY, font=("Segoe UI", 7, "bold")).pack(anchor="w")
        v = tk.Label(f, text=val, fg=TEXT_MAIN, bg=CARD_BG_SECONDARY, font=FONT_MONO_BOLD)
        v.pack(anchor="w")
        return v

    # -----------------------------------------------------------------------
    # 5. Tab 3: Scalability, Ablation & Benchmark Explorer
    # -----------------------------------------------------------------------
    def build_benchmarks_tab(self):
        top_ctrl = tk.Frame(self.tab_benchmarks, bg=CARD_BG, padx=12, pady=8, bd=0, highlightthickness=1, highlightbackground=CARD_BORDER)
        top_ctrl.pack(fill=tk.X, padx=0, pady=(0, 6))

        tk.Label(top_ctrl, text="QUANTITATIVE RESEARCH, HARDWARE SCALABILITY & ABLATION EXPLORER", fg=TEXT_MAIN, bg=CARD_BG, font=FONT_TITLE).pack(side=tk.LEFT)
        tk.Button(top_ctrl, text="Reload Benchmark CSVs", bg="#334155", fg=COLOR_HW, bd=0, font=FONT_SUB, padx=8,
                  command=self.load_benchmark_datasets).pack(side=tk.RIGHT)

        # Sub-frames: Left is charts, Right is tables
        body = tk.Frame(self.tab_benchmarks, bg=THEME_BG)
        body.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(body, bg=CARD_BG, bd=0, highlightthickness=1, highlightbackground=CARD_BORDER, width=680)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        self.fig_bench = Figure(figsize=(6.5, 6), dpi=100)
        self.ax_scale_lut = self.fig_bench.add_subplot(211)
        self.ax_scale_strat = self.fig_bench.add_subplot(212)
        apply_mpl_dark_theme(self.fig_bench, [self.ax_scale_lut, self.ax_scale_strat])
        self.fig_bench.tight_layout(pad=2.2)

        self.canvas_bench = FigureCanvasTkAgg(self.fig_bench, master=left)
        self.canvas_bench.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        right = tk.Frame(body, bg=CARD_BG, bd=0, highlightthickness=1, highlightbackground=CARD_BORDER, width=780)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(6, 0))

        tk.Label(right, text="BACKTEST & ABLATION RESULTS (RESULTS/BACKTEST_RESULTS.CSV)", fg=COLOR_BUY, bg=CARD_BG, font=FONT_TITLE).pack(anchor="w", padx=10, pady=6)

        b_cols = ("Strategy", "Return (%)", "Max DD (%)", "Sharpe", "Trades", "Win Rate (%)", "Fees ($)")
        self.bench_tree = ttk.Treeview(right, columns=b_cols, show='headings', height=12)
        for c in b_cols:
            self.bench_tree.heading(c, text=c)
            self.bench_tree.column(c, width=95, anchor="center")
        self.bench_tree.column("Strategy", width=160, anchor="w")
        self.bench_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self.load_benchmark_datasets()

    # -----------------------------------------------------------------------
    # Data Ingestion & Refresh Handlers
    # -----------------------------------------------------------------------
    def start_worker_threads(self):
        self.worker_thread = threading.Thread(target=self.market_simulation_worker, daemon=True)
        self.worker_thread.start()

    def market_simulation_worker(self):
        c = 0
        while self.is_running:
            if not self.is_paused:
                # Stochastic tick generation for 8 companies
                delta = random.choice([-0.4, -0.2, 0.0, 0.2, 0.4]) + (0.01 if c % 2 == 0 else -0.01)
                p = max(10.0, self.engine.prices[c] + delta)
                v = random.randint(50, 250)

                # Strategy Decision
                if self.engine.strategy_mode == 1:
                    dec = 1 if p > self.engine.ma_values[c] else (2 if p < self.engine.ma_values[c] else 0)
                else:
                    ma_vote = p > self.engine.ma_values[c]
                    vwap_vote = p > self.engine.vwap_values[c]
                    dec = 1 if (ma_vote and vwap_vote) else (2 if (not ma_vote and not vwap_vote) else 0)

                self.engine.update_tick(
                    sym=c,
                    price=p,
                    vol=v,
                    hw_dec=dec,
                    hw_lat=5,
                    sw_dec=dec,
                    sw_lat=random.randint(76, 88),
                    hw_score=int((p - self.engine.ma_values[c]) * 1000)
                )

                c = (c + 1) % self.engine.n
                if c == 0:
                    # Multi-company portfolio rebalance round
                    hw_codes = 0
                    for i in range(self.engine.n):
                        if self.engine.signals[i] == 1:
                            hw_codes |= (1 << (2 * i))
                        elif self.engine.signals[i] == 2 and self.engine.positions[i] > 0:
                            hw_codes |= (2 << (2 * i))
                    self.engine.update_allocation(
                        hw_codes, hw_codes,
                        int(self.engine.cash) & 0xFFFFFFFF,
                        (int(self.engine.cash) >> 32) & 0xFFFFFFFF,
                        random.randint(24, 48)
                    )

            time.sleep(1.0 / max(1.0, self.replay_speed * 4))

    def periodic_ui_refresh(self):
        try:
            self.refresh_kpis()
            self.refresh_quote_matrix()
            self.refresh_order_tape()
            self.refresh_mmio_table()
            self.refresh_pipeline_counters()
            self.update_trading_charts()
            self.update_hardware_charts()
        except Exception:
            pass
        self.root.after(100, self.periodic_ui_refresh)

    def refresh_kpis(self):
        e = self.engine
        pnl = e.equity - e.starting_cash
        pnl_pct = (pnl / e.starting_cash) * 100.0

        pnl_str = f"{'+' if pnl >= 0 else ''}${pnl:,.2f}"
        pct_str = f"{'+' if pnl_pct >= 0 else ''}{pnl_pct:.3f}%"
        self.kpi_equity.config(text=f"${e.equity:,.2f}")
        self.kpi_equity_sub.config(
            text=f"{pnl_str} ({pct_str}) | Cash: ${e.cash:,.0f}",
            fg=COLOR_BUY if pnl >= 0 else COLOR_SELL
        )

        _, p50_c, _, p99_c, _ = e.get_percentiles(e.core_latency_history)
        self.kpi_core_lat.config(text="50.0 ns (5 cyc)")
        self.kpi_core_lat_sub.config(text=f"P50: {p50_c:.0f}ns | P99: {p99_c:.0f}ns (Deterministic)")

        _, p50_a, _, p99_a, _ = e.get_percentiles(e.alloc_latency_history)
        self.kpi_alloc_lat.config(text=f"{e.alloc_latency * 10}.0 ns ({e.alloc_latency} cyc)")
        self.kpi_alloc_lat_sub.config(text=f"P50: {p50_a:.0f}ns | P99: {p99_a:.0f}ns")

        sw_mean = sum(e.sw_latency_history) / max(1, len(e.sw_latency_history))
        speedup = sw_mean / 50.0
        self.kpi_speedup.config(text=f"{speedup:.1f}x Faster")
        self.kpi_speedup_sub.config(text=f"FPGA 50ns vs RISC-V {sw_mean/1000.0:.2f}µs")

        self.kpi_thru.config(text="20.0 M Ticks/s")
        self.kpi_thru_sub.config(text=f"Drops: {e.health.eng_drop_count} | Overrun: {e.health.overrun_count}")

        win_rate = (e.winning_trades / max(1, e.total_trades)) * 100.0
        self.kpi_risk.config(text=f"Max DD: {e.max_drawdown_pct:.2f}%")
        self.kpi_risk_sub.config(text=f"Sharpe: {e.sharpe_ratio:.2f} | Win: {win_rate:.1f}%")

        # Status Pills
        self.pill_strat.config(
            text="MA-Only (SW0=1)" if e.strategy_mode == 1 else "2-of-3 (SW0=0)",
            fg=COLOR_HW if e.strategy_mode == 1 else COLOR_BUY
        )
        self.pill_health.config(
            text=f"HEALTH: {e.health.status}",
            fg=COLOR_BUY if e.health.status == "ONLINE" else COLOR_WARN
        )

    def refresh_quote_matrix(self):
        items = self.quote_tree.get_children()
        for idx in range(self.engine.n):
            ticker = COMPANY_TICKERS[idx]
            p = self.engine.prices[idx]
            base = COMPANY_BASE_PRICES.get(ticker, p)
            chg = ((p - base) / base) * 100.0
            pos = self.engine.positions[idx]
            cap = pos * 1000 * p
            w = (self.engine.weights[idx] / 32768.0) * 100.0
            pnl = pos * 1000 * (p - self.engine.avg_cost[idx]) if pos > 0 else 0.0

            sig_names = {0: "HOLD", 1: "BUY", 2: "SELL"}
            sig_txt = sig_names.get(self.engine.signals[idx], "HOLD")

            vals = (
                ticker,
                f"${p:.2f}",
                f"${self.engine.bid_prices[idx]:.2f}/${self.engine.ask_prices[idx]:.2f}",
                f"{self.engine.volumes[idx]:,}",
                f"${self.engine.ma_values[idx]:.2f}",
                f"${self.engine.vwap_values[idx]:.2f}",
                f"{self.engine.scores[idx]:+d}",
                sig_txt,
                f"{pos:,} lots",
                f"${cap:,.0f}",
                f"{w:.1f}%",
                f"{'+' if pnl>=0 else ''}${pnl:,.2f}"
            )
            if idx < len(items):
                self.quote_tree.item(items[idx], values=vals)
            else:
                self.quote_tree.insert('', tk.END, values=vals)

    def refresh_order_tape(self):
        existing = len(self.tape_tree.get_children())
        logs = self.engine.audit_log
        if len(logs) > existing:
            for tx in logs[existing:]:
                self.tape_tree.insert('', tk.END, values=(
                    tx.timestamp,
                    f"#{tx.tx_id}",
                    tx.ticker,
                    tx.raw_signal,
                    tx.alloc_decision,
                    f"${tx.price:.2f}",
                    f"{tx.volume:,}",
                    f"{tx.latency_cycles}c ({tx.latency_ns}ns)",
                    tx.error_status
                ))
            # Auto scroll to bottom
            self.tape_tree.yview_moveto(1.0)

    def refresh_mmio_table(self):
        filter_q = self.search_query.upper()
        items = self.mmio_tree.get_children()
        item_idx = 0

        # Construct raw values map from engine state
        raw_vals = {
            "POS_LIMIT": 1000,
            "BRK_HIGH": int(self.engine.prices[self.selected_company_idx] * 1.05 * 100),
            "BRK_LOW": int(self.engine.prices[self.selected_company_idx] * 0.95 * 100),
            "TICK_ID": (self.selected_company_idx << 28) | (self.engine.next_tx_id & 0x0FFFFFFF),
            "TICK_PRICE": int(self.engine.prices[self.selected_company_idx] * 100),
            "TICK_VOL": self.engine.volumes[self.selected_company_idx],
            "HW_DECISION": self.engine.signals[self.selected_company_idx],
            "HW_LATENCY": 5,
            "HW_POSITION": self.engine.positions[self.selected_company_idx],
            "STATUS": 0x81 if self.engine.strategy_mode == 1 else 0x01,
            "OVERRUN": self.engine.health.overrun_count,
            "CASH_LO": int(self.engine.cash) & 0xFFFFFFFF,
            "CASH_HI": (int(self.engine.cash) >> 32) & 0xFFFFFFFF,
            "HW_CASH_LO": int(self.engine.cash) & 0xFFFFFFFF,
            "SYMBOL_SEL": self.selected_company_idx,
            "NUM_SYMBOLS": self.engine.n,
            "N_MAX": 8,
            "PORT_MODE": 0x0F,
            "ALLOC_CODES": sum((c & 3) << (2 * i) for i, c in enumerate(self.engine.alloc_codes)),
            "ALLOC_LAT": self.engine.alloc_latency,
            "SCORE": self.engine.scores[self.selected_company_idx],
            "WEIGHT": self.engine.weights[self.selected_company_idx],
            "FRAME_ERR": self.engine.health.frame_err_count,
            "ENG_DROP": self.engine.health.eng_drop_count,
            "PKT_ABORT": self.engine.health.pkt_abort_count,
            "PKT_TIMEOUT": self.engine.health.pkt_timeout_count,
            "STRATEGY_CFG": self.engine.strategy_mode | (self.engine.strategy_change_count << 8),
            "STRAT_ORIG_DEC": self.engine.decisions_orig,
            "STRAT_MA_DEC": self.engine.decisions_ma,
            "AUDIT_TX_ID": self.engine.next_tx_id
        }

        for offset, idx, name, access, desc in MMIO_REGISTERS:
            if filter_q and (filter_q not in name and filter_q not in desc and filter_q not in f"0X{offset:02X}"):
                continue
            raw = raw_vals.get(name, 0)
            raw_hex = f"0x{raw:08X}"
            decoded = decode_mmio_val(name, raw)

            vals = (f"0x{offset:02X}", name, access, raw_hex, decoded, desc)
            if item_idx < len(items):
                self.mmio_tree.item(items[item_idx], values=vals)
            else:
                self.mmio_tree.insert('', tk.END, values=vals)
            item_idx += 1

        # Delete any leftover items if filtered
        while item_idx < len(items):
            self.mmio_tree.delete(items[item_idx])
            items.pop(item_idx)

    def refresh_pipeline_counters(self):
        p = self.engine.pipeline
        self.lbl_pipe_cycles.config(text=f"{p.total_cycles:,}")
        self.lbl_pipe_inst.config(text=f"{p.total_instructions:,}")
        self.lbl_pipe_cpi.config(text=f"{p.cpi:.2f}")
        self.lbl_pipe_hazard.config(text=f"{p.hazard_stalls:,}")
        self.lbl_pipe_branch.config(text=f"{p.branch_penalty_cycles:,}")
        self.lbl_pipe_fwd.config(text=f"{p.forwarding_ex_to_ex + p.forwarding_mem_to_ex:,}")

    def update_trading_charts(self):
        # 1. Equity & Drawdown
        self.ax_equity.clear()
        self.ax_equity.plot(self.engine.equity_history, color=COLOR_BUY, linewidth=1.5, label="Portfolio Equity ($)")
        self.ax_equity.set_title("Live Portfolio Equity Curve ($)", color=TEXT_MAIN, fontsize=8, fontweight='bold', pad=4)
        self.ax_equity.grid(True, linestyle="--", alpha=0.15, color='#4A5568')
        self.ax_equity.legend(loc="upper left", facecolor=CARD_BG, edgecolor=CARD_BORDER, labelcolor=TEXT_MAIN, fontsize=7)

        # 2. Focused Company Chart
        c = self.selected_company_idx
        ticker = COMPANY_TICKERS[c]
        prices = self.engine.price_history[c]

        self.ax_stock.clear()
        self.ax_stock.plot(prices, color='#F8FAFC', linewidth=1.3, label=f"{ticker} Price")
        if len(prices) >= 4:
            ma = [sum(prices[max(0, i-3):i+1])/len(prices[max(0, i-3):i+1]) for i in range(len(prices))]
            self.ax_stock.plot(ma, color=COLOR_HW, linestyle="--", linewidth=1.1, label="4-Point MA")
        self.ax_stock.set_title(f"{ticker} ({COMPANY_NAMES[ticker]}) Technical Signals & Moving Average", color=TEXT_MAIN, fontsize=8, fontweight='bold', pad=4)
        self.ax_stock.grid(True, linestyle="--", alpha=0.15, color='#4A5568')
        self.ax_stock.legend(loc="upper left", facecolor=CARD_BG, edgecolor=CARD_BORDER, labelcolor=TEXT_MAIN, fontsize=7)

        self.canvas_trade.draw_idle()

    def update_hardware_charts(self):
        # 1. Latency Bar Chart
        self.ax_lat_bar.clear()
        bars = ['FPGA Core\n(5c)', 'Alloc\n(32c)', 'MMIO Bus\n(82c)', 'RV32IM SW\n(820c)']
        lat_ns = [50, self.engine.alloc_latency * 10, 820, 8208]
        cols = [COLOR_HW, COLOR_ACCENT, COLOR_SW, COLOR_SELL]
        self.ax_lat_bar.bar(bars, lat_ns, color=cols, width=0.45, edgecolor=CARD_BORDER)
        self.ax_lat_bar.set_yscale('log')
        self.ax_lat_bar.set_title("Decision Latency: Hardware vs Software (ns, Log Scale)", color=TEXT_MAIN, fontsize=8, fontweight='bold', pad=4)
        self.ax_lat_bar.grid(True, linestyle="--", alpha=0.15, color='#4A5568')

        # 2. Allocator Latency Histogram
        self.ax_lat_hist.clear()
        self.ax_lat_hist.hist(self.engine.alloc_latency_history, bins=12, color=COLOR_ACCENT, edgecolor=CARD_BG)
        self.ax_lat_hist.set_title("Portfolio Allocator Latency Distribution (ns)", color=TEXT_MAIN, fontsize=8, fontweight='bold', pad=4)
        self.ax_lat_hist.grid(True, linestyle="--", alpha=0.15, color='#4A5568')

        self.canvas_hw.draw_idle()

    def load_benchmark_datasets(self):
        # Clear Benchmarks Table
        for item in self.bench_tree.get_children():
            self.bench_tree.delete(item)

        bpath = os.path.join(ROOT, 'results', 'backtest_results.csv')
        if os.path.exists(bpath):
            try:
                df = pd.read_csv(bpath)
                for _, r in df.iterrows():
                    self.bench_tree.insert('', tk.END, values=(
                        r['Strategy'].replace('_', ' '),
                        f"{r['Total_Return_Pct']:+.3f}%",
                        f"{r['Max_Drawdown_Pct']:.2f}%",
                        f"{r['Sharpe_Ratio']:.2f}",
                        r['Total_Trades'],
                        f"{r['Win_Rate_Pct']:.1f}%",
                        f"${r['Total_Fees_USD']:,.2f}"
                    ))
            except Exception:
                pass

        # Plot Scalability from results/resource_scalability.csv
        rpath = os.path.join(ROOT, 'results', 'resource_scalability.csv')
        if os.path.exists(rpath):
            try:
                rdf = pd.read_csv(rpath)
                self.ax_scale_lut.clear()
                self.ax_scale_lut.plot(rdf['N_Companies'], rdf['LUTs'], marker='o', color=COLOR_HW, label="LUT Utilization")
                self.ax_scale_lut.plot(rdf['N_Companies'], rdf['FFs'], marker='s', color=COLOR_BUY, label="FF Utilization")
                self.ax_scale_lut.set_title("Hardware Resource Scaling across Companies (N=1, 2, 4, 8)", color=TEXT_MAIN, fontsize=8, fontweight='bold', pad=4)
                self.ax_scale_lut.set_xlabel("N Companies Traded", color=TEXT_MUTED, fontsize=7)
                self.ax_scale_lut.grid(True, linestyle="--", alpha=0.15, color='#4A5568')
                self.ax_scale_lut.legend(loc="upper left", facecolor=CARD_BG, edgecolor=CARD_BORDER, labelcolor=TEXT_MAIN, fontsize=7)

                self.ax_scale_strat.clear()
                self.ax_scale_strat.plot(rdf['N_Companies'], rdf['Fmax_MHz'], marker='^', color=COLOR_SW, linewidth=1.8, label="Fmax (MHz)")
                self.ax_scale_strat.axhline(100.0, color=COLOR_SELL, linestyle=":", label="100 MHz Target Clock")
                self.ax_scale_strat.set_title("Maximum Operating Frequency (Fmax MHz) vs Company Count", color=TEXT_MAIN, fontsize=8, fontweight='bold', pad=4)
                self.ax_scale_strat.set_xlabel("N Companies Traded", color=TEXT_MUTED, fontsize=7)
                self.ax_scale_strat.grid(True, linestyle="--", alpha=0.15, color='#4A5568')
                self.ax_scale_strat.legend(loc="upper right", facecolor=CARD_BG, edgecolor=CARD_BORDER, labelcolor=TEXT_MAIN, fontsize=7)

                self.canvas_bench.draw_idle()
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Interactive Actions & Callbacks
    # -----------------------------------------------------------------------
    def toggle_pause(self):
        self.is_paused = not self.is_paused
        self.btn_run.config(text="Run" if self.is_paused else "Pause", bg=COLOR_BUY if self.is_paused else "#334155", fg="#000000" if self.is_paused else TEXT_MAIN)

    def step_tick(self):
        c = self.selected_company_idx
        p = self.engine.prices[c] + random.choice([-0.25, 0.25])
        self.engine.update_tick(c, p, 100, 1, 5, 1, 82, 120)

    def reset_engine(self):
        self.engine = TradingTerminalEngine(n_companies=8, starting_cash=100_000_000.0)

    def toggle_strategy(self):
        self.engine.strategy_mode = 1 - self.engine.strategy_mode
        self.engine.strategy_change_count += 1
        strat_txt = "MA-Only (SW0=1)" if self.engine.strategy_mode == 1 else "2-of-3 (SW0=0)"
        self.btn_strat.config(text=f"Strategy: {strat_txt}", fg=COLOR_HW if self.engine.strategy_mode == 1 else COLOR_BUY)

    def on_quote_selected(self, event):
        sel = self.quote_tree.selection()
        if sel:
            ticker = self.quote_tree.item(sel[0], "values")[0]
            if ticker in COMPANY_TICKERS:
                self.selected_company_idx = COMPANY_TICKERS.index(ticker)
                self.update_trading_charts()

    def on_search_modified(self, event):
        self.search_query = self.ent_search.get().strip()

    def export_snapshot_dialog(self):
        from .snapshot import generate_dark_terminal_snapshot
        fpath = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png")],
            initialfile=f"hft_dashboard_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        if fpath:
            generate_dark_terminal_snapshot(fpath)
            messagebox.showinfo("Export Successful", f"High-resolution snapshot saved:\n{fpath}")

    def export_tape_csv(self):
        fpath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")],
            initialfile=f"order_signal_tape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if fpath:
            with open(fpath, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Timestamp", "TID", "Ticker", "Signal", "Exec_Action", "Price", "Lots", "Latency_Cyc", "Latency_ns", "Status"])
                for tx in self.engine.audit_log:
                    w.writerow([tx.timestamp, tx.tx_id, tx.ticker, tx.raw_signal, tx.alloc_decision, tx.price, tx.volume, tx.latency_cycles, tx.latency_ns, tx.error_status])
            messagebox.showinfo("Export Successful", f"Order tape exported successfully:\n{fpath}")

