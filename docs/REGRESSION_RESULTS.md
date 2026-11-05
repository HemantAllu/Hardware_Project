# Regression results

Runner: `extras/tools/run_v12_full_regression.sh` (`--fast` skips step 8 and 6b, exit code 2 = partial).
Tools: Icarus Verilog 13, Verilator 5.031, Python 3, gcc, riscv-none-elf-gcc.

| Step | Result | Detail |
|---|---|---|
| 1 python syntax | PASS | |
| 2 model rules | PASS | cash/inventory interlock, moving average, zero volume, blocked counters |
| 3 UART | PASS | 220 bytes, 2 expected framing errors, 64 loop-back |
| 4a muldiv project TB | PASS | |
| 4b muldiv host-C reference | PASS | 163,872 vectors, 0 errors |
| 5 RV32IM core | PASS | directed, SoC demo, C programs, 200 random (2000 random also PASS) |
| 6 chain N=1/2/4/8 | PASS | e.g. N=8: 294 CPU packets, 279 engine ticks, 279 decisions, 131 register reads |
| 6b chain N=8 Icarus | PASS (273 s) | second simulator |
| 7 SoC 8/4/2 company | PASS | N=8: 2812 reports, 2241 ticks, 411 commands, 96 allocations (3 rotations), 106 glitches, 26 truncated packets, 2 resets |
| 7 burst | PASS | 28 single + 48 back-to-back: 14 accepted, 34 dropped, all counted in OVERRUN |
| 7 shipped board image | PASS | |
| 8 original suite | PASS (2017 s) | |
| 9 lint N=2 / N=8 | PASS: 0 errors; 80 / 70 warnings | all WIDTHTRUNC / WIDTHEXPAND |

Final full run (no `--fast`): every step PASS, runner prints `ALL V12-VERIFIED TESTS PASS`, exit 0. Log: `extras/build_v12/logs/`.
