"""Dashboard de terminal con rich: balance, posiciones abiertas, historial y estado por activo."""
from __future__ import annotations

from datetime import datetime

from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table

import config

console = Console()

NOTIFICATION_COLORS = {
    "BUY": "green", "WIN": "green", "LOSS": "red", "RISK": "bold red", "SUMMARY": "cyan",
}


def _fmt_money(value: float) -> str:
    return f"€{value:,.2f}"


def _header_panel(engine) -> Panel:
    portfolio = engine.portfolio
    prices = engine.current_prices()
    equity = portfolio.total_equity(prices)
    pnl = portfolio.total_pnl(prices)
    pnl_pct = portfolio.total_pnl_pct(prices)
    pnl_color = "green" if pnl >= 0 else "red"

    status = "DETENIDO (drawdown total)" if portfolio.bot_stopped else (
        "PAUSADO (drawdown diario)" if portfolio.daily_halt else "ACTIVO"
    )
    status_color = "red" if portfolio.bot_stopped else ("yellow" if portfolio.daily_halt else "green")

    text = (
        f"Balance en caja: {_fmt_money(portfolio.balance)}    "
        f"Equity total: {_fmt_money(equity)}    "
        f"P&L: [{pnl_color}]{_fmt_money(pnl)} ({pnl_pct:+.2f}%)[/{pnl_color}]    "
        f"Estado: [{status_color}]{status}[/{status_color}]"
    )
    return Panel(text, title="🤖 Trading Bot — Paper Trading (Demo)", border_style="blue")


def _positions_table(engine) -> Table:
    table = Table(title="Posiciones abiertas", expand=True)
    for col in ("Activo", "Entrada", "Actual", "Cantidad", "Stop-loss", "Take-profit", "P&L no realizado"):
        table.add_column(col)

    prices = engine.current_prices()
    if not engine.portfolio.open_positions:
        table.add_row("—", "—", "—", "—", "—", "—", "—")
    for pos in engine.portfolio.open_positions.values():
        current = prices.get(pos.asset, pos.entry_price)
        unrealized = (current - pos.entry_price) * pos.quantity
        color = "green" if unrealized >= 0 else "red"
        table.add_row(
            pos.asset, f"{pos.entry_price:.4f}", f"{current:.4f}", f"{pos.quantity:.6f}",
            f"{pos.stop_loss:.4f}", f"{pos.take_profit:.4f}",
            f"[{color}]{unrealized:+.2f}[/{color}]",
        )
    return table


def _closed_trades_table(db) -> Table:
    table = Table(title="Ultimas 10 operaciones cerradas", expand=True)
    for col in ("Cierre", "Activo", "Entrada", "Salida", "P&L", "Balance"):
        table.add_column(col)

    rows = db.get_closed_trades(10)
    if not rows:
        table.add_row("—", "—", "—", "—", "—", "—")
    for row in rows:
        pnl = row["pnl"] or 0.0
        color = "green" if pnl >= 0 else "red"
        closed_at = row["closed_at"] or ""
        table.add_row(
            closed_at[:16].replace("T", " "), row["asset"], f"{row['entry_price']:.4f}",
            f"{(row['exit_price'] or 0):.4f}", f"[{color}]{pnl:+.2f}[/{color}]",
            f"{(row['balance_after'] or 0):,.2f}",
        )
    return table


def _stats_panel(db) -> Panel:
    all_trades = db.get_all_trades()
    closed = [t for t in all_trades if t["status"] == "CLOSED"]
    total = len(closed)
    wins = sum(1 for t in closed if (t["pnl"] or 0) > 0)
    win_rate = (wins / total * 100) if total else 0.0
    best = max(closed, key=lambda t: t["pnl"] or 0, default=None)
    worst = min(closed, key=lambda t: t["pnl"] or 0, default=None)

    best_text = f"{best['asset']} {best['pnl']:+.2f}€" if best else "—"
    worst_text = f"{worst['asset']} {worst['pnl']:+.2f}€" if worst else "—"

    text = (
        f"Operaciones cerradas: {total}    Win rate: {win_rate:.1f}%\n"
        f"Mejor operacion: {best_text}    Peor operacion: {worst_text}"
    )
    return Panel(text, title="📈 Estadisticas", border_style="magenta")


def _assets_table(engine) -> Table:
    table = Table(title="Estado de los activos", expand=True)
    for col in ("Activo", "Precio", "Senal", "RSI", "ADX", "EMA9/EMA21", "MACD hist", "Actualizado"):
        table.add_column(col)

    for asset_key in config.ASSET_ORDER:
        state = engine.asset_state.get(asset_key)
        if not state:
            table.add_row(asset_key, "—", "—", "—", "—", "—", "—", "sin datos")
            continue
        ind = state["indicators"]
        signal_color = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(state["signal"], "white")
        table.add_row(
            asset_key, f"{state['last_price']:.4f}",
            f"[{signal_color}]{state['signal']}[/{signal_color}]",
            f"{ind['rsi14']:.1f}", f"{ind['adx14']:.1f}",
            f"{ind['ema9']:.2f} / {ind['ema21']:.2f}", f"{ind['macd_hist']:.4f}",
            state["updated_at"].strftime("%H:%M:%S"),
        )
    return table


def _notifications_panel(engine, limit: int = 8) -> Panel:
    """Panel con las mismas alertas que se enviarian por Telegram (senales, cierres,
    avisos de riesgo y resumen diario), para verlas directamente en la app."""
    items = engine.notifications.recent(limit)
    if not items:
        body = "[dim]Sin notificaciones todavia.[/dim]"
    else:
        blocks = []
        for n in items:
            color = NOTIFICATION_COLORS.get(n.level, "white")
            ts = n.timestamp.strftime("%H:%M:%S")
            blocks.append(f"[dim]{ts}[/dim]\n[{color}]{n.text}[/{color}]")
        body = f"\n[dim]{'─' * 30}[/dim]\n".join(blocks)
    return Panel(body, title="🔔 Notificaciones", border_style="yellow")


def _main_group(engine, db) -> Group:
    return Group(
        _header_panel(engine),
        _positions_table(engine),
        _closed_trades_table(db),
        _stats_panel(db),
        _assets_table(engine),
    )


def build_dashboard(engine, db) -> Group:
    """Vista de una sola columna (usada en el modo de impresion simple, sin --dashboard)."""
    return Group(_main_group(engine, db), _notifications_panel(engine))


def build_live_layout(engine, db) -> Layout:
    """Vista de dos columnas para --dashboard: contenido principal a la izquierda,
    notificaciones a la derecha."""
    layout = Layout()
    layout.split_row(
        Layout(name="main", ratio=3),
        Layout(name="notifications", ratio=1, minimum_size=34),
    )
    layout["main"].update(_main_group(engine, db))
    layout["notifications"].update(_notifications_panel(engine, limit=12))
    return layout


def print_snapshot(engine, db):
    console.print(build_dashboard(engine, db))


def print_history(db, limit: int = 50):
    table = Table(title=f"Historial de operaciones (ultimas {limit})", expand=True)
    for col in ("ID", "Abierta", "Cerrada", "Activo", "Entrada", "Salida", "Cantidad", "P&L", "Estado", "Razon"):
        table.add_column(col)
    for row in db.get_all_trades()[:limit]:
        pnl = row["pnl"]
        pnl_text = f"{pnl:+.2f}" if pnl is not None else "—"
        table.add_row(
            str(row["id"]), (row["opened_at"] or "")[:16].replace("T", " "),
            (row["closed_at"] or "—")[:16].replace("T", " "), row["asset"],
            f"{row['entry_price']:.4f}", f"{(row['exit_price'] or 0):.4f}" if row["exit_price"] else "—",
            f"{row['quantity']:.6f}", pnl_text, row["status"], (row["reason"] or "")[:40],
        )
    console.print(table)


def print_summary(db):
    all_trades = db.get_all_trades()
    closed = [t for t in all_trades if t["status"] == "CLOSED"]
    total = len(closed)
    wins = sum(1 for t in closed if (t["pnl"] or 0) > 0)
    losses = total - wins
    win_rate = (wins / total * 100) if total else 0.0
    total_pnl = sum((t["pnl"] or 0) for t in closed)
    best = max(closed, key=lambda t: t["pnl"] or 0, default=None)
    worst = min(closed, key=lambda t: t["pnl"] or 0, default=None)

    balance_rows = db.get_balance_history(1)
    current_balance = balance_rows[0]["balance"] if balance_rows else config.INITIAL_BALANCE
    current_equity = balance_rows[0]["equity"] if balance_rows else config.INITIAL_BALANCE

    best_text = f"{best['asset']} {best['pnl']:+.2f}€" if best else "—"
    worst_text = f"{worst['asset']} {worst['pnl']:+.2f}€" if worst else "—"

    text = (
        f"Balance inicial: {_fmt_money(config.INITIAL_BALANCE)}\n"
        f"Balance actual:  {_fmt_money(current_balance)}\n"
        f"Equity actual:   {_fmt_money(current_equity)}\n"
        f"P&L total:       {_fmt_money(current_equity - config.INITIAL_BALANCE)} "
        f"({(current_equity - config.INITIAL_BALANCE) / config.INITIAL_BALANCE * 100:+.2f}%)\n\n"
        f"Operaciones cerradas: {total}   Ganadoras: {wins}   Perdedoras: {losses}\n"
        f"Win rate: {win_rate:.1f}%\n"
        f"P&L acumulado en operaciones cerradas: {_fmt_money(total_pnl)}\n"
        f"Mejor operacion: {best_text}\n"
        f"Peor operacion: {worst_text}\n"
    )
    console.print(Panel(text, title="📊 Resumen de rendimiento", border_style="cyan"))
