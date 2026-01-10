# bot/exchange/okx_client.py
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import requests

# Optional: tavo esamas loaderis (bot/config/secrets.py), kad užkrautų bot/data/secrets/secrets.env
try:
    from bot.config.secrets import Secrets  # type: ignore
except Exception:
    Secrets = None  # type: ignore


class OKXError(RuntimeError):
    """OKX API error."""


@dataclass
class OKXConfig:
    api_key: str
    api_secret: str
    passphrase: str
    base_url: str = "https://www.okx.com"
    http_timeout: int = 10
    simulated_trading: bool = False  # DEMO/Paper mode via header


class OKXClient:
    """
    Minimalus OKX V5 REST klientas su HMAC SHA256 (Base64).

    Palaiko:
    - public time
    - public candles (get_candles)   ✅ (REIKIA DEMO LIVE)
    - private balance (auth test)
    - order place/cancel (paruošta ateičiai)

    DEMO/Paper:
    - OKX naudoja tą pačią API, tik reikia headerio: x-simulated-trading: 1
    - Įjunk per env: OKX_SIMULATED=1
    """

    def __init__(self, cfg: OKXConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # -----------------------------
    # Config from env
    # -----------------------------
    @staticmethod
    def from_env() -> "OKXClient":
        # Užkraunam secrets.env jei yra tavo loaderis
        try:
            if Secrets is not None and hasattr(Secrets, "load"):
                Secrets.load()
        except Exception:
            pass

        api_key = (os.getenv("OKX_API_KEY") or "").strip()
        api_secret = (os.getenv("OKX_API_SECRET") or "").strip()
        passphrase = (os.getenv("OKX_API_PASSPHRASE") or "").strip()

        if not api_key or not api_secret or not passphrase:
            raise OKXError(
                "OKX raktai nerasti. Patikrink bot/data/secrets/secrets.env:\n"
                "OKX_API_KEY=...\n"
                "OKX_API_SECRET=...\n"
                "OKX_API_PASSPHRASE=...   (tavo sugalvotas passphrase)\n"
                "Papildomai (nebūtina):\n"
                "OKX_SIMULATED=1  (DEMO/paper)\n"
                "OKX_HTTP_TIMEOUT=10\n"
                "OKX_BASE_URL=https://www.okx.com\n"
            )

        base_url = (os.getenv("OKX_BASE_URL") or "https://www.okx.com").strip()
        http_timeout = int(float(os.getenv("OKX_HTTP_TIMEOUT") or "10"))
        simulated = (os.getenv("OKX_SIMULATED") or "0").strip().lower() in ("1", "true", "yes")

        return OKXClient(
            OKXConfig(
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase,
                base_url=base_url,
                http_timeout=http_timeout,
                simulated_trading=simulated,
            )
        )

    # -----------------------------
    # Signing (OKX V5)
    # -----------------------------
    def _ts_iso(self) -> str:
        t = time.time()
        ms = int((t - int(t)) * 1000)
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{ms:03d}Z"

    def _sign(self, timestamp: str, method: str, request_path: str, body: str) -> str:
        prehash = f"{timestamp}{method}{request_path}{body}"
        mac = hmac.new(
            self.cfg.api_secret.encode("utf-8"),
            prehash.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(mac).decode("utf-8")

    # -----------------------------
    # Core request
    # -----------------------------
    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        auth: bool = False,
    ) -> Dict[str, Any]:
        method = method.upper().strip()
        params = params or {}
        body = body or {}

        # Query
        if params:
            qs = "&".join(f"{k}={params[k]}" for k in params if params[k] is not None)
            request_path = f"{path}?{qs}"
        else:
            request_path = path

        url = self.cfg.base_url + request_path

        # Body string (OKX reikalauja tikslios body sign'e)
        body_str = ""
        data = None
        if method in ("POST", "PUT"):
            body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            data = body_str

        headers: Dict[str, str] = {}

        if auth:
            ts = self._ts_iso()
            sign = self._sign(ts, method, request_path, body_str)

            headers.update(
                {
                    "OK-ACCESS-KEY": self.cfg.api_key,
                    "OK-ACCESS-SIGN": sign,
                    "OK-ACCESS-TIMESTAMP": ts,
                    "OK-ACCESS-PASSPHRASE": self.cfg.passphrase,
                }
            )

            # DEMO/Paper mode
            if self.cfg.simulated_trading:
                headers["x-simulated-trading"] = "1"

        try:
            resp = self.session.request(
                method=method,
                url=url,
                headers=headers,
                data=data,
                timeout=self.cfg.http_timeout,
            )
        except Exception as e:
            raise OKXError(f"OKX HTTP error: {e}")

        try:
            j = resp.json()
        except Exception:
            raise OKXError(f"OKX non-JSON response ({resp.status_code}): {resp.text[:800]}")

        code = str(j.get("code", ""))
        if code != "0":
            msg = j.get("msg", "")
            raise OKXError(f"OKX API error code={code} msg={msg} raw={str(j)[:400]}")

        return j

    # -----------------------------
    # Public endpoints
    # -----------------------------
    def server_time(self) -> int:
        j = self._request("GET", "/api/v5/public/time", auth=False)
        try:
            return int(j["data"][0]["ts"])
        except Exception:
            return int(time.time() * 1000)

    def get_candles(
        self,
        inst_id: str,
        bar: str,
        after: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[List[Any]]:
        """
        GET /api/v5/market/candles
        Returns list rows in OKX format:
          [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        """
        params: Dict[str, Any] = {
            "instId": inst_id,
            "bar": bar,
        }
        if after is not None:
            # OKX param name is "after" (pagination). We'll pass-through.
            params["after"] = str(int(after))
        if limit is not None:
            params["limit"] = str(int(limit))

        j = self._request("GET", "/api/v5/market/candles", params=params, auth=False)
        data = j.get("data", []) or []
        # OKX returns newest-first; we return as-is (adapter can sort)
        return data

    # -----------------------------
    # Private endpoints (auth test)
    # -----------------------------
    def balance(self, ccy: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if ccy:
            params["ccy"] = ccy
        return self._request("GET", "/api/v5/account/balance", params=params, auth=True)

    def api_ping(self) -> Tuple[bool, str]:
        """
        Greitas check:
        - visada patikrina public server_time (turi veikti DEMO LIVE'ui)
        - bando private balance (jei nepraeina – DEMO LIVE vistiek gali važiuoti)
        """
        try:
            _ = self.server_time()
        except Exception as e:
            return False, f"Public ping failed: {e}"

        # Private check is optional for DEMO LIVE (no orders)
        try:
            _ = self.balance()
            mode = "SIMULATED" if self.cfg.simulated_trading else "LIVE"
            return True, f"OK ({mode})"
        except Exception as e:
            # IMPORTANT: allow public-only mode to proceed
            mode = "SIMULATED" if self.cfg.simulated_trading else "LIVE"
            return True, f"PUBLIC OK ({mode}), AUTH FAILED: {e}"

    # -----------------------------
    # Orders (paruošta ateičiai)
    # -----------------------------
    def place_order(
        self,
        inst_id: str,
        side: str,
        ord_type: str,
        sz: str,
        td_mode: str = "cash",
        px: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ord_type,
            "sz": sz,
        }
        if px is not None:
            body["px"] = px
        return self._request("POST", "/api/v5/trade/order", body=body, auth=True)

    def cancel_order(self, inst_id: str, ord_id: str) -> Dict[str, Any]:
        body = {"instId": inst_id, "ordId": ord_id}
        return self._request("POST", "/api/v5/trade/cancel-order", body=body, auth=True)
