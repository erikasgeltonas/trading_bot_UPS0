# gui/params_form.py
from __future__ import annotations

import threading
import tkinter as tk

import requests

from .app_state import app_state


class ParamsFormMixin:
    """
    Tik UI išdėstymas + mode UI (enable/disable history).
    Host klasė privalo turėti callback'us:
      - on_browse_file, on_merge_files, on_download_btc, on_download_bybit
      - on_show_chart, on_run, on_save_report
    """

    def _build_layout(self):
        root = self.frame

        # ---------------- MODE row ----------------
        tk.Label(root, text="Režimas:").grid(row=0, column=0, padx=5, pady=5, sticky="w")

        initial_mode = (getattr(app_state, "mode", None) or "BACKTEST").strip().upper()
        if initial_mode not in ("BACKTEST", "TESTNET", "LIVE"):
            initial_mode = "BACKTEST"

        self.var_mode = tk.StringVar(value=initial_mode)
        self.mode_menu = tk.OptionMenu(root, self.var_mode, "BACKTEST", "TESTNET", "LIVE", command=self._on_mode_changed)
        self.mode_menu.config(width=12)
        self.mode_menu.grid(row=0, column=1, padx=5, pady=5, sticky="w")

        # ---------------- PAPER feed row (TESTNET) ----------------
        # NOTE: TESTNET pas mus = OKX PAPER (realios žvakės + paper execution programoje)
        tk.Label(root, text="TESTNET feed:").grid(row=0, column=2, padx=5, pady=5, sticky="e")

        # default list (užsikraus net jei OKX refresh dar nedarytas)
        self._paper_inst_list: list[str] = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "NEAR-USDT"]
        self.var_paper_inst = tk.StringVar(value=self._paper_inst_list[0])

        self.paper_inst_menu = tk.OptionMenu(root, self.var_paper_inst, *self._paper_inst_list)
        self.paper_inst_menu.config(width=16)
        self.paper_inst_menu.grid(row=0, column=3, padx=5, pady=5, sticky="w")

        self._paper_bars: list[str] = ["1m", "5m", "15m", "1H", "4H", "1D"]
        self.var_paper_bar = tk.StringVar(value="1m")

        self.paper_bar_menu = tk.OptionMenu(root, self.var_paper_bar, *self._paper_bars)
        self.paper_bar_menu.config(width=6)
        self.paper_bar_menu.grid(row=0, column=4, padx=5, pady=5, sticky="w")

        self.btn_refresh_okx = tk.Button(root, text="Refresh OKX", command=self._refresh_okx_instruments_async)
        self.btn_refresh_okx.grid(row=0, column=5, padx=5, pady=5, sticky="w")

        self.lbl_okx_status = tk.Label(root, text="", fg="gray")
        self.lbl_okx_status.grid(row=0, column=6, padx=5, pady=5, sticky="w")

        # ---------------- History row ----------------
        self.lbl_history = tk.Label(root, text="Istorijos failas:")
        self.lbl_history.grid(row=1, column=0, padx=5, pady=5, sticky="w")

        self.entry_history = tk.Entry(root, width=80)
        self.entry_history.grid(row=1, column=1, columnspan=4, padx=5, pady=5, sticky="we")

        self.btn_browse = tk.Button(root, text="Pasirinkti...", command=self.on_browse_file)
        self.btn_browse.grid(row=1, column=5, padx=5, pady=5)

        self.btn_merge = tk.Button(root, text="Sujungti failus", command=self.on_merge_files)
        self.btn_merge.grid(row=1, column=6, padx=5, pady=5)

        self.btn_dl_binance = tk.Button(root, text="Download BTC (Binance)", command=self.on_download_btc)
        self.btn_dl_binance.grid(row=1, column=7, padx=5, pady=5)

        self.btn_dl_bybit = tk.Button(root, text="Download Bybit", command=self.on_download_bybit)
        self.btn_dl_bybit.grid(row=1, column=8, padx=5, pady=5)

        # ---------------- Deposits row ----------------
        lbl_total = tk.Label(root, text="Bendras depozitas (pagalvė):")
        lbl_total.grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.entry_total_deposit = tk.Entry(root, width=10)
        self.entry_total_deposit.insert(0, "3000")
        self.entry_total_deposit.grid(row=2, column=1, padx=5, pady=5, sticky="w")

        lbl_stake = tk.Label(root, text="Sandorio depozitas (stake):")
        lbl_stake.grid(row=2, column=2, padx=5, pady=5, sticky="w")
        self.entry_stake = tk.Entry(root, width=10)
        self.entry_stake.insert(0, "2500")
        self.entry_stake.grid(row=2, column=3, padx=5, pady=5, sticky="w")

        # ---------------- Params header row ----------------
        tk.Label(root, text="LONG parametrai", font=("Arial", 9, "bold")).grid(row=3, column=1, padx=5, pady=5)
        tk.Label(root, text="SHORT parametrai", font=("Arial", 9, "bold")).grid(row=3, column=2, padx=5, pady=5)

        self.var_enable_long = tk.BooleanVar(value=True)
        self.var_enable_short = tk.BooleanVar(value=True)
        tk.Checkbutton(root, text="Enable LONG", variable=self.var_enable_long).grid(
            row=3, column=3, padx=5, pady=5, sticky="w"
        )
        tk.Checkbutton(root, text="Enable SHORT", variable=self.var_enable_short).grid(
            row=3, column=4, padx=5, pady=5, sticky="w"
        )

        def row(label, r, default_long, default_short):
            tk.Label(root, text=label).grid(row=r, column=0, padx=5, pady=5, sticky="w")
            e1 = tk.Entry(root, width=10)
            e1.insert(0, str(default_long))
            e1.grid(row=r, column=1, padx=5, pady=5, sticky="w")

            e2 = tk.Entry(root, width=10)
            e2.insert(0, str(default_short))
            e2.grid(row=r, column=2, padx=5, pady=5, sticky="w")
            return e1, e2

        self.entry_tp_long, self.entry_tp_short = row("TP ATR koef.:", 4, 1.0, 1.0)
        self.entry_sl_long, self.entry_sl_short = row("SL ATR koef.:", 5, 0.25, 1.0)
        self.entry_sar_long, self.entry_sar_short = row("SAR max ATR:", 6, 3.0, 3.0)
        self.entry_limit_long, self.entry_limit_short = row("Breakout offset % (pvz. 0.1 = 0.1%):", 7, 0.1, 0.1)
        self.entry_bb_period_long, self.entry_bb_period_short = row("BB periodas:", 8, 12, 12)
        self.entry_bb_lookback_long, self.entry_bb_lookback_short = row("BB lookback (barai):", 9, 4, 4)
        self.entry_bb_slope_long, self.entry_bb_slope_short = row("BB slope % (pvz. 0.004 = 0.4%):", 10, 0.004, 0.004)
        self.entry_bb_min_width_long, self.entry_bb_min_width_short = row("BB min width % (upper-mid):", 11, 0.01, 0.01)
        self.entry_bb_channel_pos_long, self.entry_bb_channel_pos_short = row("BB channel pos (0–1, pvz. 0.6):", 12, 0.6, 0.6)

        # ---------------- Buttons row ----------------
        self.btn_chart = tk.Button(root, text="Grafikas (trade analyzer)", command=self.on_show_chart)
        self.btn_chart.grid(row=13, column=0, padx=5, pady=5)

        self.btn_run = tk.Button(root, text="Run", command=self.on_run)
        self.btn_run.grid(row=13, column=1, padx=5, pady=5)

        self.btn_save = tk.Button(root, text="Save report", command=self.on_save_report)
        self.btn_save.grid(row=13, column=2, padx=5, pady=5)

        # ---------------- Output ----------------
        frame_text = tk.Frame(root)
        frame_text.grid(row=14, column=0, columnspan=9, padx=5, pady=5, sticky="nsew")

        scrollbar = tk.Scrollbar(frame_text)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text_output = tk.Text(frame_text, width=140, height=20, yscrollcommand=scrollbar.set)
        self.text_output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.text_output.yview)

        root.columnconfigure(1, weight=1)
        root.columnconfigure(2, weight=0)
        root.columnconfigure(3, weight=0)
        root.columnconfigure(4, weight=0)
        root.grid_rowconfigure(14, weight=1)

        # apply mode enable/disable
        self._apply_mode_ui()

        # optional: auto-refresh instruments when opening TESTNET
        # (neįjungiu automatiškai, kad neapkrautų; user paspaus Refresh OKX pats)

    # ---------------- OKX instruments refresh ----------------

    def _refresh_okx_instruments_async(self):
        # nešaldom UI
        try:
            self.btn_refresh_okx.config(state="disabled")
            self.lbl_okx_status.config(text="Loading OKX instruments...")
        except Exception:
            pass

        def worker():
            try:
                inst = self._fetch_okx_spot_instruments()
                # UI update
                self.frame.after(0, lambda: self._apply_okx_instruments(inst))
            except Exception as e:
                self.frame.after(0, lambda: self._okx_refresh_failed(e))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _fetch_okx_spot_instruments() -> list[str]:
        # public endpoint, raktų nereikia
        base_url = (getattr(app_state, "okx_base_url", None) or "").strip() or "https://www.okx.com"
        url = base_url.rstrip("/") + "/api/v5/public/instruments"
        params = {"instType": "SPOT"}

        r = requests.get(url, params=params, timeout=10)
        j = r.json()
        if str(j.get("code", "")) != "0":
            raise RuntimeError(f"OKX instruments error code={j.get('code')} msg={j.get('msg')}")

        data = j.get("data") or []
        out: list[str] = []
        for row in data:
            if isinstance(row, dict):
                inst_id = row.get("instId")
                if isinstance(inst_id, str) and inst_id:
                    out.append(inst_id)

        # filtruojam į populiariausią quote'ą, kad dropdown nebūtų 5000 eilučių
        # default: USDT (galėsim vėliau padaryti dropdown quote filter)
        out_usdt = [x for x in out if x.endswith("-USDT")]
        if out_usdt:
            out = out_usdt

        # stabilus rūšiavimas
        out = sorted(set(out))
        return out

    def _apply_okx_instruments(self, inst_list: list[str]):
        try:
            if not inst_list:
                raise RuntimeError("OKX instruments list is empty")

            self._paper_inst_list = inst_list

            # jei dabartinis pasirinkimas neegzistuoja - perstatom į pirmą
            cur = (self.var_paper_inst.get() or "").strip()
            if cur not in self._paper_inst_list:
                self.var_paper_inst.set(self._paper_inst_list[0])

            # perstatom OptionMenu
            menu = self.paper_inst_menu["menu"]
            menu.delete(0, "end")
            for inst in self._paper_inst_list:
                menu.add_command(label=inst, command=lambda v=inst: self.var_paper_inst.set(v))

            self.lbl_okx_status.config(text=f"OKX instruments: {len(self._paper_inst_list)} loaded")
        except Exception as e:
            self._okx_refresh_failed(e)
        finally:
            try:
                self.btn_refresh_okx.config(state="normal")
            except Exception:
                pass
            self._apply_mode_ui()

    def _okx_refresh_failed(self, e: Exception):
        try:
            self.lbl_okx_status.config(text=f"OKX load failed: {e}")
        except Exception:
            pass
        try:
            self.btn_refresh_okx.config(state="normal")
        except Exception:
            pass
        self._apply_mode_ui()

    # ---------------- MODE ----------------

    def _on_mode_changed(self, *_):
        try:
            m = (self.var_mode.get() or "BACKTEST").strip().upper()
            if m not in ("BACKTEST", "TESTNET", "LIVE"):
                m = "BACKTEST"
            app_state.mode = m
        except Exception:
            pass
        self._apply_mode_ui()

    def _apply_mode_ui(self):
        """Disable history inputs outside BACKTEST to avoid confusion."""
        mode = (self.var_mode.get() or "BACKTEST").strip().upper()
        is_backtest = mode == "BACKTEST"
        is_testnet = mode == "TESTNET"

        state_hist = "normal" if is_backtest else "disabled"

        try:
            self.entry_history.config(state=state_hist)
            self.btn_browse.config(state=state_hist)
            self.btn_merge.config(state=state_hist)
            self.btn_dl_binance.config(state=state_hist)
            self.btn_dl_bybit.config(state=state_hist)
        except Exception:
            pass

        # TESTNET feed controls only in TESTNET
        state_feed = "normal" if is_testnet else "disabled"
        try:
            self.paper_inst_menu.config(state=state_feed)
            self.paper_bar_menu.config(state=state_feed)
            self.btn_refresh_okx.config(state=state_feed)
        except Exception:
            pass
