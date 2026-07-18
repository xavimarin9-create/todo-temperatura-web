"""Obtencion de datos de precio: yfinance (crypto y oro) con respaldo Twelve Data para XAU/USD."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

import config

logger = logging.getLogger("price_feed")

# Periodo maximo permitido por yfinance segun el intervalo intradia solicitado.
YF_INTERVAL_PERIOD = {
    "5m": "60d",
    "15m": "60d",
    "1h": "730d",
    "1d": "max",
}

TWELVE_DATA_INTERVAL = {"5m": "5min", "15m": "15min", "1h": "1h"}


class PriceFeedError(Exception):
    pass


class PriceFeed:
    """Encapsula la descarga de velas OHLCV para los activos configurados."""

    def __init__(self, max_retries: int = 3, retry_backoff_seconds: int = 5):
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._cache: dict[tuple, tuple[datetime, pd.DataFrame]] = {}

    # ------------------------------------------------------------------
    # yfinance
    # ------------------------------------------------------------------
    def _download_yf(self, ticker: str, interval: str, period: str) -> pd.DataFrame:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                df = yf.download(
                    ticker,
                    interval=interval,
                    period=period,
                    progress=False,
                    auto_adjust=False,
                )
                if df is None or df.empty:
                    raise PriceFeedError(f"yfinance devolvio datos vacios para {ticker}")
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df[["Open", "High", "Low", "Close", "Volume"]]
            except Exception as exc:  # noqa: BLE001 - queremos capturar cualquier fallo de red/API
                last_exc = exc
                logger.warning(
                    "Fallo al obtener datos de %s (intento %s/%s): %s",
                    ticker, attempt, self.max_retries, exc,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_seconds * attempt)
        raise PriceFeedError(f"No se pudo obtener datos de {ticker} tras {self.max_retries} intentos") from last_exc

    # ------------------------------------------------------------------
    # Twelve Data (respaldo, solo XAU/USD)
    # ------------------------------------------------------------------
    def _fetch_twelve_data(self, symbol: str = "XAU/USD", interval: str = "15min", outputsize: int = 200) -> pd.DataFrame:
        if not config.TWELVE_DATA_API_KEY:
            raise PriceFeedError("TWELVE_DATA_API_KEY no configurada")
        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": config.TWELVE_DATA_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict) or "values" not in payload:
            raise PriceFeedError(f"Twelve Data error: {payload.get('message', payload) if isinstance(payload, dict) else payload}")

        df = pd.DataFrame(payload["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime").sort_index()
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(float) if "volume" in df.columns else 0.0
        df = df.rename(
            columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
        )
        return df[["Open", "High", "Low", "Close", "Volume"]]

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------
    def get_candles(self, asset_key: str, timeframe: str) -> pd.DataFrame:
        """Devuelve un DataFrame OHLCV con al menos ~200 velas para el timeframe pedido."""
        asset_cfg = config.ASSETS[asset_key]
        cache_key = (asset_key, timeframe)

        if timeframe == "4h":
            base = self.get_candles(asset_key, "1h")
            resampled = (
                base.resample("4h")
                .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
                .dropna()
            )
            return resampled

        period = YF_INTERVAL_PERIOD.get(timeframe, "60d")
        try:
            df = self._download_yf(asset_cfg["yf_ticker"], timeframe, period)
            self._cache[cache_key] = (datetime.utcnow(), df)
            return df
        except PriceFeedError as exc:
            logger.error("yfinance fallo para %s (%s): %s", asset_key, timeframe, exc)

            if asset_key == "XAU/USD" and config.TWELVE_DATA_API_KEY:
                logger.info("Intentando respaldo Twelve Data para XAU/USD")
                try:
                    td_interval = TWELVE_DATA_INTERVAL.get(timeframe, "15min")
                    df = self._fetch_twelve_data(interval=td_interval)
                    self._cache[cache_key] = (datetime.utcnow(), df)
                    return df
                except PriceFeedError as td_exc:
                    logger.error("Twelve Data tambien fallo para XAU/USD: %s", td_exc)

            if cache_key in self._cache:
                logger.warning("Usando ultimos datos en cache para %s (%s)", asset_key, timeframe)
                return self._cache[cache_key][1]
            raise

    def get_current_price(self, asset_key: str) -> float:
        asset_cfg = config.ASSETS[asset_key]
        timeframe = asset_cfg["main_timeframe"]
        df = self.get_candles(asset_key, timeframe)
        return float(df["Close"].iloc[-1])
