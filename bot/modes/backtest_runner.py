# bot/modes/backtest_runner.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bot.history_manager import Bar


@dataclass
class BacktestRunner:
    """
    BACKTEST režimo vykdytojas.

    Veikia su esamu TradingBot objektu (bot), naudoja:
      - bot.history (HistoryManager)
      - bot.indicator_engine / bot.df
      - bot.risk (RiskManager)
      - bot.strategy_long / bot.strategy_short
      - bot.pending_* state
      - bot.equity_curve / bot.equity_times
      - bot.trades / bot.trades_log / bot.chart_events

    history_path laikomas runner'yje (ne bot'e), kad bot liktų "context".
    """

    bot: object
    history_path: str

    entry_ttl_bars: int = 3

    # ---------------- internal helpers ----------------

    def _prepare_indicators(self, bars: list[Bar]):
        self.bot.indicator_engine.load_history(bars)
        self.bot.indicator_engine.compute_all()
        self.bot.df = self.bot.indicator_engine.get_df()

    def _signal_breakout_long(self, bars: list[Bar], signal_i: int) -> Optional[dict]:
        ref_i = signal_i - 1
        if ref_i < 0 or ref_i >= len(bars):
            return None
        off = float(getattr(self.bot, "limit_offset_pct_long", 0.0)) / 100.0
        stop = bars[ref_i].high
        limit = stop * (1.0 + off)
        return {"stop": stop, "limit": limit, "ref_i": ref_i}

    def _signal_breakout_short(self, bars: list[Bar], signal_i: int) -> Optional[dict]:
        ref_i = signal_i - 1
        if ref_i < 0 or ref_i >= len(bars):
            return None
        off = float(getattr(self.bot, "limit_offset_pct_short", 0.0)) / 100.0
        stop = bars[ref_i].low
        limit = stop * (1.0 - off)
        return {"stop": stop, "limit": limit, "ref_i": ref_i}

    @staticmethod
    def _pending_expired(now_i: int, created_i: int, ttl: int) -> bool:
        return (now_i - created_i) > ttl

    def _cancel_opposite_pending(self, side_to_keep: str):
        if side_to_keep == "LONG":
            self.bot.pending_short = None
            self.bot.pending_add_short = None
        elif side_to_keep == "SHORT":
            self.bot.pending_long = None
            self.bot.pending_add_long = None

    def _get_equity_now(self) -> float:
        try:
            risk = getattr(self.bot, "risk", None)
            if risk is None:
                return 0.0
            v = getattr(risk, "equity", None)
            if v is None:
                v = getattr(risk, "balance", None)
            if v is None:
                return 0.0
            return float(v)
        except Exception:
            return 0.0

    def _snapshot_entry_ctx(
        self,
        bar: Bar,
        side: str,
        entry_price: float,
        signal: Optional[str],
        entry_bar_index: int,
    ):
        self.bot._open_trade_ctx = {
            "side": side,
            "entry_time": getattr(bar, "datetime", None),
            "entry_price": float(entry_price),
            "entry_signal": signal,
            "entry_bar_index": int(entry_bar_index),
        }

    def _append_trade_log_on_exit(
        self,
        bar: Bar,
        exit_reason: str,
        exit_price: float,
        pnl: float,
        exit_bar_index: int,
    ):
        if not hasattr(self.bot, "_trade_id"):
            self.bot._trade_id = 0
        self.bot._trade_id += 1

        ctx = getattr(self.bot, "_open_trade_ctx", None) or {}
        risk = getattr(self.bot, "risk", None)

        side = ctx.get("side") or getattr(risk, "position_side", None) or "UNKNOWN"
        entry_time = ctx.get("entry_time")
        entry_price = ctx.get("entry_price")
        entry_bar_index = ctx.get("entry_bar_index")

        bars_held = None
        try:
            ent_i = entry_bar_index
            if ent_i is not None:
                bars_held = int(exit_bar_index - int(ent_i))
        except Exception:
            bars_held = None

        pnl_pct = None
        try:
            stake = float(getattr(self.bot, "trade_stake", 0.0))
            if stake > 0:
                pnl_pct = (float(pnl) / stake) * 100.0
        except Exception:
            pnl_pct = None

        if not hasattr(self.bot, "trades_log") or self.bot.trades_log is None:
            self.bot.trades_log = []

        # ✅ svarbu ChartTab: entry_bar_index + exit_bar_index
        self.bot.trades_log.append(
            {
                "id": int(self.bot._trade_id),
                "side": side,
                "entry_time": entry_time,
                "exit_time": getattr(bar, "datetime", None),
                "entry_price": entry_price,
                "exit_price": float(exit_price),
                "qty": None,
                "pnl": float(pnl),
                "pnl_pct": pnl_pct,
                "fees": None,
                "exit_reason": str(exit_reason),
                "bars_held": bars_held,
                "entry_signal": ctx.get("entry_signal"),
                "entry_bar_index": entry_bar_index,
                "exit_bar_index": int(exit_bar_index),
            }
        )

        self.bot._open_trade_ctx = None

    # ---------------- public API ----------------

    def run(self):
        """
        Returns:
          (trades_pnl_list, final_equity)
        """
        # init required collections if missing
        if not hasattr(self.bot, "trades") or self.bot.trades is None:
            self.bot.trades = []
        if not hasattr(self.bot, "chart_events") or self.bot.chart_events is None:
            self.bot.chart_events = []
        if not hasattr(self.bot, "trades_log") or self.bot.trades_log is None:
            self.bot.trades_log = []
        if not hasattr(self.bot, "equity_curve") or self.bot.equity_curve is None:
            self.bot.equity_curve = []
        if not hasattr(self.bot, "equity_times") or self.bot.equity_times is None:
            self.bot.equity_times = []

        # pending state
        self.bot.pending_long = None
        self.bot.pending_short = None
        self.bot.pending_add_long = None
        self.bot.pending_add_short = None

        # reset run state
        self.bot.trades = []
        self.bot.trades_log = []
        self.bot.chart_events = []
        self.bot.equity_curve = []
        self.bot.equity_times = []
        self.bot._trade_id = 0
        self.bot._open_trade_ctx = None

        bars = self.bot.history.load_finam_history(self.history_path)
        if not bars:
            return self.bot.trades, self._get_equity_now()

        self._prepare_indicators(bars)

        enable_long = bool(getattr(self.bot, "enable_long", True))
        enable_short = bool(getattr(self.bot, "enable_short", True))

        risk = self.bot.risk
        df = getattr(self.bot, "df", None)

        for i, bar in enumerate(bars):
            price_close = bar.close

            entry_flag_long = False
            entry_flag_short = False
            exit_reason_for_chart = None

            # --- indicators snapshot for this bar (from df) ---
            psar = None
            atr_val = None

            bb_mid = None
            bb_upper = None
            bb_lower = None

            macd = None
            macd_signal = None
            macd_hist = None

            plus_di = None
            minus_di = None
            adx = None

            if df is not None and i < len(df):
                row = df.iloc[i]

                # base
                psar = row.get("psar")
                atr_val = row.get("atr")

                # BB
                bb_mid = row.get("bb_mid")
                bb_upper = row.get("bb_upper")
                bb_lower = row.get("bb_lower")

                # MACD
                macd = row.get("macd")
                macd_signal = row.get("macd_signal")
                macd_hist = row.get("macd_hist")

                # DI / ADX
                plus_di = row.get("plus_di")
                minus_di = row.get("minus_di")
                adx = row.get("adx")

            # SAR trailing
            if risk.in_position:
                risk.update_sl_with_sar(current_price=price_close, atr=atr_val, psar=psar)

            # TP/SL EXIT on close
            exit_reason = risk.check_exit(price_close)
            if exit_reason is not None:
                exit_reason_for_chart = exit_reason
                pnl = risk.exit_position(price_close)
                if pnl != 0.0:
                    self.bot.trades.append(float(pnl))
                    self._append_trade_log_on_exit(
                        bar=bar,
                        exit_reason=str(exit_reason),
                        exit_price=float(price_close),
                        pnl=float(pnl),
                        exit_bar_index=i,
                    )

            # signals on bar close
            signal_long = self.bot.strategy_long.on_bar(bar) if enable_long else None
            signal_short = self.bot.strategy_short.on_bar(bar) if enable_short else None

            # if both disabled
            if not enable_long and not enable_short:
                self.bot.chart_events.append(
                    {
                        "datetime": bar.datetime,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "entry_long": False,
                        "entry_short": False,
                        "exit": exit_reason_for_chart,
                        "pos_side": risk.position_side,
                        # indicators
                        "bb_mid": bb_mid,
                        "bb_upper": bb_upper,
                        "bb_lower": bb_lower,
                        "macd": macd,
                        "macd_signal": macd_signal,
                        "macd_hist": macd_hist,
                        "atr": atr_val,
                        "plus_di": plus_di,
                        "minus_di": minus_di,
                        "adx": adx,
                        "psar": psar,
                    }
                )
                self.bot.equity_times.append(getattr(bar, "datetime", None))
                self.bot.equity_curve.append(self._get_equity_now())
                continue

            # 1) NEW SIGNAL -> create pending entry (only if flat)
            if not risk.in_position:
                both_active = (
                    signal_long in ("PARTIAL_LONG", "FULL_LONG", "BOTH_LONG")
                    and signal_short in ("PARTIAL_SHORT", "FULL_SHORT", "BOTH_SHORT")
                )

                if not both_active:
                    if signal_long in ("PARTIAL_LONG", "FULL_LONG", "BOTH_LONG") and self.bot.pending_long is None:
                        lvl = self._signal_breakout_long(bars, i)
                        if lvl is not None:
                            self.bot.pending_long = {
                                "stop": lvl["stop"],
                                "limit": lvl["limit"],
                                "ref_i": lvl["ref_i"],
                                "signal_i": i,
                                "created_i": i,
                                "ttl": self.entry_ttl_bars,
                                "signal": signal_long,
                            }
                            self._cancel_opposite_pending("LONG")

                    if (
                        signal_short in ("PARTIAL_SHORT", "FULL_SHORT", "BOTH_SHORT")
                        and self.bot.pending_short is None
                        and self.bot.pending_long is None
                    ):
                        lvl = self._signal_breakout_short(bars, i)
                        if lvl is not None:
                            self.bot.pending_short = {
                                "stop": lvl["stop"],
                                "limit": lvl["limit"],
                                "ref_i": lvl["ref_i"],
                                "signal_i": i,
                                "created_i": i,
                                "ttl": self.entry_ttl_bars,
                                "signal": signal_short,
                            }
                            self._cancel_opposite_pending("SHORT")

            # 2) PENDING FILL / TTL (ENTRY) — intrabar
            if not risk.in_position:
                # LONG pending
                if self.bot.pending_long is not None:
                    created_i = self.bot.pending_long["created_i"]
                    ttl = self.bot.pending_long["ttl"]
                    sig = self.bot.pending_long.get("signal")
                    stop = self.bot.pending_long["stop"]
                    limit = self.bot.pending_long["limit"]

                    if self._pending_expired(i, created_i, ttl):
                        self.bot.pending_long = None
                    else:
                        if bar.high >= stop:
                            if bar.open > limit:
                                pass
                            else:
                                fill_price = min(limit, max(bar.open, stop))

                                if sig in ("PARTIAL_LONG", "BOTH_LONG"):
                                    risk.enter_partial_long(fill_price, self.bot.strategy_long.curr_atr)
                                else:
                                    risk.enter_partial_long(fill_price, self.bot.strategy_long.curr_atr)
                                    risk.add_full_long(fill_price, self.bot.strategy_long.curr_atr)

                                entry_flag_long = True
                                self._snapshot_entry_ctx(
                                    bar=bar,
                                    side="LONG",
                                    entry_price=float(fill_price),
                                    signal=str(sig) if sig is not None else None,
                                    entry_bar_index=i,
                                )
                                self.bot.pending_long = None

                # SHORT pending
                if self.bot.pending_short is not None and not risk.in_position:
                    created_i = self.bot.pending_short["created_i"]
                    ttl = self.bot.pending_short["ttl"]
                    sig = self.bot.pending_short.get("signal")
                    stop = self.bot.pending_short["stop"]
                    limit = self.bot.pending_short["limit"]

                    if self._pending_expired(i, created_i, ttl):
                        self.bot.pending_short = None
                    else:
                        if bar.low <= stop:
                            if bar.open < limit:
                                pass
                            else:
                                fill_price = max(limit, min(bar.open, stop))

                                if sig in ("PARTIAL_SHORT", "BOTH_SHORT"):
                                    risk.enter_partial_short(fill_price, self.bot.strategy_short.curr_atr)
                                else:
                                    risk.enter_partial_short(fill_price, self.bot.strategy_short.curr_atr)
                                    risk.add_full_short(fill_price, self.bot.strategy_short.curr_atr)

                                entry_flag_short = True
                                self._snapshot_entry_ctx(
                                    bar=bar,
                                    side="SHORT",
                                    entry_price=float(fill_price),
                                    signal=str(sig) if sig is not None else None,
                                    entry_bar_index=i,
                                )
                                self.bot.pending_short = None

            # 3) ADD TO FULL — STOP-LIMIT from prev bar (i-1)
            if risk.in_position:
                # LONG add
                if (
                    risk.position_side == "LONG"
                    and not risk.full_filled
                    and signal_long in ("FULL_LONG", "BOTH_LONG")
                ):
                    if self.bot.pending_add_long is None:
                        lvl = self._signal_breakout_long(bars, i)
                        if lvl is not None:
                            self.bot.pending_add_long = {
                                "stop": lvl["stop"],
                                "limit": lvl["limit"],
                                "ref_i": lvl["ref_i"],
                                "signal_i": i,
                                "created_i": i,
                                "ttl": self.entry_ttl_bars,
                            }
                    else:
                        created_i = self.bot.pending_add_long["created_i"]
                        ttl = self.bot.pending_add_long["ttl"]
                        stop = self.bot.pending_add_long["stop"]
                        limit = self.bot.pending_add_long["limit"]

                        if self._pending_expired(i, created_i, ttl):
                            self.bot.pending_add_long = None
                        else:
                            if bar.high >= stop:
                                if bar.open > limit:
                                    pass
                                else:
                                    fill_price = min(limit, max(bar.open, stop))
                                    risk.add_full_long(fill_price, self.bot.strategy_long.curr_atr)
                                    entry_flag_long = True
                                    self.bot.pending_add_long = None

                # SHORT add
                if (
                    risk.position_side == "SHORT"
                    and not risk.full_filled
                    and signal_short in ("FULL_SHORT", "BOTH_SHORT")
                ):
                    if self.bot.pending_add_short is None:
                        lvl = self._signal_breakout_short(bars, i)
                        if lvl is not None:
                            self.bot.pending_add_short = {
                                "stop": lvl["stop"],
                                "limit": lvl["limit"],
                                "ref_i": lvl["ref_i"],
                                "signal_i": i,
                                "created_i": i,
                                "ttl": self.entry_ttl_bars,
                            }
                    else:
                        created_i = self.bot.pending_add_short["created_i"]
                        ttl = self.bot.pending_add_short["ttl"]
                        stop = self.bot.pending_add_short["stop"]
                        limit = self.bot.pending_add_short["limit"]

                        if self._pending_expired(i, created_i, ttl):
                            self.bot.pending_add_short = None
                        else:
                            if bar.low <= stop:
                                if bar.open < limit:
                                    pass
                                else:
                                    fill_price = max(limit, min(bar.open, stop))
                                    risk.add_full_short(fill_price, self.bot.strategy_short.curr_atr)
                                    entry_flag_short = True
                                    self.bot.pending_add_short = None

            # chart event per bar (+ indicators snapshot)
            self.bot.chart_events.append(
                {
                    "datetime": bar.datetime,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "entry_long": entry_flag_long,
                    "entry_short": entry_flag_short,
                    "exit": exit_reason_for_chart,
                    "pos_side": risk.position_side,
                    # indicators
                    "bb_mid": bb_mid,
                    "bb_upper": bb_upper,
                    "bb_lower": bb_lower,
                    "macd": macd,
                    "macd_signal": macd_signal,
                    "macd_hist": macd_hist,
                    "atr": atr_val,
                    "plus_di": plus_di,
                    "minus_di": minus_di,
                    "adx": adx,
                    "psar": psar,
                }
            )

            # true equity curve per bar
            self.bot.equity_times.append(getattr(bar, "datetime", None))
            self.bot.equity_curve.append(self._get_equity_now())

        final_equity = self._get_equity_now()
        return self.bot.trades, final_equity
