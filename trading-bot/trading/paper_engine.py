"""Motor de paper trading: ejecuta operaciones virtuales aplicando spread y comision,
gestiona stop-loss/take-profit/trailing y conecta senales -> riesgo -> portfolio -> BD -> Telegram."""
from __future__ import annotations

import logging
import math
from datetime import datetime

import pandas as pd
import pytz

import config
from database.db import Database
from notifications import telegram_bot
from notifications.notification_center import NotificationCenter
from strategy import signals as sig
from strategy import technical as ta
from strategy.risk_manager import RiskManager
from trading.portfolio import Portfolio

logger = logging.getLogger("paper_engine")

MAX_CHART_CANDLES = 150


def _candles_payload(df_ind: pd.DataFrame, limit: int = MAX_CHART_CANDLES) -> list[dict]:
    """Serializa las ultimas velas (OHLC + EMA9/EMA21) para el gráfico del dashboard web.

    Descarta velas con OHLC no numerico (huecos de datos de yfinance): un NaN
    en el JSON rompe el parseo en el navegador y congela el dashboard entero."""
    candles = []
    for ts, row in df_ind.tail(limit).iterrows():
        if any(math.isnan(row[c]) for c in ("Open", "High", "Low", "Close")):
            continue
        ema9 = float(row["ema9"]) if not math.isnan(row["ema9"]) else None
        ema21 = float(row["ema21"]) if not math.isnan(row["ema21"]) else None
        candles.append({
            "time": int(ts.value // 10**9),
            "open": float(row["Open"]), "high": float(row["High"]),
            "low": float(row["Low"]), "close": float(row["Close"]),
            "ema9": ema9, "ema21": ema21,
        })
    return candles


def _now() -> datetime:
    return datetime.now(pytz.timezone(config.TIMEZONE))


def buy_fill_price(market_price: float) -> float:
    return market_price * (1 + config.SPREAD_PCT)


def sell_fill_price(market_price: float) -> float:
    return market_price * (1 - config.SPREAD_PCT)


class PaperTradingEngine:
    def __init__(
        self,
        portfolio: Portfolio | None = None,
        db: Database | None = None,
        risk_manager: RiskManager | None = None,
    ):
        self.portfolio = portfolio or Portfolio()
        self.db = db or Database()
        self.risk = risk_manager or RiskManager()
        self.asset_state: dict[str, dict] = {}
        self.notifications = NotificationCenter()

    # ------------------------------------------------------------------
    def _notional_and_commission(self, quantity: float, fill_price: float) -> tuple[float, float]:
        notional = quantity * fill_price
        commission = notional * config.COMMISSION_PCT
        return notional, commission

    # ------------------------------------------------------------------
    def _open_trade(self, asset_key: str, signal: sig.Signal, market_price: float, atr_value: float):
        if self.portfolio.bot_stopped or self.portfolio.daily_halt:
            return
        if self.portfolio.has_open_position(asset_key):
            return
        if not self.risk.can_open_new_position(len(self.portfolio.open_positions)):
            logger.info("Limite de %s posiciones simultaneas alcanzado, se ignora BUY en %s",
                        config.MAX_OPEN_POSITIONS, asset_key)
            return

        entry_price = buy_fill_price(market_price)
        stop_loss = self.risk.calculate_stop_loss(entry_price, atr_value, asset_key)
        allocated = self.portfolio.allocated_capital(asset_key)
        plan = self.risk.calculate_position_size(
            self.portfolio.balance, entry_price, stop_loss, asset_key, allocated
        )
        if plan is None:
            logger.info("Sin capital disponible para abrir posicion en %s", asset_key)
            return

        notional, commission = self._notional_and_commission(plan.quantity, entry_price)
        cost_basis = notional + commission
        if cost_basis > self.portfolio.balance:
            scale = self.portfolio.balance / cost_basis
            plan.quantity *= scale
            notional, commission = self._notional_and_commission(plan.quantity, entry_price)
            cost_basis = notional + commission
        if plan.quantity <= 0 or cost_basis <= 0:
            return

        opened_at = _now()
        reason = signal.reason_text()
        trade_id = self.db.insert_trade_open(
            opened_at.isoformat(), asset_key, "LONG", entry_price, plan.quantity,
            stop_loss, plan.take_profit, reason,
        )
        self.portfolio.open_position(
            trade_id, asset_key, entry_price, plan.quantity, stop_loss,
            plan.take_profit, cost_basis, reason, opened_at,
        )
        self.db.log_signal(opened_at.isoformat(), asset_key, signal.action, True, reason)

        logger.info("BUY %s @ %.4f qty=%.6f SL=%.4f TP=%.4f | %s",
                    asset_key, entry_price, plan.quantity, stop_loss, plan.take_profit, reason)

        equity = self.portfolio.total_equity({asset_key: market_price})
        text = telegram_bot.format_signal_message({
            "asset": asset_key, "action": "COMPRA", "entry_price": entry_price,
            "take_profit": plan.take_profit, "stop_loss": stop_loss, "reason": reason,
            "balance": equity, "balance_pct": self.portfolio.total_pnl_pct({asset_key: market_price}),
        })
        self.notifications.add("BUY", text, opened_at)
        telegram_bot.send_message(text)

    def _close_trade(self, trade_id: int, market_price: float, close_reason: str):
        position = self.portfolio.open_positions.get(trade_id)
        if position is None:
            return
        exit_price = sell_fill_price(market_price)
        notional, commission = self._notional_and_commission(position.quantity, exit_price)
        proceeds = notional - commission

        closed_at = _now()
        _, pnl = self.portfolio.close_position(trade_id, proceeds)
        self.db.close_trade(trade_id, closed_at.isoformat(), exit_price, pnl, self.portfolio.balance)
        self.db.log_signal(closed_at.isoformat(), position.asset, "SELL", True, close_reason)

        logger.info("SELL %s @ %.4f qty=%.6f pnl=%.2f | %s",
                    position.asset, exit_price, position.quantity, pnl, close_reason)

        equity = self.portfolio.total_equity({position.asset: market_price})
        text = telegram_bot.format_trade_closed_message({
            "asset": position.asset, "exit_price": exit_price, "pnl": pnl,
            "balance": equity, "balance_pct": self.portfolio.total_pnl_pct({position.asset: market_price}),
        })
        self.notifications.add("WIN" if pnl >= 0 else "LOSS", text, closed_at)
        telegram_bot.send_message(text)

    # ------------------------------------------------------------------
    def manage_open_position(self, asset_key: str, market_price: float):
        """Comprueba stop-loss, take-profit y trailing stop para las posiciones abiertas de un activo."""
        for trade_id, position in list(self.portfolio.open_positions.items()):
            if position.asset != asset_key:
                continue
            if market_price <= position.stop_loss:
                self._close_trade(trade_id, market_price, f"Stop-loss alcanzado ({position.stop_loss:.4f})")
                continue
            if market_price >= position.take_profit:
                self._close_trade(trade_id, market_price, f"Take-profit alcanzado ({position.take_profit:.4f})")
                continue

            new_stop = self.risk.apply_trailing_stop(position.entry_price, market_price, position.stop_loss)
            if new_stop != position.stop_loss:
                self.portfolio.update_stop_loss(trade_id, new_stop)
                self.db.update_trade_stop(trade_id, new_stop)
                logger.info("Trailing stop -> break-even en %s (stop=%.4f)", asset_key, new_stop)

    # ------------------------------------------------------------------
    def evaluate_asset(self, asset_key: str, df_main, df_confirm=None, context: dict | None = None):
        """Calcula indicadores, genera senal y actua en consecuencia para un activo."""
        df_main_ind = ta.compute_indicators(df_main)
        df_confirm_ind = ta.compute_indicators(df_confirm) if df_confirm is not None else None

        signal = sig.generate_signal(asset_key, df_main_ind, df_confirm_ind, context, now=_now())
        market_price = signal.indicators["close"]

        self.asset_state[asset_key] = {
            "last_price": market_price,
            "signal": signal.action,
            "reason": signal.reason_text(),
            "indicators": signal.indicators,
            "updated_at": _now(),
            "candles": _candles_payload(df_main_ind),
        }

        self.manage_open_position(asset_key, market_price)

        executed = False
        if signal.action == sig.SELL and self.portfolio.has_open_position(asset_key):
            for trade_id, position in list(self.portfolio.open_positions.items()):
                if position.asset == asset_key:
                    self._close_trade(trade_id, market_price, signal.reason_text())
                    executed = True
        elif signal.action == sig.BUY:
            before = len(self.portfolio.open_positions)
            self._open_trade(asset_key, signal, market_price, signal.indicators["atr14"])
            executed = len(self.portfolio.open_positions) > before

        if not executed:
            self.db.log_signal(_now().isoformat(), asset_key, signal.action, False, signal.reason_text())

        return signal

    # ------------------------------------------------------------------
    def current_prices(self) -> dict[str, float]:
        return {asset: state["last_price"] for asset, state in self.asset_state.items()}

    def check_drawdowns(self):
        """Aplica los circuit breakers de drawdown diario y total. Devuelve mensajes de alerta si aplica."""
        prices = self.current_prices()
        if not prices:
            return []
        equity = self.portfolio.total_equity(prices)
        now = _now()
        self.portfolio.maybe_roll_day(now, equity)

        alerts = []
        if not self.portfolio.daily_halt and self.risk.check_daily_drawdown(self.portfolio.day_start_equity, equity):
            self.portfolio.daily_halt = True
            msg = (f"Drawdown diario del {config.MAX_DAILY_DRAWDOWN*100:.0f}% alcanzado. "
                   f"Se detienen nuevas operaciones hasta manana.")
            logger.warning(msg)
            text = telegram_bot.format_drawdown_alert_message(msg)
            self.notifications.add("RISK", text, now)
            telegram_bot.send_message(text)
            alerts.append(msg)

        if not self.portfolio.bot_stopped and self.risk.check_total_drawdown(self.portfolio.initial_balance, equity):
            self.portfolio.bot_stopped = True
            msg = (f"Drawdown total del {config.MAX_TOTAL_DRAWDOWN*100:.0f}% alcanzado "
                   f"(balance: €{equity:,.2f}). El bot se detiene.")
            logger.warning(msg)
            text = telegram_bot.format_drawdown_alert_message(msg)
            self.notifications.add("RISK", text, now)
            telegram_bot.send_message(text)
            alerts.append(msg)

        self.db.record_balance(now.isoformat(), self.portfolio.balance, equity)
        return alerts
