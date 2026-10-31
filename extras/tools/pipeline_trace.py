#!/usr/bin/env python3
"""
pipeline_trace.py <prog.elf> <trace.txt> [first_cycle [last_cycle]]

Turns the `TRACE` lines printed by tb_core.v (+TRACE) into a cycle-by-cycle
pipeline occupancy table - the raw material for the timing diagram in the report.

  IF column :  <instr>~  = fetched this cycle but squashed by a flush
               <instr>=  = held (PC and IF/ID frozen by a stall)
  ID/EX     :  '--' is a bubble
  MEM / WB  :  derived from EX: an instruction leaves EX unless the M unit is busy.
  Flags     :  LU = load-use stall   MD = multi-cycle MUL/DIV stall   BR = taken branch/jump

Typical use:
  vvp build/tb_core.vvp +IMEM=build/x_imem.hex +DMEM=build/x_dmem.hex +TRACE > trace.txt
  python3 tools/pipeline_trace.py build/x.elf trace.txt 0 40
"""
import os
import re
import subprocess
import sys


def disassemble(elf):
    out = subprocess.run([os.environ.get('RISCV_PREFIX', 'riscv64-unknown-elf') + '-objdump', '-d', '-M', 'no-aliases,numeric', elf],
                         capture_output=True, text=True, check=True).stdout
    names = {}
    for line in out.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s+[0-9a-f]{8}\s+(.*)', line)
        if m:
            names[int(m.group(1), 16)] = re.sub(r'\s+', ' ', m.group(2).split('#')[0].strip())
    return names


def main():
    elf, trace = sys.argv[1], sys.argv[2]
    first = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    last = int(sys.argv[4]) if len(sys.argv) > 4 else 10**9
    names = disassemble(elf)
    nm = lambda pc: names.get(pc, '???')

    rows = []
    for line in open(trace):
        p = line.split()
        if p and p[0] == 'TRACE':
            cyc, if_pc, idv, id_pc, exv, ex_pc, md, lu, br = p[1:]
            rows.append((int(cyc), int(if_pc, 16), int(idv), int(id_pc, 16),
                         int(exv), int(ex_pc, 16), int(md), int(lu), int(br)))

    mem = wb = '--'
    print(f"{'cyc':>4} | {'IF':<24} | {'ID':<24} | {'EX':<24} | {'MEM':<24} | {'WB':<24} | flags")
    print('-' * 150)
    for cyc, if_pc, idv, id_pc, exv, ex_pc, md, lu, br in rows:
        if_s = nm(if_pc)
        if br:
            if_s += '~'
        elif md or lu:
            if_s += '='
        id_s = nm(id_pc) if idv else '--'
        ex_s = nm(ex_pc) if exv else '--'
        if first <= cyc <= last:
            flags = ' '.join(f for f, on in (('LU', lu), ('MD', md), ('BR', br)) if on)
            print(f"{cyc:>4} | {if_s:<24} | {id_s:<24} | {ex_s:<24} | {mem:<24} | {wb:<24} | {flags}")
        # advance the derived MEM/WB view for the next cycle
        wb = mem
        mem = '--' if (md or not exv) else ex_s


if __name__ == '__main__':
    main()
