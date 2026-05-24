"""
routes/status.py — Статусы пользователей (онлайн/оффлайн)
"""
import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from database import get_db_cursor
from dependencies import require_auth
from models import HeartbeatRequest, ManyStatusesRequest
from config import ONLINE_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)
router = APIRouter(tags=['status'])

ONLINE_TIMEOUT = ONLINE_TIMEOUT_SECONDS


@router.post('/heartbeat')
def heartbeat(body: HeartbeatRequest, address: str = Depends(require_auth)):
    try:
        with get_db_cursor() as cursor:
            cursor.execute('''
                INSERT INTO user_status (address, last_seen, status, current_chat)
                VALUES (?, ?, 'online', ?)
                ON CONFLICT(address) DO UPDATE SET
                    last_seen    = excluded.last_seen,
                    status       = 'online',
                    current_chat = excluded.current_chat
            ''', (address, time.time(), body.current_chat))
        return {'status': 'ok'}
    except Exception as e:
        logger.error(f"Heartbeat error: {e}")
        raise HTTPException(500, 'Internal error')


@router.get('/get_status/{address_param}')
def get_status(address_param: str):
    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                'SELECT last_seen, status, current_chat FROM user_status WHERE address = ?',
                (address_param,)
            )
            row = cursor.fetchone()

        if not row:
            return {'address': address_param, 'status': 'offline', 'last_seen': None}

        last_seen = row[0]
        is_online = (time.time() - last_seen) < ONLINE_TIMEOUT
        return {
            'address':      address_param,
            'status':       'online' if is_online else 'offline',
            'last_seen':    last_seen,
            'current_chat': row[2] if is_online else None,
        }
    except Exception as e:
        logger.error(f"Get status error: {e}")
        raise HTTPException(500, 'Internal error')


@router.post('/get_many_statuses')
def get_many_statuses(body: ManyStatusesRequest, address: str = Depends(require_auth)):
    if not body.addresses:
        return {'statuses': {}}

    try:
        placeholders = ','.join('?' * len(body.addresses))
        with get_db_cursor() as cursor:
            cursor.execute(f'''
                SELECT address, last_seen, status, current_chat
                FROM user_status
                WHERE address IN ({placeholders})
            ''', body.addresses)
            rows = cursor.fetchall()

        now    = time.time()
        result = {}
        for row in rows:
            is_online    = (now - row[1]) < 60
            result[row[0]] = {
                'status':       'online' if is_online else 'offline',
                'last_seen':    row[1],
                'current_chat': row[2] if is_online else None,
            }
        for addr in body.addresses:
            if addr not in result:
                result[addr] = {'status': 'offline', 'last_seen': None, 'current_chat': None}

        return {'statuses': result}
    except Exception as e:
        logger.error(f"Get many statuses error: {e}")
        raise HTTPException(500, 'Internal error')