# bot/modes/live_runner.py
from __future__ import annotations

from bot.exchange.interface import IExchange


class LiveRunner:
    """
    LIVE wiring runner (stub).

    Šiame etape:
    - NEvykdo prekybos
    - NEsiunčia orderių
    - TIK:
        - patikrina, kad bot kontekstas sukonstruotas (risk/strategijos/strategy_info)
        - patikrina, kad exchange adapteris veikia (api_ping)
        - grąžina aiškų statusą GUI
    """

    def __init__(self, bot, exchange: IExchange):
        self.bot = bot
        self.exchange = exchange

    def run(self) -> dict:
        issues: list[str] = []

        # --- Bot context checks ---
        if self.bot is None:
            issues.append("bot is None")
        else:
            for attr in (
                "risk",
                "strategy_long",
                "strategy_short",
                "indicator_engine",
                "strategy_info",
            ):
                if getattr(self.bot, attr, None) is None:
                    issues.append(f"bot.{attr} is missing")

        # --- Exchange checks ---
        ping_ok = False
        ping_msg = "not checked"
        exchange_name = None

        if self.exchange is None:
            issues.append("exchange is None")
            ping_ok = False
            ping_msg = "exchange missing"
        else:
            exchange_name = getattr(self.exchange, "name", None)
            try:
                ping_ok, ping_msg = self.exchange.api_ping()
            except Exception as e:
                ping_ok = False
                ping_msg = f"api_ping raised: {e}"

            if not ping_ok:
                issues.append(f"exchange api_ping failed: {ping_msg}")

        ok = len(issues) == 0

        if ok:
            return {
                "ok": True,
                "mode": "LIVE",
                "exchange": exchange_name,
                "message": "LIVE wiring OK (exchange connected, no trading executed)",
                "exchange_ping": ping_msg,
                "checks": {
                    "risk": True,
                    "strategy_long": True,
                    "strategy_short": True,
                    "indicator_engine": True,
                    "strategy_info": True,
                    "exchange_ping": True,
                },
                "next_steps": [
                    "Pajungti LIVE execution loop (bars/ticks) ir orderių siuntimą per IExchange.place_order()",
                    "Implementuoti position sync (exchange -> local state) ir order reconciliation",
                    "Papildyti BYBIT adapterį: /v5/order/create + /v5/order/cancel",
                ],
            }

        return {
            "ok": False,
            "mode": "LIVE",
            "exchange": exchange_name,
            "message": "LIVE wiring FAIL",
            "issues": issues,
            "exchange_ping": ping_msg,
        }
