"""
cache.py — Версионированные LRU-кэши: публичные ключи, контакты, группы
"""
import json
import logging
import threading
import time
from functools import lru_cache
from typing import Optional, Tuple

from config import CONFIG
from setup import verify_address_matches_pubkey

logger = logging.getLogger(__name__)

# Импортируется отложенно, чтобы избежать циклического импорта
# (database → cache → database).  Blockchain-инстанс передаётся при вызовах.
_db_path: Optional[str] = None


def set_db_path(path: str) -> None:
    """Вызывается один раз из app.py после создания Blockchain."""
    global _db_path
    _db_path = path


def _get_db():
    """Ленивый импорт get_db_cursor, чтобы не создавать цикл."""
    from database import get_db_cursor
    return get_db_cursor(_db_path)


# =============================================================================
# Версионирование кэша (инкремент → lru_cache видит новый ключ)
# =============================================================================

_pubkey_cache_version   = 0
_pubkey_version_lock    = threading.Lock()

_contact_cache_version  = 0
_contact_version_lock   = threading.Lock()

_groups_cache_version   = 0
_groups_version_lock    = threading.Lock()


def bump_pubkey_cache_version() -> None:
    global _pubkey_cache_version
    with _pubkey_version_lock:
        _pubkey_cache_version += 1
        logger.debug(f"🔄 Pubkey cache version → {_pubkey_cache_version}")


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


# =============================================================================
# Кэш публичных ключей
# =============================================================================

@lru_cache(maxsize=CONFIG['CACHE_SIZE_PUBKEYS'])
def get_cached_public_key(address: str,
                          cache_version: int = 0) -> Tuple[Optional[str], bool]:
    """Читает pubkey из таблицы pubkey_cache (результат кэшируется по версии)."""
    with _get_db() as cursor:
        cursor.execute(
            'SELECT public_key_b64, verified FROM pubkey_cache WHERE address = ?',
            (address,)
        )
        row = cursor.fetchone()
        return (row[0], bool(row[1])) if row else (None, False)


def cache_public_key(address: str, pubkey_b64: str,
                     source: str = 'message',
                     verified: Optional[bool] = None) -> bool:
    try:
        if verified is None:
            verified = verify_address_matches_pubkey(address, pubkey_b64)
            if not verified:
                logger.warning(f"⚠️ Unverified pubkey cached for {address[:16]}...")
        with _get_db() as cursor:
            cursor.execute(
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


def fetch_public_key_from_chain(address: str) -> Tuple[Optional[str], bool]:
    """Ищет последний известный pubkey в таблице транзакций."""
    with _get_db() as cursor:
        cursor.execute(
            'SELECT sender_pubkey, metadata FROM transactions '
            'WHERE sender = ? AND sender_pubkey IS NOT NULL '
            'ORDER BY timestamp DESC LIMIT 1',
            (address,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            pubkey   = row[0]
            verified = verify_address_matches_pubkey(address, pubkey)
            return pubkey, verified
        if row and row[1]:
            try:
                meta = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                if meta.get('pubkey'):
                    pubkey   = meta['pubkey']
                    verified = verify_address_matches_pubkey(address, pubkey)
                    return pubkey, verified
            except Exception:
                pass
    return None, False


# =============================================================================
# Кэш имён контактов и групп
# =============================================================================

@lru_cache(maxsize=CONFIG['CACHE_SIZE_CONTACTS'])
def get_contact_name_cached(user_address: str, contact_address: str,
                             cache_version: int = 0) -> Optional[str]:
    with _get_db() as cursor:
        cursor.execute(
            'SELECT contact_name FROM contacts '
            'WHERE user_address = ? AND contact_address = ?',
            (user_address, contact_address)
        )
        row = cursor.fetchone()
        return row[0] if row else None


@lru_cache(maxsize=CONFIG['CACHE_SIZE_GROUPS'])
def get_user_groups_cached(address: str, cache_version: int = 0) -> tuple:
    with _get_db() as cursor:
        cursor.execute(
            'SELECT id, name, creator, members, created_at FROM groups'
        )
        groups = []
        for row in cursor.fetchall():
            members = json.loads(row[3])
            if address in members:
                groups.append({
                    'id': row[0], 'name': row[1], 'creator': row[2],
                    'members': members, 'created_at': row[4],
                })
        return tuple(groups)


def clear_all_caches() -> None:
    """Сбрасывает все LRU-кэши (вызывается при logout)."""
    get_cached_public_key.cache_clear()
    get_contact_name_cached.cache_clear()
    get_user_groups_cached.cache_clear()
    logger.debug("All LRU caches cleared")
