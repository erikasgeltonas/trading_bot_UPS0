# bot/exchange/bybit_exchange.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .bybit_client import BybitClient
from .interface import ExchangeError, IExchange, OrderRequest


class BybitExchange(IExchange):
    """
    Bybit adapter (IExchange) wrapping low-level BybitClient.

    NOTE:
    - Your current BybitClient implements ping + balance + ticker/time.
    - Spot order placement is NOT implemented in BybitClient yet.
      This adapter exposes place/cancel methods but will raise ExchangeError until you add client endpoints.
    """

    def __init__(self, client: BybitClient):
        self._client = client

    @property
    def name(self) -> str:
        return "BYBIT"

    # -----------------------------
    # Constructors
    # -----------------------------
    @staticmethod
    def from_env() -> "BybitExchange":
        return BybitExchange(BybitClient.from_env())

    # -----------------------------
    # Health / basic info
    # -----------------------------
    def api_ping(self) -> Tuple[bool, str]:
        try:
            return self._client.api_ping()
        except Exception as e:
            # contract: should not explode
            return False, f"BYBIT api_ping error: {e}"

    def server_time_ms(self) -> int:
        try:
            return int(self._client.server_time())
        except Exception:
            return 0

    # -----------------------------
    # Account
    # -----------------------------
    def get_balance(self, asset: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns raw wallet balance payload.

        Bybit balance API accepts coin filter, but needs accountType too.
        We default to UNIFIED because your client uses that in api_ping().
        """
        try:
            return self._client.wallet_balance(account_type="UNIFIED", coin=asset)
        except Exception as e:
            raise ExchangeError(f"BYBIT get_balance failed: {e}")

    # -----------------------------
    # Orders (minimal) - NOT YET WIRED
    # -----------------------------
    def place_order(self, req: OrderRequest) -> Dict[str, Any]:
        """
        Not implemented yet because BybitClient currently doesn't have place_order endpoint.

        When you want to wire it:
        - Implement in BybitClient a method like:
            place_order(category, symbol, side, orderType, qty, price=None)
          using /v5/order/create
        - Then call it from here.

        For now, we fail loudly so you don't think BYBIT LIVE trading works.
        """
        raise ExchangeError(
            "BYBIT place_order is not wired yet (BybitClient has no /v5/order/create implementation)."
        )

    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """
        Not implemented yet because BybitClient currently doesn't have cancel endpoint.

        Wire later via /v5/order/cancel.
        """
        raise ExchangeError(
            "BYBIT cancel_order is not wired yet (BybitClient has no /v5/order/cancel implementation)."
        )
