# stats_utils.py

from __future__ import annotations


def calc_stats(trades_pnl: list[float], initial_balance: float) -> dict:
    """
    Papildoma statistika – winrate, PF, max DD, recovery factor, payoff ratio ir t.t.
    trades_pnl: sąrašas float (vieno sandorio PnL pinigais)
    """

    # sanitize
    pnl = []
    for x in trades_pnl or []:
        try:
            pnl.append(float(x))
        except Exception:
            pass

    n = len(pnl)
    total_pnl = sum(pnl)

    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]

    win_count = len(wins)
    loss_count = len(losses)

    win_rate = (win_count / n * 100.0) if n else 0.0
    avg_pnl = (total_pnl / n) if n else 0.0
    avg_win = (sum(wins) / win_count) if win_count else 0.0
    avg_loss = (sum(losses) / loss_count) if loss_count else 0.0  # bus neigiamas arba 0

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

    # equity curve ir max drawdown
    equity = [float(initial_balance)]
    bal = float(initial_balance)
    for x in pnl:
        bal += x
        equity.append(bal)

    max_equity = equity[0]
    max_dd = 0.0
    for eq in equity:
        if eq > max_equity:
            max_equity = eq
        dd = max_equity - eq
        if dd > max_dd:
            max_dd = dd

    final_balance = equity[-1] if equity else float(initial_balance)

    # papildomi koeficientai
    recovery_factor = (total_pnl / max_dd) if max_dd > 0 else 0.0
    payoff_ratio = (avg_win / abs(avg_loss)) if avg_loss < 0 else 0.0
    loss_recovery_trades = (abs(avg_loss) / avg_win) if avg_win > 0 else 0.0

    return {
        "initial_balance": float(initial_balance),
        "final_balance": float(final_balance),
        "total_pnl": float(total_pnl),
        "trades": int(n),

        "win_count": int(win_count),
        "loss_count": int(loss_count),
        "win_rate": float(win_rate),

        "avg_pnl": float(avg_pnl),
        "avg_win": float(avg_win),
        "avg_loss": float(avg_loss),

        "gross_profit": float(gross_profit),
        "gross_loss": float(gross_loss),
        "profit_factor": float(profit_factor),

        "max_drawdown": float(max_dd),

        "recovery_factor": float(recovery_factor),
        "payoff_ratio": float(payoff_ratio),
        "loss_recovery_trades": float(loss_recovery_trades),
    }
