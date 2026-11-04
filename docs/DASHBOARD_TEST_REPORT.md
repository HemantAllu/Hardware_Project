# Dashboard V2.0 Verification & Test Report

## Summary
The **Dashboard V2.0** architecture was verified through full automated regression suites, hardware-in-the-loop simulation runs, and backward compatibility testing. Zero regressions were introduced, and all 10 regression stages passed with a 100% pass rate.

---

## 1. Automated Regression Suite Execution (`run_complete_regression.py`)

Execution Environment: Windows 11, Python 3.14, Vivado 2025.2 (`xvlog`).

```
==========================================================================
      RV32IM COMPLETE V12 UPGRADE — AUTOMATED REGRESSION SUITE            
==========================================================================
--> Running: 1. Python Syntax Validation ... [PASS] (0.43s)
--> Running: 2. Non-Borrowing Invariant Suite ... [PASS] (0.05s)
--> Running: 3. Physical Strategy Selector Test ... [PASS] (0.05s)
--> Running: 4. Multi-Company Offline Model Test ... [PASS] (37.82s)
--> Running: 5. Quantitative Backtest Suite ... [PASS] (2.06s)
--> Running: 6. P99 Latency Benchmark Suite ... [PASS] (2.25s)
--> Running: 7. FPGA Resource Scalability Suite ... [PASS] (1.96s)
--> Running: 8. Dashboard Headless Capture ... [PASS] (2.30s)
--> Running: 9. Verilog RTL xvlog Analysis ... [PASS] (1.33s)
--> Running: Mutation Testing Suite ... [PASS] (4/4 mutations caught)

==========================================================================
                         REGRESSION REPORT SUMMARY                         
==========================================================================
  1. Python Syntax Validation              | PASS   |  0.43s | 
  2. Non-Borrowing Invariant Suite         | PASS   |  0.05s | 
  3. Physical Strategy Selector Test       | PASS   |  0.05s | 
  4. Multi-Company Offline Model Test      | PASS   | 37.82s | 
  5. Quantitative Backtest Suite           | PASS   |  2.06s | 
  6. P99 Latency Benchmark Suite           | PASS   |  2.25s | 
  7. FPGA Resource Scalability Suite       | PASS   |  1.96s | 
  8. Dashboard Headless Capture            | PASS   |  2.30s | 
  9. Verilog RTL xvlog Analysis            | PASS   |  1.33s | 
  10. Mutation & Assertion Testing         | PASS   |  0.05s | 
--------------------------------------------------------------------------
  TOTAL TESTS: 10 | PASSED: 10 | FAILED: 0 | TIME: 48.30s
==========================================================================
```

---

## 2. Multi-Company Offline Verification Suite (`test_companies.py`)

The suite exercises the dashboard under synthetic yfinance feeds across 16 batch sessions and shared-cash portfolio configurations:

| Scenario / Test Case | Commands / Parameters | Expected Outcome | Observed Result | Status |
|---|---|---|---|---|
| **Single Company Replay** | `--company nvidia --port none --no-plot` | 390 ticks replayed, log written, PNG saved | 390 ticks logged, `.cfg` verified | **PASS** |
| **8-Company Batch Mode** | `--company all --days 2 --port none` | 16 runs (8 stocks × 2 days), summary tables | 1,478 trades, all FPGA checks PASS | **PASS** |
| **Market Integrity Check** | `verify_run.py` verification | Correct ticker re-downloads match; wrong fails | 8 logs PASS, intentional mismatch FAILS | **PASS** |
| **Shared-Cash Allocator (Cap 0%)** | `--company apple,nvidia --together --cap-pct 0` | 780 ticks merged by minute, shared cash | 61 trades, 0 cap refusals, cash PASS | **PASS** |
| **Shared-Cash Allocator (Cap 30%)** | `--company apple,nvidia --together --cap-pct 30` | 780 ticks merged, company caps enforced | 33 trades, 193 cap refusals, cash PASS | **PASS** |
| **Hybrid Allocator (2 Companies)** | `--company apple,nvidia --together --port none` | 780 ticks + 390 ALLOCATE commands | 90 BUY, 9 ROT, exact match with model | **PASS** |
| **Hybrid Allocator (4 Companies)** | `--company 4_stocks --together --port none` | 1,560 ticks + 390 ALLOCATE commands | 169 BUY, 10 ROT, exact match with model | **PASS** |
| **Ablation: No Rotation** | `--together --no-rotate` | Rotation disabled in hardware | 94 BUY, 0 ROT, exact match with model | **PASS** |
| **Legacy Bitstream Rejection** | v10 bitstream image (no allocator) | CFG_MODE rejected with clear error message | Board refused cleanly with diagnostic | **PASS** |

---

## 3. Visual & UI/UX Validation

- **Institutional Dark Theme:** Verified 16:9 1080p layout in both desktop windowed mode and headless snapshot mode (`results/dashboard_snapshot.png`).
- **Interactive Search:** Filtered all 44 registers in Tab 2 without stuttering or latency spikes.
- **Dynamic Chart Rendering:** Dual-axis charts on Tab 1 and Tab 3 smoothly redraw during live tick updates without blocking GUI thread.
- **CSV Data Export:** Order tape export and transaction audit trail export confirmed valid UTF-8 CSVs.

