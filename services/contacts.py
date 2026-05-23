"""
services/contacts.py — Бизнес-логика работы с контактами
"""
import logging
import time
from typing import Any, Dict, List, Optional

from cache import bump_contact_cache_version

logger = logging.getLogger(__name__)

_db_path: Optional[str] = None


def set_db_path(path: str) -> None:
    global _db_path
    _db_path = path


def _db():
    from database import get_db_cursor
    return get_db_cursor(_db_path)


def add_contact(user_address: str, contact_address: str, contact_name: str) -> bool:
    if not contact_name or not contact_name.strip():
        contact_name = contact_address[:10] + "..."
    try:
        with _db() as cursor:
            cursor.execute(
                'INSERT OR REPLACE INTO contacts '
                '(user_address, contact_address, contact_name, created_at) '
                'VALUES (?, ?, ?, ?)',
                (user_address, contact_address, contact_name.strip(), time.time())
            )
        bump_contact_cache_version()
        return True
    except Exception as e:
        logger.error(f"Add contact DB error: {e}")
        return False


def get_contacts(user_address: str) -> List[Dict[str, Any]]:
    with _db() as cursor:
        cursor.execute(
            'SELECT contact_address, contact_name, contact_pubkey, created_at '
            'FROM contacts WHERE user_address = ? '
            'ORDER BY contact_name COLLATE NOCASE',
            (user_address,)
        )
        return [
            {'address': row[0], 'name': row[1], 'pubkey': row[2], 'created_at': row[3]}
            for row in cursor.fetchall()
        ]


def update_contact_name(user_address: str, contact_address: str, new_name: str) -> bool:
    if not new_name or not new_name.strip():
        return False
    clean_name = ''.join(c for c in new_name.strip() if ord(c) >= 32 and ord(c) != 127)
    if not clean_name or len(clean_name) > 50:
        return False
    try:
        with _db() as cursor:
            cursor.execute(
                'UPDATE contacts SET contact_name = ? '
                'WHERE user_address = ? AND contact_address = ?',
                (clean_name, user_address, contact_address.lower())
            )
            updated = cursor.rowcount
        if updated:
            bump_contact_cache_version()
            logger.info(f"Contact name updated: {contact_address[:16]}... → '{clean_name}'")
        return bool(updated)
    except Exception as e:
        logger.error(f"Update contact name DB error: {e}")
        return False