# gui/chart_tab.py
from __future__ import annotations

import tkinter as tk
import math

import matplotlib

matplotlib.use("TkAgg")

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle


class ChartTab:
    """Chart tab (candles + signals + BB overlay + trade focus/jump + MACD panel + DI/ADX panel)."""

    def __init__(self, parent):
        self.frame = tk.Frame(parent)

        self._bot = None

        # chart_events-like list[dict] OR list[Bar-like objects] normalized into list[dict]
        self._events: list[dict] = []

        self._trades: list[dict] = []
        self._trade_by_id: dict[str, dict] = {}
        self._cur_trade_idx = 0

        # map datetime->bar_index (stringified) for matching
        self._dt_to_i: dict[str, int] = {}

        # UI state
        self._last_selected_trade: dict | None = None

        # Focus / zoom settings (tweak here)
        self.focus_pad_left = 15
        self.focus_pad_right = 15
        self.focus_min_window = 40

        # --- UI layout ---
        top = tk.Frame(self.frame)
        top.pack(fill="x", padx=8, pady=6)

        self.lbl_info = tk.Label(top, text="Chart: no data yet. Run backtest first.")
        self.lbl_info.pack(side="left")

        btns = tk.Frame(top)
        btns.pack(side="right")

        self.btn_prev = tk.Button(btns, text="Prev trade", width=10, command=self.prev_trade)
        self.btn_prev.pack(side="left", padx=2)

        self.btn_next = tk.Button(btns, text="Next trade", width=10, command=self.next_trade)
        self.btn_next.pack(side="left", padx=2)

        self.btn_reset = tk.Button(btns, text="Reset zoom", width=10, command=self.reset_zoom)
        self.btn_reset.pack(side="left", padx=2)

        self.btn_show_all = tk.Button(btns, text="Show all", width=10, command=self.show_all)
        self.btn_show_all.pack(side="left", padx=2)

        # --- Figure with 3 panels: price + MACD + DI/ADX ---
        self.fig = Figure(figsize=(10, 7), dpi=100)
        gs = self.fig.add_gridspec(3, 1, height_ratios=[3.2, 1.2, 1.2], hspace=0.08)

        self.ax_price = self.fig.add_subplot(gs[0, 0])
        self.ax_macd = self.fig.add_subplot(gs[1, 0], sharex=self.ax_price)
        self.ax_di = self.fig.add_subplot(gs[2, 0], sharex=self.ax_price)

        # cleaner look: hide x tick labels on upper shared axes
        self.ax_price.tick_params(labelbottom=False)
        self.ax_macd.tick_params(labelbottom=False)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.frame)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(fill="both", expand=True)

        toolbar = NavigationToolbar2Tk(self.canvas, self.frame)
        toolbar.update()

        self._sync_buttons()

    # -----------------------------
    # Public API (from ParamsTab / App)
    # -----------------------------
    def set_bot(self, bot):
        """Receive bot and render chart."""
        self._bot = bot

        raw_events = getattr(bot, "chart_events", None) or []
        # If no chart_events (live/testnet etc.), try fallback to bars/history on bot
        if not raw_events:
            raw_events = (
                getattr(bot, "bars", None)
                or getattr(bot, "history", None)
                or getattr(bot, "ohlcv", None)
                or []
            )

        self._events = self._normalize_events(raw_events)

        self._trades = (
            getattr(bot, "trades_log", None)
            or getattr(bot, "trades", None)
            or getattr(bot, "trade_log", None)
            or []
        )

        self._rebuild_maps()
        self._cur_trade_idx = 0
        self._last_selected_trade = None

        self._sync_buttons()
        self._render(selected_trade=None, focus=False)

    def update(self, bot):
        self.set_bot(bot)

    # Called from TradesTab callback
    def show_trade(self, trade_id, trade_dict=None):
        if not self._events:
            self.lbl_info.config(text="Chart: no data. Run backtest first.")
            self.canvas.draw()
            return

        t = trade_dict
        if t is None:
            t = self._trade_by_id.get(str(trade_id))
        if t is None:
            for x in self._trades:
                if str(x.get("id")) == str(trade_id):
                    t = x
                    break

        if t is None:
            self.lbl_info.config(text=f"Chart: trade id={trade_id} not found.")
            self._last_selected_trade = None
            self._render(selected_trade=None, focus=False)
            return

        try:
            self._cur_trade_idx = self._trades.index(t)
        except Exception:
            pass

        self._last_selected_trade = t
        self._sync_buttons()
        self._render(selected_trade=t, focus=True)

    def next_trade(self):
        if not self._trades:
            return
        self._cur_trade_idx = min(self._cur_trade_idx + 1, len(self._trades) - 1)
        self._last_selected_trade = self._trades[self._cur_trade_idx]
        self._sync_buttons()
        self._render(selected_trade=self._last_selected_trade, focus=True)

    def prev_trade(self):
        if not self._trades:
            return
        self._cur_trade_idx = max(self._cur_trade_idx - 1, 0)
        self._last_selected_trade = self._trades[self._cur_trade_idx]
        self._sync_buttons()
        self._render(selected_trade=self._last_selected_trade, focus=True)

    def reset_zoom(self):
        self._render(selected_trade=self._last_selected_trade, focus=False)

    def show_all(self):
        self._last_selected_trade = None
        self._sync_buttons()
        self._render(selected_trade=None, focus=False)

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _sync_buttons(self):
        has_trades = bool(self._trades)
        state = tk.NORMAL if has_trades else tk.DISABLED
        for b in (self.btn_prev, self.btn_next, self.btn_reset, self.btn_show_all):
            b.config(state=state)

    def _rebuild_maps(self):
        self._trade_by_id.clear()
        for t in self._trades:
            tid = t.get("id")
            if tid is None:
                continue
            self._trade_by_id[str(tid)] = t

        self._dt_to_i.clear()
        for i, ev in enumerate(self._events):
            dt = ev.get("datetime")
            if dt is None:
                continue
            self._dt_to_i[str(dt)] = i

    @staticmethod
    def _pick_first(d: dict, keys: list[str]):
        for k in keys:
            if k in d and d.get(k) is not None:
                return d.get(k)
        return None

    def _trade_entry_exit_idx(self, t: dict):
        entry_idx = self._pick_first(
            t,
            ["entry_idx", "entry_index", "entry_i", "entry_bar", "entry_bar_index", "entry_bar_idx", "i_entry"],
        )
        exit_idx = self._pick_first(
            t,
            ["exit_idx", "exit_index", "exit_i", "exit_bar", "exit_bar_index", "exit_bar_idx", "i_exit"],
        )

        def _to_int(x):
            try:
                return int(float(x))
            except Exception:
                return None

        entry_idx = _to_int(entry_idx)
        exit_idx = _to_int(exit_idx)

        if entry_idx is None:
            et = t.get("entry_time")
            if et is not None:
                entry_idx = self._dt_to_i.get(str(et))
        if exit_idx is None:
            xt = t.get("exit_time")
            if xt is not None:
                exit_idx = self._dt_to_i.get(str(xt))

        return entry_idx, exit_idx

    @staticmethod
    def _is_true(v) -> bool:
        return bool(v) and v is not None

    @staticmethod
    def _as_float_or_nan(v):
        try:
            if v is None:
                return math.nan
            return float(v)
        except Exception:
            return math.nan

    @staticmethod
    def _as_float_or_none(v):
        try:
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    def _normalize_events(self, raw_events) -> list[dict]:
        """
        Accepts:
          - list[dict] (already chart_events)
          - list[Bar-like objects] with attrs: datetime/open/high/low/close/volume (+ optional ticker/per)
        Returns list[dict] with at least: datetime, open, high, low, close, volume
        """
        if not raw_events:
            return []

        if isinstance(raw_events, list) and raw_events and isinstance(raw_events[0], dict):
            # Ensure required keys exist as float-friendly
            out: list[dict] = []
            for ev in raw_events:
                out.append(
                    {
                        **ev,
                        "datetime": ev.get("datetime"),
                        "open": ev.get("open"),
                        "high": ev.get("high"),
                        "low": ev.get("low"),
                        "close": ev.get("close"),
                        "volume": ev.get("volume", ev.get("vol")),
                    }
                )
            return out

        out: list[dict] = []
        for ev in raw_events:
            # Bar-like object
            dt = getattr(ev, "datetime", None)
            out.append(
                {
                    "datetime": dt,
                    "open": getattr(ev, "open", None),
                    "high": getattr(ev, "high", None),
                    "low": getattr(ev, "low", None),
                    "close": getattr(ev, "close", None),
                    "volume": getattr(ev, "volume", None),
                    "ticker": getattr(ev, "ticker", None),
                    "per": getattr(ev, "per", None),
                }
            )
        return out

    def _draw_candles(self, ax, x, o, h, l, c, width: float = 0.6):
        half = width / 2.0
        for i in range(len(x)):
            xi = x[i]
            oi = o[i]
            hi = h[i]
            li = l[i]
            ci = c[i]
            if oi is None or hi is None or li is None or ci is None:
                continue

            is_up = ci >= oi
            color = "green" if is_up else "red"

            ax.vlines(xi, li, hi, color=color, linewidth=1.0, zorder=2)

            y0 = min(oi, ci)
            height = abs(ci - oi)
            if height == 0:
                height = 1e-9

            rect = Rectangle(
                (xi - half, y0),
                width,
                height,
                facecolor=color,
                edgecolor=color,
                linewidth=1.0,
                zorder=3,
            )
            ax.add_patch(rect)

    def _apply_focus_xlim(self, n: int, e_i: int | None, x_i: int | None):
        if e_i is None and x_i is None:
            return (0, max(1, n - 1))

        anchors = [v for v in (e_i, x_i) if v is not None]
        left_anchor = min(anchors)
        right_anchor = max(anchors)

        left = max(0, left_anchor - int(self.focus_pad_left))
        right = min(n - 1, right_anchor + int(self.focus_pad_right))

        width = right - left
        min_w = int(self.focus_min_window)
        if width < min_w:
            need = min_w - width
            add_left = need // 2
            add_right = need - add_left
            left = max(0, left - add_left)
            right = min(n - 1, right + add_right)

            width2 = right - left
            if width2 < min_w:
                if left == 0:
                    right = min(n - 1, left + min_w)
                elif right == n - 1:
                    left = max(0, right - min_w)

        if right <= left:
            right = min(n - 1, left + max(30, min_w))

        return (left, right)

    def _y_from_index_close(self, idx: int | None):
        if idx is None:
            return None
        if idx < 0 or idx >= len(self._events):
            return None
        v = self._events[idx].get("close")
        return self._as_float_or_none(v)

    def _render(self, selected_trade=None, focus: bool = False):
        self.ax_price.clear()
        self.ax_macd.clear()
        self.ax_di.clear()

        if not self._events:
            self.lbl_info.config(text="Chart: no data. Run backtest first.")
            self.canvas.draw()
            return

        n = len(self._events)
        x = list(range(n))

        # OHLC
        o = [self._as_float_or_none(ev.get("open")) for ev in self._events]
        h = [self._as_float_or_none(ev.get("high")) for ev in self._events]
        l = [self._as_float_or_none(ev.get("low")) for ev in self._events]
        c = [self._as_float_or_none(ev.get("close")) for ev in self._events]

        # Indicators source (df if present)
        df = getattr(self._bot, "df", None) if self._bot is not None else None

        # BB overlay: prefer chart_events fields, else try df columns
        bb_mid = [self._as_float_or_nan(ev.get("bb_mid")) for ev in self._events]
        bb_upper = [self._as_float_or_nan(ev.get("bb_upper")) for ev in self._events]
        bb_lower = [self._as_float_or_nan(ev.get("bb_lower")) for ev in self._events]

        has_any_bb = (
            any(not math.isnan(v) for v in bb_mid)
            or any(not math.isnan(v) for v in bb_upper)
            or any(not math.isnan(v) for v in bb_lower)
        )

        if (not has_any_bb) and df is not None and len(df) >= n:
            try:
                if {"bb_mid", "bb_upper", "bb_lower"}.issubset(set(df.columns)):
                    bb_mid = [self._as_float_or_nan(v) for v in df["bb_mid"].iloc[:n].tolist()]
                    bb_upper = [self._as_float_or_nan(v) for v in df["bb_upper"].iloc[:n].tolist()]
                    bb_lower = [self._as_float_or_nan(v) for v in df["bb_lower"].iloc[:n].tolist()]
                    has_any_bb = (
                        any(not math.isnan(v) for v in bb_mid)
                        or any(not math.isnan(v) for v in bb_upper)
                        or any(not math.isnan(v) for v in bb_lower)
                    )
            except Exception:
                pass

        if has_any_bb:
            self.ax_price.plot(x, bb_upper, linewidth=1.0, alpha=0.85, zorder=1)
            self.ax_price.plot(x, bb_mid, linewidth=1.0, alpha=0.85, zorder=1)
            self.ax_price.plot(x, bb_lower, linewidth=1.0, alpha=0.85, zorder=1)

        # candles
        self._draw_candles(self.ax_price, x, o, h, l, c, width=0.6)

        # Signal markers from chart_events (only if present)
        long_x, long_y = [], []
        short_x, short_y = [], []
        exit_x, exit_y = [], []

        has_signal_fields = any(
            ("entry_long" in ev) or ("entry_short" in ev) or ("exit" in ev) for ev in self._events
        )

        if has_signal_fields:
            for i, ev in enumerate(self._events):
                cl = ev.get("close")
                hi = ev.get("high")
                lo = ev.get("low")

                if self._is_true(ev.get("entry_long")):
                    long_x.append(i)
                    long_y.append(lo if lo is not None else cl)

                if self._is_true(ev.get("entry_short")):
                    short_x.append(i)
                    short_y.append(hi if hi is not None else cl)

                if ev.get("exit") is not None:
                    exit_x.append(i)
                    exit_y.append(cl)

            if long_x:
                self.ax_price.scatter(long_x, long_y, marker="^", s=55, zorder=5)
            if short_x:
                self.ax_price.scatter(short_x, short_y, marker="v", s=55, zorder=5)
            if exit_x:
                self.ax_price.scatter(exit_x, exit_y, marker="x", s=45, zorder=5)

        # MACD panel (from bot.df)
        has_macd = False
        macd = macd_sig = macd_hist = []
        if df is not None and len(df) >= n:
            try:
                if {"macd", "macd_signal", "macd_hist"}.issubset(set(df.columns)):
                    macd = [self._as_float_or_nan(v) for v in df["macd"].iloc[:n].tolist()]
                    macd_sig = [self._as_float_or_nan(v) for v in df["macd_signal"].iloc[:n].tolist()]
                    macd_hist = [self._as_float_or_nan(v) for v in df["macd_hist"].iloc[:n].tolist()]
                    has_macd = (
                        any(not math.isnan(v) for v in macd)
                        or any(not math.isnan(v) for v in macd_sig)
                        or any(not math.isnan(v) for v in macd_hist)
                    )
            except Exception:
                has_macd = False
                macd = macd_sig = macd_hist = []

        if has_macd:
            self.ax_macd.bar(x, macd_hist, width=0.8, alpha=0.6)
            self.ax_macd.plot(x, macd, linewidth=1.0)
            self.ax_macd.plot(x, macd_sig, linewidth=1.0)
        else:
            self.ax_macd.text(0.01, 0.8, "MACD=OFF (no df/macd columns)", transform=self.ax_macd.transAxes)

        # DI/ADX panel (from bot.df)
        has_di = False
        plus_di = minus_di = adx = []
        if df is not None and len(df) >= n:
            try:
                if {"plus_di", "minus_di"}.issubset(set(df.columns)):
                    plus_di = [self._as_float_or_nan(v) for v in df["plus_di"].iloc[:n].tolist()]
                    minus_di = [self._as_float_or_nan(v) for v in df["minus_di"].iloc[:n].tolist()]
                    if "adx" in df.columns:
                        adx = [self._as_float_or_nan(v) for v in df["adx"].iloc[:n].tolist()]
                    else:
                        adx = [math.nan] * n

                    has_di = (
                        any(not math.isnan(v) for v in plus_di)
                        or any(not math.isnan(v) for v in minus_di)
                        or any(not math.isnan(v) for v in adx)
                    )
            except Exception:
                has_di = False
                plus_di = minus_di = adx = []

        if has_di:
            self.ax_di.plot(x, plus_di, linewidth=1.0)
            self.ax_di.plot(x, minus_di, linewidth=1.0)
            if any(not math.isnan(v) for v in adx):
                self.ax_di.plot(x, adx, linewidth=1.0, alpha=0.9)
        else:
            self.ax_di.text(0.01, 0.8, "DI=OFF (no df/plus_di/minus_di columns)", transform=self.ax_di.transAxes)

        # -----------------------------
        # Selected trade: triangles + dotted line
        # -----------------------------
        if selected_trade is not None:
            e_i, x_i = self._trade_entry_exit_idx(selected_trade)

            tid = selected_trade.get("id")
            side = str(selected_trade.get("side", "")).upper() or "?"
            ep = self._as_float_or_none(selected_trade.get("entry_price"))
            xp = self._as_float_or_none(selected_trade.get("exit_price"))
            pnl = selected_trade.get("pnl")
            et = selected_trade.get("entry_time")
            xt = selected_trade.get("exit_time")

            # fallback to close if prices missing
            if ep is None:
                ep = self._y_from_index_close(e_i)
            if xp is None:
                xp = self._y_from_index_close(x_i)

            # markers
            entry_marker = "^" if side == "LONG" else "v"
            exit_marker = "v" if side == "LONG" else "^"

            if e_i is not None and ep is not None:
                self.ax_price.scatter([e_i], [ep], marker=entry_marker, s=110, zorder=20)

            if x_i is not None and xp is not None:
                self.ax_price.scatter([x_i], [xp], marker=exit_marker, s=110, zorder=20)

            if e_i is not None and x_i is not None and ep is not None and xp is not None:
                self.ax_price.plot([e_i, x_i], [ep, xp], linestyle="--", linewidth=1.5, zorder=15)

            pos_txt = f" | Trade {self._cur_trade_idx + 1}/{len(self._trades)}" if self._trades else ""
            bb_txt = "BB=ON" if has_any_bb else "BB=OFF"
            macd_txt = "MACD=ON" if has_macd else "MACD=OFF"
            di_txt = "DI=ON" if has_di else "DI=OFF"

            self.lbl_info.config(
                text=(
                    f"Trade id={tid}{pos_txt} | {side} | entry_i={e_i} exit_i={x_i} | "
                    f"entry={ep} exit={xp} | pnl={pnl} | {et} -> {xt} | {bb_txt} {macd_txt} {di_txt}"
                )
            )

            if focus:
                left, right = self._apply_focus_xlim(n=n, e_i=e_i, x_i=x_i)
                self.ax_price.set_xlim(left, right)
                self.ax_macd.set_xlim(left, right)
                self.ax_di.set_xlim(left, right)
            else:
                self.ax_price.set_xlim(0, max(1, n - 1))
                self.ax_macd.set_xlim(0, max(1, n - 1))
                self.ax_di.set_xlim(0, max(1, n - 1))

        else:
            bb_txt = "BB=ON" if has_any_bb else "BB=OFF"
            macd_txt = "MACD=ON" if has_macd else "MACD=OFF"
            di_txt = "DI=ON" if has_di else "DI=OFF"
            sig_txt = ""
            if has_signal_fields:
                sig_txt = f" | Signals: LONG={len(long_x)} SHORT={len(short_x)} EXIT={len(exit_x)}"
            self.lbl_info.config(
                text=f"Bars: {n}{sig_txt} | Trades(log)={len(self._trades)} | {bb_txt} {macd_txt} {di_txt}"
            )
            self.ax_price.set_xlim(0, max(1, n - 1))
            self.ax_macd.set_xlim(0, max(1, n - 1))
            self.ax_di.set_xlim(0, max(1, n - 1))

        # Titles / labels
        title = "Candles"
        if has_signal_fields:
            title += " + signals (entry_long ^, entry_short v, exit x)"
        if has_any_bb:
            title += " + BB"

        self.ax_price.set_title(title)
        self.ax_price.set_ylabel("price")

        self.ax_macd.set_title("MACD")
        self.ax_macd.set_ylabel("macd")

        self.ax_di.set_title("DI / ADX")
        self.ax_di.set_xlabel("bar index")
        self.ax_di.set_ylabel("value")

        self.fig.tight_layout()
        self.canvas.draw()
