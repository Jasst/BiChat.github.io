import asyncio
import json
import logging
from pywebpush import webpush, WebPushException
from config import VAPID_PRIVATE_KEY, VAPID_SUBJECT
from database import get_db_cursor

logger = logging.getLogger(__name__)

def _send_push_sync(sub: dict, payload: str, vapid_private_key: str, vapid_claims: dict) -> None:
    webpush(
        subscription_info=sub,
        data=payload,
        vapid_private_key=vapid_private_key,
        vapid_claims=vapid_claims
    )

async def send_push(user_address: str, title: str, body: str, url: str = '/chat'):
    async with get_db_cursor() as conn:
        rows = await conn.fetch(
            "SELECT id, subscription FROM push_subscriptions WHERE user_address = $1",
            user_address
        )
    if not rows:
        return

    safe_title = title if title else "New message"
    safe_body = "🔒 You have a new encrypted message. Tap to open."
    payload = json.dumps({'title': safe_title, 'body': safe_body, 'url': url})
    vapid_claims = {"sub": VAPID_SUBJECT}

    for row in rows:
        sub_id = row['id']
        try:
            sub = json.loads(row['subscription'])
            endpoint_preview = sub.get('endpoint', '')[:60]
            await asyncio.to_thread(
                _send_push_sync,
                sub, payload,
                VAPID_PRIVATE_KEY,
                vapid_claims
            )
            logger.debug(f"Push sent to {user_address[:16]} → {endpoint_preview}...")
        except WebPushException as e:
            status_code = getattr(e.response, 'status_code', None) if e.response else None
            logger.error(f"Push failed [{status_code}] for {user_address[:16]}: {e}")
            if status_code in (404, 410):
                logger.info(f"Removing dead subscription id={sub_id} for {user_address[:16]}")
                async with get_db_cursor() as conn:
                    await conn.execute("DELETE FROM push_subscriptions WHERE id = $1", sub_id)
        except Exception as e:
            logger.error(f"Unexpected push error for {user_address[:16]}: {e}")