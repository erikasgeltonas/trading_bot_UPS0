# macd.py
from typing import Iterable, List, Optional, Tuple


def _ema(values: List[float], period: int) -> List[Optional[float]]:
    """
    Paprastas EMA skaičiavimas sąrašui.
    Pirmos (period - 1) reikšmės bus None.
    """
    if len(values) < period:
        return [None] * len(values)

    ema_values: List[Optional[float]] = []
    k = 2 / (period + 1)

    # pirmas EMA – SMA
    sma = sum(values[:period]) / period
    ema_values.extend([None] * (period - 1))
    ema_values.append(sma)

    for price in values[period:]:
        prev_ema = ema_values[-1]
        ema_values.append(price * k + prev_ema * (1 - k))

    return ema_values


def calculate_macd(
    closes: Iterable[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """
    Grąžina (macd_line, signal_line, histogram) sąrašus.
    """
    closes = list(closes)
    if len(closes) < slow:
        n = len(closes)
        return [None] * n, [None] * n, [None] * n

    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    macd_line: List[Optional[float]] = []
    for ef, es in zip(ema_fast, ema_slow):
        if ef is None or es is None:
            macd_line.append(None)
        else:
            macd_line.append(ef - es)

    # signal EMA nuo MACD
    # užpildom None ten, kur MACD dar nėra pilnas
    macd_numeric = [m for m in macd_line if m is not None]
    macd_signal_raw = _ema(macd_numeric, signal)

    signal_line: List[Optional[float]] = []
    histogram: List[Optional[float]] = []

    # sulyginam ilgius su originaliu sąrašu
    idx_signal = 0
    for m in macd_line:
        if m is None:
            signal_line.append(None)
            histogram.append(None)
        else:
            s = macd_signal_raw[idx_signal]
            signal_line.append(s)
            histogram.append(m - s if s is not None else None)
            idx_signal += 1

    return macd_line, signal_line, histogram
