# gui/optimizer_tab.py
from __future__ import annotations

import threading
import time
import random
import inspect
import tkinter as tk
from tkinter import ttk, messagebox

from .app_state import app_state


class OptimizerTab:
    """
    Optimizer TAB (MVP)
    - Reads suggested optimization plan from app_state.ai_last_payload (AI tab prepares it)
    - Runs RANDOM search (fast MVP)
    - Shows results table
    - Uses robust backtest adapter:
        1) Try bot.modes.backtest_runner.BacktestRunner if exists
        2) Else try bot.runner.TradingBot with signature-adaptive kwargs
    """

    def __init__(self, parent):
        self.frame = tk.Frame(parent)

        self._is_running = False
        self._worker_thread: threading.Thread | None = None

        self._build_ui()

    # ---------------- UI ----------------

    def _build_ui(self):
        root = self.frame

        top = tk.Frame(root)
        top.pack(fill="x", padx=8, pady=8)

        tk.Label(top, text="Optimizer (MVP)", font=("Arial", 11, "bold")).pack(side="left")

        self.btn_load = tk.Button(top, text="Load plan from AI", command=self.on_load_plan)
        self.btn_load.pack(side="right", padx=(6, 0))

        self.btn_run = tk.Button(top, text="Run RANDOM", command=self.on_run_random)
        self.btn_run.pack(side="right", padx=(6, 0))

        self.btn_stop = tk.Button(top, text="Stop", command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="right")

        # Controls
        ctrl = tk.Frame(root)
        ctrl.pack(fill="x", padx=8, pady=(0, 8))

        tk.Label(ctrl, text="Runs:").pack(side="left")
        self.entry_runs = tk.Entry(ctrl, width=8)
        self.entry_runs.insert(0, "50")
        self.entry_runs.pack(side="left", padx=(4, 12))

        tk.Label(ctrl, text="Seed:").pack(side="left")
        self.entry_seed = tk.Entry(ctrl, width=8)
        self.entry_seed.insert(0, "1")
        self.entry_seed.pack(side="left", padx=(4, 12))

        self.var_use_ai_plan = tk.BooleanVar(value=True)
        tk.Checkbutton(ctrl, text="Use AI suggested plan", variable=self.var_use_ai_plan).pack(side="left")

        # Plan table (params list)
        plan_frame = tk.LabelFrame(root, text="Optimization plan (editable)")
        plan_frame.pack(fill="x", padx=8, pady=(0, 8))

        self.plan_tree = ttk.Treeview(
            plan_frame,
            columns=("name", "min", "max", "step"),
            show="headings",
            height=6,
        )
        for col, w in (("name", 220), ("min", 120), ("max", 120), ("step", 120)):
            self.plan_tree.heading(col, text=col)
            self.plan_tree.column(col, width=w, anchor="w")
        self.plan_tree.pack(side="left", fill="x", expand=True)

        sb = ttk.Scrollbar(plan_frame, orient="vertical", command=self.plan_tree.yview)
        sb.pack(side="right", fill="y")
        self.plan_tree.configure(yscrollcommand=sb.set)

        # Results table
        res_frame = tk.LabelFrame(root, text="Results")
        res_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.res_tree = ttk.Treeview(
            res_frame,
            columns=("rank", "return_pct", "maxdd", "pf", "trades", "winrate", "params"),
            show="headings",
            height=10,
        )
        cols = [
            ("rank", 60),
            ("return_pct", 90),
            ("maxdd", 90),
            ("pf", 90),
            ("trades", 80),
            ("winrate", 90),
            ("params", 600),
        ]
        for c, w in cols:
            self.res_tree.heading(c, text=c)
            self.res_tree.column(c, width=w, anchor="w")
        self.res_tree.pack(side="left", fill="both", expand=True)

        sb2 = ttk.Scrollbar(res_frame, orient="vertical", command=self.res_tree.yview)
        sb2.pack(side="right", fill="y")
        self.res_tree.configure(yscrollcommand=sb2.set)

        # Log
        log_frame = tk.LabelFrame(root, text="Log")
        log_frame.pack(fill="both", expand=False, padx=8, pady=(0, 8))

        self.log = tk.Text(log_frame, height=8, width=140)
        self.log.pack(fill="both", expand=True)

        self._log("Optimizer ready. Click 'Load plan from AI' (optional), then 'Run RANDOM'.")

    # ---------------- utilities ----------------

    def _log(self, msg: str):
        try:
            self.log.insert(tk.END, msg.rstrip() + "\n")
            self.log.see(tk.END)
        except Exception:
            pass

    @staticmethod
    def _safe_int(x, default=0):
        try:
            return int(x)
        except Exception:
            return default

    @staticmethod
    def _safe_float(x, default=None):
        try:
            return float(x)
        except Exception:
            return default

    # ---------------- plan loading ----------------

    def on_load_plan(self):
        payload = getattr(app_state, "ai_last_payload", None)
        if not isinstance(payload, dict):
            messagebox.showerror("Optimizer", "No ai_last_payload found. Go to AI tab -> Analyze last run first.")
            return

        plan = payload.get("suggested_optimization_plan", None)
        if not isinstance(plan, list) or not plan:
            messagebox.showerror("Optimizer", "AI payload has no suggested plan.")
            return

        # Fill plan tree
        for iid in self.plan_tree.get_children():
            self.plan_tree.delete(iid)

        for item in plan:
            try:
                name = str(item.get("name"))
                r = item.get("range", {}) or {}
                vmin = r.get("min")
                vmax = r.get("max")
                step = r.get("step")
                self.plan_tree.insert("", "end", values=(name, vmin, vmax, step))
            except Exception:
                continue

        self._log(f"Loaded {len(plan)} params from AI plan.")

    def _read_plan_from_ui(self) -> list[dict]:
        out: list[dict] = []
        for iid in self.plan_tree.get_children():
            vals = self.plan_tree.item(iid, "values")
            if not vals or len(vals) < 4:
                continue
            name = str(vals[0]).strip()
            vmin = self._safe_float(vals[1], None)
            vmax = self._safe_float(vals[2], None)
            step = self._safe_float(vals[3], None)
            if not name or vmin is None or vmax is None or step is None:
                continue
            if vmax < vmin:
                vmin, vmax = vmax, vmin
            out.append({"name": name, "min": vmin, "max": vmax, "step": step})
        return out

    # ---------------- run control ----------------

    def on_run_random(self):
        if self._is_running:
            return

        last = getattr(app_state, "last_run", None)
        if not isinstance(last, dict):
            messagebox.showerror("Optimizer", "No last_run. Run backtest first (Parameters tab).")
            return

        base_params = (last.get("params", {}) or {}).copy()
        meta = last.get("meta", {}) or {}

        runs = self._safe_int(self.entry_runs.get(), 50)
        runs = max(1, min(5000, runs))

        seed = self._safe_int(self.entry_seed.get(), 1)
        random.seed(seed)

        # Determine plan
        plan: list[dict] = []
        if bool(self.var_use_ai_plan.get()):
            # prefer UI plan if filled, else try AI payload
            plan = self._read_plan_from_ui()
            if not plan:
                payload = getattr(app_state, "ai_last_payload", None)
                if isinstance(payload, dict):
                    raw = payload.get("suggested_optimization_plan", []) or []
                    for item in raw:
                        r = item.get("range", {}) or {}
                        name = str(item.get("name", "")).strip()
                        vmin = self._safe_float(r.get("min"), None)
                        vmax = self._safe_float(r.get("max"), None)
                        step = self._safe_float(r.get("step"), None)
                        if name and vmin is not None and vmax is not None and step is not None:
                            plan.append({"name": name, "min": vmin, "max": vmax, "step": step})

        if not plan:
            messagebox.showerror(
                "Optimizer",
                "No plan loaded.\nUse AI tab -> Analyze last run (creates ai_last_payload), then Optimizer -> Load plan from AI.",
            )
            return

        self._set_running(True)
        self._log(f"Starting RANDOM optimization | runs={runs} | params={len(plan)}")

        self._worker_thread = threading.Thread(
            target=self._random_worker,
            args=(meta, base_params, plan, runs, seed),
            daemon=True,
        )
        self._worker_thread.start()

    def on_stop(self):
        if not self._is_running:
            return
        self._is_running = False
        self._log("Stop requested...")

    def _set_running(self, running: bool):
        self._is_running = running
        self.btn_stop.config(state="normal" if running else "disabled")
        self.btn_run.config(state="disabled" if running else "normal")
        self.btn_load.config(state="disabled" if running else "normal")

    # ---------------- core worker ----------------

    def _random_worker(self, meta: dict, base_params: dict, plan: list[dict], runs: int, seed: int):
        results = []

        for i in range(1, runs + 1):
            if not self._is_running:
                break

            # sample params
            p = base_params.copy()
            for spec in plan:
                name = spec["name"]
                vmin = float(spec["min"])
                vmax = float(spec["max"])
                step = float(spec["step"])
                # discrete grid steps but randomized pick
                steps = int(round((vmax - vmin) / step)) if step > 0 else 0
                if steps <= 0:
                    val = vmin
                else:
                    k = random.randint(0, steps)
                    val = vmin + k * step

                # keep ints where base param is int-like
                if isinstance(p.get(name), int):
                    val = int(round(val))
                p[name] = val

            # ensure critical meta fields remain correct
            # (history_path/initial/stake etc should already be in base_params from last_run)
            try:
                stats_all, stats_long, stats_short, final_balance, trades_log = self._run_backtest_adapter(p)
            except Exception as e:
                self._ui_log(f"[{i}/{runs}] ERROR: {e}")
                continue

            # collect metrics
            ret_pct = self._return_pct(meta, final_balance)
            maxdd = self._safe_float(stats_all.get("max_drawdown"), 0.0) or 0.0
            pf = self._safe_float(stats_all.get("profit_factor"), 0.0) or 0.0
            trades = int(stats_all.get("trades", len(trades_log) if trades_log else 0) or 0)
            winrate = self._safe_float(stats_all.get("win_rate"), 0.0) or 0.0

            results.append(
                {
                    "return_pct": ret_pct,
                    "maxdd": maxdd,
                    "pf": pf,
                    "trades": trades,
                    "winrate": winrate,
                    "params": {k: p.get(k) for k in [s["name"] for s in plan]},
                }
            )

            # UI update occasionally
            if i == 1 or i % 5 == 0:
                self._ui_log(f"[{i}/{runs}] Return={ret_pct:.2f}% PF={pf:.2f} MaxDD={maxdd:.2f}% Trades={trades}")

        # sort: maximize return, then PF, then lower DD
        results.sort(key=lambda x: (x["return_pct"], x["pf"], -x["maxdd"]), reverse=True)

        def finish_ui():
            try:
                for iid in self.res_tree.get_children():
                    self.res_tree.delete(iid)

                for idx, r in enumerate(results[:200], start=1):
                    params_str = ", ".join([f"{k}={r['params'][k]}" for k in r["params"].keys()])
                    self.res_tree.insert(
                        "",
                        "end",
                        values=(
                            idx,
                            f"{r['return_pct']:.2f}",
                            f"{r['maxdd']:.2f}",
                            f"{r['pf']:.2f}",
                            r["trades"],
                            f"{r['winrate']:.2f}",
                            params_str,
                        ),
                    )

                self._log(f"Done. Completed {min(len(results), runs)} runs. Best Return={results[0]['return_pct']:.2f}% PF={results[0]['pf']:.2f} MaxDD={results[0]['maxdd']:.2f}%"
                          if results else "Done. No successful runs.")
            finally:
                self._set_running(False)

        self.frame.after(0, finish_ui)

    def _ui_log(self, msg: str):
        self.frame.after(0, lambda: self._log(msg))

    @staticmethod
    def _return_pct(meta: dict, final_balance: float) -> float:
        initial = None
        for k in ("initial", "initial_balance", "start_balance", "equity_start"):
            try:
                v = float(meta.get(k))
                initial = v
                break
            except Exception:
                continue
        if not initial or initial == 0:
            # fallback: sometimes initial stored in params
            try:
                felt = getattr(app_state, "last_run", {}).get("params", {}).get("total_deposit", None)
                if felt:
                    initial = float(felt)
            except Exception:
                pass
        if not initial or initial == 0:
            return 0.0
        return ((float(final_balance) - float(initial)) / float(initial)) * 100.0

    # ---------------- Backtest adapter ----------------

    def _run_backtest_adapter(self, params: dict):
        """
        Returns: (stats_all, stats_long, stats_short, final_balance, trades_log)

        Priority:
          1) bot.modes.backtest_runner.BacktestRunner
          2) bot.runner.TradingBot (signature-adaptive kwargs)
        """
        # 1) Try BacktestRunner (new architecture)
        try:
            from bot.modes.backtest_runner import BacktestRunner  # type: ignore

            runner = BacktestRunner(**self._filter_kwargs(BacktestRunner, params))
            bot = runner.run() if hasattr(runner, "run") else runner  # some designs return bot
            # common patterns:
            # - runner.run() returns (trades, final_balance)
            # - or sets runner.bot
            if isinstance(bot, tuple) and len(bot) == 2:
                trades_log, final_balance = bot
                stats_all = getattr(runner, "stats_all", {}) or {}
                stats_long = getattr(runner, "stats_long", {}) or {}
                stats_short = getattr(runner, "stats_short", {}) or {}
                return stats_all, stats_long, stats_short, float(final_balance), list(trades_log or [])
            if hasattr(runner, "bot") and runner.bot is not None:
                bot = runner.bot
            if hasattr(bot, "run_backtest"):
                _trades_pnl_list, final_balance = bot.run_backtest()
                trades_log = getattr(bot, "trades_log", []) or []
                # stats may already exist in bot
                stats_all = getattr(bot, "stats_all", {}) or {}
                stats_long = getattr(bot, "stats_long", {}) or {}
                stats_short = getattr(bot, "stats_short", {}) or {}
                return stats_all, stats_long, stats_short, float(final_balance), list(trades_log)
        except Exception:
            # ignore and fallback to TradingBot
            pass

        # 2) TradingBot fallback
        from bot.runner import TradingBot  # type: ignore

        # Try to map the expected init kwargs from params (your ParamsTab already uses these)
        tb_kwargs = self._map_params_to_tradingbot_kwargs(params)
        tb_kwargs = self._filter_kwargs(TradingBot, tb_kwargs)

        bot = TradingBot(**tb_kwargs)

        # Backtest execution
        if hasattr(bot, "run_backtest"):
            _trades_pnl_list, final_balance = bot.run_backtest()
        else:
            # ultra fallback
            raise RuntimeError("TradingBot has no run_backtest(). Wrong class imported for backtesting.")

        trades_log = getattr(bot, "trades_log", []) or []

        # stats may not exist -> infer minimal
        stats_all = getattr(bot, "stats_all", {}) or {}
        stats_long = getattr(bot, "stats_long", {}) or {}
        stats_short = getattr(bot, "stats_short", {}) or {}

        # if no stats present, keep empty dicts (AI/Math tabs compute stats elsewhere)
        return stats_all, stats_long, stats_short, float(final_balance), list(trades_log)

    @staticmethod
    def _filter_kwargs(cls, kwargs: dict) -> dict:
        """Keep only kwargs accepted by cls.__init__."""
        try:
            sig = inspect.signature(cls.__init__)
            accepted = set(sig.parameters.keys())
            accepted.discard("self")
            return {k: v for k, v in kwargs.items() if k in accepted}
        except Exception:
            return kwargs

    @staticmethod
    def _map_params_to_tradingbot_kwargs(p: dict) -> dict:
        """
        Map your GUI params into TradingBot init args.

        Your ParamsTab uses:
          history_path, initial_balance, trade_stake, enable_long, enable_short,
          tp_atr_mult_long, sl_atr_mult_long, limit_offset_pct_long, bb_period_long, ...
        """
        out = {}

        # history path: try several aliases (some bots use history_file/data_path)
        if "history_path" in p:
            out["history_path"] = p["history_path"]
            out["history_file"] = p["history_path"]
            out["data_path"] = p["history_path"]

        # balances/stake
        if "total_deposit" in p:
            out["initial_balance"] = p["total_deposit"]
            out["balance"] = p["total_deposit"]
        if "stake" in p:
            out["trade_stake"] = p["stake"]
            out["stake"] = p["stake"]

        # enable flags
        out["enable_long"] = bool(p.get("enable_long", True))
        out["enable_short"] = bool(p.get("enable_short", True))

        # LONG
        if "tp_long" in p:
            out["tp_atr_mult_long"] = p["tp_long"]
        if "sl_long" in p:
            out["sl_atr_mult_long"] = p["sl_long"]
        if "limit_long" in p:
            out["limit_offset_pct_long"] = p["limit_long"]
        if "bb_period_long" in p:
            out["bb_period_long"] = p["bb_period_long"]
        if "bb_lookback_long" in p:
            out["bb_lookback_long"] = p["bb_lookback_long"]
        if "bb_slope_long" in p:
            out["bb_slope_pct_long"] = p["bb_slope_long"]
        if "bb_min_width_long" in p:
            out["bb_min_width_pct_long"] = p["bb_min_width_long"]
        if "bb_channel_pos_long" in p:
            out["bb_channel_pos_long"] = p["bb_channel_pos_long"]
        if "sar_long" in p:
            out["max_sar_profit_atr_long"] = p["sar_long"]

        # SHORT
        if "tp_short" in p:
            out["tp_atr_mult_short"] = p["tp_short"]
        if "sl_short" in p:
            out["sl_atr_mult_short"] = p["sl_short"]
        if "limit_short" in p:
            out["limit_offset_pct_short"] = p["limit_short"]
        if "bb_period_short" in p:
            out["bb_period_short"] = p["bb_period_short"]
        if "bb_lookback_short" in p:
            out["bb_lookback_short"] = p["bb_lookback_short"]
        if "bb_slope_short" in p:
            out["bb_slope_pct_short"] = p["bb_slope_short"]
        if "bb_min_width_short" in p:
            out["bb_min_width_pct_short"] = p["bb_min_width_short"]
        if "bb_channel_pos_short" in p:
            out["bb_channel_pos_short"] = p["bb_channel_pos_short"]
        if "sar_short" in p:
            out["max_sar_profit_atr_short"] = p["sar_short"]

        return out
