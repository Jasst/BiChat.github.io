"""
services/notifier.py — Асинхронный менеджер уведомлений (WebSocket + офлайн-буфер)
"""
import asyncio
import logging
from collections import defaultdict
from typing import Dict, List

logger = logging.getLogger(__name__)


class AsyncMessageNotifier:
    def __init__(self, max_buffer_size: int = 100):
        self.max_buffer_size = max_buffer_size
        self._buffers: Dict[str, List[dict]] = defaultdict(list)  # офлайн-буфер
        self._lock = asyncio.Lock()

    async def add_message(self, user_address: str, message: dict):
        """Отправляет сообщение через WebSocket, если пользователь онлайн, иначе в буфер."""
        from routes.ws import manager
        sent = await manager.send_personal_message(user_address, message)
        if not sent:
            async with self._lock:
                self._buffers[user_address].append(message)
                if len(self._buffers[user_address]) > self.max_buffer_size:
                    self._buffers[user_address] = self._buffers[user_address][-self.max_buffer_size:]
            logger.debug(f"User {user_address[:16]} offline, buffered message")
        else:
            logger.debug(f"Message sent via WebSocket to {user_address[:16]}")

    async def add_group_messages(self, group_id: str, members: List[str],
                                 message: dict, exclude_sender: str = None):
        for member in members:
            if member != exclude_sender:
                await self.add_message(member, message)

    async def get_offline_messages(self, user_address: str) -> List[dict]:
        """Возвращает все накопленные сообщения для пользователя и очищает буфер."""
        async with self._lock:
            msgs = self._buffers.pop(user_address, [])
        return msgs

    async def get_stats(self) -> dict:
        async with self._lock:
            return {
                'offline_buffers': len(self._buffers),
                'total_buffered': sum(len(b) for b in self._buffers.values()),
                'max_buffer_size': self.max_buffer_size,
            }


message_notifier = AsyncMessageNotifier(max_buffer_size=100)