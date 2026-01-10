# bot/history_manager.py
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Any


@dataclass
class Bar:
    ticker: str
    per: int  # minutes
    datetime: str  # 'YYYY-MM-DD HH:MM:SS' (UTC unless your source is local)
    open: float
    high: float
    low: float
    close: float
    volume: float


def _parse_finam_datetime(date_str: str, time_str: str) -> str:
    """
    DATE: DDMMYY, TIME: HHMMSS -> 'YYYY-MM-DD HH:MM:SS'
    """
    time_str = time_str.zfill(6)

    day = int(date_str[0:2])
    month = int(date_str[2:4])
    year = int(date_str[4:6])
    year += 2000 if year < 70 else 1900

    hour = int(time_str[0:2])
    minute = int(time_str[2:4])
    second = int(time_str[4:6])

    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"


def _dt_from_ms_utc(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _timeframe_to_minutes(timeframe: str | int) -> int:
    """
    Converts timeframe to minutes.
    Supported:
      - int (already minutes)
      - strings like: '1m','3m','5m','15m','30m','1h','2h','4h','6h','12h','1d','3d','1w'
    """
    if isinstance(timeframe, int):
        if timeframe <= 0:
            raise ValueError("timeframe minutes must be > 0")
        return timeframe

    tf = timeframe.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 1440
    if tf.endswith("w"):
        return int(tf[:-1]) * 10080

    # allow pure number strings as minutes
    if tf.isdigit():
        v = int(tf)
        if v <= 0:
            raise ValueError("timeframe minutes must be > 0")
        return v

    raise ValueError(f"Unsupported timeframe format: {timeframe!r}")


class HistoryManager:
    """
    Atsakingas už istorijos užkrovimą ir cache.

    - CSV (Finam) per load_finam_history(path)
    - Birža (OKX/Bybit per IExchange) per load_exchange_history(exchange, symbol, timeframe, ...)
    """

    def __init__(self):
        # cache: key -> list[Bar]
        self._cache: dict[str, list[Bar]] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    # -------------------------
    # CSV / FINAM
    # -------------------------
    def load_finam_history(self, path: str) -> list[Bar]:
        cache_key = f"csv:finam:{Path(path).resolve()}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"History file not found: {file_path}")

        bars: list[Bar] = []
        with file_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dt = _parse_finam_datetime(row["<DATE>"], row["<TIME>"])
                bars.append(
                    Bar(
                        ticker=row["<TICKER>"],
                        per=int(row["<PER>"]),
                        datetime=dt,
                        open=float(row["<OPEN>"]),
                        high=float(row["<HIGH>"]),
                        low=float(row["<LOW>"]),
                        close=float(row["<CLOSE>"]),
                        volume=float(row["<VOL>"]),
                    )
                )

        self._cache[cache_key] = bars
        return bars

    # -------------------------
    # EXCHANGE (OKX / BYBIT)
    # -------------------------
    def load_exchange_history(
        self,
        exchange: Any,
        symbol: str,
        timeframe: str | int,
        *,
        since_ms: int | None = None,
        limit: int | None = None,
        force_reload: bool = False,
    ) -> list[Bar]:
        """
        Loads OHLCV bars from exchange.

        Expected exchange method (IExchange-style):
          - fetch_ohlcv(symbol: str, timeframe: str, since_ms: int|None=None, limit: int|None=None) -> list[list]
            where each row: [timestamp_ms, open, high, low, close, volume]

        Notes:
          - datetime is stored as UTC string.
          - per is timeframe in minutes.
        """
        # best-effort identify exchange for cache
        ex_name = getattr(exchange, "name", None) or exchange.__class__.__name__
        tf_str = str(timeframe)
        cache_key = f"ex:{ex_name}:{symbol}:{tf_str}:{since_ms}:{limit}"

        if (not force_reload) and cache_key in self._cache:
            return self._cache[cache_key]

        if not hasattr(exchange, "fetch_ohlcv"):
            raise AttributeError(
                "Exchange object must provide fetch_ohlcv(symbol, timeframe, since_ms=None, limit=None)"
            )

        # call exchange
        rows = exchange.fetch_ohlcv(symbol, tf_str, since_ms=since_ms, limit=limit)

        per_min = _timeframe_to_minutes(timeframe)
        bars: list[Bar] = []

        for r in rows:
            # tolerate tuple/list/dict-ish
            if isinstance(r, (list, tuple)) and len(r) >= 6:
                ts_ms, o, h, l, c, v = r[0], r[1], r[2], r[3], r[4], r[5]
            elif isinstance(r, dict):
                ts_ms = r.get("timestamp") or r.get("ts") or r.get("time") or r.get("t")
                o = r.get("open") or r.get("o")
                h = r.get("high") or r.get("h")
                l = r.get("low") or r.get("l")
                c = r.get("close") or r.get("c")
                v = r.get("volume") or r.get("v")
            else:
                raise ValueError(f"Unsupported OHLCV row format: {type(r)} -> {r!r}")

            if ts_ms is None:
                raise ValueError(f"OHLCV row missing timestamp: {r!r}")

            bars.append(
                Bar(
                    ticker=symbol,
                    per=per_min,
                    datetime=_dt_from_ms_utc(int(ts_ms)),
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    volume=float(v),
                )
            )

        self._cache[cache_key] = bars
        return bars

    # -------------------------
    # Convenience wrapper
    # -------------------------
    def load_history(
        self,
        *,
        path: str | None = None,
        exchange: Any | None = None,
        symbol: str | None = None,
        timeframe: str | int = "1h",
        since_ms: int | None = None,
        limit: int | None = None,
        force_reload: bool = False,
    ) -> list[Bar]:
        """
        Universal loader:
          - if path is provided -> loads CSV (Finam)
          - else loads from exchange (requires exchange + symbol)
        """
        if path:
            return self.load_finam_history(path)

        if exchange is None or not symbol:
            raise ValueError("Provide either path=... OR (exchange=... and symbol=...)")

        return self.load_exchange_history(
            exchange,
            symbol,
            timeframe,
            since_ms=since_ms,
            limit=limit,
            force_reload=force_reload,
        )
