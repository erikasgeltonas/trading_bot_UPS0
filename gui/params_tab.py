# gui/params_tab.py
from __future__ import annotations

import tkinter as tk
import logging

from .results_tab import ResultsTab

from .params_form import ParamsFormMixin
from .params_history import ParamsHistoryMixin
from .params_run import ParamsRunMixin

logger = logging.getLogger("gui.params")


class ParamsTab(ParamsFormMixin, ParamsHistoryMixin, ParamsRunMixin):
    """Pagrindinis strategijos parametrų tab'as (plonas controller)."""

    def __init__(self, parent, results_tab: ResultsTab | None = None, chart_tab=None, trades_tab=None, equity_tab=None):
        self.parent = parent
        self.frame = tk.Frame(parent)

        self.results_tab = results_tab
        self.chart_tab = chart_tab
        self.trades_tab = trades_tab
        self.equity_tab = equity_tab

        # last run state (Chart/Trades/Equity tabs need this)
        self.last_bot = None
        self.last_history_path = None
        self.last_total_deposit = None
        self.last_stake = None
        self.last_enable_long = True
        self.last_enable_short = True

        # running guard
        self._is_running = False

        # build UI + apply initial mode state
        self._build_layout()
        self._apply_mode_ui()
