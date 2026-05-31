"""
routes/ws.py — WebSocket менеджер для реального времени
"""
import asyncio
import logging
import time
from typing import Dict, Optional
from fastapi import WebSocket, WebSocketDisconnect, APIRouter, Query

from database import get_db_cursor
from services.notifier import message_notifier
from setup import load_public_key_from_b64
from cache import get_cached_public_key
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

logger = logging.getLogger(__name__)
router = APIRouter(tags=['websocket'])


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections[user_id] = websocket
        logger.info(f"User {user_id[:16]} connected via WebSocket")

    async def disconnect(self, user_id: str):
        async with self._lock:
            self.active_connections.pop(user_id, None)
        await self.broadcast_status_update(user_id, 'offline')
        logger.info(f"User {user_id[:16]} disconnected")

    async def send_personal_message(self, user_id: str, message: dict) -> bool:
        async with self._lock:
            ws = self.active_connections.get(user_id)
        if ws:
            try:
                await ws.send_json(message)
                return True
            except Exception as e:
                logger.error(f"Failed to send to {user_id}: {e}")
                await self.disconnect(user_id)
        return False

    # ✅ НОВЫЙ МЕТОД: рассылка всем подключённым клиентам
    async def broadcast(self, message: dict, exclude: str = None):
        """Отправить сообщение всем подключённым клиентам, кроме exclude (опционально)."""
        async with self._lock:
            for user_id, ws in self.active_connections.items():
                if user_id == exclude:
                    continue
                try:
                    await ws.send_json(message)
                except Exception as e:
                    logger.error(f"Broadcast to {user_id} failed: {e}")

    async def get_stats(self):
        async with self._lock:
            return {
                'active_connections': len(self.active_connections),
                'users': list(self.active_connections.keys())[:10]
            }
    async def broadcast_status_update(self, address: str, status: str):
        """Отправить всем клиентам обновление статуса пользователя."""
        await self.broadcast({
            'type': 'status_update',
            'address': address,
            'status': status
        })

manager = ConnectionManager()


async def authenticate_websocket(websocket: WebSocket, address: str, signature: str, nonce: str) -> Optional[str]:
    """Проверяет подпись и возвращает address или None (разрешены даже неверифицированные ключи)."""
    pubkey, verified = await get_cached_public_key(address)
    if not pubkey:
        return None
    if not verified:
        logger.warning(f"WebSocket auth for {address[:16]}... with unverified pubkey")
    try:
        raw_sig = bytes.fromhex(signature)
        if len(raw_sig) != 64:
            return None
        r = int.from_bytes(raw_sig[:32], 'big')
        s = int.from_bytes(raw_sig[32:], 'big')
        der_sig = encode_dss_signature(r, s)
        pubkey_obj = load_public_key_from_b64(pubkey)
        pubkey_obj.verify(der_sig, nonce.encode(), ec.ECDSA(hashes.SHA256()))
        return address
    except Exception as e:
        logger.error(f"WebSocket auth failed: {e}")
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    address: str = Query(...),
    signature: str = Query(...),
    nonce: str = Query(...)
):
    user_id = await authenticate_websocket(websocket, address, signature, nonce)
    if not user_id:
        await websocket.close(code=1008, reason="Unauthorized")
        return
    await manager.connect(user_id, websocket)
    try:
        missed = await message_notifier.get_offline_messages(user_id)
        for msg in missed:
            await websocket.send_json(msg)
        while True:
            data = await websocket.receive_json()
            msg_type = data.get('type')
            if msg_type == 'ping':
                await websocket.send_json({'type': 'pong'})
            elif msg_type == 'mark_read':
                message_id = data.get('message_id')
                if message_id:
                    async with get_db_cursor() as conn:
                        await conn.execute("""
                            UPDATE transactions SET status = 'read', read_at = $1
                            WHERE id = $2 AND recipient = $3
                        """, time.time(), message_id, user_id)
    except WebSocketDisconnect:
        await manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(user_id)