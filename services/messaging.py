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
    Возвращает список диалогов пользователя.
    Превью заполняется общим текстом, так как содержимое зашифровано.
    """
    conversations: Dict[str, Dict] = {}
    try:
        with _db() as cursor:
            cursor.execute('''
                SELECT
                    CASE WHEN sender = :addr THEN recipient ELSE sender END AS partner,
                    content, image, timestamp, sender, id
                FROM transactions
                WHERE (sender = :addr OR recipient = :addr)
                  AND NOT (sender = :addr AND recipient = :addr)
                ORDER BY timestamp DESC
            ''', {'addr': user_address})

            seen_partners: set = set()
            for row in cursor.fetchall():
                partner, raw_content, raw_image, ts, msg_sender, msg_id = row
                if partner == user_address or partner in seen_partners:
                    continue
                seen_partners.add(partner)

                cursor.execute(
                    'SELECT last_read_message_id FROM read_status '
                    'WHERE user_address = ? AND chat_id = ?',
                    (user_address, partner)
                )
                read_row = cursor.fetchone()
                last_read_id = read_row[0] if read_row else 0

                # Превью – теперь просто индикатор, без расшифровки
                if last_read_id >= msg_id:
                    preview = "✓ Прочитано"
                else:
                    preview = "💬 Новое сообщение" if msg_sender != user_address else "Вы: сообщение"

                if partner.startswith('group:'):
                    group_id = partner.split(':', 1)[1]
                    groups = get_user_groups_cached(
                        user_address, cache_version=get_groups_cache_version())
                    group = next((g for g in groups if g['id'] == group_id), None)
                    name = group['name'] if group else f'Группа {group_id[:8]}...'
                    is_group = True
                else:
                    name = (get_contact_name_cached(
                        user_address, partner,
                        cache_version=get_contact_cache_version())
                            or partner[:10] + "...")
                    is_group = False

                conversations[partner] = {
                    'address': partner,
                    'name': name,
                    'is_group': is_group,
                    'last_preview': preview,
                    'last_ts': ts,
                }
    except Exception as e:
        logger.error(f"Get conversations error: {e}")

    return sorted(conversations.values(),
                  key=lambda x: x.get('last_ts', 0), reverse=True)