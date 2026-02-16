"""Trailing stop — progressive SL management for open positions.

Rules:
  - At 1×R profit → move SL to breakeven (entry price).
  - At 1.5×R profit → trail SL by 0.5×R behind current price.
"""


class TrailingStop:
    """Tracks and updates SL for a single position.

    Args:
        entry_price: Original entry price.
        initial_sl: Original stop-loss price.
        direction: ``"buy"`` or ``"sell"``.
    """

    def __init__(
        self,
        entry_price: float,
        initial_sl: float,
        direction: str,
    ) -> None:
        self.entry_price = entry_price
        self.initial_sl = initial_sl
        self.direction = direction
        self.current_sl = initial_sl
        self._risk = abs(entry_price - initial_sl)

    def update(self, current_price: float) -> float | None:
        """Evaluate the current price and return a new SL if it should move.

        Returns:
            New SL price if the stop should be adjusted, ``None`` if no change.
        """
        if self._risk == 0:
            return None

        if self.direction == "buy":
            profit = current_price - self.entry_price
            r_multiple = profit / self._risk

            if r_multiple >= 1.5:
                # Trail by 0.5×R behind current price
                new_sl = current_price - 0.5 * self._risk
                new_sl = round(new_sl, 2)
                if new_sl > self.current_sl:
                    self.current_sl = new_sl
                    return new_sl

            elif r_multiple >= 1.0:
                # Move to breakeven
                if self.current_sl < self.entry_price:
                    self.current_sl = self.entry_price
                    return self.entry_price

        elif self.direction == "sell":
            profit = self.entry_price - current_price
            r_multiple = profit / self._risk

            if r_multiple >= 1.5:
                new_sl = current_price + 0.5 * self._risk
                new_sl = round(new_sl, 2)
                if new_sl < self.current_sl:
                    self.current_sl = new_sl
                    return new_sl

            elif r_multiple >= 1.0:
                if self.current_sl > self.entry_price:
                    self.current_sl = self.entry_price
                    return self.entry_price

        return None
