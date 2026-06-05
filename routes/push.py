# routes/push.py
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from dependencies import require_auth
from database import get_db_cursor

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/push', tags=['push'])

@router.post('/subscribe')
async def subscribe(request: Request, address: str = Depends(require_auth)):
    try:
        sub = await request.json()
        async with get_db_cursor() as conn:
            await conn.execute("""
                INSERT INTO push_subscriptions (user_address, subscription, created_at)
                VALUES ($1, $2, extract(epoch from now()))
                ON CONFLICT (user_address, subscription) DO NOTHING
            """, address, json.dumps(sub))
        return {'status': 'ok'}
    except Exception as e:
        logger.error(f"Subscribe error: {e}")
        raise HTTPException(500, 'Failed')

@router.post('/unsubscribe')
async def unsubscribe(request: Request, address: str = Depends(require_auth)):
    try:
        sub = await request.json()
        async with get_db_cursor() as conn:
            await conn.execute("""
                DELETE FROM push_subscriptions
                WHERE user_address = $1 AND subscription = $2
            """, address, json.dumps(sub))
        return {'status': 'ok'}
    except Exception as e:
        logger.error(f"Unsubscribe error: {e}")
        raise HTTPException(500, 'Failed')