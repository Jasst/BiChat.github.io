"""routes/status_async.py — Статусы пользователей онлайн/оффлайн (асинхронная версия)"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from quart import Blueprint, jsonify, request

from database_async import db
from redis_manager import redis_manager
from config_async import ONLINE_TIMEOUT

logger = logging.getLogger(__name__)
status_bp = Blueprint('status', __name__)

# Адреса, которым разрешены административные операции.
# В продакшне замените на чтение из БД / переменных окружения.
import os
_ADMIN_ADDRESS = os.getenv('ADMIN_ADDRESS', '')


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

async def _update_user_status_db(address: str, current_chat: str = "") -> None:
    """Обновляет статус пользователя в PostgreSQL"""
    await db.execute("""
        INSERT INTO user_status (address, last_seen, status, current_chat)
        VALUES ($1, NOW(), 'online', $2)
        ON CONFLICT (address) DO UPDATE SET
            last_seen = NOW(),
            status = 'online',
            current_chat = $2
    """, address, current_chat)


async def _get_user_status_db(address: str) -> Optional[Dict]:
    """Получает статус пользователя из PostgreSQL"""
    return await db.fetch_one("""
        SELECT last_seen, status, current_chat FROM user_status WHERE address = $1
    """, address)


async def _is_online_from_db(last_seen) -> bool:
    """Проверяет, онлайн ли пользователь по времени из БД"""
    if not last_seen:
        return False
    time_diff = (datetime.now() - last_seen).total_seconds()
    return time_diff < ONLINE_TIMEOUT


def _is_admin(address: str) -> bool:
    """
    Простая проверка прав администратора.

    FIX: в оригинале делался запрос к несуществующей колонке wallets.is_admin,
    что роняло оба endpoint с ошибкой 500.
    Теперь используем переменную среды ADMIN_ADDRESS.
    Если нужна БД — добавьте колонку is_admin BOOLEAN DEFAULT FALSE в wallets.
    """
    return bool(_ADMIN_ADDRESS) and address == _ADMIN_ADDRESS


# =============================================================================
# HEARTBEAT ENDPOINTS
# =============================================================================

@status_bp.route('/heartbeat', methods=['POST'])
async def heartbeat():
    """Heartbeat endpoint — клиент сообщает, что он онлайн."""
    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json() or {}
    current_chat = data.get('current_chat', '')

    await redis_manager.set_user_status(address, 'online', current_chat)
    await _update_user_status_db(address, current_chat)

    logger.debug(
        f"💓 Heartbeat from {address[:16]}..., "
        f"chat: {current_chat[:20] if current_chat else 'none'}"
    )

    return jsonify({'status': 'ok'}), 200


@status_bp.route('/heartbeat/many', methods=['POST'])
async def heartbeat_many():
    """Массовый heartbeat (несколько пользователей за раз)"""
    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json() or {}
    statuses = data.get('statuses', {})

    for addr, status_data in statuses.items():
        current_chat = status_data.get('current_chat', '')
        await redis_manager.set_user_status(addr, 'online', current_chat)
        await _update_user_status_db(addr, current_chat)

    logger.debug(f"💓 Mass heartbeat: {len(statuses)} users updated")

    return jsonify({'status': 'ok', 'updated': len(statuses)}), 200


# =============================================================================
# GET STATUS ENDPOINTS
# =============================================================================

@status_bp.route('/get_status/<string:address>', methods=['GET'])
async def get_status(address: str):
    """Получить статус конкретного пользователя."""
    if len(address) != 64 or not all(c in '0123456789abcdef' for c in address):
        return jsonify({'error': 'Invalid address format'}), 400

    redis_status = await redis_manager.get_user_status(address)

    if redis_status and redis_status.get('status') == 'online':
        return jsonify({
            'address': address,
            'status': 'online',
            'last_seen': redis_status.get('last_seen'),
            'current_chat': redis_status.get('current_chat'),
        }), 200

    row = await _get_user_status_db(address)

    if not row:
        return jsonify({
            'address': address,
            'status': 'offline',
            'last_seen': None,
            'current_chat': None,
        }), 200

    is_online = await _is_online_from_db(row['last_seen'])

    return jsonify({
        'address': address,
        'status': 'online' if is_online else 'offline',
        'last_seen': row['last_seen'].isoformat() if row['last_seen'] else None,
        'current_chat': row['current_chat'] if is_online else None,
    }), 200


@status_bp.route('/get_many_statuses', methods=['POST'])
async def get_many_statuses():
    """Получить статусы нескольких пользователей за один запрос."""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json() or {}
    addresses = data.get('addresses', [])[:100]

    if not addresses:
        return jsonify({'statuses': {}}), 200

    result = {}

    # 1. Из Redis
    for addr in addresses:
        redis_status = await redis_manager.get_user_status(addr)
        if redis_status and redis_status.get('status') == 'online':
            result[addr] = {
                'status': 'online',
                'last_seen': redis_status.get('last_seen'),
                'current_chat': redis_status.get('current_chat'),
            }

    # 2. Оставшиеся — из БД
    remaining = [a for a in addresses if a not in result]
    if remaining:
        placeholders = ','.join(f'${i + 1}' for i in range(len(remaining)))
        rows = await db.fetch_all(f"""
            SELECT address, last_seen, status, current_chat
            FROM user_status
            WHERE address IN ({placeholders})
        """, *remaining)

        now = datetime.now()
        for row in rows:
            time_diff = (
                (now - row['last_seen']).total_seconds()
                if row['last_seen'] else ONLINE_TIMEOUT + 1
            )
            is_online = time_diff < ONLINE_TIMEOUT
            result[row['address']] = {
                'status': 'online' if is_online else 'offline',
                'last_seen': row['last_seen'].isoformat() if row['last_seen'] else None,
                'current_chat': row['current_chat'] if is_online else None,
            }

    # 3. Те, кого нет совсем
    for addr in addresses:
        if addr not in result:
            result[addr] = {'status': 'offline', 'last_seen': None, 'current_chat': None}

    return jsonify({'statuses': result}), 200


# =============================================================================
# ONLINE USERS LIST
# =============================================================================

@status_bp.route('/get_online_users', methods=['GET'])
async def get_online_users():
    """Получить список онлайн пользователей (из Redis)."""
    keys = await redis_manager.client.keys("status:*")

    online_users = []
    for key in keys:
        address = key.replace("status:", "")
        status_data = await redis_manager.get_user_status(address)
        if status_data and status_data.get('status') == 'online':
            online_users.append({
                'address': address,
                'current_chat': status_data.get('current_chat'),
                'last_seen': status_data.get('last_seen'),
            })

    return jsonify({'online_count': len(online_users), 'users': online_users}), 200


# =============================================================================
# OFFLINE USERS CLEANUP (admin)
# =============================================================================

@status_bp.route('/cleanup_offline', methods=['POST'])
async def cleanup_offline():
    """Очистить старые записи оффлайн пользователей (только администратор)."""
    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'error': 'Unauthorized'}), 401

    # FIX: убрана ссылка на несуществующую колонку wallets.is_admin
    if not _is_admin(address):
        return jsonify({'error': 'Admin access required'}), 403

    cutoff = datetime.now() - timedelta(seconds=ONLINE_TIMEOUT * 2)

    result = await db.execute("""
        DELETE FROM user_status
        WHERE last_seen < $1 AND status = 'offline'
    """, cutoff)

    deleted = int(result.split()[-1]) if result else 0
    logger.info(f"🧹 Cleaned up {deleted} offline user records")

    return jsonify({'message': f'Cleaned up {deleted} offline records', 'deleted': deleted}), 200


# =============================================================================
# STATUS STATISTICS (admin)
# =============================================================================

@status_bp.route('/status/stats', methods=['GET'])
async def status_stats():
    """Статистика по статусам пользователей (только администратор)."""
    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'error': 'Unauthorized'}), 401

    # FIX: убрана ссылка на несуществующую колонку wallets.is_admin
    if not _is_admin(address):
        return jsonify({'error': 'Admin access required'}), 403

    redis_keys = await redis_manager.client.keys("status:*")
    redis_online = 0
    for key in redis_keys:
        status = await redis_manager.client.hget(key, 'status')
        if status == 'online':
            redis_online += 1

    total_users = await db.fetch_val("SELECT COUNT(*) FROM wallets") or 0
    online_users = await db.fetch_val("""
        SELECT COUNT(*) FROM user_status
        WHERE EXTRACT(EPOCH FROM (NOW() - last_seen)) < $1
    """, ONLINE_TIMEOUT) or 0

    return jsonify({
        'redis': {
            'online': redis_online,
            'total_keys': len(redis_keys),
        },
        'database': {
            'online': online_users,
            'offline': total_users - online_users,
            'total': total_users,
        },
        'online_timeout_seconds': ONLINE_TIMEOUT,
    }), 200