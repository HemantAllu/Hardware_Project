# Fully-funded trading interlock

This version prevents both forms of borrowing:

* A BUY executes only when `position + volume <= POS_LIMIT` **and** the FPGA cash balance is at least `price * volume`.
* A SELL executes only when the current holding is at least the requested volume. Short selling is not allowed.
* A tick with volume 0 never trades.
* The FPGA, RISC-V firmware, Python reference model, simulator, dashboard and post-run verifier use the same rule.

Cash uses the accelerator's price-times-lot units (`price * volume`). For the real-data dashboard this is converted (exactly) from `--starting-cash` in displayed dollars using the configured price scale and shares per lot. The default is $1,000,000,000 for real AAPL data. Each trade is the whole bar volume, and one lot of 1000 shares costs about $250,000, so $1,000,000 cannot pay for a single typical bar and no trade would ever execute. The default is $1,000,000 for `--source random` and old Price,Volume CSV files.

## FPGA registers

| Address | Name | Description |
|---|---|---|
| `0x30000034` | `CASH_LO` | Starting cash, low 32 bits; applied when `CTRL` is cleared |
| `0x30000038` | `CASH_HI` | Starting cash, high 32 bits; applied when `CTRL` is cleared |
| `0x3000003C` | `HW_CASH_LO` | Current FPGA cash, low 32 bits |

The dashboard sends `CMD_CFG_CASH` followed by RESET before the first tick. `src/mem/imem.mem` is built from the current `hft_firmware.c` (v5). After any firmware change, run `bash extras/tools/make_board_image.sh` and regenerate the bitstream. `run_hft_tests.sh` stage 5 fails if the shipped image does not match the firmware's behaviour.

## Focused check

Run `python extras/tools/test_no_borrow.py` to test that an underfunded BUY and an unheld SELL are both rejected (plus the exact moving-average and zero-volume rules). The RTL itself is tested by `run_hft_tests.sh` stage 2 (decision, position and cash of every tick against the model, with 64-bit starting cash) and stage 3 (full system, including `CMD_CFG_CASH` with a non-zero high word).

## Dashboard portfolio metrics

The dashboard displays the following values using the configured starting cash:

* **Cash balance**: cash left after all executed buys and sells.
* **Net cash flow**: cash balance minus starting cash. A negative value means more has been spent buying than received selling.
* **Holdings value**: current price multiplied by the shares still held.
* **Mark-to-market**: cash balance plus holdings value — the amount the account would be worth if its remaining shares were valued at the latest price.
* **Profit / return**: mark-to-market minus starting cash, and that profit as a percentage of starting cash.
* **Return graph**: a separate graph (window and `--save-png` snapshot) of that return for every tick.
* **Trades / BUYs refused (cash)**: how many trades executed and how many BUY signals the cash interlock refused.
