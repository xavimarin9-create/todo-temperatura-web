"""Notificaciones por Telegram. Desactivado por defecto: se activa poniendo
TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en el .env.

El formateo de los mensajes esta separado del envio para poder reutilizar el
mismo texto en el panel de notificaciones dentro de la propia app (ver
notifications/notification_center.py), sin depender de que Telegram este
activado."""
from __future__ import annotations

import logging

import requests

import config

logger = logging.getLogger("telegram_bot")

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def is_enabled() -> bool:
    return config.TELEGRAM_ENABLED


def send_message(text: str) -> bool:
    """Envia un mensaje de texto plano por Telegram. No hace nada (y no falla) si
    la integracion esta desactivada."""
    if not is_enabled():
        logger.debug("Telegram desactivado, mensaje no enviado: %s", text)
        return False

    url = API_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    payload = {"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Error enviando mensaje a Telegram: %s", exc)
        return False


def format_signal_message(trade_info: dict) -> str:
    """trade_info debe incluir: asset, action ('COMPRA'/'VENTA'), entry_price,
    take_profit, stop_loss, reason, balance, balance_pct."""
    return (
        "🔔 SEÑAL DE TRADING\n\n"
        f"📊 Activo: {trade_info['asset']}\n"
        f"📈 Tipo: {trade_info['action']}\n"
        f"💰 Precio entrada: ${trade_info['entry_price']:,.2f}\n"
        f"🎯 Take-profit: ${trade_info['take_profit']:,.2f}\n"
        f"🛑 Stop-loss: ${trade_info['stop_loss']:,.2f}\n"
        f"📐 Razón: {trade_info['reason']}\n\n"
        f"💼 Balance: €{trade_info['balance']:,.2f} ({trade_info['balance_pct']:+.2f}%)"
    )


def format_trade_closed_message(trade_info: dict) -> str:
    result_emoji = "✅" if trade_info["pnl"] >= 0 else "❌"
    return (
        f"{result_emoji} OPERACIÓN CERRADA\n\n"
        f"📊 Activo: {trade_info['asset']}\n"
        f"💰 Precio salida: ${trade_info['exit_price']:,.2f}\n"
        f"📐 P&L: €{trade_info['pnl']:,.2f}\n\n"
        f"💼 Balance: €{trade_info['balance']:,.2f} ({trade_info['balance_pct']:+.2f}%)"
    )


def format_drawdown_alert_message(text: str) -> str:
    return f"🚨 ALERTA DE RIESGO\n\n{text}"


def format_daily_summary_message(summary: dict) -> str:
    return (
        "📅 RESUMEN DIARIO\n\n"
        f"🔢 Operaciones: {summary['trades_count']}\n"
        f"✅ Ganadoras: {summary['wins']}  ❌ Perdedoras: {summary['losses']}\n"
        f"📈 Win rate: {summary['win_rate']:.1f}%\n"
        f"💰 P&L del dia: €{summary['pnl']:,.2f}\n"
        f"💼 Balance final: €{summary['ending_balance']:,.2f}"
    )


def send_signal(trade_info: dict) -> bool:
    return send_message(format_signal_message(trade_info))


def send_trade_closed(trade_info: dict) -> bool:
    return send_message(format_trade_closed_message(trade_info))


def send_drawdown_alert(text: str) -> bool:
    return send_message(format_drawdown_alert_message(text))


def send_daily_summary(summary: dict) -> bool:
    return send_message(format_daily_summary_message(summary))
