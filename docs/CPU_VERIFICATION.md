# CPU / M extension

* Reference: project-written `tools/rvsim.py` (not an independent golden core) plus an independent host-C M-extension vector generator (163,872 vectors incl. divide by zero and INT_MIN/-1): 0 errors.
* Directed hazards, SoC demo, C programs, 200 random programs per run (2000 in one extra run): all PASS.
* Not done: a comparison against Spike or another third-party RISC-V simulator.
