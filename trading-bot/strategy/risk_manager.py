"""Gestion de riesgo: position sizing, stop-loss/take-profit, trailing y circuit breakers."""
from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass
class PositionPlan:
    asset: str
    side: str            # "LONG" (paper trading solo abre largos)
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    risk_amount: float
    position_value: float


class RiskManager:
    """Aplica las reglas de riesgo definidas para el bot de paper trading."""

    def __init__(
        self,
        risk_per_trade: float = config.RISK_PER_TRADE,
        max_open_positions: int = config.MAX_OPEN_POSITIONS,
        max_daily_drawdown: float = config.MAX_DAILY_DRAWDOWN,
        max_total_drawdown: float = config.MAX_TOTAL_DRAWDOWN,
        take_profit_rr: float = config.TAKE_PROFIT_RR,
        breakeven_trigger_pct: float = config.BREAKEVEN_TRIGGER_PCT,
    ):
        self.risk_per_trade = risk_per_trade
        self.max_open_positions = max_open_positions
        self.max_daily_drawdown = max_daily_drawdown
        self.max_total_drawdown = max_total_drawdown
        self.take_profit_rr = take_profit_rr
        self.breakeven_trigger_pct = breakeven_trigger_pct

    # ------------------------------------------------------------------
    # Stop-loss / take-profit
    # ------------------------------------------------------------------
    def calculate_stop_loss(self, entry_price: float, atr_value: float, asset_key: str) -> float:
        multiplier = config.ASSETS[asset_key]["atr_stop_multiplier"]
        stop = entry_price - multiplier * atr_value
        return max(stop, 0.0)

    def calculate_take_profit(self, entry_price: float, stop_loss: float) -> float:
        risk_distance = entry_price - stop_loss
        return entry_price + self.take_profit_rr * risk_distance

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------
    def calculate_position_size(
        self,
        balance: float,
        entry_price: float,
        stop_loss: float,
        asset_key: str,
        allocated_to_asset: float,
    ) -> PositionPlan | None:
        risk_distance = entry_price - stop_loss
        if risk_distance <= 0:
            return None

        risk_amount = balance * self.risk_per_trade
        quantity = risk_amount / risk_distance
        position_value = quantity * entry_price

        max_asset_capital = balance * config.ASSETS[asset_key]["max_allocation_pct"]
        available_for_asset = max(max_asset_capital - allocated_to_asset, 0.0)
        if available_for_asset <= 0:
            return None

        if position_value > available_for_asset:
            position_value = available_for_asset
            quantity = position_value / entry_price
            risk_amount = quantity * risk_distance

        if position_value <= 0 or quantity <= 0:
            return None

        take_profit = self.calculate_take_profit(entry_price, stop_loss)

        return PositionPlan(
            asset=asset_key,
            side="LONG",
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            quantity=quantity,
            risk_amount=risk_amount,
            position_value=position_value,
        )

    # ------------------------------------------------------------------
    # Limites de exposicion
    # ------------------------------------------------------------------
    def can_open_new_position(self, open_positions_count: int) -> bool:
        return open_positions_count < self.max_open_positions

    # ------------------------------------------------------------------
    # Trailing stop a break-even
    # ------------------------------------------------------------------
    def apply_trailing_stop(self, entry_price: float, current_price: float, current_stop: float) -> float:
        """Si el precio ha subido +1.5% desde la entrada, mueve el stop a break-even."""
        gain_pct = (current_price - entry_price) / entry_price
        if gain_pct >= self.breakeven_trigger_pct and current_stop < entry_price:
            return entry_price
        return current_stop

    # ------------------------------------------------------------------
    # Circuit breakers de drawdown
    # ------------------------------------------------------------------
    def check_daily_drawdown(self, day_start_balance: float, current_equity: float) -> bool:
        """True si se ha superado el drawdown diario maximo permitido."""
        if day_start_balance <= 0:
            return False
        drawdown = (day_start_balance - current_equity) / day_start_balance
        return drawdown >= self.max_daily_drawdown

    def check_total_drawdown(self, initial_balance: float, current_equity: float) -> bool:
        """True si se ha superado el drawdown total maximo permitido (bot debe pararse)."""
        if initial_balance <= 0:
            return False
        drawdown = (initial_balance - current_equity) / initial_balance
        return drawdown >= self.max_total_drawdown
