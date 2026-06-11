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
    endpoint = sub['endpoint']
    parsed = urlparse(endpoint)
    aud = f"{parsed.scheme}://{parsed.netloc}"

    claims = {
        "sub": vapid_claims.get("sub"),
        "aud": aud,
        "exp": int(time.time()) + 86400,
    }

    webpush(
        subscription_info=sub,
        data=payload,
        vapid_private_key=vapid_private_key,
        vapid_claims=claims,
        timeout=5  # увеличил таймаут для надёжности
    )


async def _send_single_push(sub_id: int, sub: dict, payload: str, user_address: str):
    try:
        await asyncio.to_thread(
            _send_push_sync,
            sub,
            payload,
            VAPID_PRIVATE_KEY,
            {"sub": VAPID_SUBJECT}
        )
        logger.debug(f"Push sent → {user_address[:16]} {sub.get('endpoint','')[:50]}")
    except WebPushException as e:
        status_code = getattr(e.response, "status_code", None) if e.response else None
        logger.warning(f"Push failed [{status_code}] for {user_address[:16]}: {e}")

        # 410 Gone, 404 Not Found, 403 Forbidden — подписка больше недействительна
        if status_code in (403, 404, 410):
            async with get_db_cursor() as conn:
                await conn.execute(
                    "DELETE FROM push_subscriptions WHERE id = $1",
                    sub_id
                )
    except Exception as e:
        logger.exception(f"Push error for {user_address[:16]}: {e}")


async def send_push(
    user_address: str,
    title: str,
    body: str,
    url: str = "/chat",
    push_type: str = "message",
    call_id: str | None = None,
    from_name: str | None = None
):
    """
    Универсальная отправка push-уведомления:
    - message (обычное сообщение)
    - incoming_call (входящий звонок)
    """
    if not VAPID_PRIVATE_KEY or not VAPID_SUBJECT:
        logger.warning("Push skipped: VAPID keys not configured")
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

    # Базовый payload
    payload_data = {
        "type": push_type,
        "title": title or ("Incoming call" if push_type == "incoming_call" else "New message"),
        "body": body or "",
        "url": url,
    }

    if push_type == "incoming_call":
        payload_data.update({
            "call_id": call_id,
            "from": user_address,
            "from_name": from_name or user_address[:10],
            "url": f"/chat?call_id={call_id}"   # переопределяем URL для звонка
        })

    payload = json.dumps(payload_data, ensure_ascii=False)

    tasks = []
    for row in rows:
        try:
            sub = json.loads(row["subscription"])
            tasks.append(_send_single_push(row["id"], sub, payload, user_address))
        except Exception:
            logger.exception("Invalid subscription JSON, skipping")

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)