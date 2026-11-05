# UART -> MMIO -> parser -> accelerator verification

Scenarios in `tb_chain.v` / `check_chain.py` (all compared with the Python model): clean packets; framing error in each byte position 0..10 followed at once by a valid packet; stop bit held low into the next start bit (break-like); truncated packet then idle gap; command packets; DUT reset mid-packet; slow CPU (flow control); register reads of FRAME_ERR / PKT_ABORT / PKT_TIMEOUT / OVERRUN.

Results: PASS at N=1,2,4,8 (Verilator). Original parser FAILS the same stimulus.

Limits: BIT=10 is not valid for glitch tests (the glitch falls outside the sampling point). A framing error overlapping an allocation could not be produced at realistic baud rates and is not claimed as covered.
