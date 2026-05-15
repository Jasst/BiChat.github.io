"""
services/notifier.py — Система уведомлений для Long Polling
Поддерживает ожидание сообщений до 25 секунд без блокировки потоков
"""
import time
import threading
import logging
from typing import Dict, List, Optional, Set
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)


class MessageNotifier:
    """
    Потокобезопасный менеджер уведомлений для Long Polling.
    Использует события threading.Event для эффективного ожидания.
    """

    def __init__(self, default_timeout: int = 25):
        self.default_timeout = default_timeout
        self._events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._cleanup_interval = 60  # Очистка старых событий раз в минуту
        self._last_cleanup = time.time()

    def get_event(self, user_address: str) -> threading.Event:
        """Получает или создаёт Event для пользователя"""
        with self._lock:
            if user_address not in self._events:
                self._events[user_address] = threading.Event()
            return self._events[user_address]

    def notify_user(self, user_address: str) -> None:
        """Уведомляет пользователя о новых сообщениях (пробуждает ожидающие запросы)"""
        with self._lock:
            if user_address in self._events:
                self._events[user_address].set()
                logger.debug(f"Notified {user_address[:16]}... about new messages")

    def notify_group(self, group_id: str, members: List[str]) -> None:
        """Уведомляет всех участников группы"""
        for member in members:
            self.notify_user(member)

    def wait_for_messages(self, user_address: str, timeout: int = None) -> bool:
        """
        Ожидает уведомление о новых сообщениях.
        Возвращает True, если уведомление получено, False при таймауте.
        """
        if timeout is None:
            timeout = self.default_timeout

        event = self.get_event(user_address)
        # Ожидаем событие или таймаут
        triggered = event.wait(timeout)

        # Сбрасываем событие для следующего ожидания
        if triggered:
            event.clear()

        self._cleanup_old_events()
        return triggered

    def _cleanup_old_events(self) -> None:
        """Периодически очищает старые события (экономия памяти)"""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        with self._lock:
            # Не очищаем активные события, только если их слишком много
            if len(self._events) > 10000:
                logger.warning(f"Cleaning up {len(self._events)} events")
                # Оставляем только последние 5000
                to_remove = list(self._events.keys())[:-5000]
                for addr in to_remove:
                    del self._events[addr]

        self._last_cleanup = now

    def get_stats(self) -> dict:
        """Статистика для мониторинга"""
        with self._lock:
            return {
                'active_events': len(self._events),
                'default_timeout': self.default_timeout,
            }


# Глобальный экземпляр (инициализируется в app.py)
message_notifier = MessageNotifier(default_timeout=25)