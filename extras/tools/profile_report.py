#!/usr/bin/env python3
"""profile_report.py - per-tick cycle budget of the trading workload from tb_prof logs.
  python3 profile_report.py rv32im.log [rv32i.log]      (written by tools/profile_trading.sh)"""
import sys

UART_BIT = 868                       # clocks per UART bit at 100 MHz / 115200 baud


def parse(path):
    d = {}
    for ln in open(path):
        if ln.startswith(('PROF', 'TIMELINE')):
            for kv in ln.split()[1:]:
                k, v = kv.split('=')
                d[ln.split()[0] + '.' + k] = int(v)
    return d


def report(name, d):
    n, t = d['PROF.windows'], d['TIMELINE.ticks']
    cyc, ret = d['PROF.cycles'] / n, d['PROF.retired'] / n
    lu, md, fl = d['PROF.loaduse'] / n, d['PROF.mdstall'] / n, d['PROF.flush'] / n
    print('%s: software decision (sw_decide) over %d ticks' % (name, n))
    print('  cycles per decision        %7.1f   (CPI %.2f)' % (cyc, cyc / ret))
    print('    instructions retired     %7.1f' % ret)
    print('    taken-branch flushes     %7.1f   (%.1f taken branches/jumps x 2 bubbles)' % (2 * fl, fl))
    print('    MUL/DIV stalls           %7.1f   (%.1f M instructions)' % (md, d['PROF.mops'] / n))
    print('    load-use stalls          %7.1f' % lu)
    print('  operands forwarded         %7.1f   (each would be a 1-2 cycle stall without forwarding)' % (d['PROF.fwd'] / n))
    print('  loads / stores             %7.1f / %.1f' % (d['PROF.loads'] / n, d['PROF.stores'] / n))
    print('  timeline after the last byte of a tick arrives (cycles at 100 MHz):')
    print('    hardware decision        %7.1f' % (d['TIMELINE.hw_decision'] / t))
    print('    CPU sees the tick        %7.1f   (polling loop)' % (d['TIMELINE.cpu_sees_tick'] / t))
    print('    software decision done   %7.1f' % (d['TIMELINE.sw_decision_done'] / t))
    print('    first report byte out    %7.1f' % (d['TIMELINE.first_report_byte'] / t))
    print('  for scale: receiving one 12-byte tick over the UART takes %d cycles (%.2f ms), sending the'
          ' 40-byte report %d cycles (%.2f ms)' % (12 * 10 * UART_BIT, 12 * 10 * UART_BIT / 1e5, 40 * 10 * UART_BIT,
                                                    40 * 10 * UART_BIT / 1e5))
    return cyc


if __name__ == '__main__':
    c = [report(['RV32IM firmware', 'RV32I firmware (no multiply/divide hardware)'][i], parse(p))
         for i, p in enumerate(sys.argv[1:3])]
    if len(c) == 2:
        print('\nM extension speed-up of the software decision: %.1fx (%.0f -> %.0f cycles); hardware accelerator: 5 cycles'
              % (c[1] / c[0], c[1], c[0]))
