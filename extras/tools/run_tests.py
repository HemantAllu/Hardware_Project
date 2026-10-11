#!/usr/bin/env python3
"""
run_tests.py - regression for the RV32IM 5-stage core (needs iverilog + riscv gcc).

  python3 tools/run_tests.py                 # everything, 200 random programs
  python3 tools/run_tests.py --seeds 1000    # more random programs
  python3 tools/run_tests.py --only directed

Tests
  muldiv   : unit test of muldiv_unit (tb/tb_muldiv.v)
  directed : self-checking asm test (forwarding, load-use, control, RV32M hazards,
             table-driven RV32M).  Passes when dmem word 0 == 1 AND the final
             register/memory state equals the Python golden model.
  soc      : full SoC (soc_top) running sw/demo_board.S, checks the 7-segment sequence.
  c        : sw/examples/*.c compiled for rv32im, RTL state vs golden model.
  random   : random hazard-heavy programs, RTL final state vs golden model.
"""
import argparse
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build'
sys.path.insert(0, str(ROOT / 'tools'))
import rvsim            # noqa: E402
import gen_random       # noqa: E402

PREFIX = os.environ.get('RISCV_PREFIX', 'riscv64-unknown-elf')   # set by the Makefile (Windows: riscv-none-elf)
CC = PREFIX + '-gcc'
OBJCOPY = PREFIX + '-objcopy'
RTL = ['alu', 'imm_gen', 'regfile', 'control', 'forwarding_unit', 'hazard_unit',
       'muldiv_unit', 'imem', 'dmem', 'rv32im_core']
# RTL lives in <root>/rtl in the standalone repo and in <root>/../src/rtl in the Vivado project folder
RTLDIR = ROOT / 'rtl' if (ROOT / 'rtl').exists() else ROOT.parent / 'src' / 'rtl'
RTL_FILES = [str(RTLDIR / f'{m}.v') for m in RTL]
# soc_top also instantiates the trading accelerator
HFT_FILES = [str(RTLDIR / f'{m}.v') for m in ('hft_mmio', 'hft_multi', 'hft_alloc', 'hft_accelerator', 'tick_parser', 'uart')]


def run(cmd, **kw):
    r = subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)
    # RTL self-checks (e.g. the core's forwarding cross-check) print "ERROR <module>: ..."
    bad = [ln for ln in r.stdout.splitlines() if ln.startswith('ERROR ')]
    if bad:
        raise SystemExit('RTL self-check failed in %s:\n  %s' % (' '.join(map(str, cmd[:2])), '\n  '.join(bad[:5])))
    return r


def build_sim():
    run(['iverilog', '-g2005', '-Wall', '-o', str(BUILD / 'tb_core.vvp'),
         str(ROOT / 'tb' / 'tb_core.v')] + RTL_FILES)
    run(['iverilog', '-g2005', '-Wall', '-o', str(BUILD / 'tb_muldiv.vvp'),
         str(ROOT / 'tb' / 'tb_muldiv.v'), str(RTLDIR / 'muldiv_unit.v')])
    run(['iverilog', '-g2005', '-Wall', '-o', str(BUILD / 'tb_soc.vvp'),
         str(ROOT / 'tb' / 'tb_soc.v'), str(RTLDIR / 'soc_top.v'),
         str(RTLDIR / 'seg7_driver.v')] + RTL_FILES + HFT_FILES)


def assemble(src, tag, extra=()):
    elf = BUILD / f'{tag}.elf'
    srcs = src if isinstance(src, (list, tuple)) else [src]
    run([CC, '-march=rv32im', '-mabi=ilp32', '-nostdlib', '-nostartfiles', *extra,
         '-T', str(ROOT / 'sw' / 'link.ld'), *map(str, srcs), '-o', str(elf)])
    run([OBJCOPY, '-O', 'binary', '-j', '.text', str(elf), str(BUILD / f'{tag}_i.bin')])
    run([OBJCOPY, '-O', 'binary', '-j', '.rodata', '-j', '.data', str(elf),
         str(BUILD / f'{tag}_d.bin')])
    run([sys.executable, str(ROOT / 'tools' / 'bin2hex.py'),
         str(BUILD / f'{tag}_i.bin'), str(BUILD / f'{tag}_imem.hex')])
    run([sys.executable, str(ROOT / 'tools' / 'bin2hex.py'),
         str(BUILD / f'{tag}_d.bin'), str(BUILD / f'{tag}_dmem.hex')])
    return BUILD / f'{tag}_imem.hex', BUILD / f'{tag}_dmem.hex'


def parse(out):
    res = {'reg': [None] * 32, 'mem': {}, 'stat': {}}
    for line in out.splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == 'REG':
            res['reg'][int(p[1])] = int(p[2], 16)
        elif p[0] == 'MEM':
            res['mem'][int(p[1])] = int(p[2], 16)
        elif p[0] in ('CYCLES', 'RETIRED', 'LOADUSE_STALLS', 'MD_STALLS', 'TAKEN_CTRL'):
            res['stat'][p[0]] = int(p[1])
        elif p[0] == 'TIMEOUT':
            res['timeout'] = True
    return res


def run_rtl(imem, dmem, vcd=None):
    cmd = ['vvp', str(BUILD / 'tb_core.vvp'), f'+IMEM={imem}', f'+DMEM={dmem}']
    if vcd:
        cmd.append(f'+VCD={vcd}')
    return parse(run(cmd).stdout)


def run_ref(imem, dmem):
    sim = rvsim.RV32IM(rvsim.read_hex(imem), rvsim.read_hex(dmem))
    sim.run()
    return {'reg': sim.x, 'mem': {i: sim.dmem[i] for i in range(64)}, 'steps': sim.steps}


def compare(rtl, ref):
    diffs = []
    if rtl.get('timeout'):
        diffs.append('RTL timeout')
    for i in range(1, 32):
        if rtl['reg'][i] != ref['reg'][i]:
            diffs.append(f"x{i}: rtl={rtl['reg'][i]:08x} ref={ref['reg'][i]:08x}")
    for i in range(64):
        if rtl['mem'].get(i) != ref['mem'][i]:
            diffs.append(f"mem[{i}]: rtl={rtl['mem'].get(i, 0):08x} ref={ref['mem'][i]:08x}")
    return diffs


def test_muldiv():
    out = run(['vvp', str(BUILD / 'tb_muldiv.vvp')]).stdout
    ok = 'TB_MULDIV PASS' in out
    print(f"[muldiv ] {'PASS' if ok else 'FAIL'}  ({out.splitlines()[0]})")
    if not ok:
        print(out)
    return ok


def test_directed():
    src = BUILD / 'test_directed.S'
    run([sys.executable, str(ROOT / 'tools' / 'gen_directed.py'), str(src)])
    imem, dmem = assemble(src, 'directed')
    rtl = run_rtl(imem, dmem)
    ref = run_ref(imem, dmem)
    diffs = compare(rtl, ref)
    flag = rtl['mem'].get(0)
    ok = (flag == 1) and not diffs
    s = rtl['stat']
    print(f"[directed] {'PASS' if ok else 'FAIL'}  flag={flag} (1=pass, 2=fail id={rtl['mem'].get(1)})  "
          f"cycles={s.get('CYCLES')} retired={s.get('RETIRED')} (ref {ref['steps']}) "
          f"CPI={s.get('CYCLES', 0) / max(1, s.get('RETIRED', 1)):.2f} "
          f"load-use={s.get('LOADUSE_STALLS')} md-stall={s.get('MD_STALLS')} taken={s.get('TAKEN_CTRL')}")
    for d in diffs[:10]:
        print('   ', d)
    return ok


def test_soc():
    """Board demo (short DELAY) on the full SoC: checks the 7-segment sequence."""
    imem, dmem = assemble(ROOT / 'sw' / 'demo_board.S', 'demo',
                          extra=['-Wa,--defsym,DELAY=200'])
    out = run(['vvp', str(BUILD / 'tb_soc.vvp'), f'+IMEM={imem}', f'+DMEM={dmem}']).stdout
    ok = 'TB_SOC PASS' in out
    cyc = re.search(r'measured DIVU cycles.*= (\d+)', out)
    print(f"[soc    ] {'PASS' if ok else 'FAIL'}  demo_board.S sequence on 7-seg"
          f"{'  (DIVU measured ' + cyc.group(1) + ' cycles)' if cyc else ''}")
    if not ok:
        print(out)
    return ok


def test_c():
    """C workloads (sw/examples/*.c): RTL final state must equal the golden model."""
    ok_all = True
    for c in sorted((ROOT / 'sw' / 'examples').glob('*.c')):
        tag = 'c_' + c.stem
        imem, dmem = assemble([ROOT / 'sw' / 'crt0.S', c], tag,
                              extra=['-O2', '-ffreestanding', '-fno-asynchronous-unwind-tables'])
        rtl = run_rtl(imem, dmem)
        ref = run_ref(imem, dmem)
        diffs = compare(rtl, ref)
        if rtl['stat'].get('RETIRED') != ref['steps']:
            diffs.append(f"retired rtl={rtl['stat'].get('RETIRED')} ref={ref['steps']}")
        ok = not diffs
        ok_all &= ok
        s = rtl['stat']
        print(f"[c      ] {'PASS' if ok else 'FAIL'}  {c.name:<10} cycles={s.get('CYCLES'):>6} "
              f"retired={s.get('RETIRED'):>6} CPI={s.get('CYCLES', 0) / max(1, s.get('RETIRED', 1)):.2f} "
              f"md-stall={s.get('MD_STALLS')} load-use={s.get('LOADUSE_STALLS')} taken={s.get('TAKEN_CTRL')}")
        for d in diffs[:6]:
            print('   ', d)
    return ok_all


def test_random(seeds, length):
    bad = 0
    tot_cycles = tot_ret = 0
    for seed in range(1, seeds + 1):
        src = BUILD / 'rand.S'
        src.write_text(gen_random.generate(seed, length))
        imem, dmem = assemble(src, 'rand')
        rtl = run_rtl(imem, dmem)
        ref = run_ref(imem, dmem)
        diffs = compare(rtl, ref)
        # retired count must also match the reference instruction count
        # (+1: EBREAK itself retires in the RTL, and the ref counts it too)
        if rtl['stat'].get('RETIRED') != ref['steps']:
            diffs.append(f"retired rtl={rtl['stat'].get('RETIRED')} ref={ref['steps']}")
        tot_cycles += rtl['stat'].get('CYCLES', 0)
        tot_ret += rtl['stat'].get('RETIRED', 0)
        if diffs:
            bad += 1
            keep = BUILD / f'fail_seed{seed}.S'
            keep.write_text(src.read_text())
            print(f"[random ] seed {seed} MISMATCH ({len(diffs)} diffs) -> {keep.name}")
            for d in diffs[:6]:
                print('   ', d)
            if bad >= 5:
                break
    print(f"[random ] {'PASS' if bad == 0 else 'FAIL'}  {seeds} programs x {length} instr, "
          f"{bad} mismatching, avg CPI={tot_cycles / max(1, tot_ret):.2f}")
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=200)
    ap.add_argument('--len', type=int, default=300)
    ap.add_argument('--only', choices=['muldiv', 'directed', 'soc', 'c', 'random'])
    args = ap.parse_args()

    BUILD.mkdir(exist_ok=True)
    build_sim()
    results = []
    if args.only in (None, 'muldiv'):
        results.append(test_muldiv())
    if args.only in (None, 'directed'):
        results.append(test_directed())
    if args.only in (None, 'soc'):
        results.append(test_soc())
    if args.only in (None, 'c'):
        results.append(test_c())
    if args.only in (None, 'random'):
        results.append(test_random(args.seeds, args.len))
    print('ALL PASS' if all(results) else 'SOME TESTS FAILED')
    sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
