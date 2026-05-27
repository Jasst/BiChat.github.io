"""
services/notifier.py — Асинхронный менеджер уведомлений для Long Polling (asyncio.Event)
"""
import asyncio
import logging
import time
from collections import defaultdict
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class AsyncMessageNotifier:
    def __init__(self, default_timeout: int = 25, max_buffer_size: int = 100):
        self.default_timeout = default_timeout
        self.max_buffer_size = max_buffer_size
        self._buffers: Dict[str, List[dict]] = defaultdict(list)
        self._events: Dict[str, asyncio.Event] = defaultdict(asyncio.Event)
        self._lock = asyncio.Lock()

    async def add_message(self, user_address: str, message: dict) -> None:
        async with self._lock:
            self._buffers[user_address].append(message)
            if len(self._buffers[user_address]) > self.max_buffer_size:
                self._buffers[user_address] = self._buffers[user_address][-self.max_buffer_size:]
            self._events[user_address].set()
            logger.debug(f"Buffered msg for {user_address[:16]}..., buf={len(self._buffers[user_address])}")

    async def add_group_messages(self, group_id: str, members: List[str],
                                 message: dict, exclude_sender: str = None) -> None:
        for member in members:
            if member != exclude_sender:
                await self.add_message(member, message)

    async def notify_user(self, user_address: str) -> None:
        async with self._lock:
            self._events[user_address].set()

    async def notify_group(self, group_id: str, members: List[str]) -> None:
        for member in members:
            await self.notify_user(member)

    async def force_check(self, user_address: str) -> None:
        await self.notify_user(user_address)

    async def get_messages(self, user_address: str,
                           since_timestamp: float,
                           timeout: int = None) -> Tuple[List[dict], float, bool]:
        if timeout is None:
            timeout = self.default_timeout
        async with self._lock:
            buffer = self._buffers.get(user_address, [])
            new_messages = [m for m in buffer if m.get('timestamp', 0) > since_timestamp]
            if new_messages:
                last_ts = max(m.get('timestamp', 0) for m in new_messages)
                self._buffers[user_address] = [m for m in buffer if m.get('timestamp', 0) > last_ts]
                logger.debug(f"Returning {len(new_messages)} buffered msgs (immediate)")
                return new_messages, 0.0, False
            event = self._events[user_address]
            event.clear()
        try:
            await asyncio.wait_for(event.wait(), timeout)
            triggered = True
            waited = 0.0
        except asyncio.TimeoutError:
            triggered = False
            waited = float(timeout)
        async with self._lock:
            buffer = self._buffers.get(user_address, [])
            new_messages = [m for m in buffer if m.get('timestamp', 0) > since_timestamp]
            if new_messages:
                last_ts = max(m.get('timestamp', 0) for m in new_messages)
                self._buffers[user_address] = [m for m in buffer if m.get('timestamp', 0) > last_ts]
        return new_messages, waited, triggered

    async def get_stats(self) -> dict:
        async with self._lock:
            return {
                'active_events': len(self._events),
                'total_buffered': sum(len(b) for b in self._buffers.values()),
                'active_users': len(self._buffers),
                'default_timeout': self.default_timeout,
                'max_buffer_size': self.max_buffer_size,
            }


message_notifier = AsyncMessageNotifier(default_timeout=25, max_buffer_size=100)