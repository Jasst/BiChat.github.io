"""
routes/messages.py — Отправка и получение сообщений (сервер не работает с ключами)
"""
import json
import logging
import threading
import time
from typing import Dict, List

from flask import Blueprint, jsonify, request, session
from marshmallow import ValidationError

from cache import (
    get_contact_cache_version, get_contact_name_cached,
    get_groups_cache_version, get_user_groups_cached,
)
from services.messaging import get_conversations_list
from services.wallet import mine_block_async

logger = logging.getLogger(__name__)
messages_bp = Blueprint('messages', __name__)

_blockchain = None
_lottery    = None
_p2p_buffer: Dict[str, List[Dict]] = {}
_p2p_buffer_lock = threading.Lock()


def init_messages(blockchain, lottery) -> None:
    global _blockchain, _lottery
    _blockchain = blockchain
    _lottery    = lottery


@messages_bp.route('/send_message', methods=['POST'])
def send_message():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    sender = session['address']

    try:
        data = request.get_json(silent=True) or {}
        recipient = data.get('recipient')
        payload = data.get('payload')            # уже зашифрованный клиентом пакет
        msg_type = data.get('message_type', 'direct')
        group_id = data.get('group_id')

        if msg_type == 'group' and group_id:
            # Групповое: клиент передаёт encrypted_map
            encrypted_map = data.get('encrypted_map')
            if not encrypted_map or not isinstance(encrypted_map, dict):
                return jsonify({'error': 'Missing encrypted_map'}), 400

            # Проверка членства в группе
            groups = get_user_groups_cached(sender, cache_version=get_groups_cache_version())
            group = next((g for g in groups if g['id'] == group_id), None)
            if not group or sender not in group['members']:
                return jsonify({'error': 'Access denied'}), 403

            from database import get_db_cursor
            with get_db_cursor(_blockchain.db_path) as cursor:
                tx_id = _blockchain.new_transaction(
                    cursor, sender, f"group:{group_id}",
                    json.dumps({'encrypted_map': encrypted_map}), None,
                    sender_pubkey=None,
                    metadata={'encryption': 'group-ecdh-v4', 'group_id': group_id}
                )
                last_proof = _blockchain._last_block_raw(cursor)['proof']
                threading.Thread(
                    target=mine_block_async,
                    args=(_blockchain.db_path, last_proof), daemon=True
                ).start()

            _lottery.claim_message_reward(sender)
            return jsonify({'message': 'Sent', 'tx_id': tx_id, 'type': 'group'}), 201

        # P2P
        if sender == recipient:
            return jsonify({'error': 'Cannot message yourself'}), 400

        if not payload or not isinstance(payload, dict):
            return jsonify({'error': 'Missing encrypted payload'}), 400

        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            tx_id = _blockchain.new_transaction(
                cursor, sender, recipient, json.dumps(payload), None,
                sender_pubkey=None,
                metadata={'encryption': 'hybrid-v2'}
            )
            last_proof = _blockchain._last_block_raw(cursor)['proof']
            threading.Thread(
                target=mine_block_async,
                args=(_blockchain.db_path, last_proof), daemon=True
            ).start()
        _lottery.claim_message_reward(sender)
        return jsonify({'message': 'Sent', 'tx_id': tx_id, 'recipient': recipient}), 201

    except Exception as e:
        logger.error(f"send_message error: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


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
                'sender_pubkey': None,  # клиент получит ключ через /get_public_key
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
                # Ищем последний ID в этом чате
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
            updated = cursor.rowcount
        return jsonify({'status': 'ok', 'last_read': last_message_id, 'updated': bool(updated)}), 200
    except Exception as e:
        logger.error(f"Mark read error: {e}")
        return jsonify({'error': 'Failed'}), 500


@messages_bp.route('/check_new_messages')
def check_new_messages():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user_addr = session['address']
    try:
        since = float(request.args.get('since', 0))
    except (ValueError, TypeError):
        since = 0

    try:
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute('''
                SELECT id, sender, recipient, content, image, timestamp
                FROM transactions
                WHERE (recipient = ? OR recipient LIKE ?)
                  AND timestamp > ? AND sender != ?
                ORDER BY timestamp DESC LIMIT 50
            ''', (user_addr, 'group:%', since, user_addr))
            rows = cursor.fetchall()

        messages = []
        for row in rows:
            messages.append({
                'id': row[0],
                'sender': row[1],
                'chatId': (row[2] if row[2].startswith('group:') else row[1]),
                'preview': '💬 Новое сообщение',   # без расшифровки
                'isGroup': row[2].startswith('group:'),
                'timestamp': row[5],
            })
        return jsonify({'messages': messages}), 200
    except Exception as e:
        logger.error(f"check_new_messages error: {e}")
        return jsonify({'error': 'Internal error'}), 500


@messages_bp.route('/get_public_key/<string:address>')
def get_public_key_route(address: str):
    from cache import get_cached_public_key, get_pubkey_cache_version, fetch_public_key_from_chain
    pubkey, verified = get_cached_public_key(address, cache_version=get_pubkey_cache_version())
    if not pubkey:
        pubkey, verified = fetch_public_key_from_chain(address)
    if pubkey:
        return jsonify({'address': address, 'public_key': pubkey, 'verified': verified}), 200
    return jsonify({'error': 'Public key not found'}), 404