# bot/exchange/bybit_client.py
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import requests

# Naudojam tavo esamą loaderį:
# bot/config/secrets.py -> __init__ užkrauna bot/data/secrets/secrets.env į os.environ
try:
    from bot.config.secrets import Secrets  # type: ignore
except Exception:
    Secrets = None  # type: ignore


@dataclass
class BybitConfig:
    env: str  # "TESTNET" arba "LIVE"
    api_key: str
    api_secret: str
    http_timeout: int = 10
    recv_window: int = 5000

    @property
    def base_url(self) -> str:
        e = (self.env or "TESTNET").strip().upper()
        # Bybit V5:
        # LIVE:    https://api.bybit.com
        # TESTNET: https://api-testnet.bybit.com
        return "https://api-testnet.bybit.com" if e == "TESTNET" else "https://api.bybit.com"


class BybitClient:
    """
    Minimalus Bybit V5 REST clientas (HMAC SHA256).
    - Public: server time, tickers
    - Private: wallet balance (auth test)
    """

    def __init__(self, cfg: BybitConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # -----------------------------
    # Config from env
    # -----------------------------
    @staticmethod
    def from_env() -> "BybitClient":
        # 1) Užkraunam secrets.env per tavo Secrets() (jei yra)
        try:
            if Secrets is not None:
                _ = Secrets()  # tavo Secrets __init__ užkrauna env failą
        except Exception:
            # jei kažkas blogai su Secrets loaderiu, tiesiog tęsiam - env gali būti užkrautas kitu būdu
            pass

        env = os.getenv("BYBIT_ENV", "TESTNET").strip().upper()
        api_key = (os.getenv("BYBIT_API_KEY") or "").strip()
        api_secret = (os.getenv("BYBIT_API_SECRET") or "").strip()

        if not api_key or not api_secret:
            raise RuntimeError(
                "Bybit API raktai nerasti. Patikrink bot/data/secrets/secrets.env:\n"
                "BYBIT_ENV=TESTNET\n"
                "BYBIT_API_KEY=...\n"
                "BYBIT_API_SECRET=...\n"
            )

        recv_window = int(float(os.getenv("BYBIT_RECV_WINDOW", "5000")))
        http_timeout = int(float(os.getenv("BYBIT_HTTP_TIMEOUT", "10")))

        return BybitClient(
            BybitConfig(
                env=env,
                api_key=api_key,
                api_secret=api_secret,
                http_timeout=http_timeout,
                recv_window=recv_window,
            )
        )

    # -----------------------------
    # Signing (V5)
    # -----------------------------
    def _ts_ms(self) -> str:
        return str(int(time.time() * 1000))

    def _sign(self, ts: str, recv_window: str, payload: str) -> str:
        # V5 sign string = timestamp + api_key + recv_window + payload
        s = f"{ts}{self.cfg.api_key}{recv_window}{payload}"
        return hmac.new(
            self.cfg.api_secret.encode("utf-8"),
            s.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

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

        url = self.cfg.base_url + path

        # V5: payload = querystring (GET) arba raw json (POST)
        if method == "GET":
            payload = urlencode({k: v for k, v in params.items() if v is not None})
            full_url = url + (f"?{payload}" if payload else "")
            data = None
        else:
            payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            full_url = url
            data = payload

        headers: Dict[str, str] = {}

        if auth:
            ts = self._ts_ms()
            recv_window = str(self.cfg.recv_window)
            sign = self._sign(ts, recv_window, payload)

            headers.update(
                {
                    "X-BAPI-API-KEY": self.cfg.api_key,
                    "X-BAPI-SIGN": sign,
                    "X-BAPI-SIGN-TYPE": "2",
                    "X-BAPI-TIMESTAMP": ts,
                    "X-BAPI-RECV-WINDOW": recv_window,
                }
            )

        try:
            resp = self.session.request(
                method=method,
                url=full_url,
                headers=headers,
                data=data,
                timeout=self.cfg.http_timeout,
            )
        except Exception as e:
            raise RuntimeError(f"Bybit HTTP error: {e}")

        try:
            j = resp.json()
        except Exception:
            raise RuntimeError(f"Bybit non-JSON response ({resp.status_code}): {resp.text[:500]}")

        # Bybit grąžina: retCode, retMsg, result, time
        ret_code = j.get("retCode", None)
        if ret_code not in (0, "0"):
            raise RuntimeError(f"Bybit API error retCode={ret_code} retMsg={j.get('retMsg')}")

        return j

    # -----------------------------
    # Public endpoints
    # -----------------------------
    def server_time(self) -> int:
        j = self._request("GET", "/v5/market/time", auth=False)

        # Saugiai ištraukiam laiką (formatas kartais skiriasi)
        if isinstance(j.get("time"), (int, str)):
            try:
                return int(j["time"])
            except Exception:
                pass

        r = j.get("result") or {}
        for k in ("timeSecond", "timeNano", "time"):
            if k in r:
                try:
                    return int(str(r[k])[:13])  # ms approx
                except Exception:
                    pass

        return int(time.time() * 1000)

    def ticker(self, category: str, symbol: str) -> Dict[str, Any]:
        # category: spot | linear | inverse | option
        return self._request(
            "GET",
            "/v5/market/tickers",
            params={"category": category, "symbol": symbol},
            auth=False,
        )

    # -----------------------------
    # Private endpoints (test auth)
    # -----------------------------
    def wallet_balance(self, account_type: str = "UNIFIED", coin: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"accountType": account_type}
        if coin:
            params["coin"] = coin
        return self._request("GET", "/v5/account/wallet-balance", params=params, auth=True)

    def api_ping(self) -> Tuple[bool, str]:
        """
        Greitas check:
        1) server_time (public)
        2) wallet_balance (private) -> jei auth ok
        """
        try:
            _ = self.server_time()
        except Exception as e:
            return False, f"Public ping failed: {e}"

        try:
            _ = self.wallet_balance(account_type="UNIFIED")
            return True, "OK"
        except Exception as e:
            return False, f"Auth failed: {e}"
