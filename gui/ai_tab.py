# gui/ai_tab.py
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
import math
from statistics import mean, median, pstdev

from .app_state import app_state
from .strategy_info import build_strategy_info_from_params


class AiTab:
    """
    AI Agent (MVP):
    Must see:
      - last backtest run (app_state.last_run)
      - match snapshot (app_state.last_match) [set from Math tab]
      - current robot logic snapshot (strategy_info) attached to runs by ParamsTab/runner
      - future optimizer payload stored into app_state.ai_last_payload

    No auto-changing params, no auto-running.
    """

    MIN_TRADES_TO_OPTIMIZE = 5

    def __init__(self, parent):
        self.frame = tk.Frame(parent)
        self._build_layout()

    def _build_layout(self):
        root = self.frame

        top = tk.Frame(root)
        top.pack(fill="x", padx=8, pady=8)

        tk.Label(top, text="AI agent (MVP)", font=("Arial", 11, "bold")).pack(side="left")

        self.btn_analyze = tk.Button(top, text="Analyze last run", command=self.on_analyze_last_run)
        self.btn_analyze.pack(side="right")

        mid = tk.Frame(root)
        mid.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        scroll = tk.Scrollbar(mid)
        scroll.pack(side="right", fill="y")

        self.text = tk.Text(mid, wrap="word", yscrollcommand=scroll.set, width=140, height=35)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.text.yview)

        self._write_intro()

    def _write_intro(self):
        self.text.delete("1.0", tk.END)
        self.text.insert(
            tk.END,
            "AI agent ready.\n\n"
            "Workflow:\n"
            "1) Parameters tab -> Run backtest\n"
            "2) (optional) Math tab -> Set MATCH from last run\n"
            "3) AI tab -> Analyze last run\n\n"
            "This MVP is heuristic/statistics-based (no neural network).\n"
        )

    # ---------------- helpers ----------------

    @staticmethod
    def _safe_float(x, default=None):
        try:
            return float(x)
        except Exception:
            return default

    @staticmethod
    def _safe_int(x, default=0):
        try:
            return int(x)
        except Exception:
            return default

    @staticmethod
    def _fmt_pct(x, digits=2):
        if x is None:
            return "None"
        try:
            return f"{float(x):.{digits}f}"
        except Exception:
            return str(x)

    @staticmethod
    def _extract_pnls(trades_log: list[dict]) -> list[float]:
        out = []
        for t in trades_log or []:
            v = t.get("pnl", None)
            try:
                out.append(float(v))
            except Exception:
                pass
        return out

    @staticmethod
    def _downside_deviation(pnls: list[float]) -> float:
        if not pnls:
            return 0.0
        downs = [min(0.0, x) for x in pnls]
        mu = mean(downs)
        return math.sqrt(mean([(x - mu) ** 2 for x in downs]))

    @staticmethod
    def _largest_losing_trade(pnls: list[float]) -> float:
        return min(pnls) if pnls else 0.0

    @staticmethod
    def _largest_winning_trade(pnls: list[float]) -> float:
        return max(pnls) if pnls else 0.0

    @staticmethod
    def _streaks(pnls: list[float]) -> dict:
        max_win = 0
        max_loss = 0
        cur_win = 0
        cur_loss = 0
        for x in pnls:
            if x > 0:
                cur_win += 1
                cur_loss = 0
            elif x < 0:
                cur_loss += 1
                cur_win = 0
            else:
                cur_win = 0
                cur_loss = 0
            max_win = max(max_win, cur_win)
            max_loss = max(max_loss, cur_loss)
        return {"max_win_streak": max_win, "max_loss_streak": max_loss}

    @staticmethod
    def _pick_meta_balance(meta: dict) -> tuple[float | None, float | None]:
        initial = None
        final = None

        for k in ("initial", "initial_balance", "start_balance", "equity_start"):
            fv = AiTab._safe_float(meta.get(k, None), None)
            if fv is not None:
                initial = fv
                break

        for k in ("final_balance", "final", "end_balance", "equity_end", "balance_end"):
            fv = AiTab._safe_float(meta.get(k, None), None)
            if fv is not None:
                final = fv
                break

        return initial, final

    @staticmethod
    def _return_pct_from_meta(meta: dict) -> float | None:
        initial, final = AiTab._pick_meta_balance(meta)
        if initial is None or final is None or initial == 0:
            return None
        return ((final - initial) / initial) * 100.0

    @staticmethod
    def _return_pct_from_pnl(total_pnl: float | None, initial: float | None) -> float | None:
        if total_pnl is None or initial is None or initial == 0:
            return None
        return (float(total_pnl) / float(initial)) * 100.0

    @staticmethod
    def _regime_guess(stats_all: dict, stats_long: dict, stats_short: dict) -> str:
        pf = float(stats_all.get("profit_factor", 0.0) or 0.0)
        trades = int(stats_all.get("trades", 0) or 0)
        long_trades = int(stats_long.get("trades", 0) or 0)
        short_trades = int(stats_short.get("trades", 0) or 0)

        if trades <= 0:
            return "Unknown (no trades)"

        if short_trades >= max(10, int(2.5 * max(1, long_trades))) and short_trades > long_trades:
            if pf >= 1.5:
                return "Down-bias / short-friendly regime (selloffs + pullbacks tradeable)"
            return "Down-bias / short-active but weak edge (choppy selloffs)"

        if long_trades >= max(10, int(2.5 * max(1, short_trades))) and long_trades > short_trades:
            if pf >= 1.5:
                return "Up-bias / long-friendly regime (momentum/breakouts likely)"
            return "Up-bias but weak edge (choppy rallies)"

        if trades >= 80 and pf < 1.3:
            return "Choppy/noisy regime (overtrading risk)"

        if pf >= 2.0 and trades >= 20:
            return "Clear edge regime (trend or clean mean-reversion)"

        return "Mixed/unclear regime"

    @staticmethod
    def _recommend_objective(stats_all: dict) -> dict:
        maxdd = AiTab._safe_float(stats_all.get("max_drawdown"), 0.0) or 0.0
        trades = int(stats_all.get("trades", 0) or 0)

        dd_cap = 20.0
        if maxdd > 35:
            dd_cap = 25.0
        elif maxdd < 15:
            dd_cap = 15.0

        if trades < 20:
            dd_cap = max(dd_cap, 20.0)

        return {
            "objective": "maximize_expectancy",
            "constraint": f"MaxDD <= {dd_cap:.1f}%",
            "secondary": "min Trades >= 25 (avoid overfitting on small sample)",
        }

    @staticmethod
    def _recommend_params(params: dict, regime: str, long_trades: int, short_trades: int) -> list[dict]:
        """
        Recommend only params that exist in current params dict.
        Avoid suggesting a side if it has too few trades.
        """
        def rng(center: float, pct: float, step: float):
            lo = max(0.0, center * (1.0 - pct))
            hi = center * (1.0 + pct)
            return {"min": round(lo, 6), "max": round(hi, 6), "step": step}

        def add_if_exists(name: str, r: dict, hint: str | None = None):
            if name in params:
                item = {"name": name, "range": r}
                if hint:
                    item["hint"] = hint
                out.append(item)

        out: list[dict] = []

        include_long = long_trades >= AiTab.MIN_TRADES_TO_OPTIMIZE
        include_short = short_trades >= AiTab.MIN_TRADES_TO_OPTIMIZE

        if include_long:
            if "bb_period_long" in params:
                p = int(params.get("bb_period_long", 12) or 12)
                add_if_exists("bb_period_long", {"min": max(5, p - 6), "max": p + 10, "step": 1})
            add_if_exists("bb_lookback_long", {"min": 2, "max": 10, "step": 1})
            add_if_exists("bb_slope_long", rng(float(params.get("bb_slope_long", 0.004) or 0.004), 0.6, 0.0005))
            add_if_exists("bb_min_width_long", rng(float(params.get("bb_min_width_long", 0.01) or 0.01), 0.7, 0.001))
            add_if_exists("limit_long", rng(float(params.get("limit_long", 0.1) or 0.1), 0.8, 0.02))
            add_if_exists("tp_long", rng(float(params.get("tp_long", 1.0) or 1.0), 0.6, 0.1))
            add_if_exists("sl_long", rng(float(params.get("sl_long", 0.25) or 0.25), 0.8, 0.05))
            add_if_exists("sar_long", rng(float(params.get("sar_long", 3.0) or 3.0), 0.6, 0.25))

        if include_short:
            if "bb_period_short" in params:
                p = int(params.get("bb_period_short", 12) or 12)
                add_if_exists("bb_period_short", {"min": max(5, p - 6), "max": p + 10, "step": 1})
            add_if_exists("bb_lookback_short", {"min": 2, "max": 10, "step": 1})
            add_if_exists("bb_slope_short", rng(float(params.get("bb_slope_short", 0.004) or 0.004), 0.6, 0.0005))
            add_if_exists("bb_min_width_short", rng(float(params.get("bb_min_width_short", 0.01) or 0.01), 0.7, 0.001))
            add_if_exists("limit_short", rng(float(params.get("limit_short", 0.1) or 0.1), 0.8, 0.02))
            add_if_exists("tp_short", rng(float(params.get("tp_short", 1.0) or 1.0), 0.6, 0.1))
            add_if_exists("sl_short", rng(float(params.get("sl_short", 1.0) or 1.0), 0.8, 0.05))
            add_if_exists("sar_short", rng(float(params.get("sar_short", 3.0) or 3.0), 0.6, 0.25))

        if "Choppy" in regime:
            for item in out:
                if item["name"] in ("bb_slope_long", "bb_slope_short"):
                    item["hint"] = "Choppy regime: try higher slope threshold to reduce false breakouts."
                if item["name"] in ("bb_min_width_long", "bb_min_width_short"):
                    item["hint"] = "Choppy regime: try higher min width to avoid tight-band noise."

        return out

    @staticmethod
    def _get_strategy_info_for_run(run: dict, params: dict) -> tuple[dict, str]:
        """
        Priority:
          1) run["strategy_info"]  (attached by ParamsTab from runner)
          2) app_state.strategy_info (if someone put it globally)
          3) inferred from params

        Returns: (strategy_info_dict, source_label)
        """
        if isinstance(run, dict):
            si = run.get("strategy_info", None)
            if isinstance(si, dict) and si:
                return si, "run.strategy_info"

        si2 = getattr(app_state, "strategy_info", None)
        if isinstance(si2, dict) and si2:
            return si2, "app_state.strategy_info"

        return build_strategy_info_from_params(params), "inferred_from_params"

    @staticmethod
    def _build_optimizer_payload(meta: dict, params: dict, stats_all: dict, stats_long: dict, stats_short: dict,
                                 regime: str, objective: dict, plan: list[dict], strategy_info: dict) -> dict:
        return {
            "source": "ai_agent",
            "history_path": meta.get("history_path"),
            "regime": regime,
            "strategy_info": strategy_info,
            "objective": objective,
            "current_params_snapshot": params,
            "stats_snapshot": {"all": stats_all, "long": stats_long, "short": stats_short},
            "suggested_optimization_plan": plan,
            "notes": [
                "Optimizer not implemented yet. This payload is prepared for future Optimizer tab.",
                "Use MaxDD constraint + min trades constraint to avoid overfit.",
            ],
        }

    # ---------------- UI action ----------------

    def on_analyze_last_run(self):
        last = getattr(app_state, "last_run", None)
        if not last:
            messagebox.showerror("AI agent", "Nėra 'last run'. Pirma paleisk backtestą (Parameters -> Run backtest).")
            return

        last_match = getattr(app_state, "last_match", None)

        meta = last.get("meta", {}) or {}
        params = last.get("params", {}) or {}
        stats_all = last.get("stats_all", {}) or {}
        stats_long = last.get("stats_long", {}) or {}
        stats_short = last.get("stats_short", {}) or {}
        trades_log = last.get("trades_log", []) or []

        pnls = self._extract_pnls(trades_log)
        st = self._streaks(pnls)

        avg_pnl = mean(pnls) if pnls else 0.0
        med_pnl = median(pnls) if pnls else 0.0
        vol = pstdev(pnls) if len(pnls) >= 2 else 0.0
        downside = self._downside_deviation(pnls)
        best = self._largest_winning_trade(pnls)
        worst = self._largest_losing_trade(pnls)

        regime = self._regime_guess(stats_all, stats_long, stats_short)
        obj = self._recommend_objective(stats_all)

        long_trades = int(stats_long.get("trades", 0) or 0)
        short_trades = int(stats_short.get("trades", 0) or 0)

        plan = self._recommend_params(params, regime, long_trades=long_trades, short_trades=short_trades)

        initial, _final = self._pick_meta_balance(meta)
        ret_all = self._return_pct_from_meta(meta)

        long_pnl = self._safe_float(stats_long.get("total_pnl"), None)
        short_pnl = self._safe_float(stats_short.get("total_pnl"), None)
        ret_long = self._return_pct_from_pnl(long_pnl, initial) if long_trades > 0 else None
        ret_short = self._return_pct_from_pnl(short_pnl, initial) if short_trades > 0 else None

        strategy_info, strategy_source = self._get_strategy_info_for_run(last, params)

        payload = self._build_optimizer_payload(
            meta=meta,
            params=params,
            stats_all=stats_all,
            stats_long=stats_long,
            stats_short=stats_short,
            regime=regime,
            objective=obj,
            plan=plan,
            strategy_info=strategy_info,
        )
        try:
            app_state.ai_last_payload = payload
        except Exception:
            pass

        # --------- render report ---------
        self.text.delete("1.0", tk.END)

        self.text.insert(tk.END, "AI AGENT REPORT (MVP)\n")
        self.text.insert(tk.END, "=" * 90 + "\n\n")

        self.text.insert(tk.END, "Context\n")
        self.text.insert(tk.END, "-" * 90 + "\n")
        self.text.insert(
            tk.END,
            f"History file: {meta.get('history_path')}\n"
            f"Initial: {meta.get('initial')}\n"
            f"Final:   {meta.get('final_balance')}\n"
            f"Enable LONG: {params.get('enable_long')} | Enable SHORT: {params.get('enable_short')}\n"
            f"Stake: {params.get('stake')} | Total deposit: {params.get('total_deposit')}\n\n"
        )

        self.text.insert(tk.END, "Robot logic (strategy_info)\n")
        self.text.insert(tk.END, "-" * 90 + "\n")
        self.text.insert(tk.END, f"StrategyInfo source: {strategy_source}\n")
        self.text.insert(tk.END, f"Name: {strategy_info.get('name')} | Version: {strategy_info.get('version')}\n")
        self.text.insert(tk.END, f"Indicators: {', '.join(strategy_info.get('indicators', []) or [])}\n\n")

        def _print_list(title: str, items: list[str]):
            self.text.insert(tk.END, f"{title}:\n")
            if not items:
                self.text.insert(tk.END, "  (none)\n")
            else:
                for x in items:
                    self.text.insert(tk.END, f"  - {x}\n")

        _print_list("Entry rules", strategy_info.get("entry_rules", []) or [])
        _print_list("Filters", strategy_info.get("filters", []) or [])
        _print_list("Exits", strategy_info.get("exits", []) or [])
        _print_list("Risk", strategy_info.get("risk", []) or [])
        _print_list("Notes", strategy_info.get("notes", []) or [])
        self.text.insert(tk.END, "\n")

        self.text.insert(tk.END, "Headline metrics\n")
        self.text.insert(tk.END, "-" * 90 + "\n")
        self.text.insert(
            tk.END,
            f"ALL:   Trades={stats_all.get('trades')} | Return%={self._fmt_pct(ret_all)} | PF={stats_all.get('profit_factor')} | "
            f"WinRate%={stats_all.get('win_rate')} | MaxDD%={stats_all.get('max_drawdown')}\n"
            f"LONG:  Trades={stats_long.get('trades')} | Return%={self._fmt_pct(ret_long)} | PF={stats_long.get('profit_factor')} | "
            f"WinRate%={stats_long.get('win_rate')} | MaxDD%={stats_long.get('max_drawdown')}\n"
            f"SHORT: Trades={stats_short.get('trades')} | Return%={self._fmt_pct(ret_short)} | PF={stats_short.get('profit_factor')} | "
            f"WinRate%={stats_short.get('win_rate')} | MaxDD%={stats_short.get('max_drawdown')}\n\n"
        )

        # ----- MATCH compare -----
        self.text.insert(tk.END, "Match section (snapshot)\n")
        self.text.insert(tk.END, "-" * 90 + "\n")
        if not last_match:
            self.text.insert(tk.END, "No MATCH snapshot found (app_state.last_match is empty).\n")
            self.text.insert(tk.END, "Action: Math tab -> click 'Set MATCH from last run'.\n\n")
        else:
            mm = last_match.get("meta", {}) or {}
            ms_all = last_match.get("stats_all", {}) or {}
            ms_long = last_match.get("stats_long", {}) or {}
            ms_short = last_match.get("stats_short", {}) or {}

            m_ret = self._return_pct_from_meta(mm)

            # deltas
            def sf(d, k, default=0.0):
                v = d.get(k, default)
                try:
                    return float(v)
                except Exception:
                    return float(default)

            last_pf = sf(stats_all, "profit_factor", 0.0)
            match_pf = sf(ms_all, "profit_factor", 0.0)
            last_dd = sf(stats_all, "max_drawdown", 0.0)
            match_dd = sf(ms_all, "max_drawdown", 0.0)
            last_tr = sf(stats_all, "trades", 0.0)
            match_tr = sf(ms_all, "trades", 0.0)

            self.text.insert(
                tk.END,
                "MATCH is a stored snapshot (set from Math tab).\n"
                f"Match file: {mm.get('history_path')}\n"
                f"MATCH Return%: {self._fmt_pct(m_ret)} | PF={ms_all.get('profit_factor')} | Trades={ms_all.get('trades')} | MaxDD%={ms_all.get('max_drawdown')}\n"
                f"MATCH LONG: Trades={ms_long.get('trades')} PF={ms_long.get('profit_factor')} WinRate%={ms_long.get('win_rate')}\n"
                f"MATCH SHORT: Trades={ms_short.get('trades')} PF={ms_short.get('profit_factor')} WinRate%={ms_short.get('win_rate')}\n\n"
            )

            # delta summary
            self.text.insert(tk.END, "LAST vs MATCH delta (LAST - MATCH)\n")
            self.text.insert(tk.END, f"Δ PF: {last_pf - match_pf:+.3f}\n")
            self.text.insert(tk.END, f"Δ Trades: {int(last_tr - match_tr):+d}\n")
            self.text.insert(tk.END, f"Δ MaxDD%: {last_dd - match_dd:+.2f}\n")
            if ret_all is not None and m_ret is not None:
                self.text.insert(tk.END, f"Δ Return%: {ret_all - m_ret:+.2f}\n")
            self.text.insert(tk.END, "\n")

        self.text.insert(tk.END, "Regime hypothesis\n")
        self.text.insert(tk.END, "-" * 90 + "\n")
        self.text.insert(tk.END, f"{regime}\n\n")

        self.text.insert(tk.END, "Trade distribution diagnostics\n")
        self.text.insert(tk.END, "-" * 90 + "\n")
        self.text.insert(
            tk.END,
            f"Avg PnL/trade: {avg_pnl:.4f}\n"
            f"Median PnL:    {med_pnl:.4f}\n"
            f"StdDev PnL:    {vol:.4f}\n"
            f"Downside dev:  {downside:.4f}\n"
            f"Best trade:    {best:.4f}\n"
            f"Worst trade:   {worst:.4f}\n"
            f"Max win streak:  {st['max_win_streak']}\n"
            f"Max loss streak: {st['max_loss_streak']}\n\n"
        )

        self.text.insert(tk.END, "Main diagnostics (what to watch)\n")
        self.text.insert(tk.END, "-" * 90 + "\n")

        maxdd = self._safe_float(stats_all.get("max_drawdown"), 0.0) or 0.0
        pf = self._safe_float(stats_all.get("profit_factor"), 0.0) or 0.0
        trades = self._safe_int(stats_all.get("trades", 0), 0)

        diag = []

        # strategy_info sanity
        if strategy_source != "run.strategy_info":
            diag.append("• StrategyInfo is not coming from runner snapshot -> check ParamsTab prints 'Strategy info: OK' after backtest.")

        if maxdd >= 25:
            diag.append("• Drawdown is high -> focus on SL/exit tuning + filtering low-quality entries.")
        if trades < 20:
            diag.append("• Too few trades -> overfit risk. Use longer period / different dataset / smaller timeframe.")
        if trades >= 80 and pf < 1.3:
            diag.append("• Overtrading suspected (many trades, weak PF). Strengthen filters (BB slope/width) or tighten entry rules.")
        if pf < 1.3:
            diag.append("• PF is weak -> likely regime mismatch or entries too loose. Tighten filters or adjust limit offsets.")
        if pnls and abs(worst) > 2.5 * max(1e-9, abs(avg_pnl)):
            diag.append("• Tail-risk: worst trade very large vs avg trade -> consider tighter SL or max adverse move logic.")

        if bool(params.get("enable_long")) and long_trades == 0:
            diag.append("• LONG enabled but has 0 trades -> do NOT optimize LONG params yet. Ensure triggers exist.")
        if bool(params.get("enable_short")) and short_trades == 0:
            diag.append("• SHORT enabled but has 0 trades -> do NOT optimize SHORT params yet. Ensure triggers exist.")

        if long_trades < self.MIN_TRADES_TO_OPTIMIZE and bool(params.get("enable_long")) and long_trades > 0:
            diag.append(f"• LONG has only {long_trades} trades -> too small sample to optimize (need >= {self.MIN_TRADES_TO_OPTIMIZE}).")
        if short_trades < self.MIN_TRADES_TO_OPTIMIZE and bool(params.get("enable_short")) and short_trades > 0:
            diag.append(f"• SHORT has only {short_trades} trades -> too small sample to optimize (need >= {self.MIN_TRADES_TO_OPTIMIZE}).")

        if max(long_trades, short_trades) >= 15 and min(long_trades, short_trades) <= 3:
            diag.append("• Strong LONG/SHORT activity imbalance -> logic is asymmetric (ok if by design, verify).")

        if not diag:
            diag.append("• No obvious red flags. Next: controlled optimization with MaxDD constraint and min trades constraint.")

        self.text.insert(tk.END, "\n".join(diag) + "\n\n")

        self.text.insert(tk.END, "Optimization objective (recommended)\n")
        self.text.insert(tk.END, "-" * 90 + "\n")
        self.text.insert(
            tk.END,
            f"Objective:  {obj['objective']}\n"
            f"Constraint: {obj['constraint']}\n"
            f"Secondary:  {obj['secondary']}\n\n"
        )

        self.text.insert(tk.END, "Suggested optimization parameters (starter plan)\n")
        self.text.insert(tk.END, "-" * 90 + "\n")

        if not plan:
            self.text.insert(
                tk.END,
                "No optimization parameters suggested.\n"
                "Reason: both sides have too few trades OR relevant params do not exist.\n"
                "Action: run dataset/regime where that side trades OR enable only the trading side.\n\n"
            )
        else:
            for item in plan:
                r = item["range"]
                self.text.insert(tk.END, f"- {item['name']}: {r['min']} .. {r['max']} (step {r['step']})\n")
                if "hint" in item:
                    self.text.insert(tk.END, f"    hint: {item['hint']}\n")
            self.text.insert(tk.END, "\n")

        self.text.insert(tk.END, "Optimizer payload (stored)\n")
        self.text.insert(tk.END, "-" * 90 + "\n")
        self.text.insert(
            tk.END,
            "Saved to app_state.ai_last_payload.\n"
            "Future Optimizer tab will read this and auto-fill ranges/objectives.\n"
        )
