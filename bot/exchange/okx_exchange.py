# bot/exchange/okx_exchange.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List

from .interface import ExchangeError, IExchange, OrderRequest
from .okx_client import OKXClient, OKXError


class OKXExchange(IExchange):
    """
    OKX adapter (IExchange) wrapping low-level OKXClient.
    """

    def __init__(self, client: OKXClient):
        self._client = client

    @property
    def name(self) -> str:
        return "OKX"

    @staticmethod
    def from_env() -> "OKXExchange":
        return OKXExchange(OKXClient.from_env())

    # -----------------------------
    # Health
    # -----------------------------
    def api_ping(self) -> Tuple[bool, str]:
        try:
            return self._client.api_ping()
        except Exception as e:
            return False, f"OKX api_ping error: {e}"

    def server_time_ms(self) -> int:
        try:
            return int(self._client.server_time())
        except Exception:
            return 0

    # -----------------------------
    # OHLCV  <<< SVARBIAUSIA DALIS >>>
    # -----------------------------
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int | None = None,
        limit: int | None = None,
    ) -> List[List[float]]:
        """
        Returns: list of [ts_ms, open, high, low, close, volume]
        """
        try:
            candles = self._client.get_candles(
                inst_id=symbol,
                bar=timeframe,
                after=since_ms,
                limit=limit,
            )
        except OKXError as e:
            raise ExchangeError(str(e))
        except Exception as e:
            raise ExchangeError(f"OKX fetch_ohlcv failed: {e}")

        out: List[List[float]] = []

        for c in candles:
            # OKX format: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
            try:
                ts = int(c[0])
                o = float(c[1])
                h = float(c[2])
                l = float(c[3])
                cl = float(c[4])
                v = float(c[5])
                out.append([ts, o, h, l, cl, v])
            except Exception:
                continue

        return out

    # -----------------------------
    # Account
    # -----------------------------
    def get_balance(self, asset: Optional[str] = None) -> Dict[str, Any]:
        try:
            return self._client.balance(ccy=asset)
        except OKXError as e:
            raise ExchangeError(str(e))
        except Exception as e:
            raise ExchangeError(f"OKX get_balance failed: {e}")

    # -----------------------------
    # Orders
    # -----------------------------
    def place_order(self, req: OrderRequest) -> Dict[str, Any]:
        side = (req.side or "").strip().lower()
        if side not in ("buy", "sell"):
            raise ExchangeError(f"OKX place_order: invalid side={req.side!r}")

        order_type = (req.order_type or "").strip().lower()
        if order_type not in ("market", "limit"):
            raise ExchangeError(f"OKX place_order: invalid order_type={req.order_type!r}")

        if req.qty is None or float(req.qty) <= 0:
            raise ExchangeError(f"OKX place_order: invalid qty={req.qty!r}")

        if order_type == "limit":
            if req.price is None or float(req.price) <= 0:
                raise ExchangeError("OKX place_order: limit order requires price > 0")

        inst_id = req.symbol.strip()
        if not inst_id:
            raise ExchangeError("OKX place_order: symbol is empty")

        try:
            return self._client.place_order(
                inst_id=inst_id,
                side=side,
                ord_type=order_type,
                sz=str(req.qty),
                td_mode="cash",
                px=(str(req.price) if req.price is not None else None),
            )
        except OKXError as e:
            raise ExchangeError(str(e))
        except Exception as e:
            raise ExchangeError(f"OKX place_order failed: {e}")

    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        try:
            return self._client.cancel_order(inst_id=symbol, ord_id=order_id)
        except OKXError as e:
            raise ExchangeError(str(e))
        except Exception as e:
            raise ExchangeError(f"OKX cancel_order failed: {e}")
