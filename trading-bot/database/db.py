"""Capa de persistencia SQLite: trades, historial de balance, senales y resumenes diarios."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    asset TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantity REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    pnl REAL,
    balance_after REAL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN'
);

CREATE TABLE IF NOT EXISTS balance_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    balance REAL NOT NULL,
    equity REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS signals_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    asset TEXT NOT NULL,
    action TEXT NOT NULL,
    executed INTEGER NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS daily_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    trades_count INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    pnl REAL NOT NULL,
    win_rate REAL NOT NULL,
    ending_balance REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: str = config.DB_PATH):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------
    def insert_trade_open(
        self, opened_at: str, asset: str, side: str, entry_price: float,
        quantity: float, stop_loss: float, take_profit: float, reason: str,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO trades
                   (opened_at, asset, side, entry_price, quantity, stop_loss,
                    take_profit, reason, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')""",
                (opened_at, asset, side, entry_price, quantity, stop_loss, take_profit, reason),
            )
            return int(cur.lastrowid)

    def close_trade(self, trade_id: int, closed_at: str, exit_price: float, pnl: float, balance_after: float):
        with self._connect() as conn:
            conn.execute(
                """UPDATE trades
                   SET closed_at = ?, exit_price = ?, pnl = ?, balance_after = ?, status = 'CLOSED'
                   WHERE id = ?""",
                (closed_at, exit_price, pnl, balance_after, trade_id),
            )

    def update_trade_stop(self, trade_id: int, new_stop: float):
        with self._connect() as conn:
            conn.execute("UPDATE trades SET stop_loss = ? WHERE id = ?", (new_stop, trade_id))

    def get_open_trades(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM trades WHERE status = 'OPEN'").fetchall()

    def get_closed_trades(self, limit: int = 10) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM trades WHERE status = 'CLOSED' ORDER BY closed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def get_all_trades(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM trades ORDER BY opened_at DESC").fetchall()

    # ------------------------------------------------------------------
    # Balance history
    # ------------------------------------------------------------------
    def record_balance(self, timestamp: str, balance: float, equity: float):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO balance_history (timestamp, balance, equity) VALUES (?, ?, ?)",
                (timestamp, balance, equity),
            )

    def get_balance_history(self, limit: int = 200) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM balance_history ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()

    # ------------------------------------------------------------------
    # Signals log
    # ------------------------------------------------------------------
    def log_signal(self, timestamp: str, asset: str, action: str, executed: bool, reason: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO signals_log (timestamp, asset, action, executed, reason) VALUES (?, ?, ?, ?, ?)",
                (timestamp, asset, action, int(executed), reason),
            )

    def get_recent_signals(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM signals_log ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()

    # ------------------------------------------------------------------
    # Daily summary
    # ------------------------------------------------------------------
    def upsert_daily_summary(
        self, date_str: str, trades_count: int, wins: int, losses: int,
        pnl: float, win_rate: float, ending_balance: float,
    ):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO daily_summary (date, trades_count, wins, losses, pnl, win_rate, ending_balance)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(date) DO UPDATE SET
                     trades_count=excluded.trades_count, wins=excluded.wins, losses=excluded.losses,
                     pnl=excluded.pnl, win_rate=excluded.win_rate, ending_balance=excluded.ending_balance""",
                (date_str, trades_count, wins, losses, pnl, win_rate, ending_balance),
            )

    def get_daily_summaries(self, limit: int = 30) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM daily_summary ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()
