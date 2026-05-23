"""
services/messaging.py — Список диалогов (без расшифровки)
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional

from cache import (
    get_contact_name_cached, get_contact_cache_version,
    get_user_groups_cached, get_groups_cache_version,
)

logger = logging.getLogger(__name__)

_db_path: Optional[str] = None


def set_db_path(path: str) -> None:
    global _db_path
    _db_path = path


def _db():
    from database import get_db_cursor
    return get_db_cursor(_db_path)


def get_conversations_list(user_address: str) -> List[Dict[str, Any]]:
    """
    Возвращает список диалогов пользователя (2 запроса вместо N+1).
    """
    conversations = []
    try:
        with _db() as cursor:
            cursor.execute('''
                SELECT
                    partner,
                    MAX(id) AS last_msg_id,
                    MAX(timestamp) AS last_ts,
                    (SELECT sender FROM transactions t2
                     WHERE (t2.sender = ? AND t2.recipient = partner)
                        OR (t2.sender = partner AND t2.recipient = ?)
                     ORDER BY t2.timestamp DESC LIMIT 1) AS last_sender
                FROM (
                    SELECT
                        CASE WHEN sender = ? THEN recipient ELSE sender END AS partner,
                        id, timestamp, sender
                    FROM transactions
                    WHERE sender = ? OR recipient = ?
                ) AS t
                WHERE partner IS NOT NULL AND partner != ?
                GROUP BY partner
            ''', (user_address,) * 6)

            rows = cursor.fetchall()
            if not rows:
                return []

            chat_ids     = [row['partner'] for row in rows]
            placeholders = ','.join('?' * len(chat_ids))
            cursor.execute(f'''
                SELECT chat_id, last_read_message_id
                FROM read_status
                WHERE user_address = ? AND chat_id IN ({placeholders})
            ''', (user_address, *chat_ids))
            read_map = {row['chat_id']: row['last_read_message_id'] for row in cursor.fetchall()}

            for row in rows:
                partner      = row['partner']
                last_msg_id  = row['last_msg_id']
                last_ts      = row['last_ts']
                last_sender  = row['last_sender']
                last_read_id = read_map.get(partner, 0)

                if last_read_id >= last_msg_id:
                    preview = "✓ Прочитано"
                else:
                    preview = "💬 Новое сообщение" if last_sender != user_address else "Вы: сообщение"

                if partner.startswith('group:'):
                    group_id = partner.split(':', 1)[1]
                    groups   = get_user_groups_cached(user_address, cache_version=get_groups_cache_version())
                    group    = next((g for g in groups if g['id'] == group_id), None)
                    name     = group['name'] if group else f'Группа {group_id[:8]}...'
                    is_group = True
                else:
                    name = (get_contact_name_cached(user_address, partner,
                                                    cache_version=get_contact_cache_version())
                            or partner[:10] + "...")
                    is_group = False

                conversations.append({
                    'address':      partner,
                    'name':         name,
                    'is_group':     is_group,
                    'last_preview': preview,
                    'last_ts':      last_ts,
                })

    except Exception as e:
        logger.error(f"Get conversations error: {e}", exc_info=True)

    return sorted(conversations, key=lambda x: x.get('last_ts', 0), reverse=True)


# =============================================================================
# Cache for conversations list
# =============================================================================

_conversations_cache: dict = {}
_CONV_CACHE_TTL = 2  # seconds


def get_conversations_list_cached(user_address: str) -> List[Dict[str, Any]]:
    now    = time.time()
    cached = _conversations_cache.get(user_address)
    if cached and now - cached[1] < _CONV_CACHE_TTL:
        return cached[0]
    result = get_conversations_list(user_address)
    _conversations_cache[user_address] = (result, now)
    return result


def invalidate_conversations_cache(user_address: str = None) -> None:
    if user_address:
        _conversations_cache.pop(user_address, None)
    else:
        _conversations_cache.clear()