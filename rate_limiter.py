"""
rate_limiter.py — Простой in-memory rate limiter для защиты от злоупотреблений
"""
import time
import threading
from collections import defaultdict
from functools import wraps
from typing import Dict, Tuple

from flask import request, jsonify, session


class RateLimiter:
    """
    Простой rate limiter с использованием скользящего окна.
    Не требует Redis или внешних зависимостей.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients: Dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()
        self._cleanup_counter = 0

    def is_allowed(self, client_id: str, limit: int = None) -> Tuple[bool, int]:
        """
        Проверяет, разрешен ли запрос.
        Возвращает (разрешено, оставшееся_количество).
        """
        max_req = limit or self.max_requests
        now = time.time()

        with self._lock:
            # Очищаем старые записи
            self._clients[client_id] = [
                t for t in self._clients[client_id]
                if now - t < self.window_seconds
            ]

            # Проверяем лимит
            if len(self._clients[client_id]) >= max_req:
                remaining = 0
                allowed = False
            else:
                self._clients[client_id].append(now)
                remaining = max_req - len(self._clients[client_id])
                allowed = True

            # Периодическая очистка старых клиентов (каждые 100 проверок)
            self._cleanup_counter += 1
            if self._cleanup_counter > 100:
                self._cleanup()
                self._cleanup_counter = 0

            return allowed, remaining

    def _cleanup(self):
        """Удаляет клиентов с истекшими записями"""
        now = time.time()
        expired_clients = [
            client_id for client_id, timestamps in self._clients.items()
            if not timestamps or (now - timestamps[-1]) > self.window_seconds * 2
        ]
        for client_id in expired_clients:
            del self._clients[client_id]

    def get_stats(self) -> dict:
        """Возвращает статистику для мониторинга"""
        with self._lock:
            return {
                'total_clients': len(self._clients),
                'active_clients': sum(
                    1 for ts in self._clients.values()
                    if ts and time.time() - ts[-1] < self.window_seconds
                ),
                'window_seconds': self.window_seconds,
                'max_requests': self.max_requests,
            }


# Глобальные лимитеры
general_limiter = RateLimiter(max_requests=60)  # 60 запросов в минуту для всех
message_limiter = RateLimiter(max_requests=30)  # 30 сообщений в минуту
api_limiter = RateLimiter(max_requests=120)  # 120 API-запросов в минуту


def rate_limit(limiter: RateLimiter = None, limit: int = None):
    """
    Декоратор для ограничения частоты запросов.

    Использование:
        @rate_limit(message_limiter, limit=30)
        def send_message():
            ...
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Определяем идентификатор клиента
            client_id = session.get('address') or request.remote_addr or 'unknown'

            # Проверяем лимит
            current_limiter = limiter or general_limiter
            allowed, remaining = current_limiter.is_allowed(client_id, limit)

            if not allowed:
                retry_after = current_limiter.window_seconds
                return jsonify({
                    'error': 'Too many requests',
                    'retry_after': retry_after,
                    'limit': limit or current_limiter.max_requests,
                }), 429

            # Добавляем заголовки с информацией о лимитах
            response = f(*args, **kwargs)

            # Если это tuple (response, status_code) — обрабатываем
            if isinstance(response, tuple):
                resp, status = response
                if hasattr(resp, 'headers'):
                    resp.headers['X-RateLimit-Remaining'] = str(remaining)
                    resp.headers['X-RateLimit-Limit'] = str(limit or current_limiter.max_requests)
                return resp, status

            # Обычный response
            if hasattr(response, 'headers'):
                response.headers['X-RateLimit-Remaining'] = str(remaining)
                response.headers['X-RateLimit-Limit'] = str(limit or current_limiter.max_requests)

            return response

        return decorated_function

    return decorator


def get_rate_limit_stats() -> dict:
    """Возвращает статистику для админ-панели"""
    return {
        'general': general_limiter.get_stats(),
        'messages': message_limiter.get_stats(),
        'api': api_limiter.get_stats(),
    }