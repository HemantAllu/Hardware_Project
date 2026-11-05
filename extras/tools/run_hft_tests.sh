#!/bin/bash
# run_hft_tests.sh : trading accelerator tests (Icarus Verilog + RISC-V GCC)
#   0. model       Python reference model rules                        (tools/test_no_borrow.py)
#   0b. uart       uart_rx majority filter + stop-bit (framing) check, glitches, break, loop-back
#   1. unit        tick_parser + hft_accelerator, 3000 random ticks (some with volume 0),
#                  back-to-back ticks, parser resync after a broken packet, VWAP-sum overflow
#   1b. buffer     a third tick while one waits: dropped (not overwriting) and counted
#   2. cash        accelerator risk interlock: random starting cash (64-bit), position limit,
#                  SELL without holdings, zero volume, kill switch, `clear`, back-to-back pairs
#   3. system      soc_top running the freshly built hft_firmware.c; ticks sent over the UART, 40-byte
#                  reports checked against the model (default cash, small cash, 64-bit cash,
#                  AAPL scale, zero-volume ticks, kill switch, resets)
#   3b. kill flip  the system test again, with SW0 flipped while every tick is in flight
#   4. flow        the "PC" streams packets without waiting for the reports: whole packets must be
#                  dropped for hardware AND software alike (OVERRUN, LED3), never one side only
#   6. multi       hft_multi.v with 2, 4 and 8 engines, one shared cash account: random ticks incl.
#                  several companies in the SAME cycle (the cash unit serves one engine per cycle,
#                  lowest index first; latency 5 + cycles waited), caps, cash running out,
#                  plus two directed priority cases                      (tools/check_multi.py)
#   7. 2 companies soc_top + firmware with NUM_SYMBOLS = 2: interleaved ticks of two companies,
#                  per-company config and cap, shared cash, an untraded company, back to 1 company
#   8. allocator   hft_multi.v in portfolio mode (engines + hft_alloc.v), 2, 4 and 8 companies, 2 seeds: directed
#                  cases (rank, rotation, MIN_HOLD / MARGIN blocks, win / loss reweight, floor, kill,
#                  cap, MAX_LOTS, saturation, one rotation per minute), runs ON the decision
#                  boundaries, random runs; every minute checked against PortfolioModel (check_port.py)
#   9. portfolio   soc_top + firmware in portfolio mode: ticks, ALLOCATE every minute, the C copy
#                  of the allocator must agree with the hardware, and both with the model
#   5. board image the same system + flow (+ 2-company + portfolio) tests with the image that is shipped in
#                  src/mem/imem.mem, so a stale board image (older firmware than hft_firmware.c) is caught
#  10. mutation    (only with MUTATION=1) 17 allocator bugs planted one at a time, all must be caught
#   usage: extras/tools/run_hft_tests.sh        (from anywhere, ~20 minutes; MUTATION=1 adds ~15)
set -euo pipefail
X=$(cd "$(dirname "$0")/.." && pwd)          # extras/
R=$X/../src/rtl
M=$X/../src/mem
B=$X/build_hft; mkdir -p "$B"
CORE="$R/rv32im_core.v $R/alu.v $R/control.v $R/imm_gen.v $R/regfile.v $R/forwarding_unit.v $R/hazard_unit.v $R/muldiv_unit.v $R/imem.v $R/dmem.v $R/seg7_driver.v"
HFT="$R/hft_mmio.v $R/hft_multi.v $R/hft_alloc.v $R/hft_accelerator.v $R/tick_parser.v $R/uart.v"

echo "== 0. model rules"
python3 "$X/tools/test_no_borrow.py"

echo "== 0b. UART receiver: majority filter, stop-bit check, glitches, break, loop-back"
iverilog -g2012 -o "$B/uart.vvp" "$X/tb/tb_uart.v" "$R/uart.v"
vvp -n "$B/uart.vvp" > "$B/uart.log"
grep -q "^TB_UART PASS" "$B/uart.log" || { cat "$B/uart.log"; echo "FAIL: tb_uart"; exit 1; }
grep "^TB_UART" "$B/uart.log"

echo "== 1. unit test (tick_parser + accelerator)"
python3 "$X/tools/check_hft.py" genrand "$B/rand.txt"
iverilog -g2012 -o "$B/unit.vvp" "$X/tb/tb_hft_unit.v" "$R/tick_parser.v" "$R/hft_accelerator.v"
vvp -n "$B/unit.vvp" +TICKS="$B/rand.txt" > "$B/unit.log"
python3 "$X/tools/check_hft.py" unit "$B/rand.txt" "$B/unit.log"

echo "== 1b. engine input buffer: a tick that finds the buffer full is dropped and counted"
iverilog -g2012 -o "$B/drop.vvp" "$X/tb/tb_hft_drop.v" "$R/hft_accelerator.v"
vvp -n "$B/drop.vvp" > "$B/drop.log"
grep -q "^TB_HFT_DROP PASS" "$B/drop.log" || { cat "$B/drop.log"; echo "FAIL: tb_hft_drop"; exit 1; }
grep "^TB_HFT_DROP" "$B/drop.log"

echo "== 2. accelerator risk interlock (cash / limit / zero volume / clear)"
iverilog -g2012 -o "$B/cash.vvp" "$X/tb/tb_hft_cash.v" "$R/hft_accelerator.v"
for seed in 1 2 3; do
    python3 "$X/tools/check_cash.py" gen "$B/cash_ops_$seed.txt" "$seed" 60 > /dev/null
    vvp -n "$B/cash.vvp" +OPS="$B/cash_ops_$seed.txt" > "$B/cash_$seed.log"
    python3 "$X/tools/check_cash.py" check "$B/cash_ops_$seed.txt" "$B/cash_$seed.log"
done

echo "== 3. system test (firmware built from hft_firmware.c on the core, UART in/out)"
bash "$X/sw/build.sh" "$X/hft_firmware.c" "$B/fw" > /dev/null
[ -s "$B/fw/dmem.hex" ] || echo 00000000 > "$B/fw/dmem.hex"
python3 "$X/tools/check_hft.py" gen "$B/ticks.txt"
python3 "$X/tools/check_hft.py" genburst "$B/burst.txt"
iverilog -g2012 -o "$B/sys.vvp" "$X/tb/tb_hft.v" "$R/soc_top.v" $CORE $HFT
vvp -n "$B/sys.vvp" +IMEM="$B/fw/imem.hex" +DMEM="$B/fw/dmem.hex" +TICKS="$B/ticks.txt" > "$B/sys.log"
python3 "$X/tools/check_hft.py" check "$B/ticks.txt" "$B/sys.log"

echo "== 3b. kill switch flipped while each tick is being processed (HW = SW = model)"
vvp -n "$B/sys.vvp" +IMEM="$B/fw/imem.hex" +DMEM="$B/fw/dmem.hex" +TICKS="$B/ticks.txt" +KILLFLIP > "$B/sys_killflip.log"
python3 "$X/tools/check_hft.py" check "$B/ticks.txt" "$B/sys_killflip.log"

echo "== 4. flow control (packets streamed without waiting for the reports)"
vvp -n "$B/sys.vvp" +IMEM="$B/fw/imem.hex" +DMEM="$B/fw/dmem.hex" +TICKS="$B/burst.txt" +NOWAIT=5 > "$B/burst.log"
python3 "$X/tools/check_hft.py" checkburst "$B/burst.txt" "$B/burst.log"

echo "== 6. multi-company engines (hft_multi.v, shared cash, same-cycle priority)"
for N in 2 4 8; do
    iverilog -g2012 -P tb_hft_multi.N=$N -o "$B/multi$N.vvp" "$X/tb/tb_hft_multi.v" "$R/hft_multi.v" "$R/hft_alloc.v" "$R/hft_accelerator.v"
    for seed in 1 2 3; do
        python3 "$X/tools/check_multi.py" gen "$B/multi_ops_${N}_$seed.txt" "$seed" "$N" 300 > /dev/null
        vvp -n "$B/multi$N.vvp" +OPS="$B/multi_ops_${N}_$seed.txt" > "$B/multi_${N}_$seed.log"
        python3 "$X/tools/check_multi.py" check "$B/multi_${N}_$seed.log" "$N"
    done
done

echo "== 7. two companies through the whole system (firmware, NUM_SYMBOLS = 2)"
python3 "$X/tools/check_hft.py" genmulti "$B/multi.txt"
vvp -n "$B/sys.vvp" +IMEM="$B/fw/imem.hex" +DMEM="$B/fw/dmem.hex" +TICKS="$B/multi.txt" > "$B/sys_multi.log"
python3 "$X/tools/check_hft.py" check "$B/multi.txt" "$B/sys_multi.log"

echo "== 8. portfolio allocator (hft_alloc.v) against PortfolioModel"
for N in 2 4 8; do
    iverilog -g2012 -P tb_hft_port.N=$N -o "$B/port$N.vvp" "$X/tb/tb_hft_port.v" "$R/hft_multi.v" "$R/hft_alloc.v" "$R/hft_accelerator.v"
    for seed in 3 7; do
        python3 "$X/tools/check_port.py" gen "$B/port_ops_${N}_$seed.txt" $seed "$N" 300 > /dev/null
        vvp -n "$B/port$N.vvp" +OPS="$B/port_ops_${N}_$seed.txt" > "$B/port_${N}_$seed.log"
        python3 "$X/tools/check_port.py" check "$B/port_${N}_$seed.log" "$N"
    done
done

echo "== 9. portfolio mode through the whole system (firmware + hardware allocator)"
python3 "$X/tools/check_hft.py" genport "$B/port.txt"
vvp -n "$B/sys.vvp" +IMEM="$B/fw/imem.hex" +DMEM="$B/fw/dmem.hex" +TICKS="$B/port.txt" > "$B/sys_port.log"
python3 "$X/tools/check_hft.py" checkport "$B/port.txt" "$B/sys_port.log"

echo "== 5. the board image shipped in src/mem/imem.mem"
if ! { vvp -n "$B/sys.vvp" +IMEM="$M/imem.mem" +DMEM="$M/dmem.mem" +TICKS="$B/ticks.txt" > "$B/sys_shipped.log" &&
       vvp -n "$B/sys.vvp" +IMEM="$M/imem.mem" +DMEM="$M/dmem.mem" +TICKS="$B/multi.txt" > "$B/sys_multi_shipped.log" &&
       python3 "$X/tools/check_hft.py" check "$B/multi.txt" "$B/sys_multi_shipped.log" &&
       python3 "$X/tools/check_hft.py" check "$B/ticks.txt" "$B/sys_shipped.log" &&
       vvp -n "$B/sys.vvp" +IMEM="$M/imem.mem" +DMEM="$M/dmem.mem" +TICKS="$B/burst.txt" +NOWAIT=5 > "$B/burst_shipped.log" &&
       python3 "$X/tools/check_hft.py" checkburst "$B/burst.txt" "$B/burst_shipped.log" &&
       vvp -n "$B/sys.vvp" +IMEM="$M/imem.mem" +DMEM="$M/dmem.mem" +TICKS="$B/port.txt" > "$B/sys_port_shipped.log" &&
       python3 "$X/tools/check_hft.py" checkport "$B/port.txt" "$B/sys_port_shipped.log"; }; then
    echo "FAIL: src/mem/imem.mem does not behave like hft_firmware.c (stale board image?)."
    echo "      Rebuild it with:  bash extras/tools/make_board_image.sh"
    exit 1
fi
if [ "${MUTATION:-0}" = "1" ]; then
    echo "== 10. mutation test of the allocator (N = 4)"
    python3 "$X/tools/check_port.py" gen "$B/m4.txt" 3 4 300 > /dev/null
    (cd "$X/.." && python3 extras/tools/mutate_port.py "$B" 4)
fi

# RTL self-checks (cash unit serves one engine per cycle, core forwarding cross-check, ...)
if grep -l "^ERROR " "$B"/*.log > /dev/null 2>&1; then
    echo "FAIL: RTL self-check errors in:"; grep -l "^ERROR " "$B"/*.log; exit 1
fi
echo "ALL HFT TESTS PASS"
