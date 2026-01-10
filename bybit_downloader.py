# bot/bybit_downloader.py
"""
Bybit istorinių žvakių (kline) downloaderis.

Naudojame /v5/market/kline endpointą:
- be API key (tik vieši duomenys)
- spot / linear / inverse
- intervalai: 1m, 5m, 15m, 30m, 1h, 4h, 1d ir pan.

Rezultatas:
- download_bybit_klines -> pandas DataFrame
- download_bybit_to_finam_txt -> iškart Finam-stiliaus TXT failas:
  <TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple, Dict

import requests
import pandas as pd

BASE_URL = "https://api.bybit.com"

# Intervalų žemėlapis:
# raktas – ką matysi GUI ("1m", "5m", "1h" ...),
# reikšmė – (Bybit interval param, Finam <PER> kodas)
# JEI tavo Finam kodai kitokie – pasikoreguok čia.
INTERVAL_MAP: Dict[str, Tuple[str, int]] = {
    "1m": ("1", 1),
    "5m": ("5", 2),
    "15m": ("15", 3),
    "30m": ("30", 4),
    "1h": ("60", 6),
    "4h": ("240", 7),
    "1d": ("D", 8),
}


def _to_ms(dt: datetime) -> int:
    """Datetime -> timestamp ms (UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp() * 1000)


def _interval_to_ms(interval: str) -> int:
    """
    Paverčia Bybit interval parametrą į milisekundes.
    Palaikomi:
      - skaitiniai (minutės): "1", "5", "60", "240" ir t.t.
      - dieninis: "D"
    """
    if interval.isdigit():
        minutes = int(interval)
        return minutes * 60 * 1000
    if interval == "D":
        return 24 * 60 * 60 * 1000

    raise ValueError(
        f"Nežinomas intervalas '{interval}' – palaikomi tik skaitiniai (minutės) arba 'D' (diena)."
    )


def download_bybit_klines(
    symbol: str = "BTCUSDT",
    category: str = "spot",          # "spot", "linear", "inverse"
    interval: str = "60",            # Bybit interval param: "1","5","60","240","D",...
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    days_back: int = 365,            # naudojama tik jei start/end None
    limit: int = 1000,               # max vienam request
    pause_sec: float = 0.2,          # apsauga nuo rate limit
) -> pd.DataFrame:
    """
    Parsisiunčia Bybit klines ir grąžina DataFrame.

    Jei nenurodai start/end:
        - end = dabar (suapvalinta į žemyn iki pilnos valandos)
        - start = end - days_back

    Duomenys grąžinami DIDĖJANČIA tvarka pagal laiką.
    """

    if end is None:
        # apvalinam iki pilnos valandos, kad gražiau atrodytų
        now = datetime.now(timezone.utc)
        end = now.replace(minute=0, second=0, microsecond=0)

    if start is None:
        start = end - timedelta(days=days_back)

    start_ms = _to_ms(start)
    end_ms = _to_ms(end)

    if end_ms <= start_ms:
        raise ValueError("end turi būti vėlesnis už start")

    interval_ms = _interval_to_ms(interval)

    all_rows: List[list] = []

    while True:
        if end_ms < start_ms:
            break

        params = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "start": str(start_ms),
            "end": str(end_ms),
            "limit": str(limit),
        }

        resp = requests.get(f"{BASE_URL}/v5/market/kline", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("retCode") != 0:
            raise RuntimeError(
                f"Bybit API error: {data.get('retCode')} {data.get('retMsg')}"
            )

        candles = data["result"]["list"]
        # jei daugiau nebėra duomenų – baigiam
        if not candles:
            break

        # Bybit grąžina atbuline tvarka (naujausia pirma)
        all_rows.extend(candles)

        # paskutinės (seniausios šiame batch'e) žvakės startTime
        last_start_ms = int(candles[-1][0])

        # jei jau pasiekėm pradžią – stop
        if last_start_ms <= start_ms:
            break

        # kitam ciklui stumiam end į praeitį
        end_ms = last_start_ms - interval_ms

        time.sleep(pause_sec)

    if not all_rows:
        raise RuntimeError("Negauta jokių žvakių – patikrink simbolį ir datų intervalą.")

    # Struktūra pagal Bybit docs:
    # [0]=startTime, [1]=open, [2]=high, [3]=low, [4]=close, [5]=volume, [6]=turnover
    cols = ["startTime", "open", "high", "low", "close", "volume", "turnover"]
    df = pd.DataFrame(all_rows, columns=cols)

    # konvertuojam laiką ir surūšiuojam didėjančiai
    df["startTime"] = pd.to_datetime(df["startTime"], unit="ms", utc=True)
    df = df.sort_values("startTime").reset_index(drop=True)

    # pervadinam į patogesnį pavadinimą strategijai
    df = df.rename(columns={"startTime": "datetime"})

    # numeriniai stulpeliai -> float
    for col in ["open", "high", "low", "close", "volume", "turnover"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def export_df_to_finam(df: pd.DataFrame, symbol: str, per_code: int, output_path: str) -> int:
    """
    Konvertuoja DataFrame su 'datetime','open','high','low','close','volume'
    į Finam-stiliaus TXT ir išsaugo.

    Grąžina eilučių skaičių.
    """
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])

    finam_df = pd.DataFrame(
        {
            "<TICKER>": symbol,
            "<PER>": per_code,
            "<DATE>": df["datetime"].dt.strftime("%d%m%y"),
            "<TIME>": df["datetime"].dt.strftime("%H%M%S"),
            "<OPEN>": df["open"],
            "<HIGH>": df["high"],
            "<LOW>": df["low"],
            "<CLOSE>": df["close"],
            "<VOL>": df["volume"],
        }
    )

    finam_df.to_csv(output_path, index=False)
    return len(finam_df)


def download_bybit_to_finam_txt(
    symbol: str,
    interval_ui: str,
    start_date: str,
    end_date: str,
    output_path: str,
    category: str = "spot",
    limit: int = 1000,
    pause_sec: float = 0.2,
) -> dict:
    """
    Patogus wrapper'is GUI:

    - interval_ui: '1m', '5m', '15m', '30m', '1h', '4h', '1d'
    - start_date / end_date: 'YYYY-MM-DD'
    - output_path: kur išsaugoti Finam TXT

    Grąžina info dict:
      {symbol, interval, rows, output, start, end}
    """
    interval_ui = interval_ui.strip()
    if interval_ui not in INTERVAL_MAP:
        raise ValueError(
            f"Nežinomas intervalas '{interval_ui}'. "
            f"Palaikomi: {', '.join(sorted(INTERVAL_MAP.keys()))}"
        )

    bybit_interval, per_code = INTERVAL_MAP[interval_ui]

    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    df = download_bybit_klines(
        symbol=symbol,
        category=category,
        interval=bybit_interval,
        start=start_dt,
        end=end_dt,
        limit=limit,
        pause_sec=pause_sec,
    )

    rows = export_df_to_finam(df, symbol, per_code, output_path)

    return {
        "symbol": symbol,
        "interval": interval_ui,
        "rows": rows,
        "output": output_path,
        "start": start_dt,
        "end": end_dt,
    }


if __name__ == "__main__":
    # Paprastas pavyzdys, jei norėsi testuoti iš konsolės
    DAYS_BACK = 365
    out_path = "bot/data/BTCUSDT_1h_bybit_finam.txt"

    print("Downloading BTCUSDT 1h spot data from Bybit...")

    info = download_bybit_to_finam_txt(
        symbol="BTCUSDT",
        interval_ui="1h",
        start_date=(datetime.now().date() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d"),
        end_date=datetime.now().date().strftime("%Y-%m-%d"),
        output_path=out_path,
    )

    print(f"Rows: {info['rows']}")
    print(f"Saved: {info['output']}")
    print("Done.")
