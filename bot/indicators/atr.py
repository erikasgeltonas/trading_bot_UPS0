# atr.py
from typing import Iterable, List, Optional


def calculate_atr(
    highs: Iterable[float],
    lows: Iterable[float],
    closes: Iterable[float],
    period: int = 14,
) -> List[Optional[float]]:
    """
    Skaičiuoja ATR pagal Wilder metodiką.
    Grąžina sąrašą tokio pat ilgio kaip įvestys.
    Pirmos (period - 1) reikšmės bus None.
    """
    highs = list(highs)
    lows = list(lows)
    closes = list(closes)

    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows ir closes turi būti vienodo ilgio")

    trs: List[float] = []
    prev_close = closes[0]

    for i in range(len(closes)):
        high = highs[i]
        low = lows[i]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        trs.append(tr)
        prev_close = closes[i]

    if len(trs) < period:
        return [None] * len(trs)

    atr_values: List[Optional[float]] = []

    # Pirmas ATR – paprastas vidurkis
    first_atr = sum(trs[:period]) / period
    atr_values.extend([None] * (period - 1))
    atr_values.append(first_atr)

    # Tolimesni – Wilder EMA
    for i in range(period, len(trs)):
        prev_atr = atr_values[-1]
        current_tr = trs[i]
        atr = ((prev_atr * (period - 1)) + current_tr) / period
        atr_values.append(atr)

    return atr_values
