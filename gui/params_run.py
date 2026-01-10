# gui/params_run.py
from __future__ import annotations

import threading
import logging
import tkinter as tk
from tkinter import messagebox, filedialog

from bot.runner import TradingBot

from bot.modes.backtest_runner import BacktestRunner
from bot.modes.testnet_runner import TestnetRunner
from bot.modes.live_runner import LiveRunner

from bot.exchange.factory import create_exchange  # ✅ exchange factory (OKX/BYBIT)

from stats_utils import calc_stats
from .app_state import app_state

# ✅ DB storage (SQLite now, Postgres later)
from storage.sqlite_store import SQLiteStore

logger = logging.getLogger("gui.params")

# ✅ one shared store instance (same DB as before)
_store = SQLiteStore(db_path="data/tradingbot.db")


class ParamsRunMixin:
    """
    RUN logika + report + chart navigation.
    Host class privalo turėti:
    - UI widgets: var_mode, entry_history, entry_total_deposit, entry_stake,
      entry_* param fields, var_enable_long/short, text_output
    - buttons: btn_run, btn_save, btn_chart, mode_menu, history buttons
    - method: _apply_mode_ui()
    - tabs: results_tab, chart_tab, trades_tab, equity_tab
    - parent notebook: self.parent (kad select'int chart tab)

    Papildomai (jei yra ParamsForm):
    - var_paper_inst (OKX instId, pvz BTC-USDT)
    - var_paper_bar  (timeframe, pvz 1m/5m/1H)
    """

    # ---------------- helpers ----------------

    def _set_running(self, running: bool):
        self._is_running = running
        state = "disabled" if running else "normal"

        self.btn_run.config(state=state)
        self.btn_save.config(state=state)
        self.btn_chart.config(state=state)

        self.mode_menu.config(state=state)

        # history controls enable/disable depends on mode, so apply again
        if running:
            self.entry_history.config(state="disabled")
            self.btn_browse.config(state="disabled")
            self.btn_merge.config(state="disabled")
            self.btn_dl_binance.config(state="disabled")
            self.btn_dl_bybit.config(state="disabled")
        else:
            self._apply_mode_ui()

        self.btn_run.config(text="Running..." if running else "Run")

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
    def _pick_equity_series(bot):
        for attr in ("equity_curve", "equity", "balance_curve", "balance_series", "equity_series"):
            v = getattr(bot, attr, None)
            if isinstance(v, (list, tuple)) and len(v) > 0:
                return list(v), attr
        return None, None

    @staticmethod
    def _get_bot_strategy_info(bot) -> dict:
        try:
            if bot is None:
                return {}
            if hasattr(bot, "get_strategy_info"):
                v = bot.get_strategy_info()
                return v if isinstance(v, dict) else {}
            v = getattr(bot, "strategy_info", None)
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _safe_get_var_str(host, attr_name: str, default: str) -> str:
        """
        Saugi pagalba: jei UI turi pvz self.var_paper_inst (StringVar),
        paimam .get(), kitaip gražinam default.
        """
        try:
            v = getattr(host, attr_name, None)
            if v is None:
                return default
            if hasattr(v, "get"):
                s = (v.get() or "").strip()
                return s or default
            s = str(v).strip()
            return s or default
        except Exception:
            return default

    def _save_run_to_db_async(self, run_payload: dict):
        def worker():
            try:
                run_id = _store.save_run(run_payload, tag="manual")
                logger.info("Saved run to DB | run_id=%s", run_id)

                def ui_update():
                    try:
                        if isinstance(app_state.last_run, dict):
                            app_state.last_run["run_id"] = run_id
                    except Exception:
                        pass
                    try:
                        self.text_output.insert(tk.END, f"DB saved: run_id={run_id}\n")
                    except Exception:
                        pass

                self.frame.after(0, ui_update)

            except Exception as e:
                logger.exception("DB save failed: %s", e)

                def ui_warn():
                    try:
                        self.text_output.insert(tk.END, f"⚠️ DB save failed: {e}\n")
                    except Exception:
                        pass

                self.frame.after(0, ui_warn)

        threading.Thread(target=worker, daemon=True).start()

    # ---------------- Run entrypoint ----------------

    def on_run(self):
        if getattr(self, "_is_running", False):
            return

        mode = (self.var_mode.get() or "BACKTEST").strip().upper()
        if mode not in ("BACKTEST", "TESTNET", "LIVE"):
            mode = "BACKTEST"
        try:
            app_state.mode = mode
        except Exception:
            pass

        history_path = self.entry_history.get().strip()

        # ✅ history required ONLY for BACKTEST
        if mode == "BACKTEST" and not history_path:
            messagebox.showerror("Klaida", "Pasirinkite istorijos failą (BACKTEST režime).")
            return

        # ✅ instrument/timeframe (bendrai TESTNET ir LIVE)
        paper_inst_id = self._safe_get_var_str(self, "var_paper_inst", "BTC-USDT")
        paper_bar = self._safe_get_var_str(self, "var_paper_bar", "1m")

        try:
            total_deposit = float(self.entry_total_deposit.get())
            stake = float(self.entry_stake.get())

            tp_long = float(self.entry_tp_long.get())
            sl_long = float(self.entry_sl_long.get())
            sar_long = float(self.entry_sar_long.get())
            limit_long = float(self.entry_limit_long.get())
            bb_period_long = int(float(self.entry_bb_period_long.get()))
            bb_lookback_long = int(float(self.entry_bb_lookback_long.get()))
            bb_slope_long = float(self.entry_bb_slope_long.get())
            bb_min_width_long = float(self.entry_bb_min_width_long.get())
            bb_channel_pos_long = float(self.entry_bb_channel_pos_long.get())

            tp_short = float(self.entry_tp_short.get())
            sl_short = float(self.entry_sl_short.get())
            sar_short = float(self.entry_sar_short.get())
            limit_short = float(self.entry_limit_short.get())
            bb_period_short = int(float(self.entry_bb_period_short.get()))
            bb_lookback_short = int(float(self.entry_bb_lookback_short.get()))
            bb_slope_short = float(self.entry_bb_slope_short.get())
            bb_min_width_short = float(self.entry_bb_min_width_short.get())
            bb_channel_pos_short = float(self.entry_bb_channel_pos_short.get())
        except ValueError:
            messagebox.showerror("Klaida", "Neteisingi skaičiai laukeliuose (depozitas/stake/parametrai).")
            return

        enable_long_flag = bool(self.var_enable_long.get())
        enable_short_flag = bool(self.var_enable_short.get())

        self._set_running(True)
        self.text_output.delete("1.0", tk.END)
        self.text_output.insert(tk.END, f"Running... mode={mode}\n")

        params = {
            "mode": mode,
            "history_path": history_path,  # may be "" in TESTNET/LIVE
            "total_deposit": total_deposit,
            "stake": stake,
            "enable_long": enable_long_flag,
            "enable_short": enable_short_flag,

            # ✅ shared instrument/timeframe for TESTNET + LIVE
            "paper_inst_id": paper_inst_id,
            "paper_bar": paper_bar,

            "tp_long": tp_long,
            "sl_long": sl_long,
            "sar_long": sar_long,
            "limit_long": limit_long,
            "bb_period_long": bb_period_long,
            "bb_lookback_long": bb_lookback_long,
            "bb_slope_long": bb_slope_long,
            "bb_min_width_long": bb_min_width_long,
            "bb_channel_pos_long": bb_channel_pos_long,

            "tp_short": tp_short,
            "sl_short": sl_short,
            "sar_short": sar_short,
            "limit_short": limit_short,
            "bb_period_short": bb_period_short,
            "bb_lookback_short": bb_lookback_short,
            "bb_slope_short": bb_slope_short,
            "bb_min_width_short": bb_min_width_short,
            "bb_channel_pos_short": bb_channel_pos_short,
        }

        logger.info(
            "Starting run thread | mode=%s | history=%s | inst=%s | bar=%s",
            mode,
            history_path,
            paper_inst_id,
            paper_bar,
        )

        t = threading.Thread(target=self._run_worker, args=(params,), daemon=True)
        t.start()

    def _run_worker(self, params: dict):
        try:
            bot = TradingBot(
                initial_balance=params["total_deposit"],
                trade_stake=params["stake"],
                enable_long=params["enable_long"],
                enable_short=params["enable_short"],

                tp_atr_mult_long=params["tp_long"],
                sl_atr_mult_long=params["sl_long"],
                limit_offset_pct_long=params["limit_long"],
                bb_period_long=params["bb_period_long"],
                bb_lookback_long=params["bb_lookback_long"],
                bb_slope_pct_long=params["bb_slope_long"],
                bb_min_width_pct_long=params["bb_min_width_long"],
                bb_channel_pos_long=params["bb_channel_pos_long"],
                max_sar_profit_atr_long=params["sar_long"],

                tp_atr_mult_short=params["tp_short"],
                sl_atr_mult_short=params["sl_short"],
                limit_offset_pct_short=params["limit_short"],
                bb_period_short=params["bb_period_short"],
                bb_lookback_short=params["bb_lookback_short"],
                bb_slope_pct_short=params["bb_slope_short"],
                bb_min_width_pct_short=params["bb_min_width_short"],
                bb_channel_pos_short=params["bb_channel_pos_short"],
                max_sar_profit_atr_short=params["sar_short"],
            )

            # ✅ store selected instrument/timeframe on bot (kad runneriai galėtų pasiimti be signature keitimų)
            try:
                bot.paper_inst_id = params.get("paper_inst_id")
                bot.paper_bar = params.get("paper_bar")
            except Exception:
                pass

            mode = params.get("mode", "BACKTEST")

            result_obj = None
            final_balance = None

            if mode == "BACKTEST":
                runner = BacktestRunner(bot, params["history_path"])
                result_obj = runner.run()

            elif mode == "TESTNET":
                # ✅ TESTNET/PAPER: perduodam inst/bar jei runneris priima (jei nepriima — fallback į bot.paper_*).
                try:
                    runner = TestnetRunner(bot, inst_id=params.get("paper_inst_id"), bar=params.get("paper_bar"))
                except TypeError:
                    runner = TestnetRunner(bot)
                result_obj = runner.run()

            else:
                # ✅ LIVE: exchange adapter + tas pats inst/bar (ateityje LiveRunner naudos)
                exchange = create_exchange()
                try:
                    runner = LiveRunner(bot, exchange, inst_id=params.get("paper_inst_id"), bar=params.get("paper_bar"))
                except TypeError:
                    runner = LiveRunner(bot, exchange)
                result_obj = runner.run()

            trades_log = getattr(bot, "trades_log", []) or []
            strategy_info = self._get_bot_strategy_info(bot)

            stub_message = None
            if isinstance(result_obj, tuple) and len(result_obj) >= 2:
                _trades_pnl_list, final_balance = result_obj[0], result_obj[1]
            elif isinstance(result_obj, dict):
                stub_message = str(result_obj.get("message") or "")
                final_balance = result_obj.get("final_balance", None)
            else:
                final_balance = None

            if final_balance is None:
                try:
                    final_balance = bot.get_equity_now() if hasattr(bot, "get_equity_now") else float(params["total_deposit"])
                except Exception:
                    final_balance = float(params["total_deposit"])

            pnls_all = self._extract_pnls(trades_log)
            longs = [t for t in trades_log if str(t.get("side", "")).upper() == "LONG"]
            shorts = [t for t in trades_log if str(t.get("side", "")).upper() == "SHORT"]
            pnls_long = self._extract_pnls(longs)
            pnls_short = self._extract_pnls(shorts)

            stats_all = calc_stats(pnls_all, params["total_deposit"])
            stats_long = calc_stats(pnls_long, params["total_deposit"]) if pnls_long else calc_stats([], params["total_deposit"])
            stats_short = calc_stats(pnls_short, params["total_deposit"]) if pnls_short else calc_stats([], params["total_deposit"])

            equity_curve, equity_attr = self._pick_equity_series(bot)
            equity_times = getattr(bot, "equity_times", None) or getattr(bot, "equity_timestamps", None)

            meta = {
                "mode": mode,
                "history_path": params.get("history_path", ""),
                "initial": params["total_deposit"],
                "final_balance": final_balance,
                "stake": params["stake"],
                "enable_long": params["enable_long"],
                "enable_short": params["enable_short"],

                # ✅ show instrument/timeframe also in meta
                "inst_id": params.get("paper_inst_id"),
                "bar": params.get("paper_bar"),
            }

            # ✅ include exchange info in meta if LIVE dict has it
            try:
                if isinstance(result_obj, dict) and mode == "LIVE":
                    if result_obj.get("exchange"):
                        meta["exchange"] = result_obj.get("exchange")
            except Exception:
                pass

            extra = {"runner_result": result_obj, "stub_message": stub_message}

            self.frame.after(
                0,
                lambda: self._on_run_success(
                    bot=bot,
                    trades_log=trades_log,
                    longs=longs,
                    shorts=shorts,
                    meta=meta,
                    stats_all=stats_all,
                    stats_long=stats_long,
                    stats_short=stats_short,
                    final_balance=final_balance,
                    params=params,
                    equity_curve=equity_curve,
                    equity_attr=equity_attr,
                    equity_times=equity_times,
                    strategy_info=strategy_info,
                    extra=extra,
                ),
            )

        except Exception as e:
            logger.exception("Run worker failed")
            self.frame.after(0, lambda: self._on_run_error(e))

    def _on_run_success(
        self,
        bot,
        trades_log,
        longs,
        shorts,
        meta,
        stats_all,
        stats_long,
        stats_short,
        final_balance,
        params,
        equity_curve=None,
        equity_attr=None,
        equity_times=None,
        strategy_info=None,
        extra=None,
    ):
        strategy_info = strategy_info or {}
        extra = extra or {}

        if getattr(self, "results_tab", None) is not None and hasattr(self.results_tab, "update_results"):
            self.results_tab.update_results(meta, stats_all, stats_long, stats_short, None)

        if getattr(self, "trades_tab", None) is not None and hasattr(self.trades_tab, "update_trades"):
            self.trades_tab.update_trades(trades_log)

        if getattr(self, "chart_tab", None) is not None and hasattr(self.chart_tab, "set_bot"):
            try:
                self.chart_tab.set_bot(bot)
            except Exception:
                pass

        if getattr(self, "equity_tab", None) is not None and hasattr(self.equity_tab, "set_bot"):
            try:
                self.equity_tab.set_bot(bot)
            except Exception:
                pass

        try:
            app_state.strategy_info = strategy_info
        except Exception:
            pass

        mode = params.get("mode", "BACKTEST")
        stub_message = (extra.get("stub_message") or "").strip()

        self.text_output.delete("1.0", tk.END)

        inst_id = (params.get("paper_inst_id") or "").strip()
        bar = (params.get("paper_bar") or "").strip()

        self.text_output.insert(
            tk.END,
            f"Mode:   {mode}\n"
            f"Failas: {params.get('history_path','')}\n"
            f"Inst:   {inst_id}\n"
            f"TF:     {bar}\n"
            f"Initial: {params['total_deposit']:.2f}\n"
            f"Final:   {float(final_balance):.2f}\n"
            f"Trades:  {len(trades_log)} (LONG {len(longs)} / SHORT {len(shorts)})\n"
            f"Net PnL: {stats_all['total_pnl']:.2f}\n"
            f"WinRate: {stats_all['win_rate']:.2f}%\n"
            f"PF:      {stats_all['profit_factor']:.2f}\n"
            f"MaxDD:   {stats_all['max_drawdown']:.2f}\n"
        )

        if equity_curve:
            self.text_output.insert(tk.END, f"Equity curve: {len(equity_curve)} pts ({equity_attr})\n")

        if isinstance(strategy_info, dict) and strategy_info:
            self.text_output.insert(tk.END, f"Strategy info: OK ({strategy_info.get('name', 'n/a')})\n")
        else:
            self.text_output.insert(tk.END, "Strategy info: (empty)\n")

        if mode in ("TESTNET", "LIVE") and stub_message:
            self.text_output.insert(tk.END, "\n---\n" + stub_message + "\n")

        app_state.last_run = {
            "meta": meta,
            "params": params,
            "stats_all": stats_all,
            "stats_long": stats_long,
            "stats_short": stats_short,
            "trades_log": trades_log,
            "chart_events": getattr(bot, "chart_events", None),
            "equity_curve": equity_curve,
            "equity_times": equity_times,
            "equity_attr": equity_attr,
            "strategy_info": strategy_info,
            "runner_result": extra.get("runner_result"),
        }

        self._save_run_to_db_async(app_state.last_run)

        self.last_bot = bot
        self.last_history_path = params.get("history_path", "")
        self.last_total_deposit = params["total_deposit"]
        self.last_stake = params["stake"]
        self.last_enable_long = params["enable_long"]
        self.last_enable_short = params["enable_short"]

        self._set_running(False)
        logger.info("Run UI updated successfully + last_run saved (+ DB save scheduled)")

    def _on_run_error(self, e: Exception):
        self._set_running(False)
        messagebox.showerror("Klaida", f"Nepavyko paleisti:\n{e}")

    # ---------------- Report + Chart ----------------

    def on_save_report(self):
        content = self.text_output.get("1.0", tk.END).strip()
        if not content:
            messagebox.showerror("Klaida", "Nėra ką išsaugoti – raportas tuščias.")
            return

        path = filedialog.asksaveasfilename(
            title="Kur išsaugoti raportą",
            defaultextension=".txt",
            filetypes=[("TXT files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            messagebox.showerror("Klaida", f"Nepavyko išsaugoti:\n{e}")
            return

        messagebox.showinfo("OK", f"Raportas išsaugotas:\n{path}")

    def on_show_chart(self):
        if self.last_bot is None:
            messagebox.showerror("Klaida", "Pirma paleisk backtestą.")
            return
        if self.chart_tab is None:
            messagebox.showerror("Klaida", "Chart tab nėra prijungtas (chart_tab=None).")
            return
        try:
            if hasattr(self.chart_tab, "set_bot"):
                self.chart_tab.set_bot(self.last_bot)
            self.parent.select(self.chart_tab.frame)
        except Exception:
            pass
