# gui/strategy_info.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List


@dataclass
class StrategyInfo:
    """
    Lightweight, human-readable snapshot of the CURRENT robot logic.
    This is what AI agent should "see" besides raw params.
    """
    name: str = "unknown"
    version: str = "mvp"
    market: str = "unknown"
    timeframe: str = "unknown"

    entry_rules: List[str] = None
    filters: List[str] = None
    exits: List[str] = None
    risk: List[str] = None

    indicators: List[str] = None
    notes: List[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for k in ("entry_rules", "filters", "exits", "risk", "indicators", "notes"):
            if d.get(k) is None:
                d[k] = []
        return d


def build_strategy_info_from_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fallback builder when we don't import strategy code.
    Uses param keys to infer what's active.
    """
    p = params or {}

    indicators = []
    if any(k.startswith("macd") for k in p.keys()) or any(k.startswith("macd_") for k in p.keys()):
        indicators.append("MACD")
    if any(k.startswith("bb_") for k in p.keys()):
        indicators.append("Bollinger Bands")
    if any(k.startswith("atr") for k in p.keys()) or any(k.startswith("atr_") for k in p.keys()):
        indicators.append("ATR")
    if "sar_long" in p or "sar_short" in p:
        indicators.append("SAR")

    entry_rules = []
    if "limit_long" in p or "limit_short" in p:
        entry_rules.append("Entry uses limit offset (limit_*)")
    entry_rules.append("Signal components inferred from params (no direct strategy parse yet).")

    filters = []
    if "bb_slope_long" in p or "bb_slope_short" in p:
        filters.append("BB slope threshold")
    if "bb_min_width_long" in p or "bb_min_width_short" in p:
        filters.append("BB min width threshold")
    if "bb_lookback_long" in p or "bb_lookback_short" in p:
        filters.append("BB lookback filter")

    exits = []
    if "tp_long" in p or "tp_short" in p:
        exits.append("Take Profit (tp_*)")
    if "sl_long" in p or "sl_short" in p:
        exits.append("Stop Loss (sl_*)")
    if "sar_long" in p or "sar_short" in p:
        exits.append("SAR trailing/exit (sar_*)")

    risk = []
    if "stake" in p:
        risk.append(f"Fixed stake={p.get('stake')}")
    if "total_deposit" in p:
        risk.append(f"Total deposit={p.get('total_deposit')}")

    info = StrategyInfo(
        name=str(p.get("strategy_name", "MACD+BB (inferred)")),
        version=str(p.get("strategy_version", "mvp")),
        entry_rules=entry_rules,
        filters=filters,
        exits=exits,
        risk=risk,
        indicators=indicators,
        notes=[
            f"enable_long={p.get('enable_long')} enable_short={p.get('enable_short')}",
            "This snapshot is inferred from params. Later we can register exact rules from strategy code.",
        ],
    )
    return info.to_dict()
