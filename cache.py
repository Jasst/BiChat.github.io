"""
cache.py — Асинхронная версия с aiosqlite и TTL-кэшами.
"""
import json
import logging
import threading
import time
from typing import Optional, Tuple

from config import CONFIG

logger = logging.getLogger(__name__)

_db_path: Optional[str] = None


def set_db_path(path: str) -> None:
    global _db_path
    _db_path = path


from database import get_db_cursor


class TTLCache:
    def __init__(self, ttl_seconds: float = 300, maxsize: int = 256):
        self.ttl = ttl_seconds
        self.maxsize = maxsize
        self._cache = {}
        self._lock = threading.RLock()

    async def get(self, key):
        with self._lock:
            if key in self._cache:
                value, expires = self._cache[key]
                if time.time() < expires:
                    return value
                del self._cache[key]
        return None

    async def set(self, key, value):
        with self._lock:
            if len(self._cache) >= self.maxsize:
                oldest = min(self._cache.items(), key=lambda kv: kv[1][1])[0]
                del self._cache[oldest]
            self._cache[key] = (value, time.time() + self.ttl)

    async def invalidate(self, key=None):
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()


pubkey_cache = TTLCache(ttl_seconds=3600, maxsize=CONFIG['CACHE_SIZE_PUBKEYS'])
contact_name_cache = TTLCache(ttl_seconds=600, maxsize=CONFIG['CACHE_SIZE_CONTACTS'])
user_groups_cache = TTLCache(ttl_seconds=300, maxsize=CONFIG['CACHE_SIZE_GROUPS'])

_pubkey_cache_version = 0
_pubkey_version_lock = threading.Lock()
_contact_cache_version = 0
_contact_version_lock = threading.Lock()
_groups_cache_version = 0
_groups_version_lock = threading.Lock()


def bump_pubkey_cache_version() -> None:
    global _pubkey_cache_version
    with _pubkey_version_lock:
        _pubkey_cache_version += 1


def get_pubkey_cache_version() -> int:
    with _pubkey_version_lock:
        return _pubkey_cache_version


def bump_contact_cache_version() -> None:
    global _contact_cache_version
    with _contact_version_lock:
        _contact_cache_version += 1


def get_contact_cache_version() -> int:
    with _contact_version_lock:
        return _contact_cache_version


def bump_groups_cache_version() -> None:
    global _groups_cache_version
    with _groups_version_lock:
        _groups_cache_version += 1


def get_groups_cache_version() -> int:
    with _groups_version_lock:
        return _groups_cache_version


async def get_cached_public_key(address: str, cache_version: int = 0) -> Tuple[Optional[str], bool]:
    key = (address, cache_version)
    cached = await pubkey_cache.get(key)
    if cached is not None:
        return cached
    async with get_db_cursor(_db_path) as cursor:
        await cursor.execute(
            'SELECT public_key_b64, verified FROM pubkey_cache WHERE address = ?',
            (address,)
        )
        row = await cursor.fetchone()
        result = (row[0], bool(row[1])) if row else (None, False)
        await pubkey_cache.set(key, result)
        return result


async def cache_public_key(address: str, pubkey_b64: str,
                           source: str = 'message',
                           verified: Optional[bool] = None) -> bool:
    try:
        if verified is None:
            from setup import verify_address_matches_pubkey
            verified = verify_address_matches_pubkey(address, pubkey_b64)
            if not verified:
                logger.warning(f"Unverified pubkey cached for {address[:16]}...")
        async with get_db_cursor(_db_path) as cursor:
            await cursor.execute(
                'INSERT OR REPLACE INTO pubkey_cache '
                '(address, public_key_b64, updated_at, source, verified) '
                'VALUES (?, ?, ?, ?, ?)',
                (address, pubkey_b64, time.time(), source, 1 if verified else 0)
            )
        bump_pubkey_cache_version()
        return True
    except Exception as e:
        logger.error(f"Cache pubkey error: {e}")
        return False


async def fetch_public_key_from_chain(address: str) -> Tuple[Optional[str], bool]:
    async with get_db_cursor(_db_path) as cursor:
        await cursor.execute(
            'SELECT sender_pubkey, metadata FROM transactions '
            'WHERE sender = ? AND sender_pubkey IS NOT NULL '
            'ORDER BY timestamp DESC LIMIT 1',
            (address,)
        )
        row = await cursor.fetchone()
        if row and row[0]:
            pubkey = row[0]
            from setup import verify_address_matches_pubkey
            verified = verify_address_matches_pubkey(address, pubkey)
            return pubkey, verified
        # ✅ Исправлено: проверка на None и str
        if row and row[1] and isinstance(row[1], str):
            try:
                meta = json.loads(row[1])
                if meta.get('pubkey'):
                    pubkey = meta['pubkey']
                    from setup import verify_address_matches_pubkey
                    verified = verify_address_matches_pubkey(address, pubkey)
                    return pubkey, verified
            except Exception:
                pass
    return None, False


async def get_contact_name_cached(user_address: str, contact_address: str,
                                  cache_version: int = 0) -> Optional[str]:
    key = (user_address, contact_address, cache_version)
    cached = await contact_name_cache.get(key)
    if cached is not None:
        return cached
    async with get_db_cursor(_db_path) as cursor:
        await cursor.execute(
            'SELECT contact_name FROM contacts '
            'WHERE user_address = ? AND contact_address = ?',
            (user_address, contact_address)
        )
        row = await cursor.fetchone()
        result = row[0] if row else None
        await contact_name_cache.set(key, result)
        return result


async def get_user_groups_cached(address: str, cache_version: int = 0) -> tuple:
    key = (address, cache_version)
    cached = await user_groups_cache.get(key)
    if cached is not None:
        return cached
    async with get_db_cursor(_db_path) as cursor:
        await cursor.execute('SELECT id, name, creator, members, created_at FROM groups')
        groups = []
        async for row in cursor:
            members = json.loads(row[3])
            if address in members:
                groups.append({
                    'id': row[0],
                    'name': row[1],
                    'creator': row[2],
                    'members': members,
                    'created_at': row[4],
                })
        result = tuple(groups)
        await user_groups_cache.set(key, result)
        return result


async def clear_all_caches() -> None:
    await pubkey_cache.invalidate()
    await contact_name_cache.invalidate()
    await user_groups_cache.invalidate()
    logger.debug("All TTL caches cleared")