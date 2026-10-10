#!/usr/bin/env python3
"""
gen_random.py <seed> <n_instr> <out.S>

Random RV32IM program generator aimed at pipeline hazards:
  * small working set of registers (x1..x8 mostly) -> dense RAW dependencies
  * all RV32I ALU ops, all 8 RV32M ops (div-by-zero / overflow values appear often)
  * loads/stores of every width into a 256-byte window (x11 = data base)
  * forward-only branches, JAL, and AUIPC+JALR pairs (so every program terminates)
The program ends with EBREAK.  Registers x11 (base), x12 (auipc scratch) and
x13 (link) are reserved.
"""
import random
import sys

NARROW = list(range(1, 9))
WIDE = list(range(14, 32))
BASE, TMP, LINK = 11, 12, 13

RTYPE = ['add', 'sub', 'sll', 'slt', 'sltu', 'xor', 'srl', 'sra', 'or', 'and']
MTYPE = ['mul', 'mulh', 'mulhsu', 'mulhu', 'div', 'divu', 'rem', 'remu']
ITYPE = ['addi', 'slti', 'sltiu', 'xori', 'ori', 'andi']
SHIFT = ['slli', 'srli', 'srai']
BRANCH = ['beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu']
LOADS = [('lw', 4), ('lh', 2), ('lhu', 2), ('lb', 1), ('lbu', 1)]
STORES = [('sw', 4), ('sh', 2), ('sb', 1)]
EDGE = [0, 1, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 2, 0xFFFFFFFE, 0x12345678, 0xDEADBEEF, 0xFFFF]

KINDS = [('r', 22), ('m', 22), ('i', 12), ('sh', 4), ('lui', 3), ('auipc', 2), ('edge', 5),
         ('ld', 10), ('st', 8), ('br', 8), ('jal', 2), ('jalr', 2)]


def generate(seed, n):
    r = random.Random(seed)

    def dreg():
        p = r.random()
        if p < 0.84: return r.choice(NARROW)
        if p < 0.94: return r.choice(WIDE)
        return 0

    def sreg():
        p = r.random()
        if p < 0.86: return r.choice(NARROW)
        if p < 0.94: return r.choice(WIDE)
        return 0

    def imm12():
        return r.choice([0, 1, -1, 2047, -2048, 31, 32, r.randint(-2048, 2047), r.randint(-64, 64)])

    kinds, weights = zip(*KINDS)
    slots = []          # dict(type=..., asm=... | fields)

    while len(slots) < n:
        k = r.choices(kinds, weights)[0]
        idx = len(slots)
        if k in ('br', 'jal', 'jalr') and idx > n - 12:
            continue
        if k == 'r':
            slots.append(dict(t='raw', asm=f"{r.choice(RTYPE)} x{dreg()}, x{sreg()}, x{sreg()}"))
        elif k == 'm':
            slots.append(dict(t='raw', asm=f"{r.choice(MTYPE)} x{dreg()}, x{sreg()}, x{sreg()}"))
        elif k == 'i':
            slots.append(dict(t='raw', asm=f"{r.choice(ITYPE)} x{dreg()}, x{sreg()}, {imm12()}"))
        elif k == 'sh':
            slots.append(dict(t='raw', asm=f"{r.choice(SHIFT)} x{dreg()}, x{sreg()}, {r.randint(0, 31)}"))
        elif k == 'lui':
            slots.append(dict(t='raw', asm=f"lui x{dreg()}, {r.randint(0, 0xFFFFF)}"))
        elif k == 'auipc':
            slots.append(dict(t='raw', asm=f"auipc x{dreg()}, {r.randint(0, 0xFFFFF)}"))
        elif k == 'edge':
            c = r.randint(0, 4)
            d = dreg()
            asm = [f"addi x{d}, x0, 0", f"addi x{d}, x0, 1", f"addi x{d}, x0, -1",
                   f"lui x{d}, 0x80000", f"lui x{d}, 0x7ffff"][c]
            slots.append(dict(t='raw', asm=asm))
        elif k == 'ld':
            mn, size = r.choice(LOADS)
            off = r.randrange(0, 256, size)
            slots.append(dict(t='raw', asm=f"{mn} x{dreg()}, {off}(x{BASE})"))
        elif k == 'st':
            mn, size = r.choice(STORES)
            off = r.randrange(0, 256, size)
            slots.append(dict(t='raw', asm=f"{mn} x{sreg()}, {off}(x{BASE})"))
        elif k == 'br':
            slots.append(dict(t='br', op=r.choice(BRANCH), a=sreg(), b=sreg(), dist=r.randint(0, 4)))
        elif k == 'jal':
            slots.append(dict(t='jal', dist=r.randint(0, 4)))
        elif k == 'jalr':
            slots.append(dict(t='raw', asm=f"auipc x{TMP}, 0"))
            slots.append(dict(t='jalr', dist=r.randint(0, 3), auipc_idx=idx))

    total = len(slots)
    for i, s in enumerate(slots):
        s['idx'] = i
    jalr_slots = {s['idx'] for s in slots if s['t'] == 'jalr'}

    def fix(t):                      # never land in the middle of an AUIPC/JALR pair
        while t in jalr_slots:
            t += 1
        return min(t, total)

    labels = set()
    lines = []
    for s in slots:
        if s['t'] == 'br':
            t = fix(s['idx'] + 1 + s['dist']); labels.add(t)
            s['asm'] = f"{s['op']} x{s['a']}, x{s['b']}, L{t}"
        elif s['t'] == 'jal':
            t = fix(s['idx'] + 1 + s['dist']); labels.add(t)
            s['asm'] = f"jal x{LINK}, L{t}"
        elif s['t'] == 'jalr':
            t = fix(s['auipc_idx'] + 2 + s['dist'])
            labels.add(t)
            s['asm'] = f"jalr x{LINK}, {4 * (t - s['auipc_idx'])}(x{TMP})"

    for s in slots:
        if s['idx'] in labels:
            lines.append(f"L{s['idx']}:")
        lines.append("    " + s['asm'])
    lines.append(f"L{total}:")
    lines.append("    ebreak")

    prologue = ["    .section .text.start", "    .globl _start", "_start:",
                f"    lui x{BASE}, 0x10000"]
    for reg in NARROW + WIDE[:6]:
        v = r.choice(EDGE) if r.random() < 0.6 else r.getrandbits(32)
        prologue.append(f"    li x{reg}, {v}")

    data = ["", "    .section .data"]
    for _ in range(64):
        data.append(f"    .word 0x{r.getrandbits(32):08x}")

    return "\n".join(prologue + lines + data) + "\n"


if __name__ == '__main__':
    seed, n, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    with open(out, 'w') as f:
        f.write(generate(seed, n))
