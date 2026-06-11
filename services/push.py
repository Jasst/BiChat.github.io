# services/push.py

import asyncio
import json
import logging
import time
from urllib.parse import urlparse

from pywebpush import webpush, WebPushException

from config import VAPID_PRIVATE_KEY, VAPID_SUBJECT
from database import get_db_cursor

logger = logging.getLogger(__name__)


def _send_push_sync(sub: dict, payload: str, vapid_private_key: str, vapid_claims: dict) -> None:
    """
    Синхронная отправка push-уведомления через pywebpush.
    Явно задаёт aud и exp в JWT.
    """
    endpoint = sub['endpoint']
    # Определяем audience как origin endpoint'а (без пути)
    parsed = urlparse(endpoint)
    aud = f"{parsed.scheme}://{parsed.netloc}"

    claims = {
        "sub": vapid_claims.get("sub"),
        "aud": aud,
        "exp": int(time.time()) + 86400,  # 24 часа
    }

    logger.debug(f"Sending push to {endpoint[:50]}... claims={claims}")

    webpush(
        subscription_info=sub,
        data=payload,
        vapid_private_key=vapid_private_key,
        vapid_claims=claims,
        timeout=3  # таймаут на отправку
    )


async def _send_single_push(
    sub_id: int,
    sub: dict,
    payload: str,
    user_address: str
):
    try:
        await asyncio.to_thread(
            _send_push_sync,
            sub,
            payload,
            VAPID_PRIVATE_KEY,
            {"sub": VAPID_SUBJECT}
        )

        logger.debug(
            f"Push sent → {user_address[:16]} "
            f"{sub.get('endpoint','')[:50]}"
        )

    except WebPushException as e:
        status_code = (
            getattr(e.response, "status_code", None)
            if e.response else None
        )

        logger.warning(
            f"Push failed [{status_code}] "
            f"for {user_address[:16]}"
        )

        if status_code in (403, 404, 410):
            async with get_db_cursor() as conn:
                await conn.execute(
                    "DELETE FROM push_subscriptions WHERE id = $1",
                    sub_id
                )

    except Exception as e:
        logger.exception(
            f"Push error for {user_address[:16]}: {e}"
        )

async def send_push(
    user_address: str,
    title: str,
    body: str,
    url: str = "/chat"
):

    if not VAPID_PRIVATE_KEY:
        return

    async with get_db_cursor() as conn:
        rows = await conn.fetch(
            """
            SELECT id, subscription
            FROM push_subscriptions
            WHERE user_address = $1
            """,
            user_address
        )

    if not rows:
        return

    payload = json.dumps({
        "title": title or "New message",
        "body": body or "New message",
        "url": url
    })

    tasks = []

    for row in rows:
        try:
            sub = json.loads(row["subscription"])

            tasks.append(
                _send_single_push(
                    row["id"],
                    sub,
                    payload,
                    user_address
                )
            )

        except Exception:
            logger.exception("Invalid subscription")

    if tasks:
        await asyncio.gather(
            *tasks,
            return_exceptions=True
        )