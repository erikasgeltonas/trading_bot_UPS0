# bot/runner.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .risk import RiskManager
from .strategy_long import Strategy as StrategyLong
from .strategy_short import Strategy as StrategyShort
from .indicator_engine import IndicatorEngine
from .history_manager import HistoryManager, Bar


@dataclass
class TradeEntryCtx:
    side: str
    entry_time: Any | None
    entry_price: float
    entry_signal: str | None
    entry_bar_index: int | None


class TradingBot:
    """
    LIVE kontekstas (be BACKTEST ir be TESTNET).
    """

    def __init__(
        self,
        total_deposit: float = 2000.0,
        trade_stake: float = 2000.0,
        initial_balance: float | None = None,
        enable_long: bool = True,
        enable_short: bool = True,

        tp_atr_mult: float = 1.0,
        sl_atr_mult: float = 0.25,
        limit_offset_pct: float = 0.1,
        bb_period: int = 12,
        bb_lookback: int = 4,
        bb_slope_pct: float = 0.004,
        bb_min_width_pct: float = 0.01,
        bb_channel_pos: float = 0.6,
        max_sar_profit_atr: float = 3.0,

        tp_atr_mult_long: float | None = None,
        sl_atr_mult_long: float | None = None,
        limit_offset_pct_long: float | None = None,
        bb_period_long: int | None = None,
        bb_lookback_long: int | None = None,
        bb_slope_pct_long: float | None = None,
        bb_min_width_pct_long: float | None = None,
        bb_channel_pos_long: float | None = None,
        max_sar_profit_atr_long: float | None = None,

        tp_atr_mult_short: float | None = None,
        sl_atr_mult_short: float | None = None,
        limit_offset_pct_short: float | None = None,
        bb_period_short: int | None = None,
        bb_lookback_short: int | None = None,
        bb_slope_pct_short: float | None = None,
        bb_min_width_pct_short: float | None = None,
        bb_channel_pos_short: float | None = None,
        max_sar_profit_atr_short: float | None = None,
    ):
        self.enable_long = enable_long
        self.enable_short = enable_short

        if initial_balance is not None:
            total_deposit = float(initial_balance)

        self.total_deposit = float(total_deposit)
        self.trade_stake = float(trade_stake)

        self.tp_atr_mult_long = tp_atr_mult_long if tp_atr_mult_long is not None else tp_atr_mult
        self.sl_atr_mult_long = sl_atr_mult_long if sl_atr_mult_long is not None else sl_atr_mult
        self.tp_atr_mult_short = tp_atr_mult_short if tp_atr_mult_short is not None else tp_atr_mult
        self.sl_atr_mult_short = sl_atr_mult_short if sl_atr_mult_short is not None else sl_atr_mult

        self.limit_offset_pct_long = limit_offset_pct_long if limit_offset_pct_long is not None else limit_offset_pct
        self.limit_offset_pct_short = limit_offset_pct_short if limit_offset_pct_short is not None else limit_offset_pct

        self.bb_period_long = bb_period_long if bb_period_long is not None else bb_period
        self.bb_lookback_long = bb_lookback_long if bb_lookback_long is not None else bb_lookback
        self.bb_slope_pct_long = bb_slope_pct_long if bb_slope_pct_long is not None else bb_slope_pct
        self.bb_min_width_pct_long = bb_min_width_pct_long if bb_min_width_pct_long is not None else bb_min_width_pct
        self.bb_channel_pos_long = bb_channel_pos_long if bb_channel_pos_long is not None else bb_channel_pos

        self.bb_period_short = bb_period_short if bb_period_short is not None else bb_period
        self.bb_lookback_short = bb_lookback_short if bb_lookback_short is not None else bb_lookback
        self.bb_slope_pct_short = bb_slope_pct_short if bb_slope_pct_short is not None else bb_slope_pct
        self.bb_min_width_pct_short = bb_min_width_pct_short if bb_min_width_pct_short is not None else bb_min_width_pct
        self.bb_channel_pos_short = bb_channel_pos_short if bb_channel_pos_short is not None else bb_channel_pos

        self.max_sar_profit_atr_long = (
            max_sar_profit_atr_long if max_sar_profit_atr_long is not None else max_sar_profit_atr
        )
        self.max_sar_profit_atr_short = (
            max_sar_profit_atr_short if max_sar_profit_atr_short is not None else max_sar_profit_atr
        )

        # Data + indicators
        self.history = HistoryManager()

        # ✅ svarbu: engine turi skaičiuoti MACD, nes strategijos dabar be pandas
        self.indicator_engine = IndicatorEngine(
            macd_params={"fast": 12, "slow": 26, "signal": 9},
            bb_params={
                "period": bb_period,
                "lookback": bb_lookback,
                "slope_pct": bb_slope_pct,
                "min_width_pct": bb_min_width_pct,
                "channel_pos": bb_channel_pos,
            },
            atr_period=14,
        )
        self.df = None

        # Risk + strategies
        self.risk = RiskManager(
            total_deposit=self.total_deposit,
            trade_stake=self.trade_stake,
            tp_atr_mult=self.tp_atr_mult_long,
            sl_atr_mult=self.sl_atr_mult_long,
            max_sar_profit_atr=self.max_sar_profit_atr_long,
            tp_atr_mult_long=self.tp_atr_mult_long,
            sl_atr_mult_long=self.sl_atr_mult_long,
            tp_atr_mult_short=self.tp_atr_mult_short,
            sl_atr_mult_short=self.sl_atr_mult_short,
            max_sar_profit_atr_long=self.max_sar_profit_atr_long,
            max_sar_profit_atr_short=self.max_sar_profit_atr_short,
        )

        self.strategy_long = StrategyLong(
            bb_period=self.bb_period_long,
            bb_lookback=self.bb_lookback_long,
            bb_slope_pct=self.bb_slope_pct_long,
            bb_min_width_pct=self.bb_min_width_pct_long,
            bb_channel_pos=self.bb_channel_pos_long,
        )
        self.strategy_short = StrategyShort(
            bb_period=self.bb_period_short,
            bb_lookback=self.bb_lookback_short,
            bb_slope_pct=self.bb_slope_pct_short,
            bb_min_width_pct=self.bb_min_width_pct_short,
            bb_channel_pos=self.bb_channel_pos_short,
        )

        # Journals/state
        self.trades: list[float] = []
        self.trades_log: list[dict] = []
        self._trade_id: int = 0
        self._open_trade_ctx: TradeEntryCtx | None = None

        self.chart_events: list[dict] = []
        self.equity_curve: list[float] = []
        self.equity_times: list = []

        self.pending_long: dict | None = None
        self.pending_short: dict | None = None
        self.pending_add_long: dict | None = None
        self.pending_add_short: dict | None = None
        self.entry_ttl_bars: int = 3

        self.strategy_info: dict = self.get_strategy_info()

    def prepare_indicators(self, bars: list[Bar]) -> None:
        self.indicator_engine.load_history(bars)
        self.indicator_engine.compute_all()
        self.df = self.indicator_engine.get_df()

    def reset_journals(self) -> None:
        self.trades = []
        self.trades_log = []
        self._trade_id = 0
        self._open_trade_ctx = None
        self.chart_events = []
        self.equity_curve = []
        self.equity_times = []

        self.pending_long = None
        self.pending_short = None
        self.pending_add_long = None
        self.pending_add_short = None

    def snapshot_entry_ctx(
        self,
        bar_dt: Any | None,
        side: str,
        entry_price: float,
        signal: str | None,
        entry_bar_index: int | None,
    ) -> None:
        self._open_trade_ctx = TradeEntryCtx(
            side=side,
            entry_time=bar_dt,
            entry_price=float(entry_price),
            entry_signal=signal,
            entry_bar_index=entry_bar_index,
        )

    def append_trade_log_on_exit(
        self,
        exit_dt: Any | None,
        exit_reason: str,
        exit_price: float,
        pnl: float,
        exit_bar_index: int | None = None,
    ) -> None:
        self._trade_id += 1

        ctx = self._open_trade_ctx
        side = (ctx.side if ctx else None) or getattr(self.risk, "position_side", None) or "UNKNOWN"
        entry_time = ctx.entry_time if ctx else None
        entry_price = ctx.entry_price if ctx else None
        entry_signal = ctx.entry_signal if ctx else None

        bars_held = None
        try:
            if ctx and ctx.entry_bar_index is not None and exit_bar_index is not None:
                bars_held = int(exit_bar_index - int(ctx.entry_bar_index))
        except Exception:
            bars_held = None

        pnl_pct = None
        try:
            if self.trade_stake > 0:
                pnl_pct = (float(pnl) / float(self.trade_stake)) * 100.0
        except Exception:
            pnl_pct = None

        self.trades_log.append(
            {
                "id": self._trade_id,
                "side": side,
                "entry_time": entry_time,
                "exit_time": exit_dt,
                "entry_price": entry_price,
                "exit_price": float(exit_price),
                "qty": None,
                "pnl": float(pnl),
                "pnl_pct": pnl_pct,
                "fees": None,
                "exit_reason": str(exit_reason),
                "bars_held": bars_held,
                "entry_signal": entry_signal,
            }
        )

        self._open_trade_ctx = None

    def get_equity_now(self) -> float:
        try:
            v = getattr(self.risk, "equity", None)
            if v is None:
                v = getattr(self.risk, "balance", None)
            if v is None:
                return 0.0
            return float(v)
        except Exception:
            return 0.0

    def record_equity_point(self, dt: Any | None) -> None:
        self.equity_times.append(dt)
        self.equity_curve.append(self.get_equity_now())

    def get_strategy_info(self) -> dict:
        return {
            "name": "Engine indicators + Strategy rules + Risk TP/SL",
            "version": "ups0.0-paper",
            "enable_long": bool(self.enable_long),
            "enable_short": bool(self.enable_short),
            "notes": [
                "IndicatorEngine is the only source of indicators.",
                f"entry_ttl_bars={self.entry_ttl_bars}",
            ],
        }
