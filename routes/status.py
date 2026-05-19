"""
routes/status.py — Статусы пользователей (онлайн/оффлайн)
"""
import time
import logging
from flask import Blueprint, jsonify, request, session
from database import get_db_cursor

logger = logging.getLogger(__name__)
status_bp = Blueprint('status', __name__)

# Онлайн считается, если последний heartbeat был менее N секунд назад
ONLINE_TIMEOUT = 60  # 60 секунд


@status_bp.route('/heartbeat', methods=['POST'])
def heartbeat():
    """Клиент сообщает, что он онлайн"""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    address = session['address']
    data = request.get_json(silent=True) or {}
    current_chat = data.get('current_chat', '')

    try:
        with get_db_cursor() as cursor:
            cursor.execute('''
                INSERT INTO user_status (address, last_seen, status, current_chat)
                VALUES (?, ?, 'online', ?)
                ON CONFLICT(address) DO UPDATE SET
                    last_seen = excluded.last_seen,
                    status = 'online',
                    current_chat = excluded.current_chat
            ''', (address, time.time(), current_chat))
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logger.error(f"Heartbeat error: {e}")
        return jsonify({'error': 'Internal error'}), 500


@status_bp.route('/get_status/<string:address>', methods=['GET'])
def get_status(address):
    """Получить статус конкретного пользователя"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                'SELECT last_seen, status, current_chat FROM user_status WHERE address = ?',
                (address,)
            )
            row = cursor.fetchone()

        if not row:
            return jsonify({'address': address, 'status': 'offline', 'last_seen': None}), 200

        last_seen = row[0]
        is_online = (time.time() - last_seen) < ONLINE_TIMEOUT
        status = 'online' if is_online else 'offline'

        return jsonify({
            'address': address,
            'status': status,
            'last_seen': last_seen,
            'current_chat': row[2] if is_online else None
        }), 200
    except Exception as e:
        logger.error(f"Get status error: {e}")
        return jsonify({'error': 'Internal error'}), 500


@status_bp.route('/get_many_statuses', methods=['POST'])
def get_many_statuses():
    """Получить статусы нескольких пользователей"""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    addresses = data.get('addresses', [])

    if not addresses:
        return jsonify({'statuses': {}}), 200

    try:
        placeholders = ','.join('?' * len(addresses))
        with get_db_cursor() as cursor:
            cursor.execute(f'''
                SELECT address, last_seen, status, current_chat 
                FROM user_status 
                WHERE address IN ({placeholders})
            ''', addresses)
            rows = cursor.fetchall()

        now = time.time()
        result = {}
        for row in rows:
            is_online = (now - row[1]) < 60  # 60 секунд
            result[row[0]] = {
                'status': 'online' if is_online else 'offline',
                'last_seen': row[1],
                'current_chat': row[2] if is_online else None
            }

        for addr in addresses:
            if addr not in result:
                result[addr] = {'status': 'offline', 'last_seen': None, 'current_chat': None}

        return jsonify({'statuses': result}), 200
    except Exception as e:
        logger.error(f"Get many statuses error: {e}")
        return jsonify({'error': 'Internal error'}), 500