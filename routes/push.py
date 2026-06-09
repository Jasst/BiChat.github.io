# routes/push.py
# ИСПРАВЛЕНИЯ:
# 1. Добавлен столбец id SERIAL PRIMARY KEY — нужен для удаления конкретной подписки
# 2. ON CONFLICT по хешу endpoint, а не по полному JSON — iOS меняет токены внутри,
#    но endpoint остаётся тем же; это позволяет обновлять протухшие ключи
# 3. /push/subscribe теперь делает UPSERT по endpoint — обновляет subscription если она изменилась
# 4. Добавлен GET /push/vapid-public-key — фронт может получить ключ динамически

import json
import logging
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Request
from dependencies import require_auth
from database import get_db_cursor
from config import VAPID_PUBLIC_KEY

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/push', tags=['push'])


def _endpoint_hash(subscription: dict) -> str:
    """Берём хеш endpoint — стабильный идентификатор подписки."""
    endpoint = subscription.get('endpoint', '')
    return hashlib.sha256(endpoint.encode()).hexdigest()


@router.get('/vapid-public-key')
async def get_vapid_public_key():
    """Фронт может получить VAPID public key динамически."""
    return {'publicKey': VAPID_PUBLIC_KEY}


@router.post('/subscribe')
async def subscribe(request: Request, address: str = Depends(require_auth)):
    try:
        sub = await request.json()
        if not sub.get('endpoint'):
            raise HTTPException(400, 'Missing endpoint')

        endpoint_hash = _endpoint_hash(sub)
        sub_json = json.dumps(sub)

        async with get_db_cursor() as conn:
            # ИСПРАВЛЕНИЕ 2: UPSERT по endpoint_hash
            # Если iOS пересоздала subscription (новые ключи, тот же endpoint) — обновляем
            # Если совсем новая подписка — вставляем
            await conn.execute("""
                INSERT INTO push_subscriptions (user_address, subscription, endpoint_hash, created_at)
                VALUES ($1, $2, $3, extract(epoch from now()))
                ON CONFLICT (user_address, endpoint_hash)
                DO UPDATE SET
                    subscription = EXCLUDED.subscription,
                    created_at = extract(epoch from now())
            """, address, sub_json, endpoint_hash)

        logger.info(f"Push subscription saved for {address[:16]}")
        return {'status': 'ok'}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Subscribe error: {e}")
        raise HTTPException(500, 'Failed to save subscription')


@router.post('/unsubscribe')
async def unsubscribe(request: Request, address: str = Depends(require_auth)):
    try:
        sub = await request.json()
        endpoint_hash = _endpoint_hash(sub)

        async with get_db_cursor() as conn:
            await conn.execute("""
                DELETE FROM push_subscriptions
                WHERE user_address = $1 AND endpoint_hash = $2
            """, address, endpoint_hash)

        return {'status': 'ok'}

    except Exception as e:
        logger.error(f"Unsubscribe error: {e}")
        raise HTTPException(500, 'Failed')