# services/push.py
import json
import logging
from pywebpush import webpush, WebPushException
from config import VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_SUBJECT
from database import get_db_cursor

logger = logging.getLogger(__name__)

async def send_push(user_address: str, title: str, body: str, url: str = '/'):
    async with get_db_cursor() as conn:
        rows = await conn.fetch(
            "SELECT subscription FROM push_subscriptions WHERE user_address = $1",
            user_address
        )
    if not rows:
        return
    for row in rows:
        sub = json.loads(row['subscription'])
        try:
            webpush(
                subscription_info=sub,
                data=json.dumps({'title': title, 'body': body, 'url': url}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_public_key=VAPID_PUBLIC_KEY,
                vapid_claims={"sub": VAPID_SUBJECT}
            )
        except WebPushException as e:
            logger.error(f"Push failed: {e}")