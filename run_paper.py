# run_paper.py
from __future__ import annotations

import os
import sys
import time
import logging
from datetime import datetime, timezone
from typing import Optional, List


# --- ensure repo root is on PYTHONPATH (so "bot.*" works when running as script) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def _load_env_file(path: str) -> None:
    """
    Minimal .env loader (no deps).
    - KEY=VALUE
    - ignores empty lines and comments (# ...)
    - strips optional quotes
    - does NOT override already-set environment variables
    """
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f.readlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if not k:
                    continue
                if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
                    v = v[1:-1]
                if k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


# Load .env from repo root
_load_env_file(os.path.join(BASE_DIR, ".env"))

# Backward-compatible aliases (so your existing env names can work too)
if os.getenv("INITIAL_BALANCE") and not os.getenv("DEMO_INITIAL_BALANCE"):
    os.environ["DEMO_INITIAL_BALANCE"] = os.getenv("INITIAL_BALANCE", "")
if os.getenv("TRADE_STAKE") and not os.getenv("DEMO_TRADE_STAKE"):
    os.environ["DEMO_TRADE_STAKE"] = os.getenv("TRADE_STAKE", "")


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("paper_live")


from bot.runner import TradingBot
from bot.history_manager import Bar
from bot.exchange.factory import create_exchange


def utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def tf_to_minutes(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 1440
    if tf.isdigit():
        return int(tf)
    raise ValueError(f"Unsupported TF: {tf!r}")


def pick_last_closed_row(
    rows: List[List[float]],
    tf_ms: int,
    server_time_ms: int,
    *,
    close_lag_ms: int = 1500,
) -> Optional[List[float]]:
    if not rows:
        return None

    rows_sorted = sorted(rows, key=lambda r: int(r[0]))
    cutoff = int(server_time_ms) - int(close_lag_ms)

    last_closed = None
    for r in rows_sorted:
        ts = int(r[0])
        if ts + tf_ms <= cutoff:
            last_closed = r
    return last_closed


def row_to_bar(symbol: str, per_min: int, r: List[float]) -> Bar:
    ts_ms = int(r[0])
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return Bar(
        ticker=symbol,
        per=per_min,
        datetime=dt,
        open=float(r[1]),
        high=float(r[2]),
        low=float(r[3]),
        close=float(r[4]),
        volume=float(r[5]),
    )


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return int(default)
    try:
        return int(float(v))
    except Exception:
        return int(default)


def main() -> None:
    symbol = (os.getenv("SYMBOL") or "BTC-USDT").strip()
    tf = (os.getenv("TF") or "1m").strip()
    history_limit = _env_int("HISTORY_LIMIT", 300)

    # Capital
    total_deposit = _env_float("TOTAL_DEPOSIT", _env_float("DEMO_INITIAL_BALANCE", 2000.0))
    initial_balance = _env_float("DEMO_INITIAL_BALANCE", 2000.0)
    trade_stake = _env_float("DEMO_TRADE_STAKE", initial_balance)

    # ALWAYS ON (as requested)
    enable_long = True
    enable_short = True

    close_lag_ms = _env_int("CLOSE_LAG_MS", 1500)
    poll_sleep_sec = _env_float("POLL_SLEEP_SEC", 0.8)
    error_sleep_sec = _env_float("ERROR_SLEEP_SEC", 3.0)

    per_min = tf_to_minutes(tf)
    tf_ms = per_min * 60 * 1000

    logger.info("HEARTBEAT | starting PAPER bot (no DB) | LONG+SHORT enabled")
    logger.info(
        "Config | symbol=%s tf=%s history_limit=%s total_deposit=%.2f initial_balance=%.2f stake=%.2f",
        symbol, tf, history_limit, total_deposit, initial_balance, trade_stake
    )

    exchange = create_exchange(os.getenv("EXCHANGE") or "OKX")

    ping_ok, ping_msg = exchange.api_ping()
    if not ping_ok:
        logger.error("ERROR | exchange api_ping failed: %s", ping_msg)
        return
    logger.info("HEARTBEAT | exchange=%s ping=%s", getattr(exchange, "name", "?"), ping_msg)

    bot = TradingBot(
        total_deposit=total_deposit,
        trade_stake=trade_stake,
        enable_long=enable_long,
        enable_short=enable_short,
    )
    bot.reset_journals()

    last_closed_ts: Optional[int] = None
    bar_index = -1

    logger.info("HEARTBEAT | loop started (Ctrl+C to stop)")

    try:
        while True:
            try:
                server_ms = exchange.server_time_ms() or int(time.time() * 1000)

                rows = exchange.fetch_ohlcv(
                    symbol,
                    tf,
                    since_ms=None,
                    limit=max(10, min(history_limit, 500)),
                )

                last_closed = pick_last_closed_row(
                    rows,
                    tf_ms=tf_ms,
                    server_time_ms=server_ms,
                    close_lag_ms=close_lag_ms,
                )

                if last_closed is None:
                    logger.info("HEARTBEAT | no closed candle yet")
                    time.sleep(poll_sleep_sec)
                    continue

                ts = int(last_closed[0])
                if last_closed_ts is not None and ts == last_closed_ts:
                    time.sleep(poll_sleep_sec)
                    continue

                last_closed_ts = ts
                bar_index += 1
                bar = row_to_bar(symbol, per_min, last_closed)

                logger.info("CANDLE | %s | close=%.2f", bar.datetime, bar.close)

                bars_rows_sorted = sorted(rows, key=lambda r: int(r[0]))
                bars = [row_to_bar(symbol, per_min, r) for r in bars_rows_sorted]

                # Indicators
                try:
                    bot.prepare_indicators(bars)
                    df = bot.df
                except Exception as e:
                    logger.exception("ERROR | indicator compute failed: %s", e)
                    time.sleep(error_sleep_sec)
                    continue

                # Snapshot for strategies
                macd = macd_signal = atr = None
                bb_mid_seq = []
                bb_upper_seq = []
                bb_lower_seq = []
                psar = None

                try:
                    if df is not None and len(df) > 0:
                        last = df.iloc[-1]
                        macd = last.get("macd")
                        macd_signal = last.get("macd_signal")
                        atr = last.get("atr")
                        psar = last.get("psar")

                        lb = int(getattr(bot.strategy_long, "bb_lookback", 4))
                        n = lb + 1
                        bb_mid_seq = df["bb_mid"].iloc[-n:].tolist() if "bb_mid" in df.columns else []
                        bb_upper_seq = df["bb_upper"].iloc[-n:].tolist() if "bb_upper" in df.columns else []
                        bb_lower_seq = df["bb_lower"].iloc[-n:].tolist() if "bb_lower" in df.columns else []
                except Exception:
                    macd = macd_signal = atr = psar = None
                    bb_mid_seq = []
                    bb_upper_seq = []
                    bb_lower_seq = []

                # Signals
                signal_long = None
                signal_short = None

                # LONG
                try:
                    from bot.strategy_long import IndicatorsSnap as LongSnap
                    snap_l = LongSnap(
                        macd=float(macd) if macd is not None else None,
                        macd_signal=float(macd_signal) if macd_signal is not None else None,
                        bb_mid_seq=bb_mid_seq,
                        bb_upper_seq=bb_upper_seq,
                        atr=float(atr) if atr is not None else None,
                    )
                    signal_long = bot.strategy_long.on_bar(bar, indicators=snap_l, bar_index=bar_index)
                except Exception as e:
                    logger.exception("ERROR | strategy_long.on_bar failed: %s", e)
                    signal_long = None

                # SHORT
                try:
                    from bot.strategy_short import IndicatorsSnap as ShortSnap
                    try:
                        snap_s = ShortSnap(
                            macd=float(macd) if macd is not None else None,
                            macd_signal=float(macd_signal) if macd_signal is not None else None,
                            bb_mid_seq=bb_mid_seq,
                            bb_lower_seq=bb_lower_seq,
                            atr=float(atr) if atr is not None else None,
                        )
                    except TypeError:
                        snap_s = ShortSnap(
                            macd=float(macd) if macd is not None else None,
                            macd_signal=float(macd_signal) if macd_signal is not None else None,
                            bb_mid_seq=bb_mid_seq,
                            atr=float(atr) if atr is not None else None,
                        )
                    signal_short = bot.strategy_short.on_bar(bar, indicators=snap_s, bar_index=bar_index)
                except Exception as e:
                    logger.exception("ERROR | strategy_short.on_bar failed: %s", e)
                    signal_short = None

                # Trailing SL update
                try:
                    if bot.risk.in_position and atr is not None:
                        bot.risk.update_sl_with_sar(
                            current_price=bar.close,
                            atr=float(atr),
                            psar=float(psar) if psar is not None else None,
                        )
                except Exception as e:
                    logger.exception("ERROR | update_sl_with_sar failed: %s", e)

                # Exit
                try:
                    if bot.risk.in_position:
                        reason = bot.risk.check_exit(bar.close)
                        if reason:
                            pnl = bot.risk.exit_position(bar.close)
                            bot.append_trade_log_on_exit(
                                exit_dt=bar.datetime,
                                exit_reason=reason,
                                exit_price=bar.close,
                                pnl=pnl,
                                exit_bar_index=bar_index,
                            )
                            logger.info(
                                "EXIT | reason=%s price=%.2f pnl=%.2f equity=%.2f",
                                reason, bar.close, pnl, bot.get_equity_now(),
                            )
                except Exception as e:
                    logger.exception("ERROR | exit flow failed: %s", e)

                # Entry (paper)
                try:
                    if not bot.risk.in_position:
                        if signal_long == "FULL_LONG":
                            if atr is None or float(atr) <= 0:
                                logger.info("ENTRY | LONG skipped (ATR not ready)")
                            else:
                                bot.risk.enter_partial_long(entry_price=bar.close, atr=float(atr))
                                bot.risk.add_full_long(entry_price=bar.close, atr=float(atr))
                                bot.snapshot_entry_ctx(
                                    bar_dt=bar.datetime,
                                    side="LONG",
                                    entry_price=bar.close,
                                    signal=signal_long,
                                    entry_bar_index=bar_index,
                                )
                                logger.info(
                                    "ENTRY | side=LONG signal=%s price=%.2f tp=%s sl=%s units=%.6f stake=%.2f equity=%.2f",
                                    signal_long,
                                    bar.close,
                                    f"{bot.risk.tp_price:.2f}" if bot.risk.tp_price else None,
                                    f"{bot.risk.sl_price:.2f}" if bot.risk.sl_price else None,
                                    bot.risk.position_units,
                                    bot.risk.trade_stake,
                                    bot.get_equity_now(),
                                )

                        elif signal_short in ("FULL_SHORT", "SHORT", "FULL_SHORT_SIGNAL"):
                            if atr is None or float(atr) <= 0:
                                logger.info("ENTRY | SHORT skipped (ATR not ready)")
                            else:
                                # Your build may be long-only in risk manager; we log if short methods absent
                                try:
                                    bot.risk.enter_partial_short(entry_price=bar.close, atr=float(atr))
                                    bot.risk.add_full_short(entry_price=bar.close, atr=float(atr))
                                except AttributeError:
                                    logger.warning("ENTRY | SHORT signal but risk manager has no short methods (long-only build)")
                                else:
                                    bot.snapshot_entry_ctx(
                                        bar_dt=bar.datetime,
                                        side="SHORT",
                                        entry_price=bar.close,
                                        signal=str(signal_short),
                                        entry_bar_index=bar_index,
                                    )
                                    logger.info(
                                        "ENTRY | side=SHORT signal=%s price=%.2f tp=%s sl=%s units=%.6f stake=%.2f equity=%.2f",
                                        signal_short,
                                        bar.close,
                                        f"{bot.risk.tp_price:.2f}" if bot.risk.tp_price else None,
                                        f"{bot.risk.sl_price:.2f}" if bot.risk.sl_price else None,
                                        bot.risk.position_units,
                                        bot.risk.trade_stake,
                                        bot.get_equity_now(),
                                    )
                except Exception as e:
                    logger.exception("ERROR | entry flow failed: %s", e)

                # Equity point (in-memory only)
                try:
                    bot.record_equity_point(bar.datetime)
                except Exception:
                    pass

                time.sleep(0.2)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.exception("ERROR | loop exception: %s", e)
                time.sleep(error_sleep_sec)

    except KeyboardInterrupt:
        logger.info("HEARTBEAT | stopped by user (Ctrl+C)")
    finally:
        logger.info("Summary | trades=%d equity=%.2f", len(getattr(bot, "trades_log", [])), bot.get_equity_now())


if __name__ == "__main__":
    main()
