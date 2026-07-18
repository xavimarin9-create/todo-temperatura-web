"""Configuracion general del trading bot. Carga valores desde variables de entorno (.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val not in (None, "") else default


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val not in (None, "") else default


# ---------------------------------------------------------------------------
# Balance y riesgo
# ---------------------------------------------------------------------------
INITIAL_BALANCE = _float("INITIAL_BALANCE", 1000.0)
RISK_PER_TRADE = _float("RISK_PER_TRADE", 0.02)          # 2% del balance
MAX_DAILY_DRAWDOWN = _float("MAX_DAILY_DRAWDOWN", 0.05)  # 5% diario
MAX_TOTAL_DRAWDOWN = _float("MAX_TOTAL_DRAWDOWN", 0.15)  # 15% total
MAX_OPEN_POSITIONS = 3
TAKE_PROFIT_RR = 2.0            # ratio riesgo/beneficio 1:2
BREAKEVEN_TRIGGER_PCT = 0.015   # +1.5% -> mover stop a break-even

COMMISSION_PCT = 0.001   # 0.1% por operacion
SPREAD_PCT = 0.0005      # 0.05% a cada lado

MIN_INDICATORS_CONFLUENCE = 3    # generico
XAU_MIN_INDICATORS_CONFLUENCE = 4  # oro: mas conservador

# ---------------------------------------------------------------------------
# Telegram (desactivado si faltan credenciales)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# ---------------------------------------------------------------------------
# APIs de datos
# ---------------------------------------------------------------------------
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

# ---------------------------------------------------------------------------
# General
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
TIMEZONE = os.getenv("TIMEZONE", "Europe/Madrid")
LOG_FILE = str(BASE_DIR / "bot.log")
DB_PATH = str(BASE_DIR / "database" / "trading_bot.db")

# ---------------------------------------------------------------------------
# Definicion de activos
# ---------------------------------------------------------------------------
ASSETS = {
    "XAU/USD": {
        "key": "XAU/USD",
        "yf_ticker": "GC=F",
        "type": "metal",
        "priority": 1,
        "max_allocation_pct": 0.40,
        "atr_stop_multiplier": 1.0,
        "main_timeframe": "15m",
        "confirm_timeframe": "1h",
        "update_interval_minutes": 5,
        "min_confluence": XAU_MIN_INDICATORS_CONFLUENCE,
        "trading_hours": (8, 22),          # horario CET 8:00-22:00
        "restrict_trading_hours": True,
        "weekend_caution": False,
    },
    "BTC/USD": {
        "key": "BTC/USD",
        "yf_ticker": "BTC-USD",
        "type": "crypto",
        "priority": 2,
        "max_allocation_pct": 0.25,
        "atr_stop_multiplier": 1.0,
        "main_timeframe": "4h",
        "confirm_timeframe": None,
        "update_interval_minutes": 15,
        "min_confluence": MIN_INDICATORS_CONFLUENCE,
        "trading_hours": None,             # 24/7
        "restrict_trading_hours": False,
        "weekend_caution": True,
    },
    "ETH/USD": {
        "key": "ETH/USD",
        "yf_ticker": "ETH-USD",
        "type": "crypto",
        "priority": 3,
        "max_allocation_pct": 0.20,
        "atr_stop_multiplier": 1.0,
        "main_timeframe": "4h",
        "confirm_timeframe": None,
        "update_interval_minutes": 15,
        "min_confluence": MIN_INDICATORS_CONFLUENCE,
        "trading_hours": None,
        "restrict_trading_hours": False,
        "weekend_caution": True,
        "correlate_with": "BTC/USD",
    },
    "SOL/USD": {
        "key": "SOL/USD",
        "yf_ticker": "SOL-USD",
        "type": "crypto",
        "priority": 4,
        "max_allocation_pct": 0.15,
        "atr_stop_multiplier": 1.5,
        "main_timeframe": "4h",
        "confirm_timeframe": None,
        "update_interval_minutes": 15,
        "min_confluence": MIN_INDICATORS_CONFLUENCE,
        "trading_hours": None,
        "restrict_trading_hours": False,
        "weekend_caution": True,
    },
}

ASSET_ORDER = sorted(ASSETS.keys(), key=lambda k: ASSETS[k]["priority"])
