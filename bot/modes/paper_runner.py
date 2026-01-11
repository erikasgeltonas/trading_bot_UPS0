from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

import requests

from bot.history_manager import Bar
from bot.modes.backtest_runner import BacktestRunner

logger = logging.getLogger("bot.testnet")


class TestnetRunner:
    """
    TESTNET / PAPER režimas su REALIOM OKX žvakėm.

    - parsisiunčia OKX public candles
    - konvertuoja į Bar (pagal NAUJĄ signatūrą)
    - paleidžia BacktestRunner ant šių barų
    """

    def __init__(self, bot, inst_id: Optional[str] = None, bar: Optional[str] = None, limit: int = 300):
        self.bot = bot
        self.inst_id = (inst_id or getattr(bot, "paper_inst_id", None) or "BTC-USDT").strip()
        self.bar = (bar or getattr(bot, "paper_bar", None) or "1m").strip()
        self.limit = int(limit) if int(limit) > 10 else 300
        self.okx_base_url = getattr(bot, "okx_base_url", None) or "https://www.okx.com"

    # -------------------------------------------------

    def run(self) -> dict:
        if self.bot is None:
            return {"ok": False, "mode": "TESTNET", "message": "bot is None"}

        try:
            bars = self._download_okx_candles()

            if not bars:
                return {
                    "ok": False,
                    "mode": "TESTNET",
                    "exchange": "OKX",
                    "inst_id": self.inst_id,
                    "bar": self.bar,
                    "message": "OKX candles parsed = 0",
                }

            logger.info("OKX candles parsed = %s", len(bars))

            result = self._run_backtest_on_bars(bars)

            return {
                "ok": True,
                "mode": "TESTNET",
                "exchange": "OKX",
                "inst_id": self.inst_id,
                "bar": self.bar,
                "message": f"OKX snapshot OK. Candles={len(bars)}",
                "result": result,
            }

        except Exception as e:
            logger.exception("TESTNET run failed")
            return {
                "ok": False,
                "mode": "TESTNET",
                "exchange": "OKX",
                "inst_id": self.inst_id,
                "bar": self.bar,
                "message": f"TESTNET failed: {e}",
            }

    # -------------------------------------------------
    # OKX candles
    # -------------------------------------------------

    def _download_okx_candles(self) -> List[Bar]:
        """
        GET /api/v5/market/candles
        row: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        """
        url = self.okx_base_url.rstrip("/") + "/api/v5/market/candles"
        params = {
            "instId": self.inst_id,
            "bar": self.bar,
            "limit": str(self.limit),
        }

        r = requests.get(url, params=params, timeout=10)
        j = r.json()

        if str(j.get("code")) != "0":
            raise RuntimeError(f"OKX error: {j}")

        data = list(reversed(j.get("data", [])))  # chronological

        per_minutes = self._bar_to_minutes(self.bar)

        out: List[Bar] = []
        bad = 0

        for row in data:
            try:
                ts_ms = int(row[0])
                o = float(row[1])
                h = float(row[2])
                l = float(row[3])
                c = float(row[4])
                v = float(row[5]) if row[5] is not None else 0.0

                dt = datetime.utcfromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S")

                out.append(
                    Bar(
                        ticker=self.inst_id,
                        per=per_minutes,
                        datetime=dt,
                        open=o,
                        high=h,
                        low=l,
                        close=c,
                        volume=v,
                    )
                )
            except Exception:
                bad += 1

        if bad > 0:
            logger.warning("OKX candles skipped bad rows=%s", bad)

        return out

    @staticmethod
    def _bar_to_minutes(bar: str) -> int:
        b = bar.lower().strip()
        if b.endswith("m"):
            return int(b[:-1])
        if b.endswith("h"):
            return int(b[:-1]) * 60
        if b.endswith("d"):
            return int(b[:-1]) * 1440
        return 1

    # -------------------------------------------------
    # Run backtest
    # -------------------------------------------------

    def _run_backtest_on_bars(self, bars: List[Bar]) -> Any:
        try:
            if hasattr(self.bot, "reset_journals"):
                self.bot.reset_journals()
        except Exception:
            pass

        try:
            if hasattr(self.bot, "prepare_indicators"):
                self.bot.prepare_indicators(bars)
        except Exception:
            pass

        try:
            runner = BacktestRunner(self.bot, history_path="")
            if hasattr(runner, "run_on_bars"):
                return runner.run_on_bars(bars)
        except Exception:
            pass

        return {"note": "Indicators loaded, but BacktestRunner.run_on_bars() not implemented"}
