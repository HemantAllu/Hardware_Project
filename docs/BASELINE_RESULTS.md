# Baseline (original v12 zip, before changes)

* The original RTL does not elaborate under Icarus Verilog 13 (`hold_req`, `kill_l` used before declaration). Fixed as V12-FIX-01 so a baseline could be taken.
* Original `tools/run_hft_tests.sh` after V12-FIX-01 only: ALL HFT TESTS PASS, 33 m 59 s wall time.
* The same suite never injected a framing error into the parser, so it could not see the P0 bug.
* New chain test and 8-company SoC test on the ORIGINAL parser: FAIL. The chain test lists the packets after each framing error as MISSING. The SoC test reports BADFRAME / NOREPORT for the following ticks.
* RV32IM core suite: 15 PASS lines, 200 random programs (2000-program run also passes, avg CPI 4.97).
