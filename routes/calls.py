"""
routes/calls.py — WebRTC TURN credentials и состояние звонков
"""
import base64
import hashlib
import hmac
import time
import logging
from fastapi import APIRouter, Depends, HTTPException
from dependencies import require_auth
from config import (
    TURN_ENABLED, TURN_SERVER, STUN_SERVER,
    TURN_STATIC_AUTH_SECRET, TURN_USERNAME, TURN_PASSWORD,
    TURN_REALM, TURN_CREDENTIAL_TTL
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/calls', tags=['calls'])


def generate_turn_credentials(username: str):
    """Генерирует временные TURN credentials по алгоритму static-auth-secret."""
    if not TURN_STATIC_AUTH_SECRET:
        # Fallback на статические, если секрет не задан
        return {
            "username": TURN_USERNAME,
            "credential": TURN_PASSWORD,
            "ttl": 0
        }
    timestamp = int(time.time()) + TURN_CREDENTIAL_TTL
    turn_username = f"{timestamp}:{username}"
    secret_bytes = TURN_STATIC_AUTH_SECRET.encode('utf-8')
    hm = hmac.new(secret_bytes, turn_username.encode('utf-8'), hashlib.sha1)
    credential = base64.b64encode(hm.digest()).decode()   # ← base64, не hex
    return {
        "username": turn_username,
        "credential": credential,
        "ttl": TURN_CREDENTIAL_TTL
    }


@router.get('/turn-credentials')
async def get_turn_credentials(address: str = Depends(require_auth)):
    if not TURN_ENABLED:
        raise HTTPException(503, "WebRTC calls are disabled")

    # Формируем список ICE-серверов
    ice_servers = []
    if STUN_SERVER:
        ice_servers.append({"urls": STUN_SERVER})

    # TURN с TCP/UDP
    turn_urls = [f"{TURN_SERVER}?transport=udp", f"{TURN_SERVER}?transport=tcp"]
    creds = generate_turn_credentials(address)

    # 👇 ЛОГИРОВАНИЕ (чтобы видеть, что генерируется)
    logger.warning(f"TURN credentials for {address[:8]}...: user={creds['username']}, cred={creds['credential']}")

    ice_servers.append({
        "urls": turn_urls,
        "username": creds["username"],
        "credential": creds["credential"],
        "realm": TURN_REALM,
        "ttl": creds["ttl"]
    })

    return {"iceServers": ice_servers}