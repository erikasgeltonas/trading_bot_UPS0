# gui/app_state.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List


RunDict = Dict[str, Any]


@dataclass
class AppState:
    """
    Central state shared by GUI tabs.

    Standardized objects:
      - last_run:    result of Parameters -> Run backtest
      - last_match:  result of Match tab (comparison run) in the SAME STRUCTURE as last_run
      - ai_last_payload: optimizer payload prepared by AI tab (future Optimizer tab will read it)

    Expected run structure (both last_run and last_match):
      {
        "meta": {
            "history_path": str,
            "initial": float,
            "final_balance": float,
            ...
        },
        "params": { ... },               # params used
        "stats_all": { ... },            # trades, profit_factor, win_rate, max_drawdown, total_pnl, ...
        "stats_long": { ... },
        "stats_short": { ... },
        "trades_log": [ {"pnl": ... , ...}, ... ]
      }
    """

    # ✅ NEW: global mode for robot execution
    # BACKTEST / TESTNET / LIVE
    mode: str = "BACKTEST"

    # last results
    last_run: Optional[RunDict] = None
    last_match: Optional[RunDict] = None

    # produced by AI tab for future Optimizer tab
    ai_last_payload: Optional[Dict[str, Any]] = None

    # optional history (future use)
    runs_history: List[RunDict] = field(default_factory=list)

    # optional: strategy snapshot visible to AI tab (set by ParamsTab)
    strategy_info: Dict[str, Any] = field(default_factory=dict)

    def set_last_run(self, run: RunDict) -> None:
        self.last_run = run
        self._append_history(run)

    def set_last_match(self, match: RunDict) -> None:
        """
        Match tab should call this and pass a dict in the same structure as last_run.
        """
        self.last_match = match

    def clear(self) -> None:
        self.mode = "BACKTEST"
        self.last_run = None
        self.last_match = None
        self.ai_last_payload = None
        self.strategy_info = {}
        self.runs_history.clear()

    # ---------------- internal helpers ----------------

    def _append_history(self, run: RunDict) -> None:
        """
        Keep lightweight run history (optional future learning/compare).
        """
        try:
            self.runs_history.append(run)
            if len(self.runs_history) > 200:
                self.runs_history = self.runs_history[-200:]
        except Exception:
            pass


# singleton used by tabs
app_state = AppState()
