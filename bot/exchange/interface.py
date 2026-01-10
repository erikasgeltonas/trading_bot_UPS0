# bot/exchange/interface.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


class ExchangeError(RuntimeError):
    """Generic exchange-layer error (adapter-level)."""


@dataclass(frozen=True)
class OrderRequest:
    """
    Unified order request for LIVE execution.

    Notes:
    - Keep fields minimal now. We can extend later (stop/trigger, timeInForce, clientOrderId, reduceOnly, etc.)
    - 'symbol' should be a unified symbol used by your bot/GUI (e.g. "BTC-USDT" or "BTC-EUR").
      Each adapter can map it to exchange-specific formats if needed.
    """
    symbol: str
    side: str            # "buy" | "sell"
    order_type: str      # "market" | "limit"  (extend later)
    qty: float
    price: Optional[float] = None


class IExchange(ABC):
    """
    Common exchange interface (adapter contract).

    Design goals:
    - TradingBot context should not depend on any specific exchange.
    - LiveRunner should only depend on IExchange.
    - Underlying REST clients (OKXClient/BybitClient) remain low-level and exchange-specific.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable exchange name (e.g., 'OKX', 'BYBIT')."""

    # -----------------------------
    # Health / basic info
    # -----------------------------
    @abstractmethod
    def api_ping(self) -> Tuple[bool, str]:
        """
        Returns (ok, message).
        Must NOT raise for typical auth/network failures; should return ok=False with a message.
        """

    @abstractmethod
    def server_time_ms(self) -> int:
        """Exchange server time in milliseconds (best effort)."""

    # -----------------------------
    # Account
    # -----------------------------
    @abstractmethod
    def get_balance(self, asset: Optional[str] = None) -> Dict[str, Any]:
        """
        Return raw balance payload.
        Adapter may normalize later; for now keep raw JSON dict (what exchange returns).
        """

    # -----------------------------
    # Orders (minimal)
    # -----------------------------
    @abstractmethod
    def place_order(self, req: OrderRequest) -> Dict[str, Any]:
        """
        Place an order. Returns raw order response.

        Implementations should raise ExchangeError only for:
        - invalid input (side/type/qty/price) after local validation
        - unexpected adapter-level issues

        For typical API errors, it's acceptable to raise ExchangeError with a readable message.
        """

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """Cancel an order by exchange order id. Returns raw cancel response."""
