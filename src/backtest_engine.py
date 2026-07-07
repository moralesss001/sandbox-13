from __future__ import annotations


class BacktestEngine:
    def run(self, *args, **kwargs):
        """Future candle-based backtest entrypoint.

        TODO:
        - fetch or load historical candles;
        - reconstruct production-like signals without order execution;
        - apply adaptive context/risk decisions;
        - report baseline vs shadow results.
        """
        raise NotImplementedError("Backtest Mode is a safe skeleton for future implementation.")
