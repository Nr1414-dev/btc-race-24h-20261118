"""Slow EMA trend bot for the make.fun BTC race (agent-fun/bars-replay/v1).

Strategy, tuned and verified on the published 24h dev window (1,440 1-minute
cbBTC/USDC bars, BTC fell 2.8% over it):

  - Long only, one position, full size. A full-size round trip costs about
    26 bps (4 bps fee + 2 bps slippage + ~10-20 bps pool impact), so the bot
    only trades when a move can plausibly clear that: it waits for slow,
    confirmed trends instead of chasing every 1-minute wiggle. Fast 1-minute
    EMA crossovers whipsaw badly on this data (the kit's EMA 8/21 baseline
    makes 80 trades and loses ~$148 on the dev window); slow EMAs make 3
    round trips in 24h.
  - Entry: EMA(30) of closes crosses above EMA(120) (fast minus slow goes
    from <= 0 to > 0 on the bar's close). Buy 100% of cash.
  - Exit: the whole position, when EMA(30) crosses back below EMA(120), or
    when the close reaches +200 bps over the entry close (take profit).
    No trailing stop: on this data a 50 bps trail exits the one big rally
    early and turns the dev window negative.
  - Cooldown: 60 bars after an exit before a new entry, so a choppy cross
    cannot re-enter immediately.
  - Max slippage 100 bps per order (about 15x the 1-minute return std), so
    an order only ever fails on a genuine gap.

Local backtest on the dev window (exact integer fill math from the kit's
harness: fee 4 bps, slippage 2 bps, constant-product impact vs the bar's
open depth, fills at the next bar's open): net PnL +$5.36, 3 round trips,
max drawdown 1.24%. Buy-and-hold on the same window is -$31.63.

Determinism: pure float64 EMA arithmetic on the bars as they arrive, no
clock, no randomness, no network, no files. The same bars always give the
same orders.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
FAST_SPAN = 30
SLOW_SPAN = 120
TAKE_PROFIT_BPS = 200
COOLDOWN_BARS = 60
MAX_SLIPPAGE_BPS = 100


class Ema:
    """EMA seeded as the mean of its first span of closes, then
    moving 2 / (span + 1) of the way to each new close (same as the kit's
    baselines, so local grades and the server agree)."""

    def __init__(self, span):
        self.span = span
        self.warm = []
        self.value = None

    def push(self, close):
        if self.value is not None:
            self.value += (2.0 / (self.span + 1)) * (close - self.value)
            return
        self.warm.append(close)
        if len(self.warm) == self.span:
            self.value = sum(self.warm) / self.span


class Bot:
    def __init__(self):
        self.fast = Ema(FAST_SPAN)
        self.slow = Ema(SLOW_SPAN)
        self.gap_prev = None  # fast - slow after the previous bar
        self.entry_close = None  # close of the bar the open buy was decided on
        self.pending_buy_close = None  # close recorded while a buy is unfilled
        self.pending_sell = False  # a sell was sent and not yet filled
        self.cool_until = -1  # first seq a new entry may be decided on

    def on_batch(self, state, batch):
        # Fold this batch's fills in first: a filled buy confirms the entry
        # price (the close of the bar it was decided on); a filled sell
        # clears the position bookkeeping.
        for fill in batch.get("fills", []):
            if fill.get("symbol") != SYMBOL:
                continue
            if fill.get("status") != "filled":
                if fill.get("side") == "buy":
                    self.pending_buy_close = None
                elif fill.get("side") == "sell":
                    self.pending_sell = False
                continue
            if fill.get("side") == "buy":
                self.entry_close = self.pending_buy_close
                self.pending_buy_close = None
            elif fill.get("side") == "sell":
                self.entry_close = None
                self.pending_sell = False

        # Update indicators from this batch's bar (a missing bar adds nothing).
        fresh = False
        for bar in batch.get("bars", []):
            if bar.get("symbol") != SYMBOL:
                continue
            close = int(bar["c"])
            self.fast.push(close)
            self.slow.push(close)
            fresh = True
            self._close = close
        if not fresh:
            return []
        if state.warming_up:
            return []

        if self.fast.value is None or self.slow.value is None:
            return []
        gap = self.fast.value - self.slow.value
        gap_prev = self.gap_prev
        self.gap_prev = gap
        if gap_prev is None:
            return []

        close = self._close
        held = state.positions.get(SYMBOL)

        if held is not None and not self.pending_sell:
            # Exit: cross back down, or take profit at +200 bps over entry.
            if (gap < 0 and gap_prev >= 0) or (
                self.entry_close is not None
                and close >= self.entry_close * (1 + TAKE_PROFIT_BPS / 10000)
            ):
                self.cool_until = state.seq + COOLDOWN_BARS
                self.pending_sell = True
                return [{
                    "side": "sell",
                    "symbol": SYMBOL,
                    "qty": held.qty,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }]
            return []

        if held is None and self.pending_buy_close is None:
            # Entry: cross up, outside the cooldown after an exit.
            if state.seq >= self.cool_until and gap > 0 and gap_prev <= 0:
                cash = state.cash
                if cash >= int(state.hello["fees"]["min_notional_quote_units"]):
                    self.pending_buy_close = close
                    return [{
                        "side": "buy",
                        "symbol": SYMBOL,
                        "notional_quote_units": cash,
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }]
        return []


def main():
    bot = Bot()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()
