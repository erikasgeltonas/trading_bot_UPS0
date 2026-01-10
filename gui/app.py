# gui/app.py
import tkinter as tk
from tkinter import ttk
import queue
import logging

from .logging_setup import setup_global_logging

from .params_tab import ParamsTab
from .results_tab import ResultsTab
from .trades_tab import TradesTab
from .chart_tab import ChartTab
from .optimizer_tab import OptimizerTab
from .log_tab import LogTab
from .equity_tab import EquityTab
from .math_tab import MathTab
from .ai_tab import AiTab


def run_app() -> None:
    """Start main GUI application."""
    root = tk.Tk()
    root.title("Trading Bot Studio")

    # ---- logging init ----
    log_queue: queue.Queue[str] = queue.Queue(maxsize=10000)
    setup_global_logging(log_queue=log_queue, log_dir="logs")
    logger = logging.getLogger("gui.app")
    logger.info("GUI starting...")

    # Main container with tabs
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    # Create tabs (objects)
    results_tab = ResultsTab(notebook)

    # Chart tab first so we can pass callbacks into TradesTab
    chart_tab = ChartTab(notebook)

    # 1 click: focus trade on chart (no tab switch)
    def _on_trade_selected(trade_id, trade_dict):
        try:
            chart_tab.show_trade(trade_id, trade_dict)
        except Exception:
            logger.exception("chart_tab.show_trade failed (selected)")

    # Legacy: double click / enter -> focus + switch to chart
    def _on_trade_activated(trade_id, trade_dict):
        try:
            chart_tab.show_trade(trade_id, trade_dict)
            notebook.select(chart_tab.frame)  # switch to Chart tab
        except Exception:
            logger.exception("chart_tab.show_trade failed (activated)")

    # NEW: right-click menu "Eiti į grafiką" -> focus + switch to chart
    def _on_trade_goto_chart(trade_id, trade_dict):
        try:
            chart_tab.show_trade(trade_id, trade_dict)
            notebook.select(chart_tab.frame)  # switch to Chart tab
        except Exception:
            logger.exception("chart_tab.show_trade failed (goto_chart)")

    trades_tab = TradesTab(
        notebook,
        on_trade_selected=_on_trade_selected,
        on_trade_activated=_on_trade_activated,
        on_trade_goto_chart=_on_trade_goto_chart,  # ✅ NEW
        on_trade_details=None,  # optional (later)
    )

    optimizer_tab = OptimizerTab(notebook)
    log_tab = LogTab(notebook, log_queue=log_queue)
    equity_tab = EquityTab(notebook)
    math_tab = MathTab(notebook)
    ai_tab = AiTab(notebook)

    # ParamsTab gets references to other tabs
    params_tab = ParamsTab(
        notebook,
        results_tab=results_tab,
        chart_tab=chart_tab,
        trades_tab=trades_tab,
        equity_tab=equity_tab,
    )

    # Register tabs in desired order
    notebook.add(params_tab.frame, text="Parameters")
    notebook.add(results_tab.frame, text="Results")
    notebook.add(trades_tab.frame, text="Trades")
    notebook.add(chart_tab.frame, text="Chart")
    notebook.add(optimizer_tab.frame, text="Optimizer")
    notebook.add(log_tab.frame, text="Log")
    notebook.add(equity_tab.frame, text="Equity")
    notebook.add(math_tab.frame, text="Math analysis")
    notebook.add(ai_tab.frame, text="AI agent")

    root.mainloop()
