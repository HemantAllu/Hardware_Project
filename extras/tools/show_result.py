#!/usr/bin/env python3
"""show_result.py - print what a C program computed on the RV32IM core (used by the Makefile).

  python3 tools/show_result.py <prog.elf> <sim_output.txt> <imem.hex> <dmem.hex>

Reads the register / data-memory dump that tb_core.v prints when the program
reaches EBREAK, prints every global variable of the program as decimal numbers,
the cycle statistics, and compares the run with the instruction-set reference
model (tools/rvsim.py): PASS if every register and dumped memory word match.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rvsim  # noqa: E402

DMEM_BASE = 0x10000000
PREFIX = os.environ.get('RISCV_PREFIX', 'riscv64-unknown-elf')


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def parse(path):
    reg, mem, stat, timeout = {}, {}, {}, False
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0] == 'REG':
            reg[int(p[1])] = int(p[2], 16)
        elif p[0] == 'MEM':
            mem[int(p[1])] = int(p[2], 16)
        elif p[0] in ('CYCLES', 'RETIRED', 'LOADUSE_STALLS', 'MD_STALLS', 'TAKEN_CTRL'):
            stat[p[0]] = int(p[1])
        elif p[0] == 'TIMEOUT':
            timeout = True
    return reg, mem, stat, timeout


def variables(elf):
    """Global variables in data memory: (name, word index, number of words)."""
    out = subprocess.run([PREFIX + '-nm', '-S', '--defined-only', '-n', elf], capture_output=True, text=True,
                         check=True).stdout
    found = []
    for line in out.splitlines():
        p = line.split()
        if len(p) == 4 and p[2] in 'bBdDgGsS' and not p[3].startswith('__'):
            addr, size = int(p[0], 16), int(p[1], 16)
            if addr >= DMEM_BASE:
                found.append((p[3], (addr - DMEM_BASE) // 4, max(1, size // 4)))
    return found


def main():
    elf, simout, imem, dmem = sys.argv[1:5]
    name = os.path.splitext(os.path.basename(os.path.dirname(elf)))[0]
    reg, mem, stat, timeout = parse(simout)
    print('=' * 64)
    print(' %s  -  ran on the RV32IM 5-stage core (Verilog simulation)' % name)
    print('=' * 64)
    if timeout or not stat:
        print(' the program did not finish (timeout): no results')
        sys.exit(1)

    ref = rvsim.RV32IM(rvsim.read_hex(imem), rvsim.read_hex(dmem))
    ref.run()
    for var, idx, n in variables(elf):
        vals = []
        for k in range(idx, idx + n):
            vals.append(s32(mem[k]) if k in mem else s32(ref.dmem[k]))
        shown = vals if n <= 24 else vals[:24]
        txt = ', '.join(str(v) for v in shown) + (' ... (%d values)' % n if n > 24 else '')
        print(' %-10s = %s' % (var, txt if n > 1 else txt))
    print('-' * 64)
    c, r = stat['CYCLES'], stat['RETIRED']
    print(' cycles %d   instructions %d   CPI %.2f' % (c, r, c / max(1, r)))
    print(' stalls: load-use %d   MUL/DIV %d   taken branches/jumps %d'
          % (stat.get('LOADUSE_STALLS', 0), stat.get('MD_STALLS', 0), stat.get('TAKEN_CTRL', 0)))
    diffs = [i for i in range(1, 32) if reg.get(i) != ref.x[i]]
    diffs += ['mem%d' % i for i in mem if mem[i] != ref.dmem[i]]
    print('-' * 64)
    if diffs:
        print(' FAIL: %d registers/memory words differ from the reference model' % len(diffs))
        sys.exit(1)
    print(' PASS: every register and memory word matches the reference model')
    # self-checking programs (add, sub, xor, mul, div) count their wrong results in `errors`
    for var, idx, n in variables(elf):
        if var == 'errors':
            e = mem[idx] if idx in mem else ref.dmem[idx]
            if e:
                print(' FAIL: the program found %d results different from the expected values' % e)
                sys.exit(1)
            print(' PASS: every result equals the expected value (errors = 0)')


if __name__ == '__main__':
    main()
