"""
routes/messages.py — Отправка и получение сообщений (с буферизацией для Long Polling)
"""
import json
import logging
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, request, session
from marshmallow import ValidationError
from setup import rate_limit, message_limiter

from cache import (
    get_contact_cache_version, get_contact_name_cached,
    get_groups_cache_version, get_user_groups_cached,
)
from services.messaging import get_conversations_list, get_conversations_list_cached, invalidate_conversations_cache
from services.wallet import mine_block_async, staking_manager
from config import MESSAGE_FEE, COIN, COIN_NAME, STAKING_FEE_POOL_ADDRESS, ENABLE_STAKING, CONFIG

logger = logging.getLogger(__name__)
messages_bp = Blueprint('messages', __name__)

_blockchain = None
_p2p_buffer: Dict[str, List[Dict]] = {}
_p2p_buffer_lock = threading.Lock()

# =============================================================================
# Улучшенный MessageNotifier с БУФЕРИЗАЦИЕЙ сообщений
# =============================================================================

class MessageNotifier:
    """
    Потокобезопасный менеджер уведомлений для Long Polling с буферизацией.
    Сообщения накапливаются в очереди, пока клиент их не заберёт.
    """

    def __init__(self, default_timeout: int = 25, max_buffer_size: int = 100):
        self.default_timeout = default_timeout
        self.max_buffer_size = max_buffer_size
        self._events: Dict[str, threading.Event] = {}
        self._buffers: Dict[str, List[dict]] = defaultdict(list)
        self._last_timestamps: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._cleanup_counter = 0

    def get_event(self, user_address: str) -> threading.Event:
        with self._lock:
            if user_address not in self._events:
                self._events[user_address] = threading.Event()
            return self._events[user_address]

    def add_message(self, user_address: str, message: dict) -> None:
        with self._lock:
            self._buffers[user_address].append(message)
            if len(self._buffers[user_address]) > self.max_buffer_size:
                self._buffers[user_address] = self._buffers[user_address][-self.max_buffer_size:]
            if user_address in self._events:
                self._events[user_address].set()
            logger.debug(f"📦 Added message to buffer for {user_address[:16]}..., buffer size: {len(self._buffers[user_address])}")

    def add_group_messages(self, group_id: str, members: List[str], message: dict, exclude_sender: str = None) -> None:
        for member in members:
            if member != exclude_sender:
                self.add_message(member, message)

    def notify_user(self, user_address: str) -> None:
        with self._lock:
            if user_address in self._events:
                self._events[user_address].set()
                logger.debug(f"🔔 Notified {user_address[:16]}...")

    def notify_group(self, group_id: str, members: List[str]) -> None:
        for member in members:
            self.notify_user(member)

    def get_messages(self, user_address: str, since_timestamp: float, timeout: int = None) -> tuple:
        if timeout is None:
            timeout = self.default_timeout

        with self._lock:
            self._last_timestamps[user_address] = since_timestamp
            buffer = self._buffers.get(user_address, [])
            new_messages = [m for m in buffer if m.get('timestamp', 0) > since_timestamp]

            if new_messages:
                logger.debug(f"⚡ Returning {len(new_messages)} buffered messages to {user_address[:16]}...")
                last_ts = max(m.get('timestamp', 0) for m in new_messages)
                self._buffers[user_address] = [m for m in buffer if m.get('timestamp', 0) > last_ts]
                return new_messages, 0, False

        event = self.get_event(user_address)
        triggered = event.wait(timeout)

        with self._lock:
            if triggered:
                event.clear()
            buffer = self._buffers.get(user_address, [])
            new_messages = [m for m in buffer if m.get('timestamp', 0) > since_timestamp]
            if new_messages:
                last_ts = max(m.get('timestamp', 0) for m in new_messages)
                self._buffers[user_address] = [m for m in buffer if m.get('timestamp', 0) > last_ts]
            self._cleanup_counter += 1
            if self._cleanup_counter > 100:
                self._cleanup_old_buffers()
                self._cleanup_counter = 0
            return new_messages, timeout if not triggered else 0, triggered

    def _cleanup_old_buffers(self):
        one_hour_ago = time.time() - 3600
        to_delete = []
        for addr, ts in self._last_timestamps.items():
            if ts < one_hour_ago:
                to_delete.append(addr)
        for addr in to_delete:
            if addr in self._buffers:
                del self._buffers[addr]
            if addr in self._events:
                del self._events[addr]
            if addr in self._last_timestamps:
                del self._last_timestamps[addr]
        if to_delete:
            logger.debug(f"🧹 Cleaned up {len(to_delete)} inactive buffers")

    def force_check(self, user_address: str) -> None:
        with self._lock:
            if user_address in self._events:
                self._events[user_address].set()
                logger.debug(f"⚡ Forced check for {user_address[:16]}...")

    def get_stats(self) -> dict:
        with self._lock:
            total_buffered = sum(len(buf) for buf in self._buffers.values())
            return {
                'active_events': len(self._events),
                'total_buffered': total_buffered,
                'active_users': len(self._buffers),
                'default_timeout': self.default_timeout,
                'max_buffer_size': self.max_buffer_size,
            }

# Глобальный экземпляр
message_notifier = MessageNotifier(default_timeout=25, max_buffer_size=100)


def init_messages(blockchain) -> None:
    global _blockchain
    _blockchain = blockchain


# =============================================================================
# Вспомогательные функции
# =============================================================================

def _fetch_new_messages_from_db(user_addr: str, since_timestamp: float, limit: int = 50) -> List[dict]:
    from database import get_db_cursor
    try:
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute('''
                SELECT id, sender, recipient, content, image, timestamp, metadata
                FROM transactions
                WHERE (recipient = ? OR recipient LIKE ?)
                  AND timestamp > ?
                  AND sender != ?
                ORDER BY timestamp ASC
                LIMIT ?
            ''', (user_addr, 'group:%', since_timestamp, user_addr, limit))
            rows = cursor.fetchall()

        messages = []
        for row in rows:
            is_group = row[2].startswith('group:')
            chat_id = row[2] if is_group else row[1]
            sender_name = None
            if not is_group:
                try:
                    with get_db_cursor(_blockchain.db_path) as cursor2:
                        cursor2.execute(
                            'SELECT contact_name FROM contacts WHERE user_address = ? AND contact_address = ?',
                            (user_addr, row[1])
                        )
                        contact_row = cursor2.fetchone()
                        if contact_row:
                            sender_name = contact_row[0]
                except:
                    pass
            messages.append({
                'id': row[0],
                'sender': row[1],
                'sender_name': sender_name,
                'chatId': chat_id,
                'isGroup': is_group,
                'preview': '💬 Новое сообщение',
                'timestamp': row[5],
                'content': row[3],
                'image': row[4],
            })
        return messages
    except Exception as e:
        logger.error(f"_fetch_new_messages_from_db error: {e}")
        return []


# =============================================================================
# Long Polling Endpoint
# =============================================================================

@messages_bp.route('/wait_for_messages', methods=['GET'])
def wait_for_messages():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_addr = session['address']

    # Санитизация since timestamp
    try:
        since = float(request.args.get('since', 0))
        now = time.time()
        min_valid = now - 3600
        max_valid = now + 60
        since = max(min(since, max_valid), min_valid)
    except (ValueError, TypeError):
        since = time.time() - 3600

    # Ограничение timeout
    try:
        timeout = int(request.args.get('timeout', 25))
        timeout = min(max(timeout, 5), 15)
        if message_notifier.get_stats()['active_events'] > 200:
            return jsonify({'messages': [], 'throttled': True}), 200
    except (ValueError, TypeError):
        timeout = 25

    # Rate limiting (не чаще 2 раз в секунду)
    _last_poll_time = getattr(wait_for_messages, '_last_poll_time', {})
    last_request = _last_poll_time.get(user_addr, 0)
    now = time.time()
    if now - last_request < 0.5:
        _last_poll_time[user_addr] = now
        response = jsonify({'messages': [], 'throttled': True, 'timestamp': now})
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    _last_poll_time[user_addr] = now

    # Проверка существования пользователя
    from database import get_db_cursor
    try:
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute('SELECT 1 FROM wallets WHERE address = ?', (user_addr,))
            if not cursor.fetchone():
                logger.warning(f"Invalid user attempted long poll: {user_addr[:16]}...")
                response = jsonify({'error': 'Invalid user'})
                response.status_code = 403
                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'
                return response
    except Exception as e:
        logger.error(f"User validation error: {e}")
        response = jsonify({'error': 'Internal error'})
        response.status_code = 500
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    # Получение сообщений из буфера
    buffered_messages, waited_time, had_notification = message_notifier.get_messages(
        user_addr, since, timeout
    )

    if buffered_messages:
        if len(buffered_messages) > 50:
            buffered_messages = buffered_messages[:50]
        sanitized_messages = []
        for msg in buffered_messages:
            sanitized = {
                'id': msg.get('id'),
                'sender': msg.get('sender'),
                'sender_name': msg.get('sender_name'),
                'chatId': msg.get('chatId'),
                'isGroup': msg.get('isGroup', False),
                'preview': msg.get('preview', '💬 Новое сообщение'),
                'timestamp': msg.get('timestamp', time.time()),
                'content': msg.get('content'),
                'image': msg.get('image'),
            }
            sanitized_messages.append(sanitized)
        response = jsonify({
            'messages': sanitized_messages,
            'has_more': len(buffered_messages) >= 50,
            'timestamp': time.time(),
            'from_buffer': True,
            'waited': waited_time,
        })
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    # Проверка БД
    db_messages = _fetch_new_messages_from_db(user_addr, since)
    if db_messages:
        for msg in db_messages:
            message_notifier.add_message(user_addr, msg)

        # Инвалидация кэша диалогов при получении новых сообщений
        invalidate_conversations_cache(user_addr)

        if len(db_messages) > 50:
            db_messages = db_messages[:50]
        sanitized_messages = []
        for msg in db_messages:
            sanitized = {
                'id': msg.get('id'),
                'sender': msg.get('sender'),
                'sender_name': msg.get('sender_name'),
                'chatId': msg.get('chatId'),
                'isGroup': msg.get('isGroup', False),
                'preview': msg.get('preview', '💬 Новое сообщение'),
                'timestamp': msg.get('timestamp', time.time()),
                'content': msg.get('content'),
                'image': msg.get('image'),
            }
            sanitized_messages.append(sanitized)
        response = jsonify({
            'messages': sanitized_messages,
            'has_more': len(db_messages) >= 50,
            'timestamp': time.time(),
            'from_db': True,
        })
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    response = jsonify({
        'messages': [],
        'has_more': False,
        'timestamp': time.time(),
        'waited': timeout,
        'notified': had_notification,
    })
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@messages_bp.route('/message/<int:message_id>/delivered', methods=['POST'])
def mark_delivered(message_id):
    """Получатель подтверждает доставку сообщения"""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user_addr = session['address']

    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute('''
            UPDATE transactions 
            SET status = 'delivered' 
            WHERE id = ? AND recipient = ? AND status = 'sent'
        ''', (message_id, user_addr))
        cursor.connection.commit()
    return jsonify({'status': 'ok'})


@messages_bp.route('/message/<int:message_id>/read', methods=['POST'])
def mark_read(message_id):
    """Получатель подтверждает прочтение сообщения"""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user_addr = session['address']

    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute('''
            UPDATE transactions 
            SET status = 'read', read_at = ? 
            WHERE id = ? AND recipient = ? AND status IN ('sent', 'delivered')
        ''', (time.time(), message_id, user_addr))
        cursor.connection.commit()
    return jsonify({'status': 'ok'})


@messages_bp.route('/message/statuses', methods=['POST'])
def get_messages_statuses():
    """Получить статусы нескольких сообщений (для отправителя)"""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    msg_ids = data.get('ids', [])
    if not msg_ids:
        return jsonify({})

    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        placeholders = ','.join('?' * len(msg_ids))
        cursor.execute(f"SELECT id, status FROM transactions WHERE id IN ({placeholders})", msg_ids)
        rows = cursor.fetchall()
    return jsonify({str(row[0]): row[1] for row in rows})

# =============================================================================
# Legacy endpoint
# =============================================================================

@messages_bp.route('/check_new_messages', methods=['GET'])
def check_new_messages_legacy():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    since = float(request.args.get('since', 0))
    messages = _fetch_new_messages_from_db(session['address'], since)
    return jsonify({'messages': messages}), 200


# =============================================================================
# Send Message
# =============================================================================

@messages_bp.route('/send_message', methods=['POST'])
@rate_limit(message_limiter, limit=30)
def send_message():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    sender = session['address']

    try:
        data = request.get_json(silent=True) or {}
        recipient = data.get('recipient')
        payload = data.get('payload')
        msg_type = data.get('message_type', 'direct')
        group_id = data.get('group_id')
        encrypted_map = data.get('encrypted_map') if msg_type == 'group' else None

        from database import get_db_cursor

        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute("BEGIN IMMEDIATE")

            if MESSAGE_FEE > 0:
                cursor.execute('SELECT balance FROM wallets WHERE address = ?', (sender,))
                row = cursor.fetchone()
                balance = row[0] if row else 0
                if balance < MESSAGE_FEE:
                    cursor.execute("ROLLBACK")
                    return jsonify({'error': f'Insufficient balance for fee ({MESSAGE_FEE/COIN:.6f} {COIN_NAME})'}), 402

                cursor.execute('UPDATE wallets SET balance = balance - ? WHERE address = ?', (MESSAGE_FEE, sender))
                cursor.execute(
                    'INSERT INTO wallets (address, balance) VALUES (?, ?) '
                    'ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                    (STAKING_FEE_POOL_ADDRESS, MESSAGE_FEE, MESSAGE_FEE)
                )
                cursor.execute(
                    'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) '
                    'VALUES (?,?,?,?,?,?)',
                    ('message_fee', sender, STAKING_FEE_POOL_ADDRESS, MESSAGE_FEE, time.time(), 'message fee')
                )
                if ENABLE_STAKING and staking_manager:
                    staking_manager.add_to_fee_pool(MESSAGE_FEE, cursor=cursor)

            tx_id = None
            message_obj = None
            group = None  # инициализируем переменную

            if msg_type == 'group' and group_id:
                if not encrypted_map:
                    cursor.execute("ROLLBACK")
                    return jsonify({'error': 'Missing encrypted_map'}), 400

                groups = get_user_groups_cached(sender, cache_version=get_groups_cache_version())
                group = next((g for g in groups if g['id'] == group_id), None)
                if not group or sender not in group['members']:
                    cursor.execute("ROLLBACK")
                    return jsonify({'error': 'Access denied'}), 403

                tx_id = _blockchain.new_transaction(
                    cursor, sender, f"group:{group_id}",
                    json.dumps({'encrypted_map': encrypted_map}), None,
                    sender_pubkey=None,
                    metadata={'encryption': 'group-ecdh-v4', 'group_id': group_id}
                )

                message_obj = {
                    'id': tx_id,
                    'sender': sender,
                    'sender_name': None,
                    'chatId': f"group:{group_id}",
                    'isGroup': True,
                    'preview': '💬 Новое сообщение в группе',
                    'timestamp': time.time(),
                    'content': json.dumps({'encrypted_map': encrypted_map}),
                    'image': None,
                }
                message_notifier.add_group_messages(group_id, group['members'], message_obj, exclude_sender=sender)

            else:
                if sender == recipient:
                    cursor.execute("ROLLBACK")
                    return jsonify({'error': 'Cannot message yourself'}), 400
                if not payload or not isinstance(payload, dict):
                    cursor.execute("ROLLBACK")
                    return jsonify({'error': 'Missing encrypted payload'}), 400

                tx_id = _blockchain.new_transaction(
                    cursor, sender, recipient, json.dumps(payload), None,
                    sender_pubkey=None,
                    metadata={'encryption': 'hybrid-v2'}
                )

                message_obj = {
                    'id': tx_id,
                    'sender': sender,
                    'sender_name': None,
                    'chatId': recipient,
                    'isGroup': False,
                    'preview': '💬 Новое сообщение',
                    'timestamp': time.time(),
                    'content': json.dumps(payload),
                    'image': None,
                }
                message_notifier.add_message(recipient, message_obj)

            cursor.execute("COMMIT")

            # Уведомления
            if msg_type == 'group' and group_id and group:
                for member in group['members']:
                    if member != sender:
                        message_notifier.notify_user(member)
            else:
                message_notifier.notify_user(recipient)

            # Инвалидация кэша диалогов
            invalidate_conversations_cache(sender)  # у отправителя

            if msg_type == 'group' and group_id and group:
                # Для группы — инвалидируем всех участников
                for member in group['members']:
                    invalidate_conversations_cache(member)
            else:
                # Для личного сообщения — инвалидируем получателя
                invalidate_conversations_cache(recipient)

            # Фоновый майнинг (если включен)
            if CONFIG.get('ENABLE_MINING', False):
                last = _blockchain._last_block_raw(cursor)
                if last:
                    threading.Thread(
                        target=mine_block_async,
                        args=(last.get('proof', 0), sender),
                        daemon=True
                    ).start()

            return jsonify({
                'message': 'Sent',
                'tx_id': tx_id,
                'type': msg_type,
                'fee': MESSAGE_FEE
            }), 201

    except Exception as e:
        logger.error(f"send_message error: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


# =============================================================================
# GET CONVERSATION
# =============================================================================

@messages_bp.route('/get_conversation', methods=['GET'])
def get_conversation():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user_addr = session['address']
    chat_with = request.args.get('with')
    if not chat_with:
        return jsonify({'error': 'Missing "with" parameter'}), 400

    last_message_id = request.args.get('last_message_id', type=int)
    limit = min(int(request.args.get('limit', 30)), 50)
    before_id = request.args.get('before_id', type=int)

    try:
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            if chat_with.startswith('group:'):
                group_id = chat_with.split(':', 1)[1]
                groups = get_user_groups_cached(user_addr, cache_version=get_groups_cache_version())
                if not any(g['id'] == group_id and user_addr in g['members'] for g in groups):
                    return jsonify({'error': 'No access'}), 403
                query = ('SELECT id, sender, recipient, content, image, timestamp, metadata '
                         'FROM transactions WHERE recipient = ?')
                params = [chat_with]
                if last_message_id:
                    query += ' AND id > ?'; params.append(last_message_id)
                if before_id:
                    query += ' AND id < ?'; params.append(before_id)
                query += ' ORDER BY timestamp ASC LIMIT ?'; params.append(limit)
            else:
                query = '''
                    SELECT id, sender, recipient, content, image, timestamp, metadata
                    FROM (
                        SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                        UNION ALL
                        SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                    )
                '''
                params = [user_addr, chat_with, chat_with, user_addr]
                filters = []
                if last_message_id:
                    filters.append('id > ?'); params.append(last_message_id)
                if before_id:
                    filters.append('id < ?'); params.append(before_id)
                if filters:
                    query += ' WHERE ' + ' AND '.join(filters)
                query += ' ORDER BY timestamp DESC LIMIT ?'; params.append(limit)
            cursor.execute(query, params)
            rows = cursor.fetchall()

        messages = []
        for r in rows:
            msg = {
                'id': r[0], 'sender': r[1], 'recipient': r[2],
                'content': r[3], 'image': r[4], 'timestamp': r[5],
                'sender_pubkey': None,
                'metadata': r[6],
                'sender_name': get_contact_name_cached(user_addr, r[1],
                                                       cache_version=get_contact_cache_version()) or r[1][:10] + '...',
                'recipient_name': get_contact_name_cached(user_addr, r[2],
                                                         cache_version=get_contact_cache_version()) or r[2][:10] + '...',
                'is_mine': (r[1] == user_addr)
            }
            messages.append(msg)

        if not chat_with.startswith('group:'):
            messages.reverse()

        return jsonify({'messages': messages, 'chat_with': chat_with}), 200
    except Exception as e:
        logger.error(f"get_conversation error: {e}")
        return jsonify({'error': 'Failed'}), 500


@messages_bp.route('/get_conversations', methods=['GET'])
def get_conversations_route():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    # Используем кэшированную версию
    conversations = get_conversations_list_cached(session['address'])

    return jsonify({'conversations': conversations}), 200


@messages_bp.route('/mark_conversation_read', methods=['POST'])
def mark_conversation_read():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user_addr = session['address']
    data = request.get_json(silent=True) or {}
    chat_with = data.get('chat_with', '').strip()
    last_message_id = data.get('last_message_id')

    if not chat_with:
        return jsonify({'error': 'Missing chat_with'}), 400

    try:
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            if last_message_id is None:
                if chat_with.startswith('group:'):
                    cursor.execute('SELECT MAX(id) FROM transactions WHERE recipient = ?', (chat_with,))
                else:
                    cursor.execute('''
                        SELECT MAX(id) FROM transactions
                        WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)
                    ''', (user_addr, chat_with, chat_with, user_addr))
                row = cursor.fetchone()
                last_message_id = row[0] if row and row[0] else 0

            cursor.execute('''
                INSERT INTO read_status (user_address, chat_id, last_read_message_id, read_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_address, chat_id) DO UPDATE
                SET last_read_message_id = excluded.last_read_message_id,
                    read_at = excluded.read_at
                WHERE excluded.last_read_message_id > read_status.last_read_message_id
            ''', (user_addr, chat_with, last_message_id, time.time()))
        return jsonify({'status': 'ok', 'last_read': last_message_id}), 200
    except Exception as e:
        logger.error(f"Mark read error: {e}")
        return jsonify({'error': 'Failed'}), 500


@messages_bp.route('/get_public_key/<string:address>')
def get_public_key_route(address: str):
    from cache import get_cached_public_key, get_pubkey_cache_version, fetch_public_key_from_chain
    pubkey, verified = get_cached_public_key(address, cache_version=get_pubkey_cache_version())
    if not pubkey:
        pubkey, verified = fetch_public_key_from_chain(address)
    if pubkey:
        return jsonify({'address': address, 'public_key': pubkey, 'verified': verified}), 200
    return jsonify({'error': 'Public key not found'}), 404


@messages_bp.route('/search_messages', methods=['GET'])
def search_messages():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({'error': 'Query too short'}), 400

    results = _blockchain.search_messages(session['address'], query)
    return jsonify({'results': results}), 200


# =============================================================================
# Admin endpoints
# =============================================================================

@messages_bp.route('/notifier/stats')
def notifier_stats():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(message_notifier.get_stats())


@messages_bp.route('/force_check', methods=['POST'])
def force_check():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user_addr = session['address']
    message_notifier.force_check(user_addr)
    return jsonify({'status': 'ok'}), 200