"""Institutional Quant Dark Theme Configuration for RV32IM HFT Dashboard"""

# Base Surface Colors
THEME_BG = '#0B0E14'          # Deep Obsidian / Slate Canvas
CARD_BG = '#151921'           # Elevated Card Surface
CARD_BG_SECONDARY = '#1C2331' # Secondary Card Surface / Hover State
CARD_BORDER = '#262C36'       # Subtle Structural Borders
CARD_BORDER_ACCENT = '#3B82F6'

# High-Contrast Monospace Typography Palette
TEXT_MAIN = '#F8FAFC'         # Primary Readout (White/Slate)
TEXT_MUTED = '#94A3B8'        # Secondary Legend / Labels (Muted Slate)
TEXT_DIM = '#64748B'          # Metadata & Unit Suffixes

# Semantic Financial & Telemetry Indicators
COLOR_BUY = '#00E676'         # Emerald Green (BUY, Positive PnL, Speedup)
COLOR_SELL = '#FF5252'        # Coral Red (SELL, Negative PnL, Drawdown, Drops)
COLOR_HOLD = '#94A3B8'        # Neutral Slate (HOLD / NO ACTION)
COLOR_ROT = '#E040FB'         # Purple Accent (ROTATION)

COLOR_HW = '#00E5FF'          # Electric Cyan (FPGA Hardware Accelerator)
COLOR_SW = '#FFD740'          # Amber / Gold (RV32IM Software Baseline & Stalls)
COLOR_ACCENT = '#38BDF8'      # Sky Blue (Active Selections, High-Speed Bus)
COLOR_WARN = '#FFAB00'        # Amber Warning

# Font Families
FONT_FAMILY_MONO = "Consolas"
FONT_FAMILY_SANS = "Segoe UI"

FONT_HEADER = (FONT_FAMILY_SANS, 12, "bold")
FONT_TITLE = (FONT_FAMILY_SANS, 10, "bold")
FONT_SUB = (FONT_FAMILY_SANS, 9)
FONT_BADGE = (FONT_FAMILY_SANS, 8, "bold")
FONT_MONO = (FONT_FAMILY_MONO, 9)
FONT_MONO_BOLD = (FONT_FAMILY_MONO, 10, "bold")
FONT_HERO = (FONT_FAMILY_MONO, 14, "bold")

# Company Metadata
COMPANY_TICKERS = ['AAPL', 'NVDA', 'GOOGL', 'MSFT', 'AMZN', 'WMT', 'META', 'TSLA']
COMPANY_NAMES = {
    'AAPL': 'Apple Inc.',
    'NVDA': 'NVIDIA Corp.',
    'GOOGL': 'Alphabet Inc.',
    'MSFT': 'Microsoft Corp.',
    'AMZN': 'Amazon.com',
    'WMT': 'Walmart Inc.',
    'META': 'Meta Platforms',
    'TSLA': 'Tesla Inc.'
}
COMPANY_BASE_PRICES = {
    'AAPL': 255.0,
    'NVDA': 185.0,
    'GOOGL': 245.0,
    'MSFT': 515.0,
    'AMZN': 225.0,
    'WMT': 102.0,
    'META': 715.0,
    'TSLA': 435.0
}


def apply_mpl_dark_theme(fig, axs=None):
    """Applies institutional Bloomberg-style dark theme to matplotlib figures."""
    fig.patch.set_facecolor(CARD_BG)
    if axs is None:
        axs = fig.axes
    elif not isinstance(axs, (list, tuple)):
        axs = [axs]
    for ax in axs:
        ax.set_facecolor('#0E121A')
        ax.tick_params(colors=TEXT_MUTED, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(CARD_BORDER)
            spine.set_linewidth(0.8)
        ax.grid(True, linestyle="--", alpha=0.15, color='#4A5568')
        if ax.get_title():
            ax.set_title(ax.get_title(), color=TEXT_MAIN, fontsize=9, fontweight='bold', pad=6)
        if ax.get_xlabel():
            ax.set_xlabel(ax.get_xlabel(), color=TEXT_MUTED, fontsize=8)
        if ax.get_ylabel():
            ax.set_ylabel(ax.get_ylabel(), color=TEXT_MUTED, fontsize=8)

