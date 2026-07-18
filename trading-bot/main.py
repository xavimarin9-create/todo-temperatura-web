"""Punto de entrada del bot de paper trading. Loop principal + CLI."""
from __future__ import annotations

import argparse
import logging
import signal as os_signal
import sys
import threading
import time
import webbrowser
from datetime import datetime
from typing import Optional

import pytz
from rich.live import Live

import config
from dashboard import terminal_ui
from data.price_feed import PriceFeed, PriceFeedError
from database.db import Database
from notifications import telegram_bot
from strategy.risk_manager import RiskManager
from trading.paper_engine import PaperTradingEngine
from trading.portfolio import Portfolio

logger = logging.getLogger("main")


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


class TradingBot:
    """Orquesta la obtencion de datos, la evaluacion de senales y el paper trading."""

    def __init__(self):
        self.db = Database()
        self.portfolio = Portfolio()
        self.risk_manager = RiskManager()
        self.engine = PaperTradingEngine(self.portfolio, self.db, self.risk_manager)
        self.price_feed = PriceFeed()
        self.last_update: dict[str, datetime] = {}
        self.last_daily_summary_date = None
        self.running = True

    def _should_update(self, asset_key: str, now: datetime) -> bool:
        interval = config.ASSETS[asset_key]["update_interval_minutes"]
        last = self.last_update.get(asset_key)
        return last is None or (now - last).total_seconds() >= interval * 60

    def _btc_change_pct(self) -> Optional[float]:
        state = self.engine.asset_state.get("BTC/USD")
        if not state:
            return None
        ind = state["indicators"]
        prev_close = ind.get("prev_close")
        close = ind.get("close")
        if not prev_close:
            return None
        return (close - prev_close) / prev_close * 100

    def process_asset(self, asset_key: str, now: datetime):
        asset_cfg = config.ASSETS[asset_key]
        try:
            df_main = self.price_feed.get_candles(asset_key, asset_cfg["main_timeframe"])
            df_confirm = None
            if asset_cfg.get("confirm_timeframe"):
                df_confirm = self.price_feed.get_candles(asset_key, asset_cfg["confirm_timeframe"])

            context = {}
            if asset_cfg.get("correlate_with") == "BTC/USD":
                btc_change = self._btc_change_pct()
                if btc_change is not None:
                    context["btc_change_pct"] = btc_change

            self.engine.evaluate_asset(asset_key, df_main, df_confirm, context)
            self.last_update[asset_key] = now
        except PriceFeedError as exc:
            logger.error("No se pudieron obtener datos para %s: %s", asset_key, exc)
        except Exception:
            logger.exception("Error inesperado procesando %s", asset_key)

    def maybe_send_daily_summary(self, now: datetime):
        if now.hour == 23 and self.last_daily_summary_date != now.date():
            day_prefix = str(now.date())
            closed_today = [
                t for t in self.db.get_all_trades()
                if t["status"] == "CLOSED" and (t["closed_at"] or "").startswith(day_prefix)
            ]
            wins = sum(1 for t in closed_today if (t["pnl"] or 0) > 0)
            losses = len(closed_today) - wins
            pnl = sum((t["pnl"] or 0) for t in closed_today)
            win_rate = (wins / len(closed_today) * 100) if closed_today else 0.0
            equity = self.portfolio.total_equity(self.engine.current_prices())

            self.db.upsert_daily_summary(day_prefix, len(closed_today), wins, losses, pnl, win_rate, equity)
            text = telegram_bot.format_daily_summary_message({
                "trades_count": len(closed_today), "wins": wins, "losses": losses,
                "win_rate": win_rate, "pnl": pnl, "ending_balance": equity,
            })
            self.engine.notifications.add("SUMMARY", text, now)
            telegram_bot.send_message(text)
            self.last_daily_summary_date = now.date()

    def tick(self):
        now = datetime.now(pytz.timezone(config.TIMEZONE))
        for asset_key in config.ASSET_ORDER:
            if not self.running:
                break
            if self._should_update(asset_key, now):
                self.process_asset(asset_key, now)

        self.engine.check_drawdowns()
        self.maybe_send_daily_summary(now)

    def stop(self, *_args):
        if self.running:
            logger.info("Senal de parada recibida, cerrando el bot de forma limpia...")
        self.running = False


def _sleep_interruptible(bot: TradingBot, seconds: int):
    for _ in range(seconds):
        if not bot.running:
            return
        time.sleep(1)


def run_loop(bot: TradingBot, dashboard: bool = False):
    os_signal.signal(os_signal.SIGINT, bot.stop)
    os_signal.signal(os_signal.SIGTERM, bot.stop)

    if dashboard:
        with Live(terminal_ui.build_live_layout(bot.engine, bot.db), console=terminal_ui.console,
                  refresh_per_second=1, screen=True) as live:
            while bot.running:
                bot.tick()
                live.update(terminal_ui.build_live_layout(bot.engine, bot.db))
                if bot.portfolio.bot_stopped:
                    break
                _sleep_interruptible(bot, 15)
    else:
        while bot.running:
            bot.tick()
            terminal_ui.print_snapshot(bot.engine, bot.db)
            if bot.portfolio.bot_stopped:
                logger.warning("Drawdown total alcanzado. El bot se detiene.")
                break
            _sleep_interruptible(bot, 60)

    logger.info("Bot detenido. Balance final: EUR %.2f", bot.portfolio.balance)


def run_web(bot: TradingBot, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    from dashboard.web_server import create_app

    os_signal.signal(os_signal.SIGINT, bot.stop)
    os_signal.signal(os_signal.SIGTERM, bot.stop)

    app = create_app(bot)
    server_thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    server_thread.start()

    url = f"http://{host}:{port}"
    logger.info("Dashboard web disponible en %s", url)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    while bot.running:
        bot.tick()
        if bot.portfolio.bot_stopped:
            logger.warning("Drawdown total alcanzado. El bot se detiene.")
            break
        _sleep_interruptible(bot, 15)

    logger.info("Bot detenido. Balance final: EUR %.2f", bot.portfolio.balance)


def main():
    parser = argparse.ArgumentParser(
        description="Bot de paper trading (XAU/USD, BTC/USD, ETH/USD, SOL/USD)"
    )
    parser.add_argument("--dashboard", action="store_true", help="Ejecuta con dashboard interactivo en vivo (terminal)")
    parser.add_argument("--web", action="store_true",
                        help="Ejecuta con dashboard web en el navegador (graficos de velas en tiempo real)")
    parser.add_argument("--port", type=int, default=8765, help="Puerto del dashboard web (por defecto 8765)")
    parser.add_argument("--history", action="store_true", help="Muestra el historial de operaciones y termina")
    parser.add_argument("--summary", action="store_true", help="Muestra el resumen de rendimiento y termina")
    args = parser.parse_args()

    setup_logging()

    if args.history:
        terminal_ui.print_history(Database())
        return
    if args.summary:
        terminal_ui.print_summary(Database())
        return

    logger.info("Iniciando trading bot con balance inicial de EUR %.2f", config.INITIAL_BALANCE)
    logger.info(
        "Notificaciones de Telegram %s",
        "activadas" if config.TELEGRAM_ENABLED else "desactivadas (configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID)",
    )

    bot = TradingBot()
    try:
        if args.web:
            run_web(bot, port=args.port)
        else:
            run_loop(bot, dashboard=args.dashboard)
    except KeyboardInterrupt:
        bot.stop()


if __name__ == "__main__":
    main()
