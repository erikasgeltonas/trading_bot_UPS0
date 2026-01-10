# gui/math_tab.py
from __future__ import annotations

import math
import random
import tkinter as tk
from tkinter import messagebox

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .app_state import app_state


def _safe_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


def _max_drawdown_pct(series: list[float]) -> float:
    """Max drawdown in % relative to peak (0..100)."""
    if not series:
        return 0.0
    peak = series[0]
    max_dd = 0.0
    for v in series:
        if v > peak:
            peak = v
        if peak > 0:
            dd_pct = (peak - v) / peak * 100.0
            if dd_pct > max_dd:
                max_dd = dd_pct
    return max_dd


def _pct_change_series(equity: list[float]) -> list[float]:
    """Returns list of simple returns: r_t = equity_t / equity_{t-1} - 1."""
    out = []
    if not equity or len(equity) < 2:
        return out
    prev = equity[0]
    for v in equity[1:]:
        if prev == 0:
            out.append(0.0)
        else:
            out.append(v / prev - 1.0)
        prev = v
    return out


def _log_return_series(equity: list[float]) -> list[float]:
    """Log returns: lr_t = ln(equity_t / equity_{t-1})"""
    out = []
    if not equity or len(equity) < 2:
        return out
    prev = equity[0]
    for v in equity[1:]:
        if prev <= 0 or v <= 0:
            out.append(0.0)
        else:
            out.append(math.log(v / prev))
        prev = v
    return out


def _percentile(sorted_vals: list[float], p: float) -> float:
    """p in [0..100]. Linear interpolation percentile."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return d0 + d1


def _extract_pnls(trades_log: list[dict]) -> list[float]:
    out = []
    for t in trades_log or []:
        v = t.get("pnl", None)
        try:
            out.append(float(v))
        except Exception:
            pass
    return out


def _profit_concentration_metrics(pnls: list[float]) -> dict:
    """
    Atsako į klausimą "ar 1 trade ištempia viską".
    Skaičiuojam tik iš PROFIT trades (pnls>0) dalis bendrame pelne.
    """
    if not pnls:
        return {
            "total_pnl": 0.0,
            "profit_sum": 0.0,
            "top1_share": 0.0,
            "top5_share": 0.0,
            "trades_to_80pct_profit": None,
            "n_trades": 0,
            "n_wins": 0,
            "n_losses": 0,
        }

    total_pnl = float(sum(pnls))
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]

    profit_sum = float(sum(wins)) if wins else 0.0
    wins_sorted = sorted(wins, reverse=True)

    top1 = wins_sorted[0] if wins_sorted else 0.0
    top5 = sum(wins_sorted[:5]) if wins_sorted else 0.0

    top1_share = (top1 / profit_sum) if profit_sum > 0 else 0.0
    top5_share = (top5 / profit_sum) if profit_sum > 0 else 0.0

    # how many winning trades needed to reach 80% of profit
    trades_to_80 = None
    if profit_sum > 0 and wins_sorted:
        acc = 0.0
        target = 0.8 * profit_sum
        for i, x in enumerate(wins_sorted, start=1):
            acc += x
            if acc >= target:
                trades_to_80 = i
                break

    return {
        "total_pnl": total_pnl,
        "profit_sum": profit_sum,
        "top1_share": top1_share,
        "top5_share": top5_share,
        "trades_to_80pct_profit": trades_to_80,
        "n_trades": len(pnls),
        "n_wins": len(wins),
        "n_losses": len(losses),
    }


def _bootstrap_sequence(data: list[float], length: int, use_blocks: bool, block_size: int) -> list[float]:
    """
    Bootstrap with replacement.
    - If use_blocks: sample contiguous blocks from original data to preserve streaks.
    """
    if not data or length <= 0:
        return []
    n = len(data)
    if n == 1:
        return [data[0]] * length

    if not use_blocks:
        return [random.choice(data) for _ in range(length)]

    # block bootstrap
    bs = max(2, int(block_size))
    out = []
    while len(out) < length:
        start = random.randrange(0, n)
        # take bs items circularly
        for j in range(bs):
            out.append(data[(start + j) % n])
            if len(out) >= length:
                break
    return out


class MathTab:
    """
    Math/analysis tab:
    - Baseline vs Last comparison
    - "MATCH" snapshot (store current last_run into app_state.last_match)
    - Monte Carlo from REAL equity curve (bootstrapped returns)
    - Monte Carlo from TRADE PnL (captures dispersion / "one trade carries all")
    """

    def __init__(self, parent):
        self.parent = parent
        self.frame = tk.Frame(parent)
        self._build_ui()

    def _build_ui(self):
        root = self.frame

        top = tk.Frame(root)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=8)

        self.btn_set_baseline = tk.Button(top, text="Set BASELINE from last run", command=self.on_set_baseline)
        self.btn_set_baseline.pack(side=tk.LEFT)

        # NEW: set MATCH for AI tab
        self.btn_set_match = tk.Button(top, text="Set MATCH from last run", command=self.on_set_match)
        self.btn_set_match.pack(side=tk.LEFT, padx=(8, 0))

        self.btn_compare = tk.Button(top, text="Compare baseline vs last", command=self.on_compare)
        self.btn_compare.pack(side=tk.LEFT, padx=(8, 0))

        tk.Label(top, text="Monte Carlo sims:").pack(side=tk.LEFT, padx=(16, 4))
        self.entry_sims = tk.Entry(top, width=8)
        self.entry_sims.insert(0, "500")
        self.entry_sims.pack(side=tk.LEFT)

        tk.Label(top, text="Seed:").pack(side=tk.LEFT, padx=(10, 4))
        self.entry_seed = tk.Entry(top, width=8)
        self.entry_seed.insert(0, "1")
        self.entry_seed.pack(side=tk.LEFT)

        self.var_use_log = tk.BooleanVar(value=True)
        tk.Checkbutton(top, text="Use log returns (equity MC)", variable=self.var_use_log).pack(side=tk.LEFT, padx=(12, 0))

        self.btn_mc_equity = tk.Button(top, text="Run MC (from last equity)", command=self.on_run_mc_equity)
        self.btn_mc_equity.pack(side=tk.LEFT, padx=(16, 0))

        # second row controls
        top2 = tk.Frame(root)
        top2.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(0, 8))

        tk.Label(top2, text="Trade MC:").pack(side=tk.LEFT)

        self.var_block_bootstrap = tk.BooleanVar(value=True)
        tk.Checkbutton(top2, text="Block bootstrap", variable=self.var_block_bootstrap).pack(side=tk.LEFT, padx=(8, 0))

        tk.Label(top2, text="Block size (trades):").pack(side=tk.LEFT, padx=(10, 4))
        self.entry_block = tk.Entry(top2, width=6)
        self.entry_block.insert(0, "5")
        self.entry_block.pack(side=tk.LEFT)

        self.btn_mc_trades = tk.Button(top2, text="Run MC (TRADE PnL)", command=self.on_run_mc_trades)
        self.btn_mc_trades.pack(side=tk.LEFT, padx=(16, 0))

        self.btn_dispersion = tk.Button(top2, text="Trade dispersion check", command=self.on_dispersion_check)
        self.btn_dispersion.pack(side=tk.LEFT, padx=(8, 0))

        # Body split: left text, right chart
        body = tk.Frame(root)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        left = tk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = tk.Frame(body)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.text = tk.Text(left, width=74, height=28)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = tk.Scrollbar(left, command=self.text.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.config(yscrollcommand=sb.set)

        self.fig = Figure(figsize=(6.6, 4.6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Equity / Monte Carlo bands")
        self.ax.set_xlabel("Step")
        self.ax.set_ylabel("Equity")

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._print_header()

    def _print_header(self):
        self.text.delete("1.0", tk.END)
        self.text.insert(
            tk.END,
            "MATH TAB (MVP)\n"
            "- Baseline vs Last palyginimas\n"
            "- MATCH snapshot (AI tab matys per app_state.last_match)\n"
            "- Monte Carlo iš REAL equity kreivės (bootstrapped returns)\n"
            "- Monte Carlo iš TRADE PnL (geriausiai pagauna 'vienas trade ištempia viską')\n\n"
            "Flow:\n"
            "1) Params → Run backtest\n"
            "2) Math → Set BASELINE (optional)\n"
            "3) Math → Set MATCH (kad AI tab matytų match)\n"
            "4) Keiti 1 parametrą → Params → Run backtest\n"
            "5) Math → Compare / MC\n\n"
        )

    def _get_last(self):
        return getattr(app_state, "last_run", None)

    def _get_baseline(self):
        return getattr(app_state, "baseline_run", None)

    @staticmethod
    def _equity_from_run(run: dict) -> list[float] | None:
        if not run:
            return None
        eq = run.get("equity_curve", None)
        if isinstance(eq, (list, tuple)) and len(eq) >= 2:
            try:
                return [float(x) for x in eq]
            except Exception:
                return None
        return None

    # ---------- actions ----------

    def on_set_baseline(self):
        last = self._get_last()
        if not last:
            messagebox.showerror("Klaida", "Nėra last_run. Pirma paleisk backtestą.")
            return
        app_state.baseline_run = last
        self.text.insert(tk.END, "\n✅ BASELINE set iš last_run.\n")
        meta = (last.get("meta") or {})
        self.text.insert(tk.END, f"Baseline file: {meta.get('history_path','?')}\n")
        self.text.insert(tk.END, f"Baseline final: {meta.get('final_balance','?')}\n")

    def on_set_match(self):
        """
        Store current last_run into app_state.last_match so AI tab can read it as 'MATCH'.
        """
        last = self._get_last()
        if not last:
            messagebox.showerror("Klaida", "Nėra last_run. Pirma paleisk backtestą.")
            return
        try:
            app_state.set_last_match(last)
        except Exception:
            # fallback if set_last_match not available (should be available)
            app_state.last_match = last

        meta = (last.get("meta") or {})
        self.text.insert(tk.END, "\n✅ MATCH set iš last_run (į app_state.last_match).\n")
        self.text.insert(tk.END, f"Match file:  {meta.get('history_path','?')}\n")
        self.text.insert(tk.END, f"Match final: {meta.get('final_balance','?')}\n")
        self.text.insert(tk.END, "→ Dabar AI tab matys MATCH section.\n")

    def on_compare(self):
        baseline = self._get_baseline()
        last = self._get_last()
        if not baseline:
            messagebox.showerror("Klaida", "Nėra baseline_run. Pirma paspausk 'Set BASELINE from last run'.")
            return
        if not last:
            messagebox.showerror("Klaida", "Nėra last_run. Pirma paleisk backtestą.")
            return

        b_meta = baseline.get("meta") or {}
        l_meta = last.get("meta") or {}

        b_stats = baseline.get("stats_all") or {}
        l_stats = last.get("stats_all") or {}

        def f(d, k, default=0.0):
            v = d.get(k, default)
            try:
                return float(v)
            except Exception:
                return default

        b_final = f(b_meta, "final_balance", 0.0)
        l_final = f(l_meta, "final_balance", 0.0)

        b_trades = len(baseline.get("trades_log") or [])
        l_trades = len(last.get("trades_log") or [])

        self.text.insert(tk.END, "\n" + "=" * 60 + "\n")
        self.text.insert(tk.END, "BASELINE vs LAST\n")

        self.text.insert(tk.END, f"Baseline final: {b_final:.2f}\n")
        self.text.insert(tk.END, f"Last final:     {l_final:.2f}\n")
        self.text.insert(tk.END, f"Delta final:    {(l_final - b_final):.2f}\n\n")

        self.text.insert(tk.END, f"Trades: baseline {b_trades} | last {l_trades} | delta {l_trades - b_trades}\n")
        self.text.insert(tk.END, f"WinRate (%): baseline {f(b_stats,'win_rate',0.0):.2f} | last {f(l_stats,'win_rate',0.0):.2f}\n")
        self.text.insert(tk.END, f"PF:        baseline {f(b_stats,'profit_factor',0.0):.2f} | last {f(l_stats,'profit_factor',0.0):.2f}\n")
        self.text.insert(tk.END, f"MaxDD:     baseline {f(b_stats,'max_drawdown',0.0):.2f} | last {f(l_stats,'max_drawdown',0.0):.2f}\n")
        self.text.insert(tk.END, f"TotalPnL:  baseline {f(b_stats,'total_pnl',0.0):.2f} | last {f(l_stats,'total_pnl',0.0):.2f}\n")

        # plot equity comparison
        b_eq = self._equity_from_run(baseline)
        l_eq = self._equity_from_run(last)

        self.ax.clear()
        self.ax.set_title("Equity comparison")
        self.ax.set_xlabel("Step")
        self.ax.set_ylabel("Equity")

        plotted = False
        if b_eq:
            self.ax.plot(range(len(b_eq)), b_eq, label="Baseline")
            plotted = True
        if l_eq:
            self.ax.plot(range(len(l_eq)), l_eq, label="Last")
            plotted = True

        if plotted:
            self.ax.legend()
        else:
            self.text.insert(tk.END, "\n⚠️ Equity curve nerasta baseline/last (app_state neturi equity_curve).\n")

        self.canvas.draw()

    # ---------- Equity MC ----------

    def on_run_mc_equity(self):
        last = self._get_last()
        if not last:
            messagebox.showerror("Klaida", "Nėra last_run. Pirma paleisk backtestą.")
            return

        equity = self._equity_from_run(last)
        if not equity:
            messagebox.showerror("Klaida", "Nėra equity_curve last_run.")
            return

        sims = int(_safe_float(self.entry_sims.get(), 500) or 500)
        sims = max(50, min(20000, sims))

        seed = int(_safe_float(self.entry_seed.get(), 1) or 1)
        random.seed(seed)

        use_log = bool(self.var_use_log.get())
        rets = _log_return_series(equity) if use_log else _pct_change_series(equity)

        if len(rets) < 5:
            messagebox.showerror("Klaida", "Per trumpa equity kreivė Monte Carlo (mažai taškų).")
            return

        start = float(equity[0])
        steps = len(rets)

        sims_equity_by_step = [[] for _ in range(steps + 1)]
        paths_end = []
        paths_dd_pct = []

        for _ in range(sims):
            e = start
            path = [e]
            for _t in range(steps):
                r = random.choice(rets)
                if use_log:
                    e = e * math.exp(r)
                else:
                    e = e * (1.0 + r)
                path.append(e)
            paths_end.append(path[-1])
            paths_dd_pct.append(_max_drawdown_pct(path))
            for i, v in enumerate(path):
                sims_equity_by_step[i].append(v)

        bands_5, bands_50, bands_95 = [], [], []
        for i in range(steps + 1):
            col = sims_equity_by_step[i]
            col.sort()
            bands_5.append(_percentile(col, 5))
            bands_50.append(_percentile(col, 50))
            bands_95.append(_percentile(col, 95))

        paths_end_sorted = sorted(paths_end)
        dd_sorted = sorted(paths_dd_pct)

        p5_end = _percentile(paths_end_sorted, 5)
        p50_end = _percentile(paths_end_sorted, 50)
        p95_end = _percentile(paths_end_sorted, 95)

        p50_dd = _percentile(dd_sorted, 50)
        p95_dd = _percentile(dd_sorted, 95)

        real_end = float(equity[-1])
        real_dd = _max_drawdown_pct(equity)

        prob_finish_below_start = sum(1 for x in paths_end if x < start) / float(sims) * 100.0
        prob_finish_below_real = sum(1 for x in paths_end if x < real_end) / float(sims) * 100.0

        self.text.insert(tk.END, "\n" + "=" * 60 + "\n")
        self.text.insert(tk.END, "MONTE CARLO (from REAL equity)\n")
        self.text.insert(tk.END, f"Sims: {sims} | Seed: {seed} | Mode: {'log' if use_log else 'simple'} returns\n")
        self.text.insert(tk.END, f"Steps: {steps} (equity pts={len(equity)})\n\n")

        self.text.insert(tk.END, f"REAL end equity: {real_end:.2f}\n")
        self.text.insert(tk.END, f"REAL maxDD%:     {real_dd:.2f}\n\n")

        self.text.insert(tk.END, "END equity percentiles:\n")
        self.text.insert(tk.END, f"  P5:  {p5_end:.2f}\n")
        self.text.insert(tk.END, f"  P50: {p50_end:.2f}\n")
        self.text.insert(tk.END, f"  P95: {p95_end:.2f}\n\n")

        self.text.insert(tk.END, "MaxDD% distribution:\n")
        self.text.insert(tk.END, f"  P50: {p50_dd:.2f}\n")
        self.text.insert(tk.END, f"  P95: {p95_dd:.2f}\n\n")

        self.text.insert(tk.END, f"P(finish < start): {prob_finish_below_start:.2f}%\n")
        self.text.insert(tk.END, f"P(finish < real):  {prob_finish_below_real:.2f}%\n")

        # Plot
        self.ax.clear()
        self.ax.set_title("MC bands vs real equity (equity-based)")
        self.ax.set_xlabel("Step")
        self.ax.set_ylabel("Equity")

        xs = list(range(len(equity)))
        self.ax.plot(xs, equity, label="Real equity")

        xs2 = list(range(len(bands_50)))
        self.ax.plot(xs2, bands_50, label="MC P50")
        self.ax.plot(xs2, bands_5, label="MC P5")
        self.ax.plot(xs2, bands_95, label="MC P95")

        self.ax.legend()
        self.canvas.draw()

    # ---------- Trade PnL MC ----------

    def on_dispersion_check(self):
        last = self._get_last()
        if not last:
            messagebox.showerror("Klaida", "Nėra last_run. Pirma paleisk backtestą.")
            return

        pnls = _extract_pnls(last.get("trades_log") or [])
        if not pnls:
            messagebox.showerror("Klaida", "Nėra trades_log/pnl last_run.")
            return

        m = _profit_concentration_metrics(pnls)

        self.text.insert(tk.END, "\n" + "=" * 60 + "\n")
        self.text.insert(tk.END, "TRADE DISPERSION / CONCENTRATION CHECK\n")
        self.text.insert(tk.END, f"Trades: {m['n_trades']} | Wins: {m['n_wins']} | Losses: {m['n_losses']}\n")
        self.text.insert(tk.END, f"Total PnL: {m['total_pnl']:.2f}\n")
        self.text.insert(tk.END, f"Profit sum (wins only): {m['profit_sum']:.2f}\n")
        self.text.insert(tk.END, f"Top1 share of profit: {m['top1_share']*100:.2f}%\n")
        self.text.insert(tk.END, f"Top5 share of profit: {m['top5_share']*100:.2f}%\n")

        t80 = m["trades_to_80pct_profit"]
        if t80 is None:
            self.text.insert(tk.END, "Trades to reach 80% profit: n/a\n")
        else:
            self.text.insert(tk.END, f"Trades to reach 80% profit (wins): {t80}\n")

        if m["profit_sum"] > 0 and m["top1_share"] >= 0.40:
            self.text.insert(tk.END, "⚠️ Warning: Top1 trade sudaro >=40% viso pelno (koncentruota).\n")
        if m["profit_sum"] > 0 and m["top5_share"] >= 0.80:
            self.text.insert(tk.END, "⚠️ Warning: Top5 trades sudaro >=80% viso pelno (labai koncentruota).\n")

    def on_run_mc_trades(self):
        last = self._get_last()
        if not last:
            messagebox.showerror("Klaida", "Nėra last_run. Pirma paleisk backtestą.")
            return

        meta = last.get("meta") or {}
        initial = meta.get("initial", None)
        try:
            initial = float(initial)
        except Exception:
            initial = None

        pnls = _extract_pnls(last.get("trades_log") or [])
        if not pnls:
            messagebox.showerror("Klaida", "Nėra trades_log/pnl last_run.")
            return
        if initial is None:
            messagebox.showerror("Klaida", "Nėra meta.initial last_run (reikia initial balance).")
            return

        sims = int(_safe_float(self.entry_sims.get(), 500) or 500)
        sims = max(50, min(20000, sims))
        seed = int(_safe_float(self.entry_seed.get(), 1) or 1)
        random.seed(seed)

        use_blocks = bool(self.var_block_bootstrap.get())
        block_size = int(_safe_float(self.entry_block.get(), 5) or 5)
        block_size = max(2, min(200, block_size))

        n_trades = len(pnls)

        sims_equity_by_step = [[] for _ in range(n_trades + 1)]
        ends = []
        dds = []

        for _ in range(sims):
            seq = _bootstrap_sequence(pnls, n_trades, use_blocks=use_blocks, block_size=block_size)
            e = initial
            path = [e]
            for p in seq:
                e = e + float(p)
                path.append(e)
            ends.append(path[-1])
            dds.append(_max_drawdown_pct(path))
            for i, v in enumerate(path):
                sims_equity_by_step[i].append(v)

        bands_5, bands_50, bands_95 = [], [], []
        for i in range(n_trades + 1):
            col = sims_equity_by_step[i]
            col.sort()
            bands_5.append(_percentile(col, 5))
            bands_50.append(_percentile(col, 50))
            bands_95.append(_percentile(col, 95))

        ends_sorted = sorted(ends)
        dds_sorted = sorted(dds)

        p5_end = _percentile(ends_sorted, 5)
        p50_end = _percentile(ends_sorted, 50)
        p95_end = _percentile(ends_sorted, 95)

        p50_dd = _percentile(dds_sorted, 50)
        p95_dd = _percentile(dds_sorted, 95)

        real_path = [initial]
        e = initial
        for p in pnls:
            e += float(p)
            real_path.append(e)

        real_end = real_path[-1]
        real_dd = _max_drawdown_pct(real_path)

        prob_finish_below_start = sum(1 for x in ends if x < initial) / float(sims) * 100.0
        prob_finish_below_real = sum(1 for x in ends if x < real_end) / float(sims) * 100.0

        m = _profit_concentration_metrics(pnls)

        self.text.insert(tk.END, "\n" + "=" * 60 + "\n")
        self.text.insert(tk.END, "MONTE CARLO (from TRADE PnL)\n")
        self.text.insert(
            tk.END,
            f"Sims: {sims} | Seed: {seed} | Trades: {n_trades} | "
            f"Mode: {'BLOCK' if use_blocks else 'IID'} (block={block_size})\n\n"
        )

        self.text.insert(tk.END, f"Initial: {initial:.2f}\n")
        self.text.insert(tk.END, f"REAL end equity: {real_end:.2f}\n")
        self.text.insert(tk.END, f"REAL maxDD%:     {real_dd:.2f}\n\n")

        self.text.insert(tk.END, "END equity percentiles:\n")
        self.text.insert(tk.END, f"  P5:  {p5_end:.2f}\n")
        self.text.insert(tk.END, f"  P50: {p50_end:.2f}\n")
        self.text.insert(tk.END, f"  P95: {p95_end:.2f}\n\n")

        self.text.insert(tk.END, "MaxDD% distribution:\n")
        self.text.insert(tk.END, f"  P50: {p50_dd:.2f}\n")
        self.text.insert(tk.END, f"  P95: {p95_dd:.2f}\n\n")

        self.text.insert(tk.END, f"P(finish < start): {prob_finish_below_start:.2f}%\n")
        self.text.insert(tk.END, f"P(finish < real):  {prob_finish_below_real:.2f}%\n\n")

        self.text.insert(tk.END, "Concentration (wins only):\n")
        self.text.insert(tk.END, f"  Top1 share of profit: {m['top1_share']*100:.2f}%\n")
        self.text.insert(tk.END, f"  Top5 share of profit: {m['top5_share']*100:.2f}%\n")
        t80 = m["trades_to_80pct_profit"]
        self.text.insert(tk.END, f"  Trades to reach 80% profit: {t80 if t80 is not None else 'n/a'}\n")

        self.ax.clear()
        self.ax.set_title("MC bands vs real equity (trade-based)")
        self.ax.set_xlabel("Trade #")
        self.ax.set_ylabel("Equity")

        xs = list(range(len(real_path)))
        self.ax.plot(xs, real_path, label="Real (trade equity)")

        xs2 = list(range(len(bands_50)))
        self.ax.plot(xs2, bands_50, label="MC P50")
        self.ax.plot(xs2, bands_5, label="MC P5")
        self.ax.plot(xs2, bands_95, label="MC P95")

        self.ax.legend()
        self.canvas.draw()
