# =============================================================================
# Объединённый модуль: crypto_manager, cache, logging_setup,
# query_optimizer, rate_limiter, schemas
# =============================================================================

# ---------- Общие импорты ----------
import hashlib
import base64
import hmac
import json
import logging
import logging.handlers
import os
import threading
import time
from collections import defaultdict
from functools import lru_cache, wraps
from typing import Optional, Tuple, Dict, Any

# Сторонние библиотеки
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
from flask import request, jsonify, session
from marshmallow import Schema, fields, ValidationError, post_load

# Локальный конфиг (должен существовать в проекте)
from config import CONFIG


# =============================================================================
# File: crypto_manager.py
# =============================================================================

CURVE = ec.SECP256R1()

def load_public_key_from_bytes(pubkey_bytes):
    return ec.EllipticCurvePublicKey.from_encoded_point(CURVE, pubkey_bytes)

def load_public_key_from_b64(pubkey_b64):
    return load_public_key_from_bytes(base64.b64decode(pubkey_b64))

def verify_address_matches_pubkey(address, pubkey_b64):
    try:
        pubkey_bytes = base64.b64decode(pubkey_b64)
        computed = hashlib.sha256(pubkey_bytes).hexdigest()
        return hmac.compare_digest(computed, address)
    except Exception:
        return False

def get_cache_info():
    # заглушка, чтобы profile не падал
    return {"status": "crypto moved to client"}


# =============================================================================
# File: logging_setup.py
# =============================================================================

def setup_logging() -> logging.Logger:
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'messenger.log')

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=CONFIG['LOG_MAX_BYTES'],
        backupCount=CONFIG['LOG_BACKUP_COUNT'],
        encoding='utf-8',
        delay=True,
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

    is_prod   = os.getenv('FLASK_ENV') == 'production'
    log_level = logging.WARNING if is_prod else logging.INFO
    handlers  = [file_handler] if is_prod else [file_handler, console_handler]

    logging.basicConfig(level=log_level, handlers=handlers, force=True)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('sqlite3').setLevel(logging.ERROR)
    logging.getLogger('cryptography').setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.warning(f"=== App started, log path: {log_path} ===")
    return logger


# =============================================================================
# File: query_optimizer.py
# =============================================================================

class QueryCache:
    def __init__(self, ttl_seconds: float = 5.0):
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if time.time() < expiry:
                    self._hits += 1
                    return value
                else:
                    del self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._cache[key] = (value, time.time() + self.ttl_seconds)

    def invalidate(self, key: str = None) -> None:
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    def get_stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            return {
                'size': len(self._cache),
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': f"{hit_rate:.1f}%",
                'ttl_seconds': self.ttl_seconds,
            }

balance_cache = QueryCache(ttl_seconds=30.0)
contact_cache = QueryCache(ttl_seconds=60.0)
group_cache = QueryCache(ttl_seconds=30.0)
block_count_cache = QueryCache(ttl_seconds=10.0)
supply_cache = QueryCache(ttl_seconds=60.0)

def cached_query(cache: QueryCache, key_prefix: str = ""):
    def decorator(func):
        def wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}:{args}:{kwargs}"
            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            result = func(*args, **kwargs)
            cache.set(cache_key, result)
            return result
        return wrapper
    return decorator

def invalidate_user_caches(address: str) -> None:
    balance_cache.invalidate()
    contact_cache.invalidate()
    group_cache.invalidate()


# =============================================================================
# File: rate_limiter.py
# =============================================================================

class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients: Dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()
        self._cleanup_counter = 0

    def is_allowed(self, client_id: str, limit: int = None) -> Tuple[bool, int]:
        max_req = limit or self.max_requests
        now = time.time()
        with self._lock:
            self._clients[client_id] = [
                t for t in self._clients[client_id]
                if now - t < self.window_seconds
            ]
            if len(self._clients[client_id]) >= max_req:
                remaining = 0
                allowed = False
            else:
                self._clients[client_id].append(now)
                remaining = max_req - len(self._clients[client_id])
                allowed = True
            self._cleanup_counter += 1
            if self._cleanup_counter > 100:
                self._cleanup()
                self._cleanup_counter = 0
            return allowed, remaining

    def _cleanup(self):
        now = time.time()
        expired_clients = [
            client_id for client_id, timestamps in self._clients.items()
            if not timestamps or (now - timestamps[-1]) > self.window_seconds * 2
        ]
        for client_id in expired_clients:
            del self._clients[client_id]

    def get_stats(self) -> dict:
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

general_limiter = RateLimiter(max_requests=60)
message_limiter = RateLimiter(max_requests=30)
api_limiter = RateLimiter(max_requests=120)

def rate_limit(limiter: RateLimiter = None, limit: int = None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            client_id = session.get('address') or request.remote_addr or 'unknown'
            current_limiter = limiter or general_limiter
            allowed, remaining = current_limiter.is_allowed(client_id, limit)

            if not allowed:
                retry_after = current_limiter.window_seconds
                return jsonify({
                    'error': 'Too many requests',
                    'retry_after': retry_after,
                    'limit': limit or current_limiter.max_requests,
                }), 429

            response = f(*args, **kwargs)
            if isinstance(response, tuple):
                resp, status = response
                if hasattr(resp, 'headers'):
                    resp.headers['X-RateLimit-Remaining'] = str(remaining)
                    resp.headers['X-RateLimit-Limit'] = str(limit or current_limiter.max_requests)
                return resp, status

            if hasattr(response, 'headers'):
                response.headers['X-RateLimit-Remaining'] = str(remaining)
                response.headers['X-RateLimit-Limit'] = str(limit or current_limiter.max_requests)
            return response
        return decorated_function
    return decorator

def get_rate_limit_stats() -> dict:
    return {
        'general': general_limiter.get_stats(),
        'messages': message_limiter.get_stats(),
        'api': api_limiter.get_stats(),
    }


# =============================================================================
# File: schemas.py
# =============================================================================

class WalletSchema(Schema):
    mnemonic_phrase = fields.Str(
        required=True, load_only=True,
        validate=lambda x: len(x.strip()) >= 24,
    )
    @post_load
    def strip(self, data, **kwargs):
        data['mnemonic_phrase'] = data['mnemonic_phrase'].strip()
        return data

class MessageSchema(Schema):
    recipient    = fields.Str(required=True,
                               validate=lambda x: len(x) == 64 or x.startswith('group:'))
    content      = fields.Str(required=True, allow_none=False)
    image        = fields.Str(allow_none=True)
    message_type = fields.Str(load_default='direct',
                               validate=lambda x: x in ('direct', 'group'))
    group_id     = fields.Str(allow_none=True)

class GroupSchema(Schema):
    name    = fields.Str(required=True, validate=lambda x: 1 <= len(x.strip()) <= 100)
    members = fields.List(fields.Str(), required=True,
                           validate=lambda x: 1 <= len(x) <= 50)

class ContactSchema(Schema):
    address = fields.Str(required=True, validate=lambda x: len(x) == 64)
    name    = fields.Str(required=True, validate=lambda x: 1 <= len(x) <= 50)

class EditContactSchema(Schema):
    address = fields.Str(required=True, validate=lambda x: len(x) == 64)
    name    = fields.Str(required=True, validate=lambda x: 1 <= len(x.strip()) <= 50)
    @post_load
    def strip_fields(self, data, **kwargs):
        data['name']    = data['name'].strip()
        data['address'] = data['address'].strip().lower()
        return data

class DeleteMessageSchema(Schema):
    message_id = fields.Int(required=True, validate=lambda x: x > 0)