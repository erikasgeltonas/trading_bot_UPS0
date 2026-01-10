# bot/position.py

from dataclasses import dataclass
from typing import Optional


@dataclass
class PositionState:
    in_position: bool = False
    entry_price: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    parts_filled: int = 0  # kiek dalių atidaryta (0, 1 arba 2)


class PositionController:
    """
    Atsakinga tik už:
    - entry_price
    - TP/SL pagal ATR
    - TP/SL tikrinimą
    Strategija ją naudoja, RiskManager – tik priima signalus.
    """

    def __init__(self, tp_atr_mult: float = 2.0, sl_atr_mult: float = 0.25):
        self.tp_atr_mult = tp_atr_mult
        self.sl_atr_mult = sl_atr_mult
        self.state = PositionState()

    # --- helperiai ---

    @property
    def in_position(self) -> bool:
        return self.state.in_position

    def _set_levels(self, entry_price: float, atr: float) -> None:
        self.state.entry_price = entry_price
        self.state.take_profit = entry_price + self.tp_atr_mult * atr
        self.state.stop_loss = entry_price - self.sl_atr_mult * atr

    def _reset(self) -> None:
        self.state = PositionState()

    # --- vieši metodai, kuriuos kvies strategija ---

    def open_partial(self, price: float, atr: float) -> None:
        """
        Pirmas įėjimas.
        """
        if not self.state.in_position:
            self.state.in_position = True
            self.state.parts_filled = 1
            self._set_levels(price, atr)

    def open_full(self, price: float, atr: float) -> None:
        """
        Antras įėjimas (FULL_LONG).
        Jei jau turim 1 dalį – perskaičiuojam vidutinę kainą ir TP/SL.
        """
        if not self.state.in_position:
            # jei dėl kažkokių priežasčių nėra pozicijos – tiesiog atidarom pilną
            self.state.in_position = True
            self.state.parts_filled = 2
            self._set_levels(price, atr)
            return

        # jei buvo 1 dalis – laikom, kad abi dalys vienodo dydžio → aritmetinis vidurkis
        if self.state.parts_filled == 1 and self.state.entry_price is not None:
            avg_price = (self.state.entry_price + price) / 2.0
            self.state.parts_filled = 2
            self._set_levels(avg_price, atr)

    def check_exit_by_levels(self, price: float) -> Optional[str]:
        """
        Patikrina, ar kaina palietė TP/SL.
        Grąžina:
          - "TP"  – jei pasiektas TP
          - "SL"  – jei pasiektas SL
          - None  – jei dar laikom poziciją
        """
        if not self.state.in_position or self.state.entry_price is None:
            return None

        if self.state.stop_loss is not None and price <= self.state.stop_loss:
            self._reset()
            return "SL"

        if self.state.take_profit is not None and price >= self.state.take_profit:
            self._reset()
            return "TP"

        return None

    def manual_exit(self) -> bool:
        """
        Rankinis išėjimas (strategijos EXIT_LONG).
        """
        if not self.state.in_position:
            return False
        self._reset()
        return True
