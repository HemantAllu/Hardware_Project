"""UART Serial Protocol Interface with 0xAA55AA55 Framing & Desync Recovery"""
import os
import struct
import sys
import threading
import time

HEADER = struct.pack('<I', 0xAA55AA55)
FOOTER = 0x55AA55AA
REPORT_BYTES = 40


def _lower_ftdi_latency(port, ms=2):
    """Best-effort FTDI latency reduction for Linux / Windows."""
    try:
        dev = os.path.basename(os.path.realpath(port))
        path = f'/sys/bus/usb-serial/devices/{dev}/latency_timer'
        if os.path.exists(path):
            with open(path, 'w') as f:
                f.write(str(ms))
    except Exception:
        pass


class HardwareSerialInterface:
    """Thread-safe bidirectional UART communication layer for Digilent Nexys A7."""
    def __init__(self, port, baud=115200):
        self.port = port
        self.baud = baud
        self.ser = None
        self.lock = threading.Lock()
        self.connected = False
        self.stale_reports = 0

    def connect(self):
        if self.port in (None, 'none', 'NONE', ''):
            self.connected = False
            return False
        try:
            import serial
            _lower_ftdi_latency(self.port)
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            time.sleep(0.2)
            self.ser.reset_input_buffer()
            self.connected = True
            return True
        except Exception:
            self.connected = False
            return False

    def close(self):
        with self.lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.connected = False

    def write_packet(self, tid, price, vol):
        """Sends a 12-byte binary tick frame to the FPGA tick_parser."""
        if not self.connected or not self.ser:
            return False
        try:
            pkt = struct.pack('<III', tid & 0xFFFFFFFF, int(price), int(vol))
            with self.lock:
                self.ser.write(pkt)
            return True
        except Exception:
            self.connected = False
            return False

    def read_report(self, timeout=1.0):
        """Reads a 40-byte report frame from the RV32IM SoC."""
        if not self.connected or not self.ser:
            return None
        deadline = time.time() + timeout
        buf = b''
        while time.time() < deadline:
            try:
                with self.lock:
                    waiting = self.ser.in_waiting
                    if waiting > 0:
                        buf += self.ser.read(min(waiting, 128))
                i = buf.find(HEADER)
                if i < 0:
                    buf = buf[-3:]
                    time.sleep(0.001)
                    continue
                buf = buf[i:]
                if len(buf) >= REPORT_BYTES:
                    words = struct.unpack('<10I', buf[:REPORT_BYTES])
                    if words[9] == FOOTER:
                        return words[1:9]  # id, price, vol, hw_dec, hw_lat, sw_dec, sw_lat, hw_pos/score
                    buf = buf[4:]
            except Exception:
                self.connected = False
                return None
            time.sleep(0.001)
        return None

