"""
services/notifier.py — Асинхронный менеджер уведомлений (WebSocket + офлайн-буфер)
"""
import asyncio
import logging
import json
import time
from collections import defaultdict
from typing import Dict, List

logger = logging.getLogger(__name__)


class AsyncMessageNotifier:
    def __init__(self, max_buffer_size: int = 100):
        self.max_buffer_size = max_buffer_size
        # _buffers больше не нужен, всё храним в БД

    async def add_message(self, user_address: str, message: dict):
        """Сохраняет сообщение в БД, если пользователь не онлайн, иначе отправляет сразу."""
        from routes.ws import manager
        sent = await manager.send_personal_message(user_address, message)
        if not sent:
            from database import get_db_cursor
            async with get_db_cursor() as conn:
                await conn.execute(
                    "INSERT INTO offline_messages (user_address, payload, created_at) VALUES ($1, $2, $3)",
                    user_address, json.dumps(message), time.time()
                )
            logger.debug(f"User {user_address[:16]} offline, saved to DB")
        else:
            logger.debug(f"Message sent via WebSocket to {user_address[:16]}")

    async def add_group_messages(self, group_id: str, members: List[str],
                                 message: dict, exclude_sender: str = None):
        for member in members:
            if member != exclude_sender:
                await self.add_message(member, message)

    async def get_offline_messages(self, user_address: str) -> List[dict]:
        """Возвращает все накопленные сообщения из БД и удаляет их."""
        from database import get_db_cursor
        async with get_db_cursor() as conn:
            rows = await conn.fetch(
                "SELECT payload FROM offline_messages WHERE user_address = $1 ORDER BY created_at ASC",
                user_address
            )
            await conn.execute("DELETE FROM offline_messages WHERE user_address = $1", user_address)
        return [json.loads(row['payload']) for row in rows]

    async def get_stats(self) -> dict:
        from database import get_db_cursor
        async with get_db_cursor() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM offline_messages")
            return {
                'offline_buffers': count,  # приблизительно
                'total_buffered': count,
                'max_buffer_size': self.max_buffer_size,
            }


message_notifier = AsyncMessageNotifier(max_buffer_size=100)