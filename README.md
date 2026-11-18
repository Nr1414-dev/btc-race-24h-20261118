# BTC Race Bot — slow EMA trend follower (cbBTC/USDC, 1-minute bars)

Entry for make.fun competition `btc-race-24h-20261118-1444`:
"Race a BTC trading bot live for 24 hours".

## Strategy

Long only, one position, full size. A full-size round trip costs ~26 bps
(4 bps fee + 2 bps slippage + ~10–20 bps pool impact), so the bot only
trades slow, confirmed trends instead of chasing 1-minute noise.

- **Entry:** EMA(30) of closes crosses above EMA(120). Buy 100% of cash.
- **Exit:** whole position when EMA(30) crosses back below EMA(120), or
  when the close reaches +200 bps over the entry close (take profit).
  No trailing stop — on the dev window a 50 bps trail exits the one big
  rally early and turns the result negative.
- **Cooldown:** 60 bars after an exit before a new entry.
- **Max slippage:** 100 bps per order.

## Files

- `main.py` — the bot (Python 3.13, standard library only). Speaks
  `agent-fun/bars-replay/v1` over stdin/stdout.
- `vendor/makefun_bars.py` — byte-identical copy of the kit's Python SDK
  shim (kit `sdk/makefun_bars.py`).

## Local backtest (dev window, exact integer fill math from the kit)

Net PnL **+$5.36**, 3 round trips, max drawdown 1.24%.
Buy-and-hold on the same window: −$31.63. The kit's EMA 8/21 baseline:
−$148.17 (80 trades of whipsaw).

## Run

```
python3 -P -s main.py
```

Deterministic: pure float64 EMA arithmetic on the bars as they arrive —
no clock, no randomness, no network, no files.
