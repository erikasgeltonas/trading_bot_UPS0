# bollinger.py
from typing import Iterable, List, Optional, Tuple
import math


def calculate_bb(
    closes: Iterable[float],
    period: int = 20,
    std_mult: float = 2.0,
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """
    Grąžina (middle, upper, lower) bb sąrašus.
    Pirmos (period - 1) reikšmės – None.
    """
    closes = list(closes)
    n = len(closes)

    middle: List[Optional[float]] = [None] * n
    upper: List[Optional[float]] = [None] * n
    lower: List[Optional[float]] = [None] * n

    if n < period:
        return middle, upper, lower

    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(variance)

        middle[i] = mean
        upper[i] = mean + std_mult * std
        lower[i] = mean - std_mult * std

    return middle, upper, lower
