"""redis_manager.py — Redis для кэша, очередей и Pub/Sub"""
import asyncio
import redis.asyncio as redis
import json
import logging
from typing import Any, Optional, List, Dict
from datetime import datetime

from config_async import REDIS_URL, CACHE_TTL, LONG_POLLING_TIMEOUT

logger = logging.getLogger(__name__)


class RedisManager:
    """Менеджер Redis для всех задач"""

    def __init__(self):
        self.client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Подключается к Redis"""
        self.client = await redis.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=50,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        await self.client.ping()
        logger.info("✅ Redis connected")

    async def close(self) -> None:
        """Закрывает соединение"""
        if self.client:
            await self.client.aclose()
            logger.info("Redis closed")

    # =========================================================================
    # КЭШИРОВАНИЕ
    # =========================================================================

    async def cache_get(self, key: str) -> Optional[Any]:
        """Получает значение из кэша"""
        data = await self.client.get(key)
        if data:
            return json.loads(data)
        return None

    async def cache_set(self, key: str, value: Any, ttl: int = None) -> None:
        """Сохраняет значение в кэш"""
        if ttl is None:
            ttl = CACHE_TTL.get('balance', 30)
        await self.client.setex(key, ttl, json.dumps(value))

    async def cache_delete(self, key: str) -> None:
        """Удаляет ключ из кэша"""
        await self.client.delete(key)

    async def cache_delete_pattern(self, pattern: str) -> None:
        """Удаляет все ключи по паттерну"""
        keys = await self.client.keys(pattern)
        if keys:
            await self.client.delete(*keys)

    # =========================================================================
    # ОЧЕРЕДИ СООБЩЕНИЙ (для long polling)
    # =========================================================================

    async def queue_push(self, user_address: str, message: dict) -> None:
        """Добавляет сообщение в очередь пользователя"""
        key = f"queue:{user_address}"
        await self.client.lpush(key, json.dumps(message))
        await self.client.ltrim(key, 0, 99)  # максимум 100 сообщений

        # Уведомляем через Pub/Sub
        await self.client.publish(f"notify:{user_address}", "1")
        logger.debug(f"📦 Message queued for {user_address[:16]}...")

    async def queue_push_group(self, group_id: str, members: List[str],
                               message: dict, exclude_sender: str = None) -> None:
        """Добавляет сообщение в очередь всех участников группы"""
        for member in members:
            if member != exclude_sender:
                await self.queue_push(member, message)

    # FIX: метод отсутствовал — вызывался из messages_async.py
    async def notify_user(self, user_address: str) -> None:
        """Явно публикует уведомление без добавления в очередь.
        Используется, когда сообщение уже помещено через queue_push,
        но нужно дополнительно «разбудить» ожидающий long-poll запрос."""
        await self.client.publish(f"notify:{user_address}", "1")
        logger.debug(f"🔔 Notified {user_address[:16]}...")

    async def queue_pop(self, user_address: str, since_timestamp: float,
                        timeout: int = LONG_POLLING_TIMEOUT) -> tuple:
        """
        Получает сообщения из очереди с асинхронным ожиданием (long polling).

        ИСПРАВЛЕНИЕ: pubsub.get_message() в redis.asyncio не блокирует поток —
        оно возвращает None мгновенно, если сообщений нет.
        Правильный способ — итерировать pubsub.listen() под asyncio.wait_for(),
        что корректно ждёт событие без блокировки event loop.

        Возвращает: (messages, waited_time, had_notification)
        """
        key = f"queue:{user_address}"

        # 1. Проверяем уже накопленные сообщения
        messages = await self._drain_queue(key, since_timestamp)
        if messages:
            return messages, 0, True

        # 2. Подписываемся и ждём уведомление
        pubsub = self.client.pubsub()
        await pubsub.subscribe(f"notify:{user_address}")

        notified = False
        try:
            async def _wait_for_notification():
                """Итерирует pubsub до первого реального сообщения."""
                async for msg in pubsub.listen():
                    if msg.get("type") == "message":
                        return True
                return False  # на случай закрытия pubsub

            try:
                notified = await asyncio.wait_for(
                    _wait_for_notification(),
                    timeout=float(timeout)
                )
            except asyncio.TimeoutError:
                notified = False

        finally:
            await pubsub.unsubscribe(f"notify:{user_address}")
            await pubsub.aclose()

        if notified:
            messages = await self._drain_queue(key, since_timestamp)
            if messages:
                return messages, 0, True

        return [], timeout, False

    async def _drain_queue(self, key: str, since_timestamp: float) -> List[dict]:
        """Вычитывает сообщения из очереди, новее since_timestamp, и очищает её."""
        raw_messages = await self.client.lrange(key, 0, -1)
        if not raw_messages:
            return []

        result = []
        for raw in raw_messages:
            try:
                msg = json.loads(raw)
                if msg.get('timestamp', 0) > since_timestamp:
                    result.append(msg)
            except json.JSONDecodeError:
                logger.warning(f"Bad message in queue {key}: {raw!r}")

        if result:
            await self.client.delete(key)

        return result

    # =========================================================================
    # СЕССИИ (альтернатива Flask session)
    # =========================================================================

    async def session_get(self, session_id: str, key: str) -> Optional[Any]:
        """Получает значение из сессии"""
        data = await self.client.hget(f"session:{session_id}", key)
        if data:
            return json.loads(data)
        return None

    async def session_set(self, session_id: str, key: str, value: Any,
                          ttl: int = 86400) -> None:
        """Сохраняет значение в сессию"""
        await self.client.hset(f"session:{session_id}", key, json.dumps(value))
        await self.client.expire(f"session:{session_id}", ttl)

    async def session_get_all(self, session_id: str) -> dict:
        """Получает все данные сессии"""
        data = await self.client.hgetall(f"session:{session_id}")
        result = {}
        for k, v in data.items():
            try:
                result[k] = json.loads(v)
            except Exception:
                result[k] = v
        return result

    async def session_delete(self, session_id: str) -> None:
        """Удаляет сессию"""
        await self.client.delete(f"session:{session_id}")

    # =========================================================================
    # RATE LIMITING
    # =========================================================================

    async def rate_limit_check(self, key: str, limit: int, window: int = 60) -> tuple:
        """
        Проверяет rate limit.
        Возвращает (allowed, remaining, retry_after)
        """
        now = datetime.now().timestamp()
        window_key = f"rate:{key}:{int(now / window)}"

        current = await self.client.incr(window_key)
        if current == 1:
            await self.client.expire(window_key, window)

        if current > limit:
            ttl = await self.client.ttl(window_key)
            return False, 0, ttl

        return True, limit - current, 0

    # =========================================================================
    # СТАТУСЫ ПОЛЬЗОВАТЕЛЕЙ
    # =========================================================================

    async def set_user_status(self, address: str, status: str,
                              current_chat: str = "") -> None:
        """Устанавливает статус пользователя"""
        key = f"status:{address}"
        await self.client.hset(key, mapping={
            'status': status,
            'current_chat': current_chat,
            'last_seen': datetime.now().isoformat()
        })
        await self.client.expire(key, 120)  # TTL 2 минуты

    async def get_user_status(self, address: str) -> dict:
        """Получает статус пользователя"""
        key = f"status:{address}"
        data = await self.client.hgetall(key)
        if not data:
            return {'status': 'offline', 'current_chat': None, 'last_seen': None}
        return data

    async def get_many_statuses(self, addresses: List[str]) -> dict:
        """Получает статусы нескольких пользователей"""
        result = {}
        for addr in addresses:
            result[addr] = await self.get_user_status(addr)
        return result

    # =========================================================================
    # СТАТИСТИКА
    # =========================================================================

    async def get_stats(self) -> dict:
        """Возвращает статистику Redis"""
        info = await self.client.info()
        return {
            'connected': True,
            'used_memory': info.get('used_memory_human'),
            'total_connections': info.get('total_connections_received'),
            'keys': await self.client.dbsize(),
        }


# Глобальный экземпляр
redis_manager = RedisManager()