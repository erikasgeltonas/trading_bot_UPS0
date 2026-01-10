# bot/strategy_short.py
from __future__ import annotations

from dataclasses import dataclass
from math import isnan
from typing import Optional, Sequence


@dataclass
class IndicatorsSnap:
    macd: Optional[float]
    macd_signal: Optional[float]
    bb_mid_seq: Sequence[Optional[float]]   # last (lookback+1) values, oldest->newest
    bb_lower_seq: Sequence[Optional[float]] # last (lookback+1) values, oldest->newest
    atr: Optional[float]


class Strategy:
    """
    SHORT strategija (CROSS + LATCH) – veidrodis LONG'ui, be pandas.

    1) MACD kerta 0 iš viršaus -> latch N barų (setup)
    2) BB lower trend down + kaina apatinėje BB zonoje (trigger)
    FULL_SHORT kai: macd_active && bb_ok
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
        self.bb_period = int(bb_period)
        self.bb_lookback = int(bb_lookback)
        self.bb_slope_pct = float(bb_slope_pct)
        self.bb_min_width_pct = float(bb_min_width_pct)
        self.bb_channel_pos = float(bb_channel_pos)

        self.macd_latch_bars = int(macd_latch_bars)
        self._macd_latch = 0
        self._prev_macd: Optional[float] = None

        self.min_signal_gap = int(min_signal_gap)
        self._last_signal_i: Optional[int] = None

        self.curr_atr: float = 0.0

    def _is_valid_num(self, x: Optional[float]) -> bool:
        return x is not None and not isnan(float(x))

    def _signal_gap_ok(self, i: int) -> bool:
        if self._last_signal_i is None:
            return True
        return (i - self._last_signal_i) >= self.min_signal_gap

    def _update_macd_latch(self, macd: Optional[float], sig: Optional[float]) -> bool:
        """
        Veidrodis LONG:
        - jei macd > 0 -> latch=0
        - new trigger: prev_macd >= 0 AND macd < 0 AND macd < sig -> latch=N
        - kitaip latch--
        """
        if not self._is_valid_num(macd) or not self._is_valid_num(sig):
            self._macd_latch = max(self._macd_latch - 1, 0)
            if self._is_valid_num(macd):
                self._prev_macd = float(macd)
            return self._macd_latch > 0

        macd_f = float(macd)
        sig_f = float(sig)

        if macd_f > 0:
            self._macd_latch = 0
            self._prev_macd = macd_f
            return False

        prev = self._prev_macd
        new_trigger = (prev is not None) and (prev >= 0.0) and (macd_f < 0.0) and (macd_f < sig_f)

        if new_trigger:
            self._macd_latch = self.macd_latch_bars
        else:
            if self._macd_latch > 0:
                self._macd_latch -= 1

        self._prev_macd = macd_f
        return self._macd_latch > 0

    def _bb_trend_down(self, bb_mid_seq: Sequence[Optional[float]], bb_lower_seq: Sequence[Optional[float]], close: float, open_: float) -> bool:
        lb = self.bb_lookback
        if len(bb_lower_seq) < lb + 1 or len(bb_mid_seq) < lb + 1:
            return False

        lower_vals = []
        mid_vals = []
        for v in bb_lower_seq:
            if not self._is_valid_num(v):
                return False
            lower_vals.append(float(v))
        for v in bb_mid_seq:
            if not self._is_valid_num(v):
                return False
            mid_vals.append(float(v))

        lower_now = lower_vals[-1]
        mid_now = mid_vals[-1]

        # 1) lower leidžiasi kiekviename iš paskutinių lookback barų
        for k in range(lb):
            if not (lower_vals[-1 - k] < lower_vals[-2 - k]):
                return False

        # 2) bendras nuolydis (kiek % nusileido)
        base = lower_vals[0]  # t-lb
        if base <= 0:
            return False
        slope_pct = (base - lower_now) / base
        if slope_pct < self.bb_slope_pct:
            return False

        # 3) plotis (mid-lower)
        if mid_now <= lower_now or mid_now <= 0:
            return False
        width_pct = (mid_now - lower_now) / mid_now
        if width_pct < self.bb_min_width_pct:
            return False

        # 4) kaina apatinėje kanalo dalyje: lower <= price < mid
        price = float(close)
        if not (price < mid_now and price >= lower_now):
            return False
        channel_range = mid_now - lower_now
        if channel_range <= 0:
            return False
        pos = (mid_now - price) / channel_range  # 0 ties mid, 1 ties lower
        if pos < self.bb_channel_pos:
            return False

        # 5) meškų žvakė
        if not (float(close) < float(open_)):
            return False

        return True

    def on_bar(self, bar, indicators: IndicatorsSnap, bar_index: int) -> str | None:
        if self._is_valid_num(indicators.atr):
            self.curr_atr = float(indicators.atr)

        if not self._signal_gap_ok(bar_index):
            self._update_macd_latch(indicators.macd, indicators.macd_signal)
            return None

        macd_active = self._update_macd_latch(indicators.macd, indicators.macd_signal)

        bb_ok = self._bb_trend_down(
            indicators.bb_mid_seq,
            indicators.bb_lower_seq,
            close=float(bar.close),
            open_=float(bar.open),
        )

        if macd_active and bb_ok:
            self._last_signal_i = int(bar_index)
            return "FULL_SHORT"

        return None
