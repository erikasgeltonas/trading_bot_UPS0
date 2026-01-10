# bot/exchange/factory.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .interface import ExchangeError, IExchange
from .okx_exchange import OKXExchange
from .bybit_exchange import BybitExchange


def _resolve_env_path(env_path: str | None = None) -> Path:
    """
    Resolve env path without validating required keys.
    Priority:
      1) explicit env_path arg
      2) <project_root>/data/secrets/.env
      3) <project_root>/bot/data/secrets/secrets.env
      4) <project_root>/bot/data/secrets/.env
    """
    if env_path:
        return Path(env_path)

    project_root = Path(__file__).resolve().parents[2]  # .../TRADING_BOT_UPS1.0
    candidates = [
        project_root / "data" / "secrets" / ".env",
        project_root / "bot" / "data" / "secrets" / "secrets.env",
        project_root / "bot" / "data" / "secrets" / ".env",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _load_env_file_if_present(env_path: str | None = None) -> None:
    """
    Minimal .env loader that ONLY loads KEY=VALUE into os.environ if not already set.
    Does NOT validate anything (so OKX can work even if BYBIT keys are missing).
    """
    path = _resolve_env_path(env_path)
    if not path.exists():
        return

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # allow optional quotes
                if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
                    value = value[1:-1]

                os.environ.setdefault(key, value)
    except Exception:
        # Do not fail app startup if secrets file is malformed; adapters will raise clearer errors.
        return


def create_exchange(exchange: Optional[str] = None, env_path: Optional[str] = None) -> IExchange:
    """
    Factory that returns a concrete exchange adapter implementing IExchange.

    Selection:
      - argument `exchange` if provided
      - else env EXCHANGE (OKX/BYBIT)
      - else default OKX

    NOTE:
    We load the secrets env file (if present) WITHOUT validation.
    Individual adapters will validate required keys for their exchange.
    """
    _load_env_file_if_present(env_path)

    ex = (exchange or os.getenv("EXCHANGE") or "OKX").strip().upper()

    if ex in ("OKX",):
        return OKXExchange.from_env()

    if ex in ("BYBIT", "BYB"):
        return BybitExchange.from_env()

    raise ExchangeError(f"Unknown exchange: {ex!r}. Supported: OKX, BYBIT")
