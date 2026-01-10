from __future__ import annotations

import os
from pathlib import Path


class SecretsError(RuntimeError):
    """Raised when secrets are missing or invalid."""


class Secrets:
    """
    Centralized secrets loader.
    - Loads .env-like file with KEY=VALUE lines
    - No network calls
    - Safe to import anywhere
    """

    def __init__(self, env_path: str | None = None):
        path = self._resolve_env_path(env_path)

        if not path.exists():
            raise SecretsError(
                f"Secrets file not found: {path}\n"
                f"Create it by copying secrets_template.env and filling values.\n"
                f"Supported default locations:\n"
                f"  - <project_root>/data/secrets/.env\n"
                f"  - <project_root>/bot/data/secrets/secrets.env\n"
            )

        self.env_path = path
        self._load_env_file(self.env_path)

        # Required
        self.bybit_env = self._get_required("BYBIT_ENV").upper()
        self.bybit_api_key = self._get_required("BYBIT_API_KEY")
        self.bybit_api_secret = self._get_required("BYBIT_API_SECRET")

        # Optional
        self.bybit_recv_window = int(os.getenv("BYBIT_RECV_WINDOW", "5000"))
        self.bybit_http_timeout = int(os.getenv("BYBIT_HTTP_TIMEOUT", "10"))

        if self.bybit_env not in ("TESTNET", "LIVE"):
            raise SecretsError("BYBIT_ENV must be TESTNET or LIVE")

    @staticmethod
    def _resolve_env_path(env_path: str | None) -> Path:
        """
        Resolve env path.
        Priority:
          1) explicit env_path arg
          2) <project_root>/data/secrets/.env
          3) <project_root>/bot/data/secrets/secrets.env   (your current layout)
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

        # default (first) if none exists
        return candidates[0]

    @staticmethod
    def _load_env_file(path: Path):
        """
        Minimal .env loader (no external deps).
        Supports lines like:
          KEY=VALUE
        Ignores empty lines and # comments.
        """
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # allow optional quotes
                if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
                    value = value[1:-1]

                os.environ.setdefault(key, value)

    @staticmethod
    def _get_required(name: str) -> str:
        val = os.getenv(name)
        if not val:
            raise SecretsError(f"Missing required secret: {name}")
        return val

    def summary(self) -> dict:
        """Safe summary for logs / GUI (NO secrets exposed)."""
        return {
            "env": self.bybit_env,
            "recv_window": self.bybit_recv_window,
            "timeout": self.bybit_http_timeout,
            "api_key_loaded": bool(self.bybit_api_key),
            "api_secret_loaded": bool(self.bybit_api_secret),
            "env_path": str(self.env_path),
        }
