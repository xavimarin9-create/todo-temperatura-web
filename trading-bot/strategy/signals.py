"""Generador de senales BUY/SELL/HOLD basado en confluencia de indicadores tecnicos.

Interpretacion de la confluencia:
 - Para una senal de COMPRA se exigen dos filtros estructurales obligatorios
   (cruce alcista EMA9/21 como disparador, y precio > EMA200 como filtro de
   tendencia) mas un numero minimo de confirmaciones adicionales (MACD, RSI,
   ADX, Volumen). El minimo de confirmaciones adicionales es
   ``min_confluence - 2`` (2 para la mayoria de activos, 3 para XAU/USD que es
   mas conservador).
 - Para una senal de VENTA basta con que se cumpla CUALQUIERA de las
   condiciones de venta (logica OR), ya que su proposito es proteger el
   capital saliendo de una posicion.
 - HOLD (no abrir nuevas posiciones) si ADX < 20, si el RSI esta en zona
   neutral 45-55, o si no se alcanza el minimo de confirmaciones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd
import pytz

import config
from strategy import technical as ta

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


@dataclass
class Signal:
    asset: str
    action: str
    reasons: list = field(default_factory=list)
    confluence_count: int = 0
    indicators: dict = field(default_factory=dict)
    timestamp: Optional[object] = None

    def reason_text(self) -> str:
        return " + ".join(self.reasons) if self.reasons else "Sin motivo"


def _is_within_trading_hours(asset_cfg: dict, now: Optional[datetime] = None) -> bool:
    if not asset_cfg.get("restrict_trading_hours"):
        return True
    tz = pytz.timezone(config.TIMEZONE)
    now = now.astimezone(tz) if now else datetime.now(tz)
    start_h, end_h = asset_cfg["trading_hours"]
    return start_h <= now.hour < end_h


def _is_weekend(now: Optional[datetime] = None) -> bool:
    tz = pytz.timezone(config.TIMEZONE)
    now = now.astimezone(tz) if now else datetime.now(tz)
    return now.weekday() >= 5


def _bearish_divergence(df: pd.DataFrame, lookback: int = 20) -> bool:
    if len(df) < lookback:
        return False
    window = df.iloc[-lookback:]
    mid = lookback // 2
    first_half, second_half = window.iloc[:mid], window.iloc[mid:]
    price_higher_high = second_half["Close"].max() > first_half["Close"].max()
    rsi_lower_high = second_half["rsi14"].max() < first_half["rsi14"].max()
    return bool(price_higher_high and rsi_lower_high)


def _ema_cross_up(snap: dict) -> bool:
    return snap["prev_ema9"] <= snap["prev_ema21"] and snap["ema9"] > snap["ema21"]


def _ema_cross_down(snap: dict) -> bool:
    return snap["prev_ema9"] >= snap["prev_ema21"] and snap["ema9"] < snap["ema21"]


def _macd_cross_down(snap: dict) -> bool:
    was_above = snap["prev_macd"] >= snap["prev_macd_signal"]
    now_below = snap["macd"] < snap["macd_signal"]
    return was_above and now_below and snap["macd_hist"] < 0


def _touches_upper_band(snap: dict) -> bool:
    return snap["close"] >= snap["bb_upper"]


def generate_signal(
    asset_key: str,
    df_main: pd.DataFrame,
    df_confirm: Optional[pd.DataFrame] = None,
    context: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> Signal:
    """Genera una senal de trading para un activo dado.

    df_main: dataframe OHLCV con indicadores ya calculados (compute_indicators) en el
        timeframe principal del activo.
    df_confirm: dataframe OHLCV con indicadores en el timeframe de confirmacion
        (solo XAU/USD lo usa: 1h).
    context: informacion adicional, p.ej. {'btc_change_pct': -4.2} para la
        correlacion ETH/BTC.
    """
    context = context or {}
    asset_cfg = config.ASSETS[asset_key]
    min_confluence = asset_cfg["min_confluence"]

    snap = ta.latest_snapshot(df_main)
    reasons: list[str] = []

    # --- Restriccion de horario (solo XAU/USD) ---------------------------------
    if not _is_within_trading_hours(asset_cfg, now):
        return Signal(asset_key, HOLD, ["Fuera de horario de mercado (8:00-22:00 CET)"],
                      0, snap, snap["timestamp"])

    weekend_caution = asset_cfg.get("weekend_caution") and _is_weekend(now)

    # --- Correlacion ETH/BTC ----------------------------------------------------
    if asset_cfg.get("correlate_with") == "BTC/USD":
        btc_change = context.get("btc_change_pct")
        if btc_change is not None and btc_change < -3.0:
            return Signal(asset_key, HOLD,
                          [f"BTC cae fuerte ({btc_change:.1f}%): se evita comprar ETH"],
                          0, snap, snap["timestamp"])

    # --- Condiciones de COMPRA ---------------------------------------------------
    cond_cross_up = _ema_cross_up(snap)
    cond_price_above_ema200 = snap["close"] > snap["ema200"]
    cond_macd_bull = (
        snap["macd"] > snap["macd_signal"]
        and snap["macd_hist"] > 0
        and snap["macd_hist"] > snap["prev_macd_hist"]
    )
    cond_rsi_ok = 30 <= snap["rsi14"] <= 65
    adx_threshold = 30 if weekend_caution else 25
    cond_adx = snap["adx14"] > adx_threshold
    cond_volume = snap["volume"] > snap["volume_sma20"] > 0

    buy_confirmations = [
        (cond_macd_bull, "MACD alcista con histograma creciente"),
        (cond_rsi_ok, f"RSI {snap['rsi14']:.1f} en rango sano (30-65)"),
        (cond_adx, f"ADX {snap['adx14']:.1f} > {adx_threshold} (tendencia confirmada)"),
        (cond_volume, "Volumen por encima de la media de 20 periodos"),
    ]
    buy_confirm_count = sum(1 for ok, _ in buy_confirmations if ok)
    required_extra = max(min_confluence - 2, 1)

    # --- Condiciones de bloqueo (HOLD) ------------------------------------------
    range_market = snap["adx14"] < 20
    neutral_rsi = 45 <= snap["rsi14"] <= 55

    # --- Confirmacion adicional en timeframe superior (solo XAU/USD) -----------
    confirm_ok = True
    if df_confirm is not None and len(df_confirm) >= 2:
        confirm_snap = ta.latest_snapshot(df_confirm)
        confirm_ok = confirm_snap["close"] > confirm_snap["ema200"]
        if confirm_ok:
            reasons.append("Confirmacion alcista en 1h (precio > EMA200)")

    # --- Condiciones de VENTA (OR) ----------------------------------------------
    sell_triggers = []
    if _ema_cross_down(snap):
        sell_triggers.append("Cruce bajista EMA9/EMA21")
    if snap["rsi14"] > 75 and _bearish_divergence(df_main):
        sell_triggers.append(f"RSI {snap['rsi14']:.1f} > 75 con divergencia bajista")
    if _touches_upper_band(snap) and snap["rsi14"] > 70:
        sell_triggers.append("Precio toca banda superior de Bollinger + RSI > 70")
    if _macd_cross_down(snap):
        sell_triggers.append("Cruce bajista MACD con histograma negativo")

    if sell_triggers:
        return Signal(asset_key, SELL, sell_triggers, len(sell_triggers), snap, snap["timestamp"])

    if range_market:
        return Signal(asset_key, HOLD, ["ADX < 20: mercado sin direccion clara"], 0, snap,
                      snap["timestamp"])
    if neutral_rsi:
        return Signal(asset_key, HOLD, ["RSI en zona neutral (45-55)"], 0, snap,
                      snap["timestamp"])

    if cond_cross_up and cond_price_above_ema200 and confirm_ok and buy_confirm_count >= required_extra:
        reasons = ["Cruce alcista EMA9/EMA21", "Precio > EMA200"] + reasons
        reasons += [text for ok, text in buy_confirmations if ok]
        if weekend_caution:
            reasons.append("Fin de semana: exigencia extra de tendencia (spread mas alto)")
        confluence = 2 + buy_confirm_count
        return Signal(asset_key, BUY, reasons, confluence, snap, snap["timestamp"])

    return Signal(asset_key, HOLD, ["Confluencia insuficiente para abrir posicion"], buy_confirm_count,
                  snap, snap["timestamp"])
