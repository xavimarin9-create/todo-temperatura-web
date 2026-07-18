"""Servidor web local (Flask) que expone el estado del bot para verlo en el
navegador con graficos de velas en tiempo real. Solo escucha en 127.0.0.1: no
expone nada a internet ni se conecta a ningun broker o exchange real."""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import pytz
from flask import Flask, jsonify, send_from_directory

import config

WEB_DIR = Path(__file__).resolve().parent / "web"


def _safe_num(value, decimals: int):
    """Redondea un numero, o devuelve None si es NaN/Inf/invalido.

    Un indicador puede ser NaN mientras no hay suficiente historico (p.ej. la
    EMA200 necesita 200 velas). jsonify() serializaria ese NaN como el token
    literal `NaN`, que no es JSON valido: el navegador fallaria al parsear
    *toda* la respuesta y el dashboard entero se quedaria congelado en el
    ultimo dato bueno (reloj incluido), sin ningun aviso."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v, decimals) if math.isfinite(v) else None


def _asset_payload(state: dict) -> dict:
    ind = state["indicators"]
    return {
        "has_data": True,
        "price": _safe_num(state["last_price"], 5),
        "signal": state["signal"],
        "reason": state["reason"],
        "updated_at": state["updated_at"].isoformat(),
        "rsi": _safe_num(ind["rsi14"], 1),
        "adx": _safe_num(ind["adx14"], 1),
        "ema9": _safe_num(ind["ema9"], 5),
        "ema21": _safe_num(ind["ema21"], 5),
        "ema200": _safe_num(ind["ema200"], 5),
        "macd_hist": _safe_num(ind["macd_hist"], 6),
        "candles": state.get("candles", []),
    }


def build_state_payload(bot) -> dict:
    engine = bot.engine
    portfolio = engine.portfolio
    prices = engine.current_prices()
    equity = portfolio.total_equity(prices)
    now = datetime.now(pytz.timezone(config.TIMEZONE))

    assets = []
    for asset_key in config.ASSET_ORDER:
        state = engine.asset_state.get(asset_key)
        if not state:
            assets.append({"asset": asset_key, "has_data": False})
        else:
            payload = {"asset": asset_key}
            payload.update(_asset_payload(state))
            assets.append(payload)

    positions = []
    for pos in portfolio.open_positions.values():
        current = prices.get(pos.asset, pos.entry_price)
        positions.append({
            "asset": pos.asset,
            "entry_price": _safe_num(pos.entry_price, 6),
            "current_price": _safe_num(current, 6),
            "quantity": _safe_num(pos.quantity, 8),
            "stop_loss": _safe_num(pos.stop_loss, 6),
            "take_profit": _safe_num(pos.take_profit, 6),
            "unrealized_pnl": _safe_num((current - pos.entry_price) * pos.quantity, 2),
        })

    closed_trades = [
        {
            "asset": row["asset"], "closed_at": row["closed_at"],
            "entry_price": row["entry_price"], "exit_price": row["exit_price"],
            "pnl": row["pnl"], "balance_after": row["balance_after"],
        }
        for row in bot.db.get_closed_trades(10)
    ]

    all_trades = bot.db.get_all_trades()
    closed_all = [t for t in all_trades if t["status"] == "CLOSED"]
    total = len(closed_all)
    wins = sum(1 for t in closed_all if (t["pnl"] or 0) > 0)
    win_rate = (wins / total * 100) if total else 0.0
    best = max(closed_all, key=lambda t: t["pnl"] or 0, default=None)
    worst = min(closed_all, key=lambda t: t["pnl"] or 0, default=None)

    notifications = [
        {"timestamp": n.timestamp.isoformat(), "level": n.level, "text": n.text}
        for n in engine.notifications.recent(15)
    ]

    status = "STOPPED" if portfolio.bot_stopped else ("PAUSED" if portfolio.daily_halt else "ACTIVE")

    return {
        "server_time": now.isoformat(),
        "initial_balance": _safe_num(portfolio.initial_balance, 2),
        "balance": _safe_num(portfolio.balance, 2),
        "equity": _safe_num(equity, 2),
        "pnl": _safe_num(portfolio.total_pnl(prices), 2),
        "pnl_pct": _safe_num(portfolio.total_pnl_pct(prices), 2),
        "status": status,
        "assets": assets,
        "positions": positions,
        "closed_trades": closed_trades,
        "notifications": notifications,
        "stats": {
            "total_closed": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": win_rate,
            "best": {"asset": best["asset"], "pnl": best["pnl"]} if best else None,
            "worst": {"asset": worst["asset"], "pnl": worst["pnl"]} if worst else None,
        },
    }


def create_app(bot) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.logger.setLevel("WARNING")

    @app.route("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.route("/vendor/<path:filename>")
    def vendor(filename):
        return send_from_directory(WEB_DIR / "vendor", filename)

    @app.route("/api/state")
    def state():
        return jsonify(build_state_payload(bot))

    return app
