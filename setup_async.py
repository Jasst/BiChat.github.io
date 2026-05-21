# =============================================================================
# setup_async.py — Адаптированный модуль для асинхронной версии (Quart + Redis)
# =============================================================================

import hashlib
import base64
import hmac
import json
import logging
import logging.handlers
import os
import time
from collections import defaultdict
from functools import wraps
from typing import Optional, Tuple, Dict, Any, List

# Сторонние библиотеки
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from quart import request, jsonify
from marshmallow import Schema, fields, ValidationError, post_load

# Локальный конфиг
from config_async import (
    RATE_LIMIT_REQUESTS, RATE_LIMIT_MESSAGES, RATE_LIMIT_API,
    LOG_MAX_BYTES, LOG_BACKUP_COUNT
)

# Redis для rate limiting
from redis_manager import redis_manager

logger = logging.getLogger(__name__)

# =============================================================================
# КРИПТОГРАФИЯ (без изменений, работает с Quart)
# =============================================================================

CURVE = ec.SECP256R1()


def load_public_key_from_bytes(pubkey_bytes: bytes):
    """Загружает публичный ключ из байтов"""
    return ec.EllipticCurvePublicKey.from_encoded_point(CURVE, pubkey_bytes)


def load_public_key_from_b64(pubkey_b64: str):
    """Загружает публичный ключ из base64"""
    return load_public_key_from_bytes(base64.b64decode(pubkey_b64))


def verify_address_matches_pubkey(address: str, pubkey_b64: str) -> bool:
    """Проверяет соответствие адреса публичному ключу"""
    try:
        pubkey_bytes = base64.b64decode(pubkey_b64)
        computed = hashlib.sha256(pubkey_bytes).hexdigest()
        return hmac.compare_digest(computed, address)
    except Exception:
        return False


def get_cache_info() -> dict:
    """Информация о кэше (теперь Redis)"""
    return {"status": "Redis cache active", "type": "distributed"}


# =============================================================================
# ЛОГИРОВАНИЕ (асинхронно-совместимое)
# =============================================================================

def setup_logging() -> logging.Logger:
    """Настройка логирования (совместимо с Quart)"""
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'messenger.log')

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding='utf-8',
        delay=True,
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

    is_prod = os.getenv('FLASK_ENV') == 'production'
    log_level = logging.WARNING if is_prod else logging.INFO
    handlers = [file_handler] if is_prod else [file_handler, console_handler]

    logging.basicConfig(level=log_level, handlers=handlers, force=True)

    # Настройка логгеров
    logging.getLogger('quart').setLevel(logging.WARNING)
    logging.getLogger('hypercorn').setLevel(logging.WARNING)
    logging.getLogger('cryptography').setLevel(logging.WARNING)
    logging.getLogger('asyncpg').setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.warning(f"=== Async App started, log path: {log_path} ===")
    return logger


# =============================================================================
# RATE LIMITER (Redis-based, асинхронный)
# =============================================================================

class AsyncRateLimiter:
    """
    Асинхронный rate limiter на Redis.
    Заменяет синхронную версию из setup.py
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def is_allowed(self, client_id: str, limit: int = None) -> Tuple[bool, int, int]:
        """
        Проверяет rate limit.
        Returns: (allowed, remaining, retry_after)
        """
        max_req = limit or self.max_requests
        now = int(time.time())
        window_key = now // self.window_seconds
        key = f"rate:{client_id}:{window_key}"

        current = await redis_manager.client.incr(key)
        if current == 1:
            await redis_manager.client.expire(key, self.window_seconds)

        if current > max_req:
            ttl = await redis_manager.client.ttl(key)
            return False, 0, ttl

        return True, max_req - current, 0

    async def get_stats(self) -> dict:
        """Статистика (приблизительная)"""
        # Получаем все ключи rate limiting
        keys = await redis_manager.client.keys("rate:*")
        return {
            'type': 'redis',
            'total_keys': len(keys),
            'window_seconds': self.window_seconds,
            'max_requests': self.max_requests,
        }


# Глобальные экземпляры
general_limiter = AsyncRateLimiter(max_requests=RATE_LIMIT_REQUESTS, window_seconds=60)
message_limiter = AsyncRateLimiter(max_requests=RATE_LIMIT_MESSAGES, window_seconds=60)
api_limiter = AsyncRateLimiter(max_requests=RATE_LIMIT_API, window_seconds=60)


def rate_limit(limiter: AsyncRateLimiter = None, limit: int = None):
    """
    Декоратор rate limiting для асинхронных Quart эндпоинтов.

    Использование:
        @rate_limit(limit=30)
        async def my_endpoint():
            ...
    """

    def decorator(f):
        @wraps(f)
        async def decorated_function(*args, **kwargs):
            # Определяем клиента
            session_id = request.cookies.get('session_id')
            client_id = None

            if session_id:
                client_id = await redis_manager.session_get(session_id, 'address')

            if not client_id:
                client_id = request.remote_addr or 'unknown'

            # Выбираем лимитер
            current_limiter = limiter or general_limiter
            max_req = limit or current_limiter.max_requests

            # Проверяем лимит
            allowed, remaining, retry_after = await current_limiter.is_allowed(client_id, max_req)

            if not allowed:
                response = await jsonify({
                    'error': 'Too many requests',
                    'retry_after': retry_after,
                    'limit': max_req,
                })
                response.status_code = 429
                response.headers['X-RateLimit-Remaining'] = '0'
                response.headers['X-RateLimit-Limit'] = str(max_req)
                response.headers['Retry-After'] = str(retry_after)
                return response

            # Выполняем оригинальную функцию
            response = await f(*args, **kwargs)

            # Добавляем заголовки
            if hasattr(response, 'headers'):
                response.headers['X-RateLimit-Remaining'] = str(remaining)
                response.headers['X-RateLimit-Limit'] = str(max_req)

            return response

        return decorated_function

    return decorator


async def get_rate_limit_stats() -> dict:
    """Возвращает статистику всех rate limiters"""
    return {
        'general': await general_limiter.get_stats(),
        'messages': await message_limiter.get_stats(),
        'api': await api_limiter.get_stats(),
    }


# =============================================================================
# SCHEMAS (Marshmallow) — без изменений
# =============================================================================

class WalletSchema(Schema):
    """Схема для создания кошелька"""
    mnemonic_phrase = fields.Str(
        required=True,
        load_only=True,
        validate=lambda x: len(x.strip()) >= 24,
    )

    @post_load
    def strip(self, data, **kwargs):
        data['mnemonic_phrase'] = data['mnemonic_phrase'].strip()
        return data


class MessageSchema(Schema):
    """Схема для отправки сообщения"""
    recipient = fields.Str(
        required=True,
        validate=lambda x: len(x) == 64 or x.startswith('group:')
    )
    content = fields.Str(required=True, allow_none=False)
    image = fields.Str(allow_none=True)
    message_type = fields.Str(
        load_default='direct',
        validate=lambda x: x in ('direct', 'group')
    )
    group_id = fields.Str(allow_none=True)


class GroupSchema(Schema):
    """Схема для создания группы"""
    name = fields.Str(
        required=True,
        validate=lambda x: 1 <= len(x.strip()) <= 100
    )
    members = fields.List(
        fields.Str(),
        required=True,
        validate=lambda x: 1 <= len(x) <= 50
    )


class ContactSchema(Schema):
    """Схема для добавления контакта"""
    address = fields.Str(
        required=True,
        validate=lambda x: len(x) == 64
    )
    name = fields.Str(
        required=True,
        validate=lambda x: 1 <= len(x) <= 50
    )


class EditContactSchema(Schema):
    """Схема для редактирования контакта"""
    address = fields.Str(
        required=True,
        validate=lambda x: len(x) == 64
    )
    name = fields.Str(
        required=True,
        validate=lambda x: 1 <= len(x.strip()) <= 50
    )

    @post_load
    def strip_fields(self, data, **kwargs):
        data['name'] = data['name'].strip()
        data['address'] = data['address'].strip().lower()
        return data


class DeleteMessageSchema(Schema):
    """Схема для удаления сообщения"""
    message_id = fields.Int(
        required=True,
        validate=lambda x: x > 0
    )


class TransferSchema(Schema):
    """Схема для перевода монет"""
    recipient = fields.Str(
        required=True,
        validate=lambda x: len(x) == 64
    )
    amount = fields.Int(
        required=True,
        validate=lambda x: x > 0
    )


class StakeSchema(Schema):
    """Схема для стейкинга"""
    amount = fields.Int(
        required=True,
        validate=lambda x: x >= 10_000_000  # MIN_STAKE_AMOUNT
    )


class MineSchema(Schema):
    """Схема для майнинга"""
    proof = fields.Int(required=True)
    challenge = fields.Str(required=True)
    last_proof = fields.Int(required=True)
    last_index = fields.Int(required=True)


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def validate_address(address: str) -> bool:
    """Проверяет валидность адреса"""
    return len(address) == 64 and all(c in '0123456789abcdef' for c in address)


def validate_group_id(group_id: str) -> bool:
    """Проверяет валидность ID группы"""
    return len(group_id) == 32 and all(c in '0123456789abcdef' for c in group_id)


def sanitize_string(text: str, max_length: int = 1000) -> str:
    """Очищает строку от непечатаемых символов"""
    if not text:
        return ""
    return ''.join(c for c in text if ord(c) >= 32 and ord(c) != 127)[:max_length]


def truncate_address(address: str, length: int = 10) -> str:
    """Обрезает адрес для логов"""
    if not address:
        return "unknown"
    return address[:length] + "..." if len(address) > length else address


# =============================================================================
# ЭКСПОРТЫ (для обратной совместимости)
# =============================================================================

# Сохраняем старые имена для совместимости с некоторыми импортами
balance_cache = None  # Заменён на Redis
contact_cache = None  # Заменён на Redis
group_cache = None  # Заменён на Redis


def cached_query(cache, key_prefix=""):
    """Заглушка для совместимости (используйте Redis напрямую)"""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def invalidate_user_caches(address: str) -> None:
    """Инвалидирует кэш пользователя в Redis"""
    import asyncio
    from redis_manager import redis_manager

    async def _invalidate():
        await redis_manager.cache_delete_pattern(f"balance:{address}")
        await redis_manager.cache_delete_pattern(f"contacts:{address}")
        await redis_manager.cache_delete_pattern(f"groups:{address}")
        await redis_manager.cache_delete_pattern(f"pubkey:{address}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_invalidate())
        else:
            loop.run_until_complete(_invalidate())
    except Exception as e:
        logger.warning(f"Failed to invalidate caches for {address}: {e}")