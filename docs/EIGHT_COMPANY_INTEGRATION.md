# Eight-company SoC integration

`extras/tb/tb_soc_8company.v` instantiates `soc_top` with `HFT_N_MAX=N` and runs the real firmware. `check_soc8.py` compares every report with `SysModel` (phases A..F plus a directed rotation phase D2).

N=8 result: 2954 stimulus lines, 2812 reports, 2241 ticks, 411 commands, 64 untraded-company ticks, 96 allocations with 3 rotations, 106 stop-bit glitches, 26 truncated packets, 2 board resets, 8 counter checks. PASS. N=4 and N=2 also PASS. The shipped board image also PASSES at N=8.
