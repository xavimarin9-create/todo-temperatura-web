"""Indicadores tecnicos: EMA, MACD, RSI, StochRSI, Bollinger Bands, ATR, ADX, volumen."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    return result.fillna(50)


def stoch_rsi(close: pd.Series, period: int = 14, smooth_k: int = 3, smooth_d: int = 3):
    rsi_series = rsi(close, period)
    lowest = rsi_series.rolling(period).min()
    highest = rsi_series.rolling(period).max()
    denom = (highest - lowest).replace(0, np.nan)
    raw_k = ((rsi_series - lowest) / denom * 100).fillna(50)
    k = raw_k.rolling(smooth_k).mean()
    d = k.rolling(smooth_d).mean()
    return k, d


def bollinger_bands(close: pd.Series, period: int = 20, num_std: float = 2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_atr = atr(df, period)
    plus_dm_s = pd.Series(plus_dm, index=df.index).ewm(
        alpha=1 / period, min_periods=period, adjust=False
    ).mean()
    minus_dm_s = pd.Series(minus_dm, index=df.index).ewm(
        alpha=1 / period, min_periods=period, adjust=False
    ).mean()

    plus_di = 100 * (plus_dm_s / tr_atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm_s / tr_atr.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_series = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx_series.fillna(0)


def volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume.rolling(period).mean()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Anade todas las columnas de indicadores a una copia del dataframe OHLCV."""
    out = df.copy()

    out["ema9"] = ema(out["Close"], 9)
    out["ema21"] = ema(out["Close"], 21)
    out["ema50"] = ema(out["Close"], 50)
    out["ema200"] = ema(out["Close"], 200)

    macd_line, signal_line, hist = macd(out["Close"])
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist

    out["rsi14"] = rsi(out["Close"], 14)
    k, d = stoch_rsi(out["Close"], 14)
    out["stoch_rsi_k"] = k
    out["stoch_rsi_d"] = d

    upper, mid, lower = bollinger_bands(out["Close"], 20, 2.0)
    out["bb_upper"] = upper
    out["bb_mid"] = mid
    out["bb_lower"] = lower

    out["atr14"] = atr(out, 14)
    out["adx14"] = adx(out, 14)

    if "Volume" in out.columns:
        out["volume_sma20"] = volume_sma(out["Volume"], 20)
    else:
        out["Volume"] = 0.0
        out["volume_sma20"] = 0.0

    return out


def latest_snapshot(df: pd.DataFrame) -> dict:
    """Devuelve un dict con los valores de indicadores en la ultima vela y la anterior
    (util para detectar cruces)."""
    if len(df) < 2:
        raise ValueError("Se necesitan al menos 2 velas para el snapshot")

    last = df.iloc[-1]
    prev = df.iloc[-2]

    return {
        "close": float(last["Close"]),
        "prev_close": float(prev["Close"]),
        "ema9": float(last["ema9"]),
        "ema21": float(last["ema21"]),
        "ema50": float(last["ema50"]),
        "ema200": float(last["ema200"]),
        "prev_ema9": float(prev["ema9"]),
        "prev_ema21": float(prev["ema21"]),
        "macd": float(last["macd"]),
        "macd_signal": float(last["macd_signal"]),
        "macd_hist": float(last["macd_hist"]),
        "prev_macd": float(prev["macd"]),
        "prev_macd_signal": float(prev["macd_signal"]),
        "prev_macd_hist": float(prev["macd_hist"]),
        "rsi14": float(last["rsi14"]),
        "prev_rsi14": float(prev["rsi14"]),
        "stoch_rsi_k": float(last["stoch_rsi_k"]) if not pd.isna(last["stoch_rsi_k"]) else 50.0,
        "stoch_rsi_d": float(last["stoch_rsi_d"]) if not pd.isna(last["stoch_rsi_d"]) else 50.0,
        "bb_upper": float(last["bb_upper"]),
        "bb_mid": float(last["bb_mid"]),
        "bb_lower": float(last["bb_lower"]),
        "atr14": float(last["atr14"]),
        "adx14": float(last["adx14"]),
        "volume": float(last["Volume"]),
        "volume_sma20": float(last["volume_sma20"]) if last["volume_sma20"] else 0.0,
        "timestamp": df.index[-1],
    }
