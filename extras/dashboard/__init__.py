"""RV32IM FPGA HFT Professional Trading Dashboard V2.0 Modular Package"""
from .theme import *
from .mmio_map import MMIO_REGISTERS, decode_mmio_val
from .engine import TradingTerminalEngine, AuditTransaction, SystemHealthState
from .serial_if import HardwareSerialInterface
from .ui import HFTTradingTerminalGUI
from .snapshot import generate_dark_terminal_snapshot

