"""Estado del portfolio: balance, posiciones abiertas e historial de la sesion en curso."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import config


@dataclass
class Position:
    trade_id: int
    asset: str
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    cost_basis: float
    opened_at: datetime
    reason: str


class Portfolio:
    """Mantiene el estado en memoria del paper trading (la persistencia va aparte, en SQLite)."""

    def __init__(self, initial_balance: float = config.INITIAL_BALANCE):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.open_positions: dict[int, Position] = {}
        self.closed_trades: list[dict] = []

        self.current_day: date = datetime.now().date()
        self.day_start_equity = initial_balance
        self.daily_halt = False
        self.bot_stopped = False

    # ------------------------------------------------------------------
    def allocated_capital(self, asset_key: str) -> float:
        return sum(p.cost_basis for p in self.open_positions.values() if p.asset == asset_key)

    def has_open_position(self, asset_key: str) -> bool:
        return any(p.asset == asset_key for p in self.open_positions.values())

    def open_position(
        self, trade_id: int, asset: str, entry_price: float, quantity: float,
        stop_loss: float, take_profit: float, cost_basis: float, reason: str, opened_at: datetime,
    ) -> Position:
        self.balance -= cost_basis
        position = Position(trade_id, asset, entry_price, quantity, stop_loss, take_profit,
                             cost_basis, opened_at, reason)
        self.open_positions[trade_id] = position
        return position

    def close_position(self, trade_id: int, proceeds: float) -> tuple[Position, float]:
        position = self.open_positions.pop(trade_id)
        self.balance += proceeds
        pnl = proceeds - position.cost_basis
        self.closed_trades.append({
            "trade_id": trade_id, "asset": position.asset, "pnl": pnl,
            "entry_price": position.entry_price, "cost_basis": position.cost_basis,
        })
        return position, pnl

    def update_stop_loss(self, trade_id: int, new_stop: float):
        if trade_id in self.open_positions:
            self.open_positions[trade_id].stop_loss = new_stop

    # ------------------------------------------------------------------
    def unrealized_pnl(self, current_prices: dict[str, float]) -> float:
        total = 0.0
        for p in self.open_positions.values():
            price = current_prices.get(p.asset)
            if price is None:
                continue
            total += (price - p.entry_price) * p.quantity
        return total

    def total_equity(self, current_prices: dict[str, float]) -> float:
        equity = self.balance
        for p in self.open_positions.values():
            price = current_prices.get(p.asset, p.entry_price)
            equity += p.quantity * price
        return equity

    def total_pnl(self, current_prices: dict[str, float]) -> float:
        return self.total_equity(current_prices) - self.initial_balance

    def total_pnl_pct(self, current_prices: dict[str, float]) -> float:
        return (self.total_pnl(current_prices) / self.initial_balance) * 100

    # ------------------------------------------------------------------
    def maybe_roll_day(self, now: datetime, current_equity: float):
        """Reinicia el contador de drawdown diario si ha cambiado el dia."""
        if now.date() != self.current_day:
            self.current_day = now.date()
            self.day_start_equity = current_equity
            self.daily_halt = False

    # ------------------------------------------------------------------
    def win_rate(self) -> float:
        if not self.closed_trades:
            return 0.0
        wins = sum(1 for t in self.closed_trades if t["pnl"] > 0)
        return wins / len(self.closed_trades) * 100

    def best_trade(self) -> Optional[dict]:
        return max(self.closed_trades, key=lambda t: t["pnl"], default=None)

    def worst_trade(self) -> Optional[dict]:
        return min(self.closed_trades, key=lambda t: t["pnl"], default=None)
