"""
services/messaging.py — Список диалогов (без расшифровки)
"""
import json
import logging
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
    Возвращает список диалогов пользователя (оптимизировано: 2 запроса вместо N+1).
    """
    conversations = []
    try:
        with _db() as cursor:
            # 1. Получаем последнее сообщение для каждого партнёра
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
            ''', (user_address, user_address, user_address, user_address, user_address, user_address))

            rows = cursor.fetchall()
            if not rows:
                return []

            # 2. Получаем статусы чтения для всех чатов одним запросом
            chat_ids = [row['partner'] for row in rows]
            placeholders = ','.join('?' * len(chat_ids))
            cursor.execute(f'''
                SELECT chat_id, last_read_message_id
                FROM read_status
                WHERE user_address = ? AND chat_id IN ({placeholders})
            ''', (user_address, *chat_ids))
            read_map = {row['chat_id']: row['last_read_message_id'] for row in cursor.fetchall()}

            # 3. Формируем результат
            for row in rows:
                partner = row['partner']
                last_msg_id = row['last_msg_id']
                last_ts = row['last_ts']
                last_sender = row['last_sender']
                last_read_id = read_map.get(partner, 0)

                # preview
                if last_read_id >= last_msg_id:
                    preview = "✓ Прочитано"
                else:
                    preview = "💬 Новое сообщение" if last_sender != user_address else "Вы: сообщение"

                # имя и тип
                if partner.startswith('group:'):
                    group_id = partner.split(':', 1)[1]
                    groups = get_user_groups_cached(user_address, cache_version=get_groups_cache_version())
                    group = next((g for g in groups if g['id'] == group_id), None)
                    name = group['name'] if group else f'Группа {group_id[:8]}...'
                    is_group = True
                else:
                    name = (get_contact_name_cached(user_address, partner,
                                                    cache_version=get_contact_cache_version())
                            or partner[:10] + "...")
                    is_group = False

                conversations.append({
                    'address': partner,
                    'name': name,
                    'is_group': is_group,
                    'last_preview': preview,
                    'last_ts': last_ts,
                })

    except Exception as e:
        logger.error(f"Get conversations error: {e}")
        # выводим traceback для отладки
        import traceback
        logger.error(traceback.format_exc())

    return sorted(conversations, key=lambda x: x.get('last_ts', 0), reverse=True)


# services/messaging.py (добавить в конец файла)

# =============================================================================
# КЭШ ДЛЯ СПИСКА ДИАЛОГОВ
# =============================================================================

from functools import lru_cache
import time
from typing import List, Dict, Any

_conversations_cache = {}
_CONV_CACHE_TTL = 2  # секунды


def get_conversations_list_cached(user_address: str) -> List[Dict[str, Any]]:
    """
    Кэшированная версия get_conversations_list.
    TTL = 2 секунды, чтобы не кэшировать слишком долго.
    """
    now = time.time()
    cached = _conversations_cache.get(user_address)
    if cached and now - cached[1] < _CONV_CACHE_TTL:
        return cached[0]

    result = get_conversations_list(user_address)
    _conversations_cache[user_address] = (result, now)
    return result


def invalidate_conversations_cache(user_address: str = None):
    """
    Сброс кэша диалогов (вызывать при отправке/получении сообщения)
    """
    if user_address:
        _conversations_cache.pop(user_address, None)
    else:
        _conversations_cache.clear()