# gui/trades_tab.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv
import logging

logger = logging.getLogger("gui.trades_tab")


class TradesTab:
    """Trades list tab (TSLab-like) with right-click context menu."""

    def __init__(
        self,
        parent,
        on_trade_selected=None,
        on_trade_activated=None,
        on_trade_goto_chart=None,   # NEW: right-click -> go to chart
        on_trade_details=None,      # NEW: optional (can be None)
    ):
        """
        Args:
            parent: notebook/tab parent
            on_trade_selected: callable(trade_id, trade_dict) - called on single selection
            on_trade_activated: callable(trade_id, trade_dict) - legacy (double-click/Enter). Optional.
            on_trade_goto_chart: callable(trade_id, trade_dict) - right-click menu action
            on_trade_details: callable(trade_id, trade_dict) - optional right-click action
        """
        self.frame = tk.Frame(parent)
        self._all_trades: list[dict] = []

        self._on_trade_selected = on_trade_selected
        self._on_trade_activated = on_trade_activated

        self._on_trade_goto_chart = on_trade_goto_chart
        self._on_trade_details = on_trade_details

        # map Treeview item iid -> trade dict
        self._trade_by_iid: dict[str, dict] = {}

        self._build_layout()
        logger.info("TradesTab INIT (context menu enabled)")

    # --------- Wiring helpers (non-breaking) ---------
    def set_trade_selected_callback(self, cb):
        self._on_trade_selected = cb

    def set_trade_activated_callback(self, cb):
        self._on_trade_activated = cb

    def set_trade_goto_chart_callback(self, cb):
        self._on_trade_goto_chart = cb

    def set_trade_details_callback(self, cb):
        self._on_trade_details = cb

    # --------- UI ---------
    def _build_layout(self):
        root = self.frame
        container = tk.Frame(root, bg="#1e1e1e")
        container.pack(fill="both", expand=True)

        # Top bar
        top = tk.Frame(container, bg="#1e1e1e")
        top.pack(fill="x")

        tk.Label(top, text="Search:", fg="#dcdcdc", bg="#1e1e1e").pack(side="left", padx=(8, 4), pady=6)
        self.search_var = tk.StringVar()
        e = tk.Entry(top, textvariable=self.search_var, width=40)
        e.pack(side="left", padx=(0, 8), pady=6)
        e.bind("<KeyRelease>", lambda _evt: self._apply_filter())

        ttk.Button(top, text="Export CSV", command=self.export_csv).pack(side="left", padx=8, pady=6)

        # Tree style
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Trades.Treeview",
            background="#1e1e1e",
            fieldbackground="#1e1e1e",
            foreground="#dcdcdc",
            rowheight=24,
            borderwidth=0,
        )
        style.configure(
            "Trades.Treeview.Heading",
            background="#2a2a2a",
            foreground="#ffffff",
            relief="flat",
            padding=(6, 6),
        )
        style.map("Trades.Treeview.Heading", background=[("active", "#333333")])

        # Tree area
        area = tk.Frame(container, bg="#1e1e1e")
        area.pack(fill="both", expand=True)

        cols = ("id", "side", "entry_time", "exit_time", "entry", "exit", "pnl", "pnl_pct", "reason", "bars")
        self.tree = ttk.Treeview(area, columns=cols, show="headings", style="Trades.Treeview", selectmode="browse")

        headings = {
            "id": "ID",
            "side": "Side",
            "entry_time": "Entry time",
            "exit_time": "Exit time",
            "entry": "Entry",
            "exit": "Exit",
            "pnl": "PnL",
            "pnl_pct": "PnL %",
            "reason": "Exit reason",
            "bars": "Bars held",
        }
        for c in cols:
            self.tree.heading(c, text=headings[c])

        self.tree.column("id", width=60, anchor="e", stretch=False)
        self.tree.column("side", width=80, anchor="w", stretch=False)
        self.tree.column("entry_time", width=170, anchor="w", stretch=False)
        self.tree.column("exit_time", width=170, anchor="w", stretch=False)
        self.tree.column("entry", width=110, anchor="e", stretch=False)
        self.tree.column("exit", width=110, anchor="e", stretch=False)
        self.tree.column("pnl", width=110, anchor="e", stretch=False)
        self.tree.column("pnl_pct", width=90, anchor="e", stretch=False)
        self.tree.column("reason", width=130, anchor="w", stretch=False)
        self.tree.column("bars", width=100, anchor="e", stretch=False)

        vsb = ttk.Scrollbar(area, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(area, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        area.grid_rowconfigure(0, weight=1)
        area.grid_columnconfigure(0, weight=1)

        # Tags for coloring
        self.tree.tag_configure("win", foreground="#4FC3F7")
        self.tree.tag_configure("loss", foreground="#FF8A65")
        self.tree.tag_configure("muted", foreground="#9e9e9e")

        # Selection event (1 click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select_event, add="+")

        # Legacy activation (keep, but not required)
        self.tree.bind("<Return>", self._on_activate_event, add="+")
        self.tree.bind("<Double-1>", self._on_activate_event, add="+")
        self.tree.bind("<Double-Button-1>", self._on_activate_event, add="+")

        # Context menu (right click)
        self._ctx = tk.Menu(self.frame, tearoff=0)
        self._ctx.add_command(label="Eiti į grafiką", command=self._ctx_goto_chart)
        # optional: details (minimal – can be wired later)
        self._ctx.add_command(label="Sandorio detalės (vėliau)", command=self._ctx_details)

        # Windows / Linux right click
        self.tree.bind("<Button-3>", self._on_right_click, add="+")
        # macOS sometimes uses Button-2 for right click
        self.tree.bind("<Button-2>", self._on_right_click, add="+")

    # ---------- Public API ----------
    def update_trades(self, trades_log: list[dict]) -> None:
        self._all_trades = trades_log or []
        self._apply_filter()

    def get_selected_trade(self):
        """Returns (trade_id, trade_dict) or (None, None)."""
        sel = self.tree.selection()
        if not sel:
            return None, None
        iid = sel[0]
        t = self._trade_by_iid.get(iid)
        if not t:
            return None, None
        return t.get("id"), t

    # ---------- Internal ----------
    def _apply_filter(self):
        q = (self.search_var.get() or "").strip().lower()

        # clear tree + map
        self.tree.delete(*self.tree.get_children())
        self._trade_by_iid.clear()

        for t in self._all_trades:
            row = self._trade_to_row(t)

            hay = " ".join(str(x).lower() for x in row)
            if q and q not in hay:
                continue

            pnl = t.get("pnl")
            tag = "muted"
            try:
                pnl_f = float(pnl)
                tag = "win" if pnl_f > 0 else "loss"
            except Exception:
                pass

            trade_id = t.get("id", "")
            iid = str(trade_id) if trade_id is not None else ""

            if not iid or iid in self._trade_by_iid:
                iid = f"row_{len(self._trade_by_iid)+1}"

            self._trade_by_iid[iid] = t
            self.tree.insert("", "end", iid=iid, values=row, tags=(tag,))

    def _on_select_event(self, _evt=None):
        if not callable(self._on_trade_selected):
            return
        trade_id, trade = self.get_selected_trade()
        if trade is None:
            return
        try:
            logger.info("Trade selected | id=%s", trade_id)
            self._on_trade_selected(trade_id, trade)
        except Exception:
            logger.exception("on_trade_selected callback failed")

    def _on_activate_event(self, _evt=None):
        """Legacy activation (double-click/Enter). Not required for your UX."""
        trade_id, trade = self.get_selected_trade()
        if trade is None:
            return
        cb = self._on_trade_activated
        if callable(cb):
            try:
                logger.info("Trade activated (legacy) | id=%s", trade_id)
                cb(trade_id, trade)
            except Exception:
                logger.exception("on_trade_activated callback failed")

    # ---------- Context menu ----------
    def _on_right_click(self, evt):
        """
        Right-click should select the row under mouse, then show menu.
        """
        try:
            iid = self.tree.identify_row(evt.y)
            if iid:
                try:
                    self.tree.selection_set(iid)
                    self.tree.focus(iid)
                except Exception:
                    pass
        except Exception:
            iid = None

        trade_id, trade = self.get_selected_trade()
        has_trade = trade is not None

        # enable/disable menu items based on selection + wired callbacks
        try:
            self._ctx.entryconfig("Eiti į grafiką", state=("normal" if has_trade else "disabled"))
        except Exception:
            pass
        try:
            self._ctx.entryconfig("Sandorio detalės (vėliau)", state=("normal" if has_trade else "disabled"))
        except Exception:
            pass

        try:
            self._ctx.tk_popup(evt.x_root, evt.y_root)
        finally:
            try:
                self._ctx.grab_release()
            except Exception:
                pass

    def _ctx_goto_chart(self):
        trade_id, trade = self.get_selected_trade()
        if trade is None:
            return

        cb = self._on_trade_goto_chart
        if not callable(cb):
            messagebox.showerror("Klaida", "Nėra prijungtos komandos 'Eiti į grafiką' (callback).")
            return

        try:
            logger.info("Context: goto chart | id=%s", trade_id)
            cb(trade_id, trade)
        except Exception:
            logger.exception("on_trade_goto_chart callback failed")
            messagebox.showerror("Klaida", "Nepavyko pereiti į grafiką (žiūrėk Log tab).")

    def _ctx_details(self):
        # minimal now: optional callback, otherwise info
        trade_id, trade = self.get_selected_trade()
        if trade is None:
            return

        cb = self._on_trade_details
        if callable(cb):
            try:
                logger.info("Context: trade details | id=%s", trade_id)
                cb(trade_id, trade)
            except Exception:
                logger.exception("on_trade_details callback failed")
                messagebox.showerror("Klaida", "Nepavyko atidaryti detalių (žiūrėk Log tab).")
        else:
            messagebox.showinfo("Info", "Detalių langas bus pridėtas vėliau. Dabar veikia 'Eiti į grafiką'.")

    # ---------- formatting ----------
    @staticmethod
    def _fmt_dt(x):
        return "-" if x is None else str(x)

    @staticmethod
    def _fmt_num(x, decimals=2):
        try:
            return f"{float(x):.{decimals}f}"
        except Exception:
            return "-"

    def _trade_to_row(self, t: dict):
        return (
            t.get("id", "-"),
            t.get("side", "-"),
            self._fmt_dt(t.get("entry_time")),
            self._fmt_dt(t.get("exit_time")),
            self._fmt_num(t.get("entry_price")),
            self._fmt_num(t.get("exit_price")),
            self._fmt_num(t.get("pnl")),
            (self._fmt_num(t.get("pnl_pct")) + " %") if t.get("pnl_pct") is not None else "-",
            t.get("exit_reason", "-"),
            t.get("bars_held", "-"),
        )

    def export_csv(self):
        path = filedialog.asksaveasfilename(
            title="Export Trades to CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(
                    ["ID", "Side", "Entry time", "Exit time", "Entry", "Exit", "PnL", "PnL %", "Exit reason", "Bars held"]
                )
                for t in self._all_trades:
                    w.writerow(self._trade_to_row(t))
            messagebox.showinfo("Export", f"CSV exported:\n{path}")
        except Exception as e:
            messagebox.showerror("Export error", str(e))
