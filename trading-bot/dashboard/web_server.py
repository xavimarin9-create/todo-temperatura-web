"""Servidor web local (Flask) que expone el estado del bot para verlo en el
navegador con graficos de velas en tiempo real. Solo escucha en 127.0.0.1: no
expone nada a internet ni se conecta a ningun broker o exchange real."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytz
from flask import Flask, jsonify, send_from_directory

import config

WEB_DIR = Path(__file__).resolve().parent / "web"


def _asset_payload(state: dict) -> dict:
    ind = state["indicators"]
    return {
        "has_data": True,
        "price": round(state["last_price"], 5),
        "signal": state["signal"],
        "reason": state["reason"],
        "updated_at": state["updated_at"].isoformat(),
        "rsi": round(ind["rsi14"], 1),
        "adx": round(ind["adx14"], 1),
        "ema9": round(ind["ema9"], 5),
        "ema21": round(ind["ema21"], 5),
        "ema200": round(ind["ema200"], 5),
        "macd_hist": round(ind["macd_hist"], 6),
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
            "entry_price": pos.entry_price,
            "current_price": current,
            "quantity": pos.quantity,
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
            "unrealized_pnl": (current - pos.entry_price) * pos.quantity,
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
        "initial_balance": portfolio.initial_balance,
        "balance": portfolio.balance,
        "equity": equity,
        "pnl": portfolio.total_pnl(prices),
        "pnl_pct": portfolio.total_pnl_pct(prices),
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

    @app.route("/api/state")
    def state():
        return jsonify(build_state_payload(bot))

    return app
