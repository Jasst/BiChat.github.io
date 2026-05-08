"""
routes/messages.py — Отправка, получение, расшифровка сообщений
"""
import hmac
import json
import logging
import threading
import time
from typing import Dict, List

from flask import Blueprint, jsonify, request, session
from marshmallow import ValidationError

from cache import (
    cache_public_key, fetch_public_key_from_chain,
    get_cached_public_key, get_contact_cache_version,
    get_groups_cache_version, get_pubkey_cache_version,
    get_user_groups_cached, get_contact_name_cached,
)
from crypto_manager import (
    compute_shared_key_b64, encrypt_hybrid, encrypt_message_aead,
    generate_address, get_public_key_b64, decrypt_hybrid,
)
from schemas import MessageSchema
from services.messaging import get_conversations_list, process_message_decryption
from services.wallet import mine_block_async

logger      = logging.getLogger(__name__)
messages_bp = Blueprint('messages', __name__)

# Ссылки, инициализируемые из app.py
_blockchain = None
_lottery    = None
_socketio   = None
_p2p_buffer: Dict[str, List[Dict]] = {}
_p2p_buffer_lock = threading.Lock()


def init_messages(blockchain, lottery, socketio) -> None:
    global _blockchain, _lottery, _socketio
    _blockchain = blockchain
    _lottery    = lottery
    _socketio   = socketio


def _notify_new_message(recipient: str, tx_id: int, sender: str = None) -> None:
    _socketio.emit('new_message',
                   {'chat_id': sender if sender else recipient,
                    'tx_id': tx_id, 'sender': sender},
                   room=recipient)


# =============================================================================
# Отправка сообщения
# =============================================================================

@messages_bp.route('/send_message', methods=['POST'])
def send_message():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data      = MessageSchema().load(request.get_json())
        sender    = session['address']
        recipient = data['recipient']
        content   = data['content']
        image     = data.get('image')
        msg_type  = data.get('message_type', 'direct')
        group_id  = data.get('group_id')
        mnemonic  = session.get('mnemonic')
        if not mnemonic:
            return jsonify({'error': 'Session expired. Please login again.'}), 401

        if not hmac.compare_digest(generate_address(mnemonic), sender):
            return jsonify({'error': 'Authentication failed'}), 403

        my_pubkey = get_public_key_b64(mnemonic)

        # ── Групповая отправка ──────────────────────────────────────────────
        if msg_type == 'group' and group_id:
            groups = get_user_groups_cached(sender, cache_version=get_groups_cache_version())
            group  = next((g for g in groups if g['id'] == group_id), None)
            if not group or sender not in group['members']:
                return jsonify({'error': 'Group not found or no access'}), 404

            encrypted_map = {}
            for member in group['members']:
                try:
                    member_pubkey, _ = get_cached_public_key(
                        member, cache_version=get_pubkey_cache_version())
                    if not member_pubkey:
                        member_pubkey, _ = fetch_public_key_from_chain(member)
                    if not member_pubkey:
                        continue
                    key = compute_shared_key_b64(mnemonic, member_pubkey, member)
                    aad = sender.encode('utf-8')
                    encrypted_map[member] = {
                        'content': encrypt_message_aead(key, content, associated_data=aad),
                        'image':   encrypt_message_aead(key, image, associated_data=aad) if image else None,
                        'sender':  sender,
                    }
                except Exception as e:
                    logger.warning(f"⚠️ Encrypt for {member[:10]}... failed: {type(e).__name__}")

            if not encrypted_map:
                return jsonify({'error': 'Encryption failed for all members'}), 500

            from database import get_db_cursor
            with get_db_cursor(_blockchain.db_path) as cursor:
                tx_id      = _blockchain.new_transaction(
                    cursor, sender, f"group:{group_id}",
                    json.dumps(encrypted_map), None,
                    sender_pubkey=my_pubkey,
                    metadata={'encryption': 'group-ecdh-v4', 'group_id': group_id},
                )
                last_proof = _blockchain._last_block_raw(cursor)['proof']
                threading.Thread(
                    target=mine_block_async,
                    args=(_blockchain.db_path, last_proof), daemon=True).start()

            for member in group['members']:
                _socketio.emit('new_message',
                               {'chat_id': f"group:{group_id}", 'tx_id': tx_id},
                               room=member)
                _lottery.add_ticket(sender)

            return jsonify({
                'message': 'Sent', 'tx_id': tx_id,
                'recipient': f"group:{group_id}", 'type': 'group',
                'encryption': 'group-ecdh-v4',
                'members_encrypted': len(encrypted_map),
            }), 201

        # ── P2P отправка ────────────────────────────────────────────────────
        if sender == recipient:
            return jsonify({'error': 'Cannot message yourself'}), 400

        recipient_pubkey, recipient_verified = get_cached_public_key(
            recipient, cache_version=get_pubkey_cache_version())
        if not recipient_pubkey:
            recipient_pubkey, recipient_verified = fetch_public_key_from_chain(recipient)

        from database import get_db_cursor

        if recipient_pubkey:
            payload = encrypt_hybrid(mnemonic, recipient_pubkey, recipient,
                                     content, image_data=image)
            with get_db_cursor(_blockchain.db_path) as cursor:
                tx_id      = _blockchain.new_transaction(
                    cursor, sender, recipient, json.dumps(payload), None,
                    sender_pubkey=my_pubkey,
                    metadata={'encryption': 'hybrid-v2',
                              'key_verified': recipient_verified},
                )
                last_proof = _blockchain._last_block_raw(cursor)['proof']
                threading.Thread(
                    target=mine_block_async,
                    args=(_blockchain.db_path, last_proof), daemon=True).start()
            _notify_new_message(recipient, tx_id, sender=sender)
            _lottery.add_ticket(sender)
            return jsonify({
                'message': 'Sent', 'tx_id': tx_id, 'recipient': recipient,
                'type': 'direct', 'encryption': 'hybrid-v2',
                'key_verified': recipient_verified,
            }), 201

        # Key-exchange fallback
        key_exchange_payload = {
            'my_pubkey':      my_pubkey,
            'message':        'key_exchange_request',
            'version':        'key_exchange',
            'sender_address': sender,
            'timestamp':      time.time(),
        }
        with get_db_cursor(_blockchain.db_path) as cursor:
            tx_id      = _blockchain.new_transaction(
                cursor, sender, recipient,
                json.dumps(key_exchange_payload), None,
                sender_pubkey=my_pubkey,
                metadata={'encryption': 'key_exchange'},
            )
            last_proof = _blockchain._last_block_raw(cursor)['proof']
            threading.Thread(
                target=mine_block_async,
                args=(_blockchain.db_path, last_proof), daemon=True).start()
        cache_public_key(sender, my_pubkey, source='outgoing', verified=True)
        _notify_new_message(recipient, tx_id, sender=sender)
        _lottery.add_ticket(sender)
        return jsonify({
            'message': 'Key exchange sent.', 'tx_id': tx_id, 'recipient': recipient,
            'key_exchange': True, 'my_pubkey': my_pubkey,
        }), 201

    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        import os
        logger.error(f"❌ send_message error: {type(e).__name__}",
                     exc_info=os.getenv('FLASK_ENV') != 'production')
        return jsonify({'error': 'Internal server error'}), 500


# =============================================================================
# Получение истории / диалогов
# =============================================================================

@messages_bp.route('/get_conversation', methods=['GET'])
def get_conversation():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        user_addr = session['address']
        mnemonic  = session.get('mnemonic')
        if not mnemonic:
            return jsonify({'error': 'Session expired. Please login again.'}), 401
        if not hmac.compare_digest(generate_address(mnemonic), user_addr):
            return jsonify({'error': 'Authentication failed'}), 403

        chat_with      = request.args.get('with')
        if not chat_with:
            return jsonify({'error': 'Missing "with" parameter'}), 400
        last_message_id = request.args.get('last_message_id', type=int)
        limit           = min(int(request.args.get('limit', 30)), 50)
        before_id       = request.args.get('before_id', type=int)

        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            if chat_with.startswith('group:'):
                group_id   = chat_with.split(':', 1)[1]
                groups     = get_user_groups_cached(user_addr,
                                                    cache_version=get_groups_cache_version())
                user_group = next((g for g in groups if g['id'] == group_id), None)
                if not user_group or user_addr not in user_group['members']:
                    return jsonify({'error': 'No access to this group'}), 403
                query  = ('SELECT id, sender, recipient, content, image, timestamp, '
                          'sender_pubkey, metadata FROM transactions WHERE recipient = ?')
                params = [chat_with]
                if last_message_id:
                    query += ' AND id > ?'; params.append(last_message_id)
                if before_id:
                    query += ' AND id < ?'; params.append(before_id)
                query += ' ORDER BY timestamp ASC LIMIT ?'; params.append(limit)
            else:
                query = '''
                    SELECT id, sender, recipient, content, image, timestamp, sender_pubkey, metadata
                    FROM (
                        SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                        UNION ALL
                        SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                    )
                '''
                params  = [user_addr, chat_with, chat_with, user_addr]
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

        def _row_to_msg(r):
            return {'id': r[0], 'sender': r[1], 'recipient': r[2],
                    'content': r[3], 'image': r[4], 'timestamp': r[5],
                    'sender_pubkey': r[6], 'metadata': r[7]}

        if chat_with.startswith('group:'):
            messages = [_row_to_msg(r) for r in rows]
        else:
            messages = list(reversed([_row_to_msg(r) for r in rows]))

        decrypted = []
        for msg in messages:
            dec = process_message_decryption(msg, user_addr, mnemonic)
            dec['sender_name']    = (get_contact_name_cached(
                user_addr, msg['sender'],
                cache_version=get_contact_cache_version()) or msg['sender'])
            dec['recipient_name'] = (get_contact_name_cached(
                user_addr, msg['recipient'],
                cache_version=get_contact_cache_version()) or msg['recipient'])
            dec['is_mine'] = (msg['sender'] == user_addr)
            if msg.get('metadata'):
                try:
                    meta = (json.loads(msg['metadata'])
                            if isinstance(msg['metadata'], str)
                            else msg['metadata'])
                    if not dec.get('encryption_type'):
                        dec['encryption_type'] = meta.get('encryption', 'unknown')
                    if dec.get('key_verified') is None:
                        dec['key_verified'] = meta.get('key_verified', False)
                except Exception:
                    pass
            decrypted.append(dec)

        return jsonify({
            'messages':        decrypted,
            'has_more':        len(messages) == limit,
            'chat_with':       chat_with,
            'last_message_id': messages[-1]['id'] if messages else None,
        }), 200

    except Exception as e:
        logger.error(f"❌ get_conversation error: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': f'Failed to load messages: {type(e).__name__}'}), 500


@messages_bp.route('/get_conversations', methods=['GET'])
def get_conversations_route():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        return jsonify({'conversations': get_conversations_list(session['address'])}), 200
    except Exception as e:
        logger.error(f"Get conversations error: {e}")
        return jsonify({'error': 'Failed'}), 500


@messages_bp.route('/mark_conversation_read', methods=['POST'])
def mark_conversation_read():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user_addr = session['address']
    data      = request.get_json() or {}
    chat_with = data.get('chat_with', '').strip()
    last_message_id = data.get('last_message_id')
    if not chat_with:
        return jsonify({'error': 'Missing chat_with'}), 400

    try:
        from database import get_db_cursor
        if last_message_id is None:
            with get_db_cursor(_blockchain.db_path) as cursor:
                if chat_with.startswith('group:'):
                    cursor.execute('SELECT MAX(id) FROM transactions WHERE recipient = ?',
                                   (chat_with,))
                else:
                    cursor.execute(
                        'SELECT MAX(id) FROM transactions '
                        'WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)',
                        (user_addr, chat_with, chat_with, user_addr)
                    )
                row             = cursor.fetchone()
                last_message_id = row[0] if row and row[0] else 0

        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute('''
                INSERT INTO read_status (user_address, chat_id, last_read_message_id, read_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_address, chat_id) DO UPDATE
                SET last_read_message_id = excluded.last_read_message_id,
                    read_at = excluded.read_at
                WHERE excluded.last_read_message_id > read_status.last_read_message_id
            ''', (user_addr, chat_with, last_message_id, time.time()))
            updated = cursor.rowcount

        return jsonify({'status': 'ok', 'last_read_message_id': last_message_id,
                        'updated': bool(updated)}), 200
    except Exception as e:
        logger.error(f"Mark read error: {e}")
        return jsonify({'error': 'Failed to update read status'}), 500


@messages_bp.route('/check_new_messages')
def check_new_messages():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user_addr = session['address']
    mnemonic  = session.get('mnemonic')
    try:
        since = request.args.get('since', type=float) or 0
    except ValueError:
        since = 0

    messages = []
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

        for row in rows:
            msg     = {'id': row[0], 'sender': row[1], 'recipient': row[2],
                       'content': row[3], 'image': row[4], 'timestamp': row[5]}
            preview = '💬 Новое сообщение'
            if mnemonic:
                dec = process_message_decryption(msg, user_addr, mnemonic)
                if dec.get('image'):
                    preview = '📷 Изображение'
                elif dec.get('content'):
                    c       = dec['content'] or ''
                    preview = c[:60] + ('…' if len(c) > 60 else '')
            messages.append({
                'id':        msg['id'],
                'sender':    msg['sender'],
                'chatId':    (msg['recipient'] if msg['recipient'].startswith('group:')
                              else msg['sender']),
                'preview':   preview,
                'isGroup':   msg['recipient'].startswith('group:'),
                'timestamp': msg['timestamp'],
            })
    except Exception as e:
        logger.error(f"check_new_messages error: {e}")
        return jsonify({'error': 'Internal error'}), 500

    return jsonify({'messages': messages}), 200


@messages_bp.route('/decrypt_message', methods=['POST'])
def decrypt_message_api():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data              = request.get_json()
        encrypted_payload = data.get('encrypted_payload')
        peer_address      = data.get('peer_address')
        if not encrypted_payload or not peer_address:
            return jsonify({'error': 'Missing fields'}), 400
        user_addr = session['address']
        mnemonic  = session.get('mnemonic')
        if not mnemonic:
            return jsonify({'error': 'Session expired'}), 401

        peer_pubkey, _ = get_cached_public_key(peer_address,
                                                cache_version=get_pubkey_cache_version())
        if not peer_pubkey:
            peer_pubkey, _ = fetch_public_key_from_chain(peer_address)
        if not peer_pubkey:
            return jsonify({'content': '[Waiting for key exchange...]'}), 200

        decrypted = decrypt_hybrid(mnemonic, peer_pubkey, peer_address, encrypted_payload)
        return jsonify({'content': decrypted.get('content'),
                        'image':   decrypted.get('image')}), 200
    except Exception as e:
        logger.error(f"P2P decrypt error: {e}")
        return jsonify({'content': '[Decryption failed]'}), 200


@messages_bp.route('/p2p-poll')
def p2p_poll():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    chat_id   = request.args.get('chat', '')
    since     = float(request.args.get('since', 0))
    user_addr = session['address']
    if not chat_id:
        return jsonify([]), 400

    with _p2p_buffer_lock:
        msgs     = _p2p_buffer.get(chat_id, [])
        new_msgs = [m for m in msgs
                    if m['ts'] > since and m['recipient'] in (user_addr, chat_id)]
        cutoff   = time.time() - 300
        for addr in list(_p2p_buffer.keys()):
            _p2p_buffer[addr] = [m for m in _p2p_buffer[addr] if m['ts'] > cutoff]
            if not _p2p_buffer[addr]:
                del _p2p_buffer[addr]
    return jsonify(new_msgs), 200


@messages_bp.route('/get_public_key/<string:address>')
def get_public_key_route(address: str):
    pubkey, verified = get_cached_public_key(address,
                                              cache_version=get_pubkey_cache_version())
    if not pubkey:
        pubkey, verified = fetch_public_key_from_chain(address)
    if pubkey:
        return jsonify({'address': address, 'public_key': pubkey, 'verified': verified}), 200
    return jsonify({'error': 'Public key not found'}), 404
