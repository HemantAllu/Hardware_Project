# Allocator

* Compared with `PortfolioModel` in the original suite (2/4/8 companies) and in the 8-company SoC test.
* Measured hardware allocation latency (SoC, N=8): min 13, mean 31.9, max 64 cycles over 96 allocations. N=4: 9 / 24.5 / 40. N=2: 7 / 13.4 / 22.
* These are observed values, not a proof. The earlier v12 notes state a bound of 8 + 12n; this audit re-checked it on the allocations above but did not formally prove it.
