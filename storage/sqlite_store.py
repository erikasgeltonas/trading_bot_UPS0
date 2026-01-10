# storage/sqlite_store.py
from __future__ import annotations

import os
import json
import sqlite3
from typing import Any, Dict, List, Optional, Union
from datetime import datetime


class SQLiteStore:
    """
    SQLite storage for:
      - Backtest runs (existing): runs + trades
      - Demo-live sessions (NEW): live_sessions + live_candles + live_equity + live_trades

    Designed to be easily portable to Postgres (JSON -> JSONB).
    """

    def __init__(self, db_path: str = "data/tradingbot.db"):
        self.db_path = db_path
        self._ensure_dirs()
        self._init_db()

    # ---------- internal ----------

    def _ensure_dirs(self) -> None:
        base_dir = os.path.dirname(self.db_path)
        if base_dir and not os.path.exists(base_dir):
            os.makedirs(base_dir, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _utc_iso() -> str:
        return datetime.utcnow().isoformat()

    def _init_db(self) -> None:
        with self._connect() as conn:
            cur = conn.cursor()

            # -------------------------
            # BACKTEST (existing)
            # -------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,

                    history_path TEXT,
                    tag TEXT,

                    final_balance REAL,
                    total_pnl REAL,
                    max_dd REAL,
                    profit_factor REAL,
                    win_rate REAL,
                    trades_count INTEGER,

                    params_json TEXT,
                    meta_json TEXT,
                    stats_all_json TEXT,
                    stats_long_json TEXT,
                    stats_short_json TEXT
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    idx INTEGER,

                    side TEXT,
                    entry_time TEXT,
                    exit_time TEXT,
                    pnl REAL,

                    trade_json TEXT,

                    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
                )
                """
            )

            # -------------------------
            # DEMO LIVE (NEW)
            # -------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS live_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    stopped_at TEXT,

                    exchange TEXT,
                    symbol TEXT,
                    timeframe TEXT,

                    tag TEXT,
                    initial_balance REAL,
                    trade_stake REAL,

                    meta_json TEXT
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS live_candles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,

                    ts_ms INTEGER,
                    dt TEXT,

                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,

                    candle_json TEXT,

                    UNIQUE(session_id, ts_ms),
                    FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS live_equity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,

                    dt TEXT,
                    equity REAL,

                    UNIQUE(session_id, dt),
                    FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS live_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    idx INTEGER,

                    side TEXT,
                    entry_time TEXT,
                    exit_time TEXT,
                    pnl REAL,
                    exit_reason TEXT,

                    trade_json TEXT,

                    FOREIGN KEY (session_id) REFERENCES live_sessions(id) ON DELETE CASCADE
                )
                """
            )

            conn.commit()

    # =========================================================
    # BACKTEST API (unchanged)
    # =========================================================

    def save_run(self, run: Dict[str, Any], tag: Optional[str] = None) -> int:
        """
        Saves a backtest run into DB.
        Returns run_id.
        """
        meta = run.get("meta", {}) or {}
        stats_all = run.get("stats_all", {}) or {}
        stats_long = run.get("stats_long", {}) or {}
        stats_short = run.get("stats_short", {}) or {}
        params = run.get("params", {}) or {}

        created_at = self._utc_iso()

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO runs (
                    created_at,
                    history_path,
                    tag,
                    final_balance,
                    total_pnl,
                    max_dd,
                    profit_factor,
                    win_rate,
                    trades_count,
                    params_json,
                    meta_json,
                    stats_all_json,
                    stats_long_json,
                    stats_short_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    meta.get("history_path"),
                    tag,
                    meta.get("final_balance"),
                    stats_all.get("total_pnl"),
                    stats_all.get("max_drawdown"),
                    stats_all.get("profit_factor"),
                    stats_all.get("win_rate"),
                    len(run.get("trades_log", []) or []),
                    json.dumps(params),
                    json.dumps(meta),
                    json.dumps(stats_all),
                    json.dumps(stats_long),
                    json.dumps(stats_short),
                ),
            )

            run_id = int(cur.lastrowid)

            trades = run.get("trades_log", []) or []
            for i, t in enumerate(trades):
                cur.execute(
                    """
                    INSERT INTO trades (
                        run_id,
                        idx,
                        side,
                        entry_time,
                        exit_time,
                        pnl,
                        trade_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        i,
                        t.get("side"),
                        t.get("entry_time"),
                        t.get("exit_time"),
                        t.get("pnl"),
                        json.dumps(t),
                    ),
                )

            conn.commit()

        return run_id

    def list_runs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    id,
                    created_at,
                    history_path,
                    tag,
                    final_balance,
                    total_pnl,
                    max_dd,
                    profit_factor,
                    win_rate,
                    trades_count
                FROM runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )

            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def get_run(self, run_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
            row = cur.fetchone()
            if not row:
                return None

            run = dict(row)
            for k in (
                "params_json",
                "meta_json",
                "stats_all_json",
                "stats_long_json",
                "stats_short_json",
            ):
                if run.get(k):
                    run[k] = json.loads(run[k])

            cur.execute("SELECT * FROM trades WHERE run_id = ? ORDER BY idx ASC", (run_id,))
            trades = []
            for t in cur.fetchall():
                td = dict(t)
                if td.get("trade_json"):
                    td["trade_json"] = json.loads(td["trade_json"])
                trades.append(td)

            run["trades"] = trades
            return run

    def get_trades(self, run_id: int) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM trades WHERE run_id = ? ORDER BY idx ASC", (run_id,))
            rows = cur.fetchall()
            out = []
            for r in rows:
                d = dict(r)
                if d.get("trade_json"):
                    d["trade_json"] = json.loads(d["trade_json"])
                out.append(d)
            return out

    # =========================================================
    # DEMO LIVE API (NEW)
    # =========================================================

    def start_live_session(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        initial_balance: float,
        trade_stake: float,
        tag: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        created_at = self._utc_iso()
        meta_json = json.dumps(meta or {})

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO live_sessions (
                    created_at, exchange, symbol, timeframe, tag,
                    initial_balance, trade_stake, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (created_at, exchange, symbol, timeframe, tag, float(initial_balance), float(trade_stake), meta_json),
            )
            conn.commit()
            return int(cur.lastrowid)

    def stop_live_session(self, session_id: int) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE live_sessions SET stopped_at = ? WHERE id = ?",
                (self._utc_iso(), int(session_id)),
            )
            conn.commit()

    def insert_live_candle(self, session_id: int, candle: Dict[str, Any]) -> None:
        """
        candle dict example:
          {
            "ts_ms": 123,
            "dt": "YYYY-MM-DD HH:MM:SS",
            "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...
          }
        """
        ts_ms = int(candle.get("ts_ms") or 0)
        dt = str(candle.get("dt") or "")
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR IGNORE INTO live_candles (
                    session_id, ts_ms, dt, open, high, low, close, volume, candle_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(session_id),
                    ts_ms,
                    dt,
                    float(candle.get("open") or 0.0),
                    float(candle.get("high") or 0.0),
                    float(candle.get("low") or 0.0),
                    float(candle.get("close") or 0.0),
                    float(candle.get("volume") or 0.0),
                    json.dumps(candle),
                ),
            )
            conn.commit()

    def insert_live_equity(self, session_id: int, dt: str, equity: float) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO live_equity (session_id, dt, equity)
                VALUES (?, ?, ?)
                """,
                (int(session_id), str(dt), float(equity)),
            )
            conn.commit()

    def insert_live_trade(self, session_id: int, idx: int, trade: Dict[str, Any]) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO live_trades (
                    session_id, idx, side, entry_time, exit_time, pnl, exit_reason, trade_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(session_id),
                    int(idx),
                    trade.get("side"),
                    trade.get("entry_time"),
                    trade.get("exit_time"),
                    trade.get("pnl"),
                    trade.get("exit_reason"),
                    json.dumps(trade),
                ),
            )
            conn.commit()

    def list_live_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, created_at, stopped_at, exchange, symbol, timeframe, tag, initial_balance, trade_stake
                FROM live_sessions
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_live_trades(self, session_id: int) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM live_trades WHERE session_id = ? ORDER BY idx ASC",
                (int(session_id),),
            )
            rows = cur.fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                if d.get("trade_json"):
                    d["trade_json"] = json.loads(d["trade_json"])
                out.append(d)
            return out
