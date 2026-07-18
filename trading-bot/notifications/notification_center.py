"""Cola en memoria con las alertas que el bot genera (senales, cierres, riesgo,
resumen diario), para mostrarlas directamente en el dashboard de la app."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Optional

MAX_NOTIFICATIONS = 50


@dataclass
class Notification:
    timestamp: datetime
    level: str   # "BUY" | "WIN" | "LOSS" | "RISK" | "SUMMARY"
    text: str


class NotificationCenter:
    def __init__(self, max_items: int = MAX_NOTIFICATIONS):
        self._items: Deque[Notification] = deque(maxlen=max_items)

    def add(self, level: str, text: str, timestamp: Optional[datetime] = None) -> Notification:
        notification = Notification(timestamp or datetime.now(), level, text)
        self._items.appendleft(notification)
        return notification

    def recent(self, limit: int = 10) -> list[Notification]:
        return list(self._items)[:limit]
