# bot/binance_downloader.py

import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib import request, parse


FINAM_FIELDS = [
    "<TICKER>",
    "<PER>",
    "<DATE>",
    "<TIME>",
    "<OPEN>",
    "<HIGH>",
    "<LOW>",
    "<CLOSE>",
    "<VOL>",
]


_BINANCE_INTERVAL_MS = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "8h": 8 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


def _per_from_interval(interval: str) -> int:
    """
    Finam <PER> kodas – mums nesvarbus, bet įrašom kažką logiško.
    (strategijoje jo nenaudojam).
    """
    mapping = {
        "1m": 1,
        "3m": 1,
        "5m": 2,
        "15m": 4,
        "30m": 5,
        "1h": 6,
        "2h": 6,
        "4h": 7,
        "6h": 7,
        "8h": 7,
        "12h": 7,
        "1d": 8,
    }
    return mapping.get(interval, 0)


def _date_to_ms(date_str: str) -> int:
    """
    'YYYY-MM-DD' -> epoch ms (UTC)
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _ms_to_date_time_strings(ms: int) -> tuple[str, str]:
    """
    Binance ms -> (DATE, TIME) Finam formatu:
      DATE: DDMMYY
      TIME: HHMMSS
    """
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    date_str = dt.strftime("%d%m%y")
    time_str = dt.strftime("%H%M%S")
    return date_str, time_str


def _binance_klines(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    limit: int = 1000,
) -> list[list]:
    """
    Paimam vieną Binance /api/v3/klines gabalą.
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": limit,
    }
    url = "https://api.binance.com/api/v3/klines?" + parse.urlencode(params)
    with request.urlopen(url, timeout=30) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)


def download_binance_klines(
    symbol: str,
    interval: str,
    start_date: str,
    end_date: str,
    output_path: str,
) -> dict:
    """
    Atsisiunčia Binance žvakes ir išsaugo Finam stiliaus .txt faile.

    :param symbol: pvz. 'BTCUSDT'
    :param interval: pvz. '1h', '30m'
    :param start_date: 'YYYY-MM-DD'
    :param end_date: 'YYYY-MM-DD' (įskaitant šią dieną)
    :param output_path: kur išsaugoti .txt
    :return: info dict su eilučių skaičiumi ir pan.
    """
    if interval not in _BINANCE_INTERVAL_MS:
        raise ValueError(f"Nepalaikomas intervalas: {interval}")

    start_ms = _date_to_ms(start_date)
    # end_date įskaitom iki tos dienos pabaigos
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_ms = int((end_dt + timedelta(days=1)).timestamp() * 1000) - 1

    step_ms = _BINANCE_INTERVAL_MS[interval] * 1000  # 1000 žvakių vienu request
    per_code = _per_from_interval(interval)

    all_rows: list[dict] = []
    current = start_ms

    while current < end_ms:
        chunk_end = min(current + step_ms, end_ms)
        klines = _binance_klines(symbol, interval, current, chunk_end)
        if not klines:
            # jei nieko negrąžina – judam toliau, kad neįstrigtume
            current = chunk_end + 1
            continue

        for k in klines:
            open_time = int(k[0])
            o = float(k[1])
            h = float(k[2])
            l = float(k[3])
            c = float(k[4])
            v = float(k[5])

            date_str, time_str = _ms_to_date_time_strings(open_time)

            all_rows.append(
                {
                    "<TICKER>": symbol,
                    "<PER>": str(per_code),
                    "<DATE>": date_str,
                    "<TIME>": time_str,
                    "<OPEN>": f"{o:.6f}",
                    "<HIGH>": f"{h:.6f}",
                    "<LOW>": f"{l:.6f}",
                    "<CLOSE>": f"{c:.6f}",
                    "<VOL>": f"{v:.6f}",
                }
            )

        # pereinam prie kitos žvakių porcijos
        current = int(klines[-1][0]) + _BINANCE_INTERVAL_MS[interval]

    if not all_rows:
        raise RuntimeError("Binance negrąžino duomenų.")

    # surūšiuojam pagal datą ir laiką (šiaip turėtų ir taip būti, bet dėl saugumo)
    all_rows.sort(key=lambda r: (r["<DATE>"], r["<TIME>"]))

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FINAM_FIELDS)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    return {
        "symbol": symbol,
        "interval": interval,
        "rows": len(all_rows),
        "output": str(out_path),
        "start_date": start_date,
        "end_date": end_date,
    }
