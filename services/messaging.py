# services/messaging.py
import logging
import time
from typing import Any, Dict, List

from cache import get_contact_name_cached, get_contact_cache_version
from database import get_db_cursor

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Основная функция получения списка диалогов (с поддержкой статусов)
# ------------------------------------------------------------------
async def get_conversations_list(user_address: str) -> List[Dict[str, Any]]:
    """
    Возвращает список диалогов (личных и групповых) с последним сообщением.
    Для своих последних сообщений показывает статус (отправлено/доставлено/прочитано).
    """
    conversations = []
    try:
        async with get_db_cursor() as conn:
            # 1. Личные диалоги – исключаем групповые чаты
            rows = await conn.fetch("""
                SELECT
                    partner,
                    MAX(id) AS last_msg_id,
                    MAX(timestamp) AS last_ts,
                    (
                        SELECT sender
                        FROM transactions t2
                        WHERE (t2.sender = $1 AND t2.recipient = partner)
                           OR (t2.sender = partner AND t2.recipient = $1)
                        ORDER BY t2.timestamp DESC
                        LIMIT 1
                    ) AS last_sender,
                    (
                        SELECT status
                        FROM transactions t2
                        WHERE (t2.sender = $1 AND t2.recipient = partner)
                           OR (t2.sender = partner AND t2.recipient = $1)
                        ORDER BY t2.timestamp DESC
                        LIMIT 1
                    ) AS last_status
                FROM (
                    SELECT
                        CASE WHEN sender = $1 THEN recipient ELSE sender END AS partner,
                        id,
                        timestamp,
                        sender
                    FROM transactions
                    WHERE (sender = $1 OR recipient = $1)
                      -- ✅ Исключаем групповые чаты из личных диалогов
                      AND recipient NOT LIKE 'group:%'
                      AND sender NOT LIKE 'group:%'
                ) AS t
                WHERE partner IS NOT NULL AND partner != $1
                GROUP BY partner
                ORDER BY last_ts DESC
            """, user_address)

            # 2. Групповые диалоги (только те, в которых пользователь состоит)
            #    Получаем группы, в которых есть хотя бы одно сообщение от пользователя
            group_rows = await conn.fetch("""
                SELECT
                    recipient AS partner,
                    MAX(id) AS last_msg_id,
                    MAX(timestamp) AS last_ts,
                    (
                        SELECT sender
                        FROM transactions t2
                        WHERE t2.recipient = recipient
                        ORDER BY t2.timestamp DESC
                        LIMIT 1
                    ) AS last_sender
                FROM transactions
                WHERE recipient LIKE 'group:%' AND sender = $1
                GROUP BY recipient
                ORDER BY last_ts DESC
            """, user_address)

            # Объединяем личные и групповые диалоги
            all_rows = rows + group_rows
            if not all_rows:
                return []

            # Получаем статус прочтения каждого диалога
            chat_ids = [row['partner'] for row in all_rows]
            placeholders = ','.join(f'${i+2}' for i in range(len(chat_ids)))
            read_rows = await conn.fetch(f"""
                SELECT chat_id, last_read_message_id
                FROM read_status
                WHERE user_address = $1 AND chat_id IN ({placeholders})
            """, user_address, *chat_ids)
            read_map = {row['chat_id']: row['last_read_message_id'] for row in read_rows}

            # Группы – из кэша
            from cache import get_user_groups_cached, get_groups_cache_version
            groups = await get_user_groups_cached(user_address, cache_version=await get_groups_cache_version())
            groups_by_id = {g['id']: g for g in groups}

            for row in all_rows:
                partner = row['partner']
                last_msg_id = row['last_msg_id']
                last_ts = row['last_ts']
                last_sender = row['last_sender']
                last_read_id = read_map.get(partner, 0)

                is_group = partner.startswith('group:')
                if is_group:
                    group_id = partner.split(':', 1)[1]
                    group = groups_by_id.get(group_id)
                    if not group:  # группа удалена — не показываем диалог
                        continue
                    name = group['name'] if group else f'Группа {group_id[:8]}...'
                else:
                    name = (await get_contact_name_cached(user_address, partner,
                            cache_version=await get_contact_cache_version())
                            or partner[:10] + "...")

                # ---------- Формируем preview ----------
                if last_sender == user_address:
                    # Своё последнее сообщение – показываем статус
                    status = row.get('last_status', 'sent')
                    if status == 'read':
                        preview = "✓✓ Прочитано"
                    elif status == 'delivered':
                        preview = "✓✓ Доставлено"
                    else:
                        preview = "✓ Отправлено"
                else:
                    # Чужое сообщение
                    if last_read_id >= last_msg_id:
                        preview = "✓ Прочитано"
                    else:
                        preview = "💬 Новое сообщение"

                conversations.append({
                    'address': partner,
                    'name': name,
                    'is_group': is_group,
                    'last_preview': preview,
                    'last_ts': last_ts,
                })

    except Exception as e:
        logger.error(f"Get conversations error: {e}", exc_info=True)

    return sorted(conversations, key=lambda x: x.get('last_ts', 0), reverse=True)


# ------------------------------------------------------------------
# Кэширующая обёртка (TTL 2 секунды)
# ------------------------------------------------------------------
_conversations_cache: dict = {}
_CONV_CACHE_TTL = 2

async def get_conversations_list_cached(user_address: str) -> List[Dict[str, Any]]:
    now = time.time()
    cached = _conversations_cache.get(user_address)
    if cached and now - cached[1] < _CONV_CACHE_TTL:
        return cached[0]
    result = await get_conversations_list(user_address)
    _conversations_cache[user_address] = (result, now)
    return result

async def invalidate_conversations_cache(user_address: str = None) -> None:
    if user_address:
        _conversations_cache.pop(user_address, None)
    else:
        _conversations_cache.clear()