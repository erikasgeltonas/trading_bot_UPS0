# bot/indicator_engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .indicators.macd import calculate_macd
from .indicators.bb import calculate_bb
from .indicators.atr import calculate_atr


class SeriesList(list):
    """
    Minimalus "Series" pakaitalas:
    - elgiasi kaip list
    - turi .tolist() suderinamumui
    - turi .iloc suderinamumui (grąžina save)
    - turi .values suderinamumui (grąžina list)
    """
    def tolist(self) -> List[Any]:
        return list(self)

    @property
    def iloc(self) -> "SeriesList":
        return self

    @property
    def values(self) -> List[Any]:
        return list(self)


class Frame:
    """
    Minimalus "DataFrame" pakaitalas IndicatorEngine reikmėms:
    - df["close"] -> SeriesList
    - df["atr"] = [...]
    - df.empty
    """
    def __init__(self) -> None:
        self._cols: Dict[str, SeriesList] = {}

    @property
    def empty(self) -> bool:
        if not self._cols:
            return True
        # jei bent viena kolona turi duomenų -> ne empty
        return all(len(v) == 0 for v in self._cols.values())

    def __contains__(self, key: str) -> bool:
        return key in self._cols

    def __getitem__(self, key: str) -> SeriesList:
        return self._cols[key]

    def __setitem__(self, key: str, values: Iterable[Any]) -> None:
        self._cols[key] = SeriesList(values)

    def get(self, key: str, default: Any = None) -> Any:
        return self._cols.get(key, default)

    def columns(self) -> List[str]:
        return list(self._cols.keys())

    def to_dict(self) -> Dict[str, List[Any]]:
        return {k: list(v) for k, v in self._cols.items()}


class IndicatorEngine:
    """
    Indikatorių orchestratorius (minimalus, švarus, BE pandas):

    - MACD (mūsų)
    - Bollinger Bands (mūsų)
    - ATR (mūsų)

    Nėra jokių fillna, jokių „apsaugų“, jokių papildomų logikų.
    """
    def __init__(
        self,
        macd_params: dict | None = None,
        bb_params: dict | None = None,
        atr_period: int = 14,
    ):
        self.macd_params = macd_params or {}
        self.bb_params = bb_params or {}
        self.atr_period = atr_period

        self.df: Optional[Frame] = None

    # ----------------------------------------------------

    def load_history(self, bars: list) -> None:
        fr = Frame()

        # surenkam į list’us
        datetimes: List[Any] = []
        opens: List[float] = []
        highs: List[float] = []
        lows: List[float] = []
        closes: List[float] = []
        volumes: List[float] = []

        for b in bars:
            datetimes.append(getattr(b, "datetime", None))
            opens.append(float(b.open))
            highs.append(float(b.high))
            lows.append(float(b.low))
            closes.append(float(b.close))
            volumes.append(float(b.volume))

        fr["datetime"] = datetimes
        fr["open"] = opens
        fr["high"] = highs
        fr["low"] = lows
        fr["close"] = closes
        fr["volume"] = volumes

        self.df = fr

    # ----------------------------------------------------

    def compute_all(self) -> None:
        if self.df is None or self.df.empty:
            return

        self._compute_macd()
        self._compute_bb()
        self._compute_atr()

    # ----------------------------------------------------
    # MACD
    # ----------------------------------------------------

    def _compute_macd(self) -> None:
        assert self.df is not None

        closes = self.df["close"].tolist()

        p = self.macd_params
        fast = int(p.get("fast", 12))
        slow = int(p.get("slow", 26))
        signal = int(p.get("signal", 9))

        macd, macd_signal, macd_hist = calculate_macd(
            closes=closes,
            fast=fast,
            slow=slow,
            signal=signal,
        )

        self.df["macd"] = macd
        self.df["macd_signal"] = macd_signal
        self.df["macd_hist"] = macd_hist

    # ----------------------------------------------------
    # BB
    # ----------------------------------------------------

    def _compute_bb(self) -> None:
        assert self.df is not None

        closes = self.df["close"].tolist()

        p = self.bb_params
        period = int(p.get("period", 20))
        std_mult = float(p.get("std_mult", 2.0))

        bb_mid, bb_upper, bb_lower = calculate_bb(
            closes=closes,
            period=period,
            std_mult=std_mult,
        )

        self.df["bb_mid"] = bb_mid
        self.df["bb_upper"] = bb_upper
        self.df["bb_lower"] = bb_lower

    # ----------------------------------------------------
    # ATR
    # ----------------------------------------------------

    def _compute_atr(self) -> None:
        assert self.df is not None

        highs = self.df["high"].tolist()
        lows = self.df["low"].tolist()
        closes = self.df["close"].tolist()

        atr = calculate_atr(
            highs=highs,
            lows=lows,
            closes=closes,
            period=int(self.atr_period),
        )

        self.df["atr"] = atr

    # ----------------------------------------------------

    def get_df(self) -> Frame:
        """
        Palieku pavadinimą get_df() suderinamumui su esamu kodu.
        Grąžina mūsų Frame (ne pandas).
        """
        if self.df is None:
            raise RuntimeError("Indicators not computed / history not loaded")
        return self.df
