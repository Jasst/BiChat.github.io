"""
services/notifier.py — Буферизованный менеджер уведомлений для Long Polling.
Потокобезопасен: sync-роуты (threadpool) могут безопасно вызывать add_message().
Async long-polling использует run_in_executor для ожидания.
"""
import logging
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class MessageNotifier:
    """
    Потокобезопасный менеджер уведомлений с буферизацией сообщений.
    Sync-совместимый: работает как из threadpool FastAPI, так и из async через executor.
    """

    def __init__(self, default_timeout: int = 25, max_buffer_size: int = 100):
        self.default_timeout  = default_timeout
        self.max_buffer_size  = max_buffer_size
        self._events:          Dict[str, threading.Event] = {}
        self._buffers:         Dict[str, List[dict]]      = defaultdict(list)
        self._last_timestamps: Dict[str, float]           = {}
        self._lock            = threading.Lock()
        self._cleanup_counter = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_event(self, user_address: str) -> threading.Event:
        if user_address not in self._events:
            self._events[user_address] = threading.Event()
        return self._events[user_address]

    # ------------------------------------------------------------------
    # Public: add messages (called from sync send_message routes)
    # ------------------------------------------------------------------

    def add_message(self, user_address: str, message: dict) -> None:
        with self._lock:
            self._buffers[user_address].append(message)
            if len(self._buffers[user_address]) > self.max_buffer_size:
                self._buffers[user_address] = self._buffers[user_address][-self.max_buffer_size:]
            self._get_event(user_address).set()
            logger.debug(
                f"Buffered msg for {user_address[:16]}..., "
                f"buf={len(self._buffers[user_address])}"
            )

    def add_group_messages(self, group_id: str, members: List[str],
                           message: dict, exclude_sender: str = None) -> None:
        for member in members:
            if member != exclude_sender:
                self.add_message(member, message)

    def notify_user(self, user_address: str) -> None:
        with self._lock:
            self._get_event(user_address).set()

    def notify_group(self, group_id: str, members: List[str]) -> None:
        for member in members:
            self.notify_user(member)

    def force_check(self, user_address: str) -> None:
        with self._lock:
            self._get_event(user_address).set()

    # ------------------------------------------------------------------
    # Public: wait for messages (blocking — use run_in_executor in async routes)
    # ------------------------------------------------------------------

    def get_messages(self, user_address: str,
                     since_timestamp: float,
                     timeout: int = None) -> Tuple[List[dict], int, bool]:
        """
        Returns (messages, waited_seconds, was_notified).
        Blocks for up to `timeout` seconds.
        Safe to call from a threadpool executor.
        """
        if timeout is None:
            timeout = self.default_timeout

        with self._lock:
            self._last_timestamps[user_address] = since_timestamp
            buffer       = self._buffers.get(user_address, [])
            new_messages = [m for m in buffer if m.get('timestamp', 0) > since_timestamp]

            if new_messages:
                last_ts = max(m.get('timestamp', 0) for m in new_messages)
                self._buffers[user_address] = [m for m in buffer if m.get('timestamp', 0) > last_ts]
                logger.debug(f"Returning {len(new_messages)} buffered msgs (immediate)")
                return new_messages, 0, False

            # Prepare to wait — clear the event under lock so we don't miss a signal
            event = self._get_event(user_address)
            event.clear()

        # Wait outside the lock so other threads can call add_message()
        triggered = event.wait(timeout)

        with self._lock:
            if triggered:
                event.clear()
            buffer       = self._buffers.get(user_address, [])
            new_messages = [m for m in buffer if m.get('timestamp', 0) > since_timestamp]
            if new_messages:
                last_ts = max(m.get('timestamp', 0) for m in new_messages)
                self._buffers[user_address] = [m for m in buffer if m.get('timestamp', 0) > last_ts]

            self._cleanup_counter += 1
            if self._cleanup_counter >= 100:
                self._cleanup_old_buffers()
                self._cleanup_counter = 0

        return new_messages, (0 if triggered else timeout), triggered

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup_old_buffers(self) -> None:
        one_hour_ago = time.time() - 3600
        to_delete = [
            addr for addr, ts in self._last_timestamps.items()
            if ts < one_hour_ago
        ]
        for addr in to_delete:
            self._buffers.pop(addr, None)
            self._events.pop(addr, None)
            self._last_timestamps.pop(addr, None)
        if to_delete:
            logger.debug(f"Cleaned up {len(to_delete)} inactive buffers")

    def get_stats(self) -> dict:
        with self._lock:
            return {
                'active_events':  len(self._events),
                'total_buffered': sum(len(b) for b in self._buffers.values()),
                'active_users':   len(self._buffers),
                'default_timeout': self.default_timeout,
                'max_buffer_size': self.max_buffer_size,
            }


# Singleton
message_notifier = MessageNotifier(default_timeout=25, max_buffer_size=100)