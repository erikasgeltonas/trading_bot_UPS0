# bot/risk.py
from __future__ import annotations


class RiskManager:
    """
    Rizikos valdymas su fiksuotu sandorio depozitu (stake) ir bendra equity (total_deposit).

    - total_deposit / initial_balance = bendra sąskaita (equity), kuri auga/krenta nuo PnL.
    - trade_stake = kiek USD (ar EUR) NAUDOJAM vienam sandoriui (fiksuotas).
      Pvz: total_deposit=2500, trade_stake=2000.
      Tada 500 yra "pagalvė". Jei equity krenta, galim nebeturėti pakankamai stake naujiems trade'ams.

    Pozicijos dydis:
    - PARTIAL = 0.5 * trade_stake
    - FULL papildymas = dar 0.5 * trade_stake
    PnL skaičiuojamas per realius vienetus (units = notional / entry_price).
    """

    def __init__(
        self,
        # senas pavadinimas paliekamas dėl suderinamumo
        initial_balance: float = 2000.0,

        # nauji (GUI) – jei nepaduoti, fallback į initial_balance
        total_deposit: float | None = None,
        trade_stake: float | None = None,

        # baziniai (fallback) koefai
        tp_atr_mult: float = 1.0,
        sl_atr_mult: float = 0.25,
        be_atr_trigger: float = 1.0,
        max_sar_profit_atr: float = 3.0,

        # atskiri long/short (jei None – naudoja bazinius)
        tp_atr_mult_long: float | None = None,
        sl_atr_mult_long: float | None = None,
        tp_atr_mult_short: float | None = None,
        sl_atr_mult_short: float | None = None,
        max_sar_profit_atr_long: float | None = None,
        max_sar_profit_atr_short: float | None = None,
    ):
        # --- equity (bendra sąskaita) ---
        equity_start = float(total_deposit) if total_deposit is not None else float(initial_balance)
        self.balance = float(equity_start)

        # --- stake (fiksuotas sandorio dydis pinigais) ---
        # jei nepaduota – elgiamės kaip anksčiau: visa sąskaita = stake
        self.trade_stake = float(trade_stake) if trade_stake is not None else float(equity_start)

        base_tp = float(tp_atr_mult)
        base_sl = float(sl_atr_mult)
        base_sar = float(max_sar_profit_atr)

        self.tp_atr_mult_long = float(tp_atr_mult_long) if tp_atr_mult_long is not None else base_tp
        self.sl_atr_mult_long = float(sl_atr_mult_long) if sl_atr_mult_long is not None else base_sl
        self.tp_atr_mult_short = float(tp_atr_mult_short) if tp_atr_mult_short is not None else base_tp
        self.sl_atr_mult_short = float(sl_atr_mult_short) if sl_atr_mult_short is not None else base_sl

        self.max_sar_profit_atr_long = float(max_sar_profit_atr_long) if max_sar_profit_atr_long is not None else base_sar
        self.max_sar_profit_atr_short = float(max_sar_profit_atr_short) if max_sar_profit_atr_short is not None else base_sar

        self.be_atr_trigger = float(be_atr_trigger)

        # Pozicijos būsena
        self.position_side: str = "NONE"  # "NONE", "LONG", "SHORT"
        self.full_filled: bool = False

        # Pozicijos parametrai
        self.entry_price: float | None = None

        # kiek PINIGŲ panaudota pozicijai (notional)
        self.position_notional: float = 0.0

        # kiek vienetų (BTC, akcijų ir t.t.)
        self.position_units: float = 0.0

        self.tp_price: float | None = None
        self.sl_price: float | None = None

    # ---------------------- helperiai ------------------------

    @property
    def in_position(self) -> bool:
        return self.position_side != "NONE"

    def _can_open_notional(self, notional: float) -> bool:
        # paprasta taisyklė: negalim atidaryti, jei equity mažesnė už reikalingą notional
        # (taip pagalvė realiai riboja trade'us)
        return self.balance >= notional and notional > 0

    # ---------------------- įėjimai --------------------------

    def _open_position(self, side: str, entry_price: float, atr: float, notional: float):
        """
        Atidaryti / papildyti poziciją už konkrečią sumą (notional).
        """
        if atr is None or atr <= 0:
            return
        if entry_price is None or entry_price <= 0:
            return
        if not self._can_open_notional(notional):
            return

        # parenkam TP/SL koefus pagal pusę
        if side == "LONG":
            tp_k = self.tp_atr_mult_long
            sl_k = self.sl_atr_mult_long
        else:
            tp_k = self.tp_atr_mult_short
            sl_k = self.sl_atr_mult_short

        add_units = float(notional) / float(entry_price)

        if not self.in_position:
            # nauja pozicija
            self.position_side = side
            self.entry_price = float(entry_price)
            self.position_notional = float(notional)
            self.position_units = float(add_units)
        else:
            # papildom ta pačia kryptimi – perdarom avg entry per units
            if self.position_side != side:
                return
            if self.entry_price is None:
                return

            old_units = self.position_units
            old_ep = self.entry_price

            new_units = old_units + add_units
            if new_units <= 0:
                return

            # svertinis vidurkis pagal units
            avg_price = (old_ep * old_units + entry_price * add_units) / new_units

            self.entry_price = float(avg_price)
            self.position_units = float(new_units)
            self.position_notional += float(notional)

        ep = self.entry_price
        if ep is None:
            return

        if side == "LONG":
            self.tp_price = ep + tp_k * atr
            self.sl_price = ep - sl_k * atr
        else:  # SHORT
            self.tp_price = ep - tp_k * atr
            self.sl_price = ep + sl_k * atr

    def enter_partial_long(self, entry_price: float, atr: float):
        if self.in_position and self.position_side not in ("LONG", "NONE"):
            return
        self._open_position("LONG", entry_price, atr, notional=0.5 * self.trade_stake)
        self.full_filled = False

    def add_full_long(self, entry_price: float, atr: float):
        if not self.in_position or self.position_side != "LONG":
            return
        if self.full_filled:
            return
        self._open_position("LONG", entry_price, atr, notional=0.5 * self.trade_stake)
        self.full_filled = True

    def enter_partial_short(self, entry_price: float, atr: float):
        if self.in_position and self.position_side not in ("SHORT", "NONE"):
            return
        self._open_position("SHORT", entry_price, atr, notional=0.5 * self.trade_stake)
        self.full_filled = False

    def add_full_short(self, entry_price: float, atr: float):
        if not self.in_position or self.position_side != "SHORT":
            return
        if self.full_filled:
            return
        self._open_position("SHORT", entry_price, atr, notional=0.5 * self.trade_stake)
        self.full_filled = True

    # ---------------------- SAR / SL atnaujinimas ------------

    def update_sl_with_sar(self, current_price: float, atr: float, psar: float | None):
        """
        Trailing SL pagal SAR:
        - SL stumiam tik pelno kryptimi
        - ribojam, kad nuo entry iki SL nebūtų daugiau nei max_sar_profit_atr_* * ATR
        """
        if not self.in_position or psar is None or atr is None or atr <= 0:
            return
        if self.entry_price is None or self.sl_price is None:
            return

        ep = self.entry_price

        if self.position_side == "LONG":
            profit_atr = max(0.0, (current_price - ep) / atr)
            if profit_atr <= 0:
                return
            max_sar_atr = self.max_sar_profit_atr_long
            max_sl = ep + min(profit_atr, max_sar_atr) * atr
            new_sl = min(max(self.sl_price, psar), max_sl)
            if new_sl > self.sl_price:
                self.sl_price = new_sl

        else:  # SHORT
            profit_atr = max(0.0, (ep - current_price) / atr)
            if profit_atr <= 0:
                return
            max_sar_atr = self.max_sar_profit_atr_short
            max_sl = ep - min(profit_atr, max_sar_atr) * atr
            new_sl = max(min(self.sl_price, psar), max_sl)
            if new_sl < self.sl_price:
                self.sl_price = new_sl

    # ---------------------- TP/SL tikrinimas -----------------

    def check_exit(self, price: float) -> str | None:
        """
        Patikrina, ar reikia uždaryti poziciją:
        grąžina 'TP', 'SL' arba None.
        """
        if not self.in_position or self.tp_price is None or self.sl_price is None:
            return None

        if self.position_side == "LONG":
            if price <= self.sl_price:
                return "SL"
            if price >= self.tp_price:
                return "TP"
        else:  # SHORT
            if price >= self.sl_price:
                return "SL"
            if price <= self.tp_price:
                return "TP"

        return None

    # ---------------------- išėjimas --------------------------

    def _exit(self, price: float) -> float:
        if not self.in_position or self.entry_price is None or self.position_units <= 0:
            return 0.0

        ep = self.entry_price
        units = self.position_units

        if self.position_side == "LONG":
            pnl = (price - ep) * units
        else:
            pnl = (ep - price) * units

        self.balance += pnl

        self.position_side = "NONE"
        self.entry_price = None
        self.position_notional = 0.0
        self.position_units = 0.0
        self.tp_price = None
        self.sl_price = None
        self.full_filled = False

        return float(pnl)

    def exit_position(self, price: float) -> float:
        return self._exit(price)

    # backward compat
    def exit_long(self, price: float) -> float:
        return self._exit(price)
