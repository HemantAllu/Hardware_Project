#!/usr/bin/env python3
"""
rvsim.py - tiny RV32IM instruction-set reference simulator (golden model).

It decodes the raw machine words (not the assembly), so it is independent of the
RTL.  Memory map matches the hardware testbench:
    instruction memory : 0x00000000 ..          (read only)
    data memory        : 0x10000000 .. +4*DMEM_WORDS
EBREAK / ECALL stop the simulation.

Usage:  rvsim.py imem.hex dmem.hex   -> prints REG / MEM lines like tb_core.v
"""
import sys

M32 = 0xFFFFFFFF
DMEM_BASE = 0x10000000


def s32(x):
    x &= M32
    return x - (1 << 32) if x >> 31 else x


def sext(x, bits):
    x &= (1 << bits) - 1
    return x - (1 << bits) if x >> (bits - 1) else x


# ----------------------------------------------------------------- RV32M ops
def op_mul(a, b):    return (s32(a) * s32(b)) & M32
def op_mulh(a, b):   return ((s32(a) * s32(b)) >> 32) & M32
def op_mulhsu(a, b): return ((s32(a) * (b & M32)) >> 32) & M32
def op_mulhu(a, b):  return (((a & M32) * (b & M32)) >> 32) & M32


def op_div(a, b):
    if b & M32 == 0:
        return M32
    sa, sb = s32(a), s32(b)
    if sa == -(1 << 31) and sb == -1:
        return 0x80000000
    q = abs(sa) // abs(sb)
    if (sa < 0) != (sb < 0):
        q = -q
    return q & M32


def op_divu(a, b):
    return M32 if b & M32 == 0 else (a & M32) // (b & M32)


def op_rem(a, b):
    if b & M32 == 0:
        return a & M32
    sa, sb = s32(a), s32(b)
    if sa == -(1 << 31) and sb == -1:
        return 0
    r = abs(sa) % abs(sb)
    if sa < 0:
        r = -r
    return r & M32


def op_remu(a, b):
    return a & M32 if b & M32 == 0 else (a & M32) % (b & M32)


M_OPS = [op_mul, op_mulh, op_mulhsu, op_mulhu, op_div, op_divu, op_rem, op_remu]
M_NAMES = ['mul', 'mulh', 'mulhsu', 'mulhu', 'div', 'divu', 'rem', 'remu']


# ------------------------------------------------------------------ simulator
class RV32IM:
    def __init__(self, imem, dmem_init, dmem_words=1024):
        self.imem = list(imem)
        self.dmem = [0] * dmem_words
        for i, w in enumerate(dmem_init[:dmem_words]):
            self.dmem[i] = w & M32
        self.x = [0] * 32
        self.pc = 0
        self.steps = 0
        self.halted = False

    # -- memory --------------------------------------------------------------
    def _didx(self, addr, size):
        off = addr - DMEM_BASE
        if off < 0 or off + size > 4 * len(self.dmem) or addr % size:
            raise RuntimeError(f"bad data access addr={addr:#x} size={size} pc={self.pc:#x}")
        return off

    def load(self, addr, size, signed):
        off = self._didx(addr, size)
        word = self.dmem[off >> 2]
        v = (word >> (8 * (off & 3))) & ((1 << (8 * size)) - 1)
        return sext(v, 8 * size) & M32 if signed else v

    def store(self, addr, size, val):
        off = self._didx(addr, size)
        word = self.dmem[off >> 2]
        sh = 8 * (off & 3)
        mask = ((1 << (8 * size)) - 1) << sh
        self.dmem[off >> 2] = (word & ~mask & M32) | ((val << sh) & mask)

    def fetch(self):
        i = self.pc >> 2
        return self.imem[i] if i < len(self.imem) else 0x13

    # -- execution -----------------------------------------------------------
    def step(self):
        w = self.fetch()
        pc = self.pc
        op = w & 0x7F
        rd, f3 = (w >> 7) & 31, (w >> 12) & 7
        rs1, rs2, f7 = (w >> 15) & 31, (w >> 20) & 31, w >> 25
        a, b = self.x[rs1], self.x[rs2]
        imm_i = sext(w >> 20, 12)
        imm_s = sext(((w >> 25) << 5) | ((w >> 7) & 31), 12)
        imm_b = sext(((w >> 31) << 12) | (((w >> 7) & 1) << 11) |
                     (((w >> 25) & 0x3F) << 5) | (((w >> 8) & 0xF) << 1), 13)
        imm_u = w & 0xFFFFF000
        imm_j = sext(((w >> 31) << 20) | (((w >> 12) & 0xFF) << 12) |
                     (((w >> 20) & 1) << 11) | (((w >> 21) & 0x3FF) << 1), 21)
        npc = (pc + 4) & M32
        res = None

        if op == 0x37:   res = imm_u                                   # LUI
        elif op == 0x17: res = (pc + imm_u) & M32                      # AUIPC
        elif op == 0x6F: res = npc; npc = (pc + imm_j) & M32           # JAL
        elif op == 0x67: res = npc; npc = (a + imm_i) & M32 & ~1       # JALR
        elif op == 0x63:                                               # BRANCH
            taken = {0: a == b, 1: a != b, 4: s32(a) < s32(b), 5: s32(a) >= s32(b),
                     6: a < b, 7: a >= b}[f3]
            if taken:
                npc = (pc + imm_b) & M32
        elif op == 0x03:                                               # LOAD
            addr = (a + imm_i) & M32
            res = {0: lambda: self.load(addr, 1, True), 1: lambda: self.load(addr, 2, True),
                   2: lambda: self.load(addr, 4, False), 4: lambda: self.load(addr, 1, False),
                   5: lambda: self.load(addr, 2, False)}[f3]()
        elif op == 0x23:                                               # STORE
            addr = (a + imm_s) & M32
            self.store(addr, {0: 1, 1: 2, 2: 4}[f3], b)
        elif op == 0x13:                                               # OP-IMM
            sh = imm_i & 31
            res = {0: (a + imm_i) & M32, 2: int(s32(a) < imm_i), 3: int(a < (imm_i & M32)),
                   4: a ^ (imm_i & M32), 6: a | (imm_i & M32), 7: a & (imm_i & M32),
                   1: (a << sh) & M32,
                   5: (s32(a) >> sh) & M32 if (w >> 30) & 1 else a >> sh}[f3]
        elif op == 0x33:                                               # OP
            if f7 == 1:
                res = M_OPS[f3](a, b)
            else:
                sh = b & 31
                res = {0: (a - b) & M32 if f7 & 0x20 else (a + b) & M32,
                       1: (a << sh) & M32, 2: int(s32(a) < s32(b)), 3: int(a < b),
                       4: a ^ b, 5: (s32(a) >> sh) & M32 if f7 & 0x20 else a >> sh,
                       6: a | b, 7: a & b}[f3]
        elif op == 0x73:
            if w in (0x00000073, 0x00100073):
                self.halted = True
        # FENCE / unknown: NOP

        if res is not None and rd != 0:
            self.x[rd] = res & M32
        self.pc = npc
        self.steps += 1

    def run(self, max_steps=2_000_000):
        while not self.halted and self.steps < max_steps:
            self.step()
        if not self.halted:
            raise RuntimeError("reference simulation did not halt")


def read_hex(path):
    words = []
    with open(path) as f:
        for line in f:
            line = line.split('//')[0].strip()
            if line:
                words.append(int(line, 16))
    return words


def main():
    imem = read_hex(sys.argv[1])
    dmem = read_hex(sys.argv[2]) if len(sys.argv) > 2 else []
    sim = RV32IM(imem, dmem)
    sim.run()
    print(f"RETIRED {sim.steps}")
    for i in range(32):
        print(f"REG {i} {sim.x[i]:08x}")
    for i in range(64):
        print(f"MEM {i} {sim.dmem[i]:08x}")


if __name__ == '__main__':
    main()
