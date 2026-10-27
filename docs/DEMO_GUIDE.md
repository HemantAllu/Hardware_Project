# Demo guide

1. Simulation: `bash extras/tools/run_v12_full_regression.sh --fast` (about 10 min) or without `--fast` for everything.
2. Offline replay: `python3 extras/tools/make_benchmarks.py` regenerates `results/`.
3. Board: build in Vivado (see VIVADO_TIMING_REPORT.md), program the Nexys A7, stream packets at 115200 8N1. The dashboard GUI (`extras/hft_dashboard.py`) was not tested headless.
