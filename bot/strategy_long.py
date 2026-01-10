# bot/strategy_long.py
from __future__ import annotations

from dataclasses import dataclass
from math import isnan
from typing import Optional, Sequence


@dataclass
class IndicatorsSnap:
    macd: Optional[float]
    macd_signal: Optional[float]
    bb_mid_seq: Sequence[Optional[float]]  # last (lookback+1) values, oldest->newest
    bb_upper_seq: Sequence[Optional[float]]  # last (lookback+1) values, oldest->newest
    atr: Optional[float]


class Strategy:
    """
    LONG strategija (CROSS + LATCH) – be pandas.

    1) MACD kerta 0 iš apačios -> latch N barų (setup)
    2) BB upper trend up + kaina viršutinėje BB zonoje (trigger)
    FULL_LONG kai: macd_active && bb_ok
    """

    def __init__(
        self,
        bb_period: int = 12,
        bb_lookback: int = 4,
        bb_slope_pct: float = 0.004,
        bb_min_width_pct: float = 0.01,
        bb_channel_pos: float = 0.6,
        min_signal_gap: int = 8,
        macd_latch_bars: int = 10,
    ):
        # BB params
        self.bb_period = int(bb_period)
        self.bb_lookback = int(bb_lookback)
        self.bb_slope_pct = float(bb_slope_pct)
        self.bb_min_width_pct = float(bb_min_width_pct)
        self.bb_channel_pos = float(bb_channel_pos)

        # MACD latch
        self.macd_latch_bars = int(macd_latch_bars)
        self._macd_latch = 0
        self._prev_macd: Optional[float] = None

        # gap
        self.min_signal_gap = int(min_signal_gap)
        self._last_signal_i: Optional[int] = None

        # ATR (tik exportui RiskManageriui)
        self.curr_atr: float = 0.0

    def _is_valid_num(self, x: Optional[float]) -> bool:
        return x is not None and not isnan(float(x))

    def _signal_gap_ok(self, i: int) -> bool:
        if self._last_signal_i is None:
            return True
        return (i - self._last_signal_i) >= self.min_signal_gap

    def _update_macd_latch(self, macd: Optional[float], sig: Optional[float]) -> bool:
        """
        Veikia tik su paskutine reikšme + internal prev_macd.
        - jei macd < 0 -> latch=0
        - new trigger: prev_macd <= 0 AND macd > 0 AND macd > sig -> latch=N
        - kitaip latch--
        """
        if not self._is_valid_num(macd) or not self._is_valid_num(sig):
            self._macd_latch = max(self._macd_latch - 1, 0)
            # prev_macd atnaujinam tik jei macd valid
            if self._is_valid_num(macd):
                self._prev_macd = float(macd)
            return self._macd_latch > 0

        macd_f = float(macd)
        sig_f = float(sig)

        # jei MACD vėl nukrito žemiau 0 – setup mirė
        if macd_f < 0:
            self._macd_latch = 0
            self._prev_macd = macd_f
            return False

        prev = self._prev_macd
        new_trigger = (prev is not None) and (prev <= 0.0) and (macd_f > 0.0) and (macd_f > sig_f)

        if new_trigger:
            self._macd_latch = self.macd_latch_bars
        else:
            if self._macd_latch > 0:
                self._macd_latch -= 1

        self._prev_macd = macd_f
        return self._macd_latch > 0

    def _bb_trend_up(self, bb_mid_seq: Sequence[Optional[float]], bb_upper_seq: Sequence[Optional[float]], close: float, open_: float) -> bool:
        """
        Reikia paskutinių (lookback+1) bb_upper/bb_mid reikšmių (oldest->newest).
        Sąlygos identiškos senam LONG.
        """
        lb = self.bb_lookback
        if len(bb_upper_seq) < lb + 1 or len(bb_mid_seq) < lb + 1:
            return False

        # validate last values
        upper_vals = []
        mid_vals = []
        for v in bb_upper_seq:
            if not self._is_valid_num(v):
                return False
            upper_vals.append(float(v))
        for v in bb_mid_seq:
            if not self._is_valid_num(v):
                return False
            mid_vals.append(float(v))

        upper_now = upper_vals[-1]
        mid_now = mid_vals[-1]

        # 1) upper kyla kiekviename iš paskutinių lookback barų
        # turim lb+1 taškų: [t-lb, ..., t]
        for k in range(lb):
            if not (upper_vals[-1 - k] > upper_vals[-2 - k]):
                return False

        # 2) bendras nuolydis procentais
        base = upper_vals[0]  # t-lb
        if base <= 0:
            return False
        slope_pct = (upper_now - base) / base
        if slope_pct < self.bb_slope_pct:
            return False

        # 3) plotis (upper-mid)
        if upper_now <= mid_now or mid_now <= 0:
            return False
        width_pct = (upper_now - mid_now) / mid_now
        if width_pct < self.bb_min_width_pct:
            return False

        # 4) kaina viršutinėje kanalo dalyje: mid < price <= upper
        price = float(close)
        if not (price > mid_now and price <= upper_now):
            return False
        channel_range = upper_now - mid_now
        if channel_range <= 0:
            return False
        pos = (price - mid_now) / channel_range
        if pos < self.bb_channel_pos:
            return False

        # 5) bulių žvakė
        if not (float(close) > float(open_)):
            return False

        return True

    def on_bar(self, bar, indicators: IndicatorsSnap, bar_index: int) -> str | None:
        # ATR export
        if self._is_valid_num(indicators.atr):
            self.curr_atr = float(indicators.atr)

        # gap
        if not self._signal_gap_ok(bar_index):
            # vis tiek atnaujinam MACD latch state
            self._update_macd_latch(indicators.macd, indicators.macd_signal)
            return None

        # MACD latch
        macd_active = self._update_macd_latch(indicators.macd, indicators.macd_signal)

        # BB trigger
        bb_ok = self._bb_trend_up(
            indicators.bb_mid_seq,
            indicators.bb_upper_seq,
            close=float(bar.close),
            open_=float(bar.open),
        )

        if macd_active and bb_ok:
            self._last_signal_i = int(bar_index)
            return "FULL_LONG"

        return None
