"""
routes/messages.py — Отправка и получение сообщений (сервер не работает с ключами)
"""
import json
import logging
import threading
import time
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, request, session
from marshmallow import ValidationError
from setup import rate_limit, message_limiter

from cache import (
    get_contact_cache_version, get_contact_name_cached,
    get_groups_cache_version, get_user_groups_cached,
)
from services.messaging import get_conversations_list
from services.wallet import mine_block_async, staking_manager
from config import MESSAGE_FEE, COIN, COIN_NAME, STAKING_FEE_POOL_ADDRESS, ENABLE_STAKING, CONFIG

logger = logging.getLogger(__name__)
messages_bp = Blueprint('messages', __name__)

_blockchain = None
_p2p_buffer: Dict[str, List[Dict]] = {}
_p2p_buffer_lock = threading.Lock()

# =============================================================================
# Long Polling Notifier (упрощённая версия, без отдельного файла)
# =============================================================================

class MessageNotifier:
    """Потокобезопасный менеджер уведомлений для Long Polling"""

    def __init__(self, default_timeout: int = 25):
        self.default_timeout = default_timeout
        self._events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def get_event(self, user_address: str) -> threading.Event:
        with self._lock:
            if user_address not in self._events:
                self._events[user_address] = threading.Event()
            return self._events[user_address]

    def notify_user(self, user_address: str) -> None:
        with self._lock:
            if user_address in self._events:
                self._events[user_address].set()
                logger.debug(f"Notified {user_address[:16]}...")

    def notify_group(self, group_id: str, members: List[str]) -> None:
        for member in members:
            self.notify_user(member)

    def wait_for_messages(self, user_address: str, timeout: int = None) -> bool:
        if timeout is None:
            timeout = self.default_timeout
        event = self.get_event(user_address)
        triggered = event.wait(timeout)
        if triggered:
            event.clear()
        return triggered

    def get_stats(self) -> dict:
        with self._lock:
            return {'active_events': len(self._events)}

# Глобальный экземпляр
message_notifier = MessageNotifier(default_timeout=25)


def init_messages(blockchain) -> None:
    global _blockchain
    _blockchain = blockchain


# =============================================================================
# Вспомогательные функции
# =============================================================================

def _get_new_messages_since(user_addr: str, since_timestamp: float, limit: int = 50) -> List[dict]:
    """Получает новые сообщения после указанного времени"""
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

            # Получаем имя отправителя (если есть в контактах)
            sender_name = None
            if not is_group and not is_group:
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
            })

        return messages

    except Exception as e:
        logger.error(f"_get_new_messages_since error: {e}")
        return []


# =============================================================================
# Long Polling Endpoint (НОВЫЙ!)
# =============================================================================

@messages_bp.route('/wait_for_messages', methods=['GET'])
def wait_for_messages():
    """
    Long Polling эндпоинт — ожидает новые сообщения до 30 секунд.
    Клиент должен передавать timestamp последнего полученного сообщения.
    """
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_addr = session['address']

    # Получаем параметры
    try:
        since = float(request.args.get('since', 0))
        timeout = min(int(request.args.get('timeout', 25)), 30)  # Максимум 30 секунд
    except (ValueError, TypeError):
        since = 0
        timeout = 25

    # Ждём уведомление о новых сообщениях
    has_new = message_notifier.wait_for_messages(user_addr, timeout)

    # Проверяем реальные новые сообщения
    new_messages = _get_new_messages_since(user_addr, since)

    return jsonify({
        'messages': new_messages,
        'has_more': len(new_messages) >= 50,
        'timestamp': time.time(),
        'waited': timeout,
        'notified': has_new
    }), 200


# =============================================================================
# Legacy endpoint (для обратной совместимости)
# =============================================================================

@messages_bp.route('/check_new_messages', methods=['GET'])
def check_new_messages_legacy():
    """Legacy endpoint — лучше использовать /wait_for_messages"""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    since = float(request.args.get('since', 0))
    messages = _get_new_messages_since(session['address'], since)
    return jsonify({'messages': messages}), 200


# =============================================================================
# Send Message (с уведомлениями)
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

        # --- Открываем транзакцию ---
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute("BEGIN IMMEDIATE")

            # Проверка баланса для комиссии
            if MESSAGE_FEE > 0:
                cursor.execute('SELECT balance FROM wallets WHERE address = ?', (sender,))
                row = cursor.fetchone()
                balance = row[0] if row else 0
                if balance < MESSAGE_FEE:
                    cursor.execute("ROLLBACK")
                    return jsonify({'error': f'Insufficient balance for fee ({MESSAGE_FEE/COIN:.6f} {COIN_NAME})'}), 402

                # Списание комиссии
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

            # Сохраняем сообщение
            tx_id = None

            if msg_type == 'group' and group_id:
                # Групповое сообщение
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

                # ✅ Уведомляем всех участников группы (кроме отправителя)
                for member in group['members']:
                    if member != sender:
                        message_notifier.notify_user(member)

            else:
                # Личное сообщение
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

                # ✅ Уведомляем получателя
                message_notifier.notify_user(recipient)

            cursor.execute("COMMIT")

            # Асинхронный майнинг (если включён)
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
# GET CONVERSATION (без изменений, но оставляем)
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
    return jsonify({'conversations': get_conversations_list(session['address'])}), 200


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


# =============================================================================
# Admin endpoint для мониторинга
# =============================================================================

@messages_bp.route('/notifier/stats')
def notifier_stats():
    """Статистика системы уведомлений (только для админов)"""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    # Можно добавить проверку на админа
    return jsonify(message_notifier.get_stats())