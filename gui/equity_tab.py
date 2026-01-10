# gui/equity_tab.py
import tkinter as tk

import matplotlib
matplotlib.use("TkAgg")

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure


class EquityTab:
    """Equity tab: equity curve + drawdown."""

    def __init__(self, parent):
        self.frame = tk.Frame(parent)

        self._bot = None
        self._equity = []   # list of floats
        self._x = []        # list of ints
        self._dd = []       # drawdown in %

        top = tk.Frame(self.frame)
        top.pack(fill="x", padx=8, pady=6)

        self.lbl_info = tk.Label(top, text="Equity: no data yet. Run backtest first.")
        self.lbl_info.pack(side="left")

        self.fig = Figure(figsize=(10, 6), dpi=100)
        self.ax_eq = self.fig.add_subplot(211)
        self.ax_dd = self.fig.add_subplot(212)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        toolbar = NavigationToolbar2Tk(self.canvas, self.frame)
        toolbar.update()

    # -------- Public API --------
    def set_bot(self, bot):
        self._bot = bot
        self._build_series()
        self._render()

    def update(self, bot):
        self.set_bot(bot)

    # -------- Internal --------
    def _build_series(self):
        self._equity = []
        self._x = []
        self._dd = []

        if self._bot is None:
            return

        # 1) Prefer ready-made equity curve if exists
        eq = getattr(self._bot, "equity_curve", None) or getattr(self._bot, "equity", None)
        if eq and isinstance(eq, (list, tuple)) and len(eq) > 1:
            try:
                self._equity = [float(v) for v in eq]
                self._x = list(range(len(self._equity)))
                self._dd = self._calc_drawdown_pct(self._equity)
                return
            except Exception:
                pass

        # 2) Else build from trades_log (step equity)
        trades = (
            getattr(self._bot, "trades_log", None)
            or getattr(self._bot, "trades", None)
            or getattr(self._bot, "trade_log", None)
            or []
        )

        initial = getattr(self._bot, "initial_balance", None)
        if initial is None:
            initial = getattr(self._bot, "start_balance", None)
        if initial is None:
            initial = 3000.0  # fallback, kad bent kažką rodytų

        eq_vals = [float(initial)]
        for t in trades:
            try:
                pnl = float(t.get("pnl", 0.0))
            except Exception:
                pnl = 0.0
            eq_vals.append(eq_vals[-1] + pnl)

        self._equity = eq_vals
        self._x = list(range(len(eq_vals)))
        self._dd = self._calc_drawdown_pct(self._equity)

    @staticmethod
    def _calc_drawdown_pct(equity):
        peak = None
        dd = []
        for v in equity:
            if peak is None or v > peak:
                peak = v
            if peak and peak != 0:
                dd.append((v - peak) / peak * 100.0)
            else:
                dd.append(0.0)
        return dd

    def _render(self):
        self.ax_eq.clear()
        self.ax_dd.clear()

        if not self._equity or len(self._equity) < 2:
            self.lbl_info.config(text="Equity: no data yet. Run backtest first.")
            self.canvas.draw()
            return

        self.ax_eq.plot(self._x, self._equity, linewidth=1.2)
        self.ax_eq.set_title("Equity curve")
        self.ax_eq.set_xlabel("step")
        self.ax_eq.set_ylabel("equity")

        self.ax_dd.plot(self._x, self._dd, linewidth=1.0)
        self.ax_dd.set_title("Drawdown (%)")
        self.ax_dd.set_xlabel("step")
        self.ax_dd.set_ylabel("dd %")

        start = self._equity[0]
        end = self._equity[-1]
        ret = (end - start) / start * 100.0 if start else 0.0
        max_dd = min(self._dd) if self._dd else 0.0

        self.lbl_info.config(text=f"Start={start:.2f} | End={end:.2f} | Return={ret:.2f}% | MaxDD={max_dd:.2f}%")
        self.fig.tight_layout()
        self.canvas.draw()
