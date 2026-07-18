# Trading Bot Demo — Paper Trading

Bot de trading en **papel** (dinero virtual, sin conexion a ningun exchange real)
que opera automaticamente sobre **XAU/USD** (oro), **BTC/USD**, **ETH/USD** y
**SOL/USD** usando analisis tecnico multi-indicador con gestion de riesgo
conservadora.

> ⚠️ Esto es una demo educativa de paper trading. No ejecuta ordenes reales,
> no requiere ninguna API de pago y no debe usarse como asesoramiento
> financiero.

## Arquitectura

```
trading-bot/
├── main.py                  # Punto de entrada, loop principal, CLI
├── config.py                # Configuracion (balance, riesgo, activos, timeframes)
├── strategy/
│   ├── technical.py         # EMA, MACD, RSI, StochRSI, Bollinger, ATR, ADX
│   ├── signals.py           # Generador de senales BUY/SELL/HOLD
│   └── risk_manager.py      # Position sizing, stop-loss/take-profit, drawdown
├── data/
│   └── price_feed.py        # yfinance + respaldo Twelve Data
├── trading/
│   ├── paper_engine.py      # Ejecucion virtual (spread, comision)
│   └── portfolio.py         # Balance, posiciones abiertas, historial en memoria
├── notifications/
│   └── telegram_bot.py      # Alertas por Telegram (desactivado por defecto)
├── database/
│   └── db.py                # SQLite: trades, balance_history, signals_log, daily_summary
├── dashboard/
│   └── terminal_ui.py       # Dashboard en terminal (rich)
├── requirements.txt
├── .env.example
└── README.md
```

## Instalacion

Requiere Python 3.10+.

```bash
cd trading-bot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env            # opcional: ajusta balance, riesgo, Telegram, etc.
```

## Ejecucion

```bash
# Loop principal (imprime un snapshot del dashboard en cada iteracion)
python main.py

# Dashboard interactivo en vivo (pantalla completa, se refresca solo)
python main.py --dashboard

# Ver historial completo de operaciones
python main.py --history

# Ver resumen de rendimiento (balance, P&L, win rate, mejor/peor trade)
python main.py --summary
```

Para detener el bot en cualquier momento: `Ctrl+C`. El cierre es limpio, no
corrompe el estado ni dejas posiciones a medio guardar.

## Que hace el bot

- Arranca con un balance virtual configurable (por defecto **1.000 €**).
- Descarga velas OHLCV con `yfinance` (`GC=F` para oro, `BTC-USD`, `ETH-USD`,
  `SOL-USD` para las cripto). Si `yfinance` falla al pedir XAU/USD y hay una
  `TWELVE_DATA_API_KEY` configurada, usa Twelve Data como respaldo.
- Calcula EMA 9/21/50/200, MACD, RSI, Stochastic RSI, Bandas de Bollinger,
  ATR y ADX sobre cada activo.
- Genera senales BUY/SELL/HOLD exigiendo confluencia de varios indicadores
  (4 minimo para XAU/USD, que es el activo prioritario y mas conservador; 3
  para el resto). Nunca opera si no hay confluencia suficiente.
- Calcula el tamano de posicion arriesgando como maximo el **2% del balance**
  por operacion, con un maximo de **3 posiciones simultaneas** y limites de
  asignacion de capital por activo (40% XAU, 25% BTC, 20% ETH, 15% SOL).
- Pone stop-loss basado en ATR (1.0x, o 1.5x en SOL por su volatilidad) y
  take-profit con ratio riesgo/beneficio 1:2. Cuando una posicion lleva
  +1.5% de beneficio, mueve el stop a break-even.
- Si el balance cae un 5% en un dia, deja de abrir operaciones nuevas hasta
  el dia siguiente. Si cae un 15% desde el balance inicial, el bot se
  detiene por completo.
- Simula comisiones (0.1%) y spread (0.05% en cada sentido) para que el
  resultado sea realista.
- Guarda cada operacion, cada senal (ejecutada o no, con el motivo) y el
  balance historico en SQLite (`database/trading_bot.db`).
- Registra toda la actividad en `bot.log`.

## Telegram (opcional, desactivado por defecto)

El bot funciona perfectamente sin Telegram. Para activarlo:

1. Crea un bot con [@BotFather](https://t.me/BotFather) y copia el token.
2. Consigue tu `chat_id` (por ejemplo escribiendo a
   [@userinfobot](https://t.me/userinfobot)).
3. Rellena `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en tu `.env`.

Con eso activado, el bot avisa al abrir/cerrar operaciones, al activarse el
freno por drawdown diario/total y con un resumen diario a las 23:00 (hora
`Europe/Madrid` por defecto, configurable con `TIMEZONE`).

## Notas sobre los datos

- XAU/USD se actualiza cada 5 minutos (timeframe principal 15m, confirmacion
  en 1h) y solo opera entre las 8:00 y las 22:00 CET.
- BTC/USD, ETH/USD y SOL/USD se actualizan cada 15 minutos sobre velas de 4h
  (construidas a partir de velas de 1h de yfinance, ya que yfinance no ofrece
  el intervalo 4h de forma nativa). Operan 24/7, con mas cautela los fines de
  semana (exigen ADX mas alto) por el spread mas ancho habitual.
- ETH/USD no compra si BTC/USD esta cayendo con fuerza (>3% en la ultima
  vela), para evitar operar contra la correlacion del mercado cripto.

## Limitaciones conocidas

- yfinance depende de Yahoo Finance; si Yahoo cambia su API o hay cortes de
  red, el bot reintenta con backoff y cae a datos en cache o (solo para
  XAU/USD) a Twelve Data. Si todo falla, se salta esa actualizacion sin
  crashear.
- Es una demo de paper trading: nunca coloca ordenes reales ni requiere
  credenciales de ningun bróker o exchange.
