"""routes/messages_async.py — Асинхронные сообщения с буферизацией и Long Polling через Redis"""
import json
import logging
import time
from typing import Dict, List, Optional

from quart import Blueprint, jsonify, request
from datetime import datetime

from database_async import db
from redis_manager import redis_manager
from config_async import (
    MESSAGE_FEE, STAKING_FEE_POOL_ADDRESS, COIN, COIN_NAME,
    ENABLE_STAKING, LONG_POLLING_TIMEOUT, MAX_MESSAGES_PER_POLL
)

logger = logging.getLogger(__name__)
messages_bp = Blueprint('messages', __name__)

# FIX: был getattr(wait_for_messages, '_last_poll_time', {}) — словарь создавался
# заново на каждый вызов, rate-limiting никогда не срабатывал.
# Теперь хранится на уровне модуля.
_poll_rate_limit: Dict[str, float] = {}


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

async def _fetch_new_messages_from_db(user_addr: str, since_timestamp: float,
                                       limit: int = 50) -> List[dict]:
    """Асинхронно получает новые сообщения из БД (fallback для Redis)"""
    try:
        rows = await db.fetch_all("""
            SELECT id, sender, recipient, content, image,
                   EXTRACT(EPOCH FROM timestamp) as ts, metadata
            FROM transactions
            WHERE (recipient = $1 OR recipient LIKE 'group:%')
              AND EXTRACT(EPOCH FROM timestamp) > $2
              AND sender != $1
            ORDER BY timestamp ASC
            LIMIT $3
        """, user_addr, since_timestamp, limit)

        messages = []
        for row in rows:
            is_group = row['recipient'].startswith('group:')
            chat_id = row['recipient'] if is_group else row['sender']

            sender_name = None
            if not is_group:
                contact = await db.fetch_one("""
                    SELECT contact_name FROM contacts
                    WHERE user_address = $1 AND contact_address = $2
                """, user_addr, row['sender'])
                if contact:
                    sender_name = contact['contact_name']

            messages.append({
                'id': row['id'],
                'sender': row['sender'],
                'sender_name': sender_name,
                'chatId': chat_id,
                'isGroup': is_group,
                'preview': '💬 Новое сообщение',
                'timestamp': row['ts'],
                'content': row['content'],
                'image': row['image'],
            })
        return messages
    except Exception as e:
        logger.error(f"_fetch_new_messages_from_db error: {e}")
        return []


async def _get_contact_name(contact_address: str) -> Optional[str]:
    """Получает имя контакта из кэша или БД"""
    try:
        cached = await redis_manager.cache_get(f"contact_name:{contact_address}")
        if cached:
            return cached

        contact = await db.fetch_one("""
            SELECT contact_name FROM contacts
            WHERE contact_address = $1
            LIMIT 1
        """, contact_address)

        if contact:
            await redis_manager.cache_set(
                f"contact_name:{contact_address}",
                contact['contact_name'],
                ttl=300
            )
            return contact['contact_name']

        return None
    except Exception as e:
        logger.error(f"_get_contact_name error: {e}")
        return None


def _sanitize_message(msg: dict) -> dict:
    """Возвращает только безопасные поля для клиента."""
    return {
        'id': msg.get('id'),
        'sender': msg.get('sender'),
        'sender_name': msg.get('sender_name'),
        'chatId': msg.get('chatId'),
        'isGroup': msg.get('isGroup', False),
        'preview': msg.get('preview', '💬 Новое сообщение'),
        'timestamp': msg.get('timestamp', time.time()),
    }


# =============================================================================
# LONG POLLING ENDPOINT (Redis-based)
# =============================================================================

@messages_bp.route('/wait_for_messages', methods=['GET'])
async def wait_for_messages():
    """
    Long polling endpoint — асинхронное ожидание сообщений через Redis.
    """
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    # Санитизация параметров
    try:
        since = float(request.args.get('since', 0))
        now = time.time()
        since = max(min(since, now + 60), now - 3600)
    except (ValueError, TypeError):
        since = time.time() - 3600

    try:
        timeout = int(request.args.get('timeout', LONG_POLLING_TIMEOUT))
        timeout = min(max(timeout, 5), 30)
    except (ValueError, TypeError):
        timeout = LONG_POLLING_TIMEOUT

    # FIX: используем модульный словарь вместо getattr-хака
    now = time.time()
    last_request = _poll_rate_limit.get(user_address, 0)
    if now - last_request < 0.5:
        _poll_rate_limit[user_address] = now
        resp = jsonify({'messages': [], 'throttled': True, 'timestamp': now})
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    _poll_rate_limit[user_address] = now

    # Проверка существования пользователя
    try:
        exists = await db.fetch_val(
            "SELECT 1 FROM wallets WHERE address = $1", user_address
        )
        if not exists:
            logger.warning(f"Invalid user attempted long poll: {user_address[:16]}...")
            return jsonify({'error': 'Invalid user'}), 403
    except Exception as e:
        logger.error(f"User validation error: {e}")
        return jsonify({'error': 'Internal error'}), 500

    # Получаем сообщения из Redis очереди (с настоящим async ожиданием)
    buffered_messages, waited_time, had_notification = await redis_manager.queue_pop(
        user_address, since, timeout
    )

    no_cache_headers = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
    }

    if buffered_messages:
        capped = buffered_messages[:MAX_MESSAGES_PER_POLL]
        resp = jsonify({
            'messages': [_sanitize_message(m) for m in capped],
            'has_more': len(buffered_messages) > MAX_MESSAGES_PER_POLL,
            'timestamp': time.time(),
            'from_buffer': True,
            'waited': waited_time,
        })
        for k, v in no_cache_headers.items():
            resp.headers[k] = v
        return resp

    # Fallback: проверяем БД
    db_messages = await _fetch_new_messages_from_db(user_address, since)
    if db_messages:
        for msg in db_messages:
            await redis_manager.queue_push(user_address, msg)

        capped = db_messages[:MAX_MESSAGES_PER_POLL]
        resp = jsonify({
            'messages': [_sanitize_message(m) for m in capped],
            'has_more': len(db_messages) > MAX_MESSAGES_PER_POLL,
            'timestamp': time.time(),
            'from_db': True,
        })
        for k, v in no_cache_headers.items():
            resp.headers[k] = v
        return resp

    resp = jsonify({
        'messages': [],
        'has_more': False,
        'timestamp': time.time(),
        'waited': timeout,
        'notified': had_notification,
    })
    for k, v in no_cache_headers.items():
        resp.headers[k] = v
    return resp


# =============================================================================
# LEGACY ENDPOINT
# =============================================================================

@messages_bp.route('/check_new_messages', methods=['GET'])
async def check_new_messages_legacy():
    """Legacy endpoint для проверки новых сообщений"""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    since = float(request.args.get('since', 0))
    messages = await _fetch_new_messages_from_db(user_address, since)
    return jsonify({'messages': messages}), 200


# =============================================================================
# SEND MESSAGE
# =============================================================================

@messages_bp.route('/send_message', methods=['POST'])
async def send_message():
    """Отправка сообщения (личное или групповое)"""
    session_id = request.cookies.get('session_id')
    sender = await redis_manager.session_get(session_id, 'address')

    if not sender:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    recipient = data.get('recipient')
    payload = data.get('payload')
    msg_type = data.get('message_type', 'direct')
    group_id = data.get('group_id')
    encrypted_map = data.get('encrypted_map')

    if msg_type == 'group' and not group_id:
        return jsonify({'error': 'Group ID required'}), 400

    if msg_type != 'group' and not recipient:
        return jsonify({'error': 'Recipient required'}), 400

    async with db.transaction() as conn:
        # 1. Проверка и списание комиссии
        if MESSAGE_FEE > 0:
            balance = await conn.fetchval(
                "SELECT balance FROM wallets WHERE address = $1 FOR UPDATE", sender
            )
            if not balance or balance < MESSAGE_FEE:
                return jsonify({
                    'error': f'Insufficient balance for fee ({MESSAGE_FEE / COIN:.6f} {COIN_NAME})'
                }), 402

            await conn.execute(
                "UPDATE wallets SET balance = balance - $1 WHERE address = $2",
                MESSAGE_FEE, sender
            )
            await conn.execute("""
                INSERT INTO wallets (address, balance) VALUES ($1, $2)
                ON CONFLICT (address) DO UPDATE SET balance = wallets.balance + $2
            """, STAKING_FEE_POOL_ADDRESS, MESSAGE_FEE)

            await conn.execute("""
                INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note)
                VALUES ('message_fee', $1, $2, $3, NOW(), $4)
            """, sender, STAKING_FEE_POOL_ADDRESS, MESSAGE_FEE, 'message fee')

        # 2. Сохранение сообщения
        tx_id = None
        message_obj = None

        if msg_type == 'group' and group_id:
            if not encrypted_map:
                return jsonify({'error': 'Missing encrypted_map'}), 400

            group = await conn.fetchrow(
                "SELECT members FROM groups WHERE id = $1", group_id
            )
            if not group:
                return jsonify({'error': 'Group not found'}), 404

            members = json.loads(group['members'])
            if sender not in members:
                return jsonify({'error': 'Access denied'}), 403

            recipient_addr = f"group:{group_id}"
            encrypted_payload = json.dumps({'encrypted_map': encrypted_map})

            tx_id = await conn.fetchval("""
                INSERT INTO transactions (sender, recipient, content, timestamp, metadata)
                VALUES ($1, $2, $3, NOW(), $4)
                RETURNING id
            """, sender, recipient_addr, encrypted_payload,
                json.dumps({'encryption': 'group-ecdh-v4', 'group_id': group_id}))

            message_obj = {
                'id': tx_id,
                'sender': sender,
                'sender_name': None,
                'chatId': f"group:{group_id}",
                'isGroup': True,
                'preview': '💬 Новое сообщение в группе',
                'timestamp': time.time(),
                'content': encrypted_payload,
                'image': None,
            }

            await redis_manager.queue_push_group(
                group_id, members, message_obj, exclude_sender=sender
            )

        else:
            if sender == recipient:
                return jsonify({'error': 'Cannot message yourself'}), 400

            if not payload or not isinstance(payload, dict):
                return jsonify({'error': 'Missing encrypted payload'}), 400

            content = json.dumps(payload)

            tx_id = await conn.fetchval("""
                INSERT INTO transactions (sender, recipient, content, timestamp, metadata)
                VALUES ($1, $2, $3, NOW(), $4)
                RETURNING id
            """, sender, recipient, content,
                json.dumps({'encryption': 'hybrid-v2'}))

            sender_name = await _get_contact_name(sender)

            message_obj = {
                'id': tx_id,
                'sender': sender,
                'sender_name': sender_name,
                'chatId': recipient,
                'isGroup': False,
                'preview': '💬 Новое сообщение',
                'timestamp': time.time(),
                'content': content,
                'image': None,
            }

            # queue_push уже публикует notify через Pub/Sub внутри себя
            await redis_manager.queue_push(recipient, message_obj)

        logger.info(
            f"📨 Message {tx_id} sent: {sender[:10]} → "
            f"{recipient[:10] if recipient else group_id[:10]}"
        )

        return jsonify({
            'message': 'Sent',
            'tx_id': tx_id,
            'type': msg_type,
            'fee': MESSAGE_FEE
        }), 201


# =============================================================================
# GET CONVERSATION HISTORY
# =============================================================================

@messages_bp.route('/get_conversation', methods=['GET'])
async def get_conversation():
    """Получение истории переписки с пагинацией"""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    chat_with = request.args.get('with')
    if not chat_with:
        return jsonify({'error': 'Missing "with" parameter'}), 400

    limit = min(int(request.args.get('limit', 30)), 100)
    before_id = request.args.get('before_id', type=int)
    last_message_id = request.args.get('last_message_id', type=int)

    try:
        if chat_with.startswith('group:'):
            group_id = chat_with[6:]

            group = await db.fetch_one(
                "SELECT members FROM groups WHERE id = $1", group_id
            )
            if not group or user_address not in json.loads(group['members']):
                return jsonify({'error': 'Access denied'}), 403

            query = """
                SELECT id, sender, recipient, content, image,
                       EXTRACT(EPOCH FROM timestamp) as ts, metadata
                FROM transactions
                WHERE recipient = $1
            """
            params = [chat_with]

            if last_message_id:
                query += " AND id > $2"
                params.append(last_message_id)

            if before_id:
                query += f" AND id < ${len(params) + 1}"
                params.append(before_id)

            query += f" ORDER BY timestamp ASC LIMIT ${len(params) + 1}"
            params.append(limit)

            rows = await db.fetch_all(query, *params)

        else:
            query = """
                SELECT id, sender, recipient, content, image,
                       EXTRACT(EPOCH FROM timestamp) as ts, metadata
                FROM transactions
                WHERE (sender = $1 AND recipient = $2)
                   OR (sender = $2 AND recipient = $1)
            """
            params = [user_address, chat_with]

            if last_message_id:
                query += " AND id > $3"
                params.append(last_message_id)

            if before_id:
                query += f" AND id < ${len(params) + 1}"
                params.append(before_id)

            query += f" ORDER BY timestamp DESC LIMIT ${len(params) + 1}"
            params.append(limit)

            rows = await db.fetch_all(query, *params)

        messages = [
            {
                'id': row['id'],
                'sender': row['sender'],
                'recipient': row['recipient'],
                'content': row['content'],
                'image': row['image'],
                'timestamp': row['ts'],
                'metadata': row['metadata'],
                'is_mine': row['sender'] == user_address,
            }
            for row in rows
        ]

        if not chat_with.startswith('group:'):
            messages.reverse()

        return jsonify({'messages': messages, 'chat_with': chat_with}), 200

    except Exception as e:
        logger.error(f"get_conversation error: {e}")
        return jsonify({'error': 'Failed to load conversation'}), 500


# =============================================================================
# GET CONVERSATIONS LIST
# =============================================================================

@messages_bp.route('/get_conversations', methods=['GET'])
async def get_conversations_list():
    """Список всех диалогов пользователя с последними сообщениями"""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        cache_key = f"conversations:{user_address}"
        cached = await redis_manager.cache_get(cache_key)
        if cached:
            return jsonify({'conversations': cached}), 200

        rows = await db.fetch_all("""
            WITH last_messages AS (
                SELECT DISTINCT ON (partner)
                    CASE
                        WHEN sender = $1 THEN recipient
                        ELSE sender
                    END AS partner,
                    id,
                    sender,
                    EXTRACT(EPOCH FROM timestamp) as ts
                FROM transactions
                WHERE sender = $1 OR recipient = $1
                ORDER BY partner, timestamp DESC
            )
            SELECT
                lm.*,
                CASE
                    WHEN lm.partner LIKE 'group:%' THEN
                        (SELECT name FROM groups WHERE id = SUBSTRING(lm.partner, 7))
                    ELSE
                        (SELECT contact_name FROM contacts
                         WHERE user_address = $1 AND contact_address = lm.partner LIMIT 1)
                END as display_name
            FROM last_messages lm
            ORDER BY lm.ts DESC
            LIMIT 50
        """, user_address)

        conversations = [
            {
                'address': row['partner'],
                'name': row['display_name'] or (
                    row['partner'][:10] + '...'
                    if not row['partner'].startswith('group:') else 'Группа'
                ),
                'is_group': row['partner'].startswith('group:'),
                'last_preview': (
                    '💬 Сообщение' if row['sender'] != user_address else 'Вы: сообщение'
                ),
                'last_ts': row['ts'],
            }
            for row in rows
        ]

        await redis_manager.cache_set(cache_key, conversations, ttl=30)
        return jsonify({'conversations': conversations}), 200

    except Exception as e:
        logger.error(f"get_conversations_list error: {e}")
        return jsonify({'error': 'Failed to load conversations'}), 500


# =============================================================================
# MARK CONVERSATION AS READ
# =============================================================================

@messages_bp.route('/mark_conversation_read', methods=['POST'])
async def mark_conversation_read():
    """Отметить диалог как прочитанный"""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json() or {}
    chat_with = data.get('chat_with', '').strip()
    last_message_id = data.get('last_message_id')

    if not chat_with:
        return jsonify({'error': 'Missing chat_with'}), 400

    try:
        if last_message_id is None:
            if chat_with.startswith('group:'):
                last_message_id = await db.fetch_val(
                    "SELECT MAX(id) FROM transactions WHERE recipient = $1",
                    chat_with
                ) or 0
            else:
                last_message_id = await db.fetch_val("""
                    SELECT MAX(id) FROM transactions
                    WHERE (sender = $1 AND recipient = $2)
                       OR (sender = $2 AND recipient = $1)
                """, user_address, chat_with) or 0

        await db.execute("""
            INSERT INTO read_status (user_address, chat_id, last_read_message_id, read_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (user_address, chat_id) DO UPDATE
            SET last_read_message_id = EXCLUDED.last_read_message_id,
                read_at = EXCLUDED.read_at
            WHERE EXCLUDED.last_read_message_id > read_status.last_read_message_id
        """, user_address, chat_with, last_message_id)

        await redis_manager.cache_delete(f"conversations:{user_address}")
        return jsonify({'status': 'ok', 'last_read': last_message_id}), 200

    except Exception as e:
        logger.error(f"Mark read error: {e}")
        return jsonify({'error': 'Failed to mark as read'}), 500


# =============================================================================
# GET PUBLIC KEY
# =============================================================================

@messages_bp.route('/get_public_key/<string:address>', methods=['GET'])
async def get_public_key_route(address: str):
    """Получить публичный ключ пользователя по адресу"""
    if len(address) != 64:
        return jsonify({'error': 'Invalid address'}), 400

    pubkey = await redis_manager.cache_get(f"pubkey:{address}")
    if pubkey:
        return jsonify({'address': address, 'public_key': pubkey,
                        'verified': True, 'source': 'cache'}), 200

    row = await db.fetch_one("""
        SELECT sender_pubkey FROM transactions
        WHERE sender = $1 AND sender_pubkey IS NOT NULL
        ORDER BY timestamp DESC LIMIT 1
    """, address)

    if row and row['sender_pubkey']:
        pubkey = row['sender_pubkey']
        await redis_manager.cache_set(f"pubkey:{address}", pubkey, ttl=3600)
        return jsonify({'address': address, 'public_key': pubkey,
                        'verified': True, 'source': 'blockchain'}), 200

    return jsonify({'error': 'Public key not found'}), 404


# =============================================================================
# ADMIN / MONITORING ENDPOINTS
# =============================================================================

@messages_bp.route('/notifier/stats', methods=['GET'])
async def notifier_stats():
    """Статистика системы уведомлений"""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    stats = await redis_manager.get_stats()
    return jsonify({
        'type': 'redis',
        'stats': stats,
        'long_polling_timeout': LONG_POLLING_TIMEOUT,
        'max_messages_per_poll': MAX_MESSAGES_PER_POLL,
    }), 200


@messages_bp.route('/force_check', methods=['POST'])
async def force_check():
    """Принудительно пробудить ожидающие long polling запросы"""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    await redis_manager.notify_user(user_address)
    return jsonify({'status': 'ok'}), 200