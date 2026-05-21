"""middleware.py — Промежуточные слои для асинхронного приложения"""
import time
import logging
from quart import request, jsonify, g
from functools import wraps

from redis_manager import redis_manager
from config_async import RATE_LIMIT_REQUESTS

logger = logging.getLogger(__name__)


class RateLimitMiddleware:
    """Rate limiting middleware"""

    async def __call__(self, request, call_next):
        # Получаем IP или адрес пользователя
        client_id = request.remote_addr

        # Публичные эндпоинты не лимитируем
        public_endpoints = ['/health', '/metrics', '/login', '/create_wallet', '/login/nonce']
        if request.path in public_endpoints:
            return await call_next(request)

        # Проверяем лимит
        allowed, remaining, retry_after = await redis_manager.rate_limit_check(
            f"rate:{client_id}", RATE_LIMIT_REQUESTS, 60
        )

        if not allowed:
            response = await jsonify({
                'error': 'Too many requests',
                'retry_after': retry_after
            })
            response.status_code = 429
            response.headers['X-RateLimit-Remaining'] = '0'
            response.headers['Retry-After'] = str(retry_after)
            return response

        # Продолжаем
        response = await call_next(request)
        response.headers['X-RateLimit-Remaining'] = str(remaining)
        response.headers['X-RateLimit-Limit'] = str(RATE_LIMIT_REQUESTS)

        return response


class LoggingMiddleware:
    """Логирование запросов"""

    async def __call__(self, request, call_next):
        start_time = time.time()

        # Логируем запрос
        logger.info(f"→ {request.method} {request.path} from {request.remote_addr}")

        response = await call_next(request)

        # Логируем ответ
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"← {response.status_code} {request.method} {request.path} ({elapsed_ms:.1f}ms)")

        return response


class AuthMiddleware:
    """Проверка авторизации (если не через blueprint)"""

    PUBLIC_PATHS = {
        '/', '/health', '/metrics', '/login', '/login/nonce',
        '/create_wallet', '/static', '/uploads'
    }

    async def __call__(self, request, call_next):
        # Публичные пути пропускаем
        if request.path in self.PUBLIC_PATHS:
            return await call_next(request)

        # Проверяем сессию
        session_id = request.cookies.get('session_id')
        if not session_id:
            return await jsonify({'error': 'Unauthorized'}), 401

        address = await redis_manager.session_get(session_id, 'address')
        if not address:
            return await jsonify({'error': 'Unauthorized'}), 401

        # Сохраняем в контекст
        g.user_address = address
        g.session_id = session_id

        return await call_next(request)


class CompressionMiddleware:
    """Сжатие ответов (альтернатива flask-compress)"""

    async def __call__(self, request, call_next):
        response = await call_next(request)

        # Сжимаем большие ответы
        if response.headers.get('Content-Type') in ['application/json', 'text/html']:
            if response.content_length and response.content_length > 1024:
                response.headers['Content-Encoding'] = 'gzip'
                # Здесь нужна реальная реализация gzip
                # Для простоты пока пропускаем

        return response


def require_auth(f):
    """Декоратор для проверки авторизации"""
    @wraps(f)
    async def decorated(*args, **kwargs):
        session_id = request.cookies.get('session_id')
        if not session_id:
            return jsonify({'error': 'Unauthorized'}), 401

        address = await redis_manager.session_get(session_id, 'address')
        if not address:
            return jsonify({'error': 'Unauthorized'}), 401

        request.user_address = address
        request.session_id = session_id

        return await f(*args, **kwargs)
    return decorated


def rate_limit(limit: int = 60, window: int = 60):
    """Декоратор rate limiting"""
    def decorator(f):
        @wraps(f)
        async def decorated(*args, **kwargs):
            client_id = request.remote_addr
            if hasattr(request, 'user_address'):
                client_id = request.user_address

            allowed, remaining, retry_after = await redis_manager.rate_limit_check(
                f"rate:{f.__name__}:{client_id}", limit, window
            )

            if not allowed:
                response = await jsonify({
                    'error': 'Too many requests',
                    'retry_after': retry_after
                })
                response.status_code = 429
                return response

            response = await f(*args, **kwargs)

            if hasattr(response, 'headers'):
                response.headers['X-RateLimit-Remaining'] = str(remaining)
                response.headers['X-RateLimit-Limit'] = str(limit)

            return response
        return decorated
    return decorator


def timing(f):
    """Декоратор для замера времени выполнения"""
    @wraps(f)
    async def decorated(*args, **kwargs):
        start = time.time()
        result = await f(*args, **kwargs)
        elapsed = (time.time() - start) * 1000
        logger.debug(f"{f.__name__} took {elapsed:.2f}ms")
        return result
    return decorated


# Применение middleware в app_async.py:
#
# from middleware import RateLimitMiddleware, LoggingMiddleware, AuthMiddleware
#
# app.asgi_app = LoggingMiddleware()(app.asgi_app)
# app.asgi_app = RateLimitMiddleware()(app.asgi_app)
# app.asgi_app = AuthMiddleware()(app.asgi_app)