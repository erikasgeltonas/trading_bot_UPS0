# run_demo_live.py
from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from bot.runner import TradingBot
from bot.history_manager import Bar
from bot.exchange.factory import create_exchange
from storage.sqlite_store import SQLiteStore


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("demo_live")


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


def bar_to_candle_dict(bar: Bar, ts_ms: int) -> Dict[str, Any]:
    return {
        "ts_ms": int(ts_ms),
        "dt": str(bar.datetime),
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(bar.volume),
        "symbol": bar.ticker,
        "per_min": int(bar.per),
    }


def main() -> None:
    symbol = (os.getenv("SYMBOL") or "BTC-USDT").strip()
    tf = (os.getenv("TF") or "1m").strip()
    history_limit = int(os.getenv("HISTORY_LIMIT") or "300")

    initial_balance = float(os.getenv("DEMO_INITIAL_BALANCE") or "2000")
    trade_stake = float(os.getenv("DEMO_TRADE_STAKE") or str(initial_balance))

    db_path = (os.getenv("DB_PATH") or "data/tradingbot.db").strip()
    tag = (os.getenv("DEMO_TAG") or "DEMO_LIVE").strip()

    close_lag_ms = int(os.getenv("CLOSE_LAG_MS") or "1500")
    poll_sleep_sec = float(os.getenv("POLL_SLEEP_SEC") or "0.8")
    error_sleep_sec = float(os.getenv("ERROR_SLEEP_SEC") or "3.0")

    per_min = tf_to_minutes(tf)
    tf_ms = per_min * 60 * 1000

    logger.info("HEARTBEAT | starting DEMO (live candles, paper trades)")
    logger.info(
        "Config | symbol=%s tf=%s history_limit=%s initial_balance=%.2f trade_stake=%.2f db=%s",
        symbol, tf, history_limit, initial_balance, trade_stake, db_path,
    )

    exchange = create_exchange(os.getenv("EXCHANGE") or "OKX")

    ping_ok, ping_msg = exchange.api_ping()
    if not ping_ok:
        logger.error("ERROR | exchange api_ping failed: %s", ping_msg)
    else:
        logger.info("HEARTBEAT | exchange=%s ping=%s", getattr(exchange, "name", "?"), ping_msg)

    bot = TradingBot(
        total_deposit=initial_balance,
        trade_stake=trade_stake,
        enable_long=True,
        enable_short=False,
    )
    bot.reset_journals()

    store = SQLiteStore(db_path)
    session_id = store.start_live_session(
        exchange=str(getattr(exchange, "name", "UNKNOWN")),
        symbol=symbol,
        timeframe=tf,
        initial_balance=initial_balance,
        trade_stake=trade_stake,
        tag=tag,
        meta={
            "started_at": utc_now_str(),
            "mode": "DEMO_PAPER",
            "notes": "No real orders. Demo position simulation only.",
        },
    )
    logger.info("HEARTBEAT | DB session started | session_id=%s", session_id)

    last_closed_ts: Optional[int] = None
    bar_index = -1
    last_saved_trade_count = 0

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

                logger.info("HEARTBEAT | new closed bar | %s | close=%.2f", bar.datetime, bar.close)

                bars_rows_sorted = sorted(rows, key=lambda r: int(r[0]))
                bars = [row_to_bar(symbol, per_min, r) for r in bars_rows_sorted]

                try:
                    bot.prepare_indicators(bars)
                    df = bot.df
                except Exception as e:
                    logger.exception("ERROR | indicator compute failed: %s", e)
                    time.sleep(error_sleep_sec)
                    continue

                # ---- build indicator snapshot for strategy (NO pandas inside strategy) ----
                macd = macd_signal = atr = None
                bb_mid_seq = []
                bb_upper_seq = []
                psar = None

                try:
                    if df is not None and len(df) > 0:
                        last = df.iloc[-1]
                        macd = last.get("macd")
                        macd_signal = last.get("macd_signal")
                        atr = last.get("atr")
                        psar = last.get("psar")

                        # last (lookback+1) values for BB (oldest->newest)
                        lb = int(getattr(bot.strategy_long, "bb_lookback", 4))
                        n = lb + 1
                        bb_mid_seq = df["bb_mid"].iloc[-n:].tolist() if "bb_mid" in df.columns else []
                        bb_upper_seq = df["bb_upper"].iloc[-n:].tolist() if "bb_upper" in df.columns else []
                except Exception:
                    macd = macd_signal = atr = psar = None
                    bb_mid_seq = []
                    bb_upper_seq = []

                # Strategy signal
                signal = None
                try:
                    if bot.enable_long:
                        from bot.strategy_long import IndicatorsSnap as LongSnap
                        snap = LongSnap(
                            macd=float(macd) if macd is not None else None,
                            macd_signal=float(macd_signal) if macd_signal is not None else None,
                            bb_mid_seq=bb_mid_seq,
                            bb_upper_seq=bb_upper_seq,
                            atr=float(atr) if atr is not None else None,
                        )
                        signal = bot.strategy_long.on_bar(bar, indicators=snap, bar_index=bar_index)
                except Exception as e:
                    logger.exception("ERROR | strategy_long.on_bar failed: %s", e)
                    signal = None

                # Trailing SL update (if in position)
                try:
                    if bot.risk.in_position and atr is not None:
                        bot.risk.update_sl_with_sar(
                            current_price=bar.close,
                            atr=float(atr),
                            psar=float(psar) if psar is not None else None
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

                # Entry (DEMO/PAPER)
                try:
                    if (not bot.risk.in_position) and signal == "FULL_LONG":
                        if atr is None or float(atr) <= 0:
                            logger.info("ENTRY | skipped (ATR not ready)")
                        else:
                            bot.risk.enter_partial_long(entry_price=bar.close, atr=float(atr))
                            bot.risk.add_full_long(entry_price=bar.close, atr=float(atr))

                            bot.snapshot_entry_ctx(
                                bar_dt=bar.datetime,
                                side="LONG",
                                entry_price=bar.close,
                                signal=signal,
                                entry_bar_index=bar_index,
                            )

                            logger.info(
                                "ENTRY | side=LONG signal=%s price=%.2f tp=%s sl=%s units=%.6f stake=%.2f equity=%.2f",
                                signal,
                                bar.close,
                                f"{bot.risk.tp_price:.2f}" if bot.risk.tp_price else None,
                                f"{bot.risk.sl_price:.2f}" if bot.risk.sl_price else None,
                                bot.risk.position_units,
                                bot.risk.trade_stake,
                                bot.get_equity_now(),
                            )
                except Exception as e:
                    logger.exception("ERROR | entry flow failed: %s", e)

                # Equity point
                try:
                    bot.record_equity_point(bar.datetime)
                except Exception:
                    pass

                # DB writes
                try:
                    store.insert_live_candle(session_id, bar_to_candle_dict(bar, ts_ms=ts))
                    store.insert_live_equity(session_id, bar.datetime, bot.get_equity_now())

                    if len(bot.trades_log) > last_saved_trade_count:
                        for idx in range(last_saved_trade_count, len(bot.trades_log)):
                            t = dict(bot.trades_log[idx])
                            store.insert_live_trade(session_id, idx=idx, trade=t)
                        last_saved_trade_count = len(bot.trades_log)

                except Exception as e:
                    logger.warning("ERROR | DB write failed: %s", e)

                time.sleep(0.2)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.exception("ERROR | loop exception: %s", e)
                time.sleep(error_sleep_sec)

    except KeyboardInterrupt:
        logger.info("HEARTBEAT | stopped by user (Ctrl+C)")
    finally:
        try:
            store.stop_live_session(session_id)
        except Exception:
            pass

        logger.info("Summary | session_id=%s trades=%d equity=%.2f",
                    session_id, len(bot.trades_log), bot.get_equity_now())


if __name__ == "__main__":
    main()
