"""
routes/ws.py — WebSocket менеджер для реального времени
(включая сигнализацию для WebRTC голосовых/видео звонков)
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

# ДОБАВЛЕНО: импорт функции отправки push
from services.push import send_push

logger = logging.getLogger(__name__)
router = APIRouter(tags=['websocket'])


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()
        self.calls: Dict[str, Dict] = {}  # call_id -> информация о звонке
        asyncio.create_task(self._cleanup_old_calls())

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

    async def broadcast(self, message: dict, exclude: str = None):
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

    async def _cleanup_old_calls(self):
        while True:
            await asyncio.sleep(30)  # каждые 30 секунд
            now = time.time()
            expired = []
            async with self._lock:
                for call_id, info in self.calls.items():
                    if now - info.get('created_at', 0) > 60:  # 60 секунд таймаут
                        expired.append(call_id)
                for call_id in expired:
                    del self.calls[call_id]
                    logger.info(f"Removed expired call {call_id}")

    async def broadcast_status_update(self, address: str, status: str):
        await self.broadcast({
            'type': 'status_update',
            'address': address,
            'status': status
        })


manager = ConnectionManager()


async def authenticate_websocket(websocket: WebSocket, address: str, signature: str, nonce: str) -> Optional[str]:
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

            # ---------- Обработка звонков (WebRTC) ----------
            elif msg_type == 'call_offer':
                target = data.get('target')
                call_id = data.get('call_id')
                sdp = data.get('sdp')
                from_name = data.get('from_name') or user_id[:10]
                if target and call_id:
                    async with manager._lock:
                        manager.calls[call_id] = {
                            'from': user_id,
                            'to': target,
                            'state': 'offer_sent',
                            'created_at': time.time(),
                            'offer_sdp': sdp,
                            'from_name': from_name
                        }
                    # 1. Пытаемся отправить через WebSocket (если пользователь онлайн)
                    await manager.send_personal_message(target, {
                        'type': 'incoming_call',
                        'call_id': call_id,
                        'from': user_id,
                        'sdp': sdp,
                        'from_name': from_name
                    })
                    # 2. Отправляем push-уведомление
                    await send_push(
                        user_address=target,
                        title="Входящий звонок",
                        body=f"{from_name} звонит вам",
                        push_type="incoming_call",
                        call_id=call_id,
                        from_name=from_name
                    )
                    logger.info(f"Call offer {call_id}: push sent to {target[:16]} from {user_id[:16]}")

            elif msg_type == 'get_call':
                call_id = data.get('call_id')
                async with manager._lock:
                    call_info = manager.calls.get(call_id)
                if call_info and call_info.get('offer_sdp'):
                    await websocket.send_json({
                        'type': 'incoming_call',
                        'call_id': call_id,
                        'from': call_info['from'],
                        'sdp': call_info['offer_sdp'],
                        'from_name': call_info.get('from_name', call_info['from'][:10])
                    })
                else:
                    await websocket.send_json({'type': 'call_not_found', 'call_id': call_id})

            elif msg_type == 'call_answer':
                target = data.get('target')
                call_id = data.get('call_id')
                sdp = data.get('sdp')
                if target and call_id:
                    async with manager._lock:
                        if call_id in manager.calls:
                            manager.calls[call_id]['state'] = 'answered'
                    await manager.send_personal_message(target, {
                        'type': 'call_answer',
                        'call_id': call_id,
                        'from': user_id,
                        'sdp': sdp
                    })
                    logger.debug(f"Call answer {call_id} from {user_id[:8]} to {target[:8]}")

            elif msg_type == 'call_ice':
                target = data.get('target')
                call_id = data.get('call_id')
                candidate = data.get('candidate')
                if target and call_id and candidate:
                    await manager.send_personal_message(target, {
                        'type': 'call_ice',
                        'call_id': call_id,
                        'from': user_id,
                        'candidate': candidate
                    })

            elif msg_type == 'call_hangup':
                target = data.get('target')
                call_id = data.get('call_id')
                async with manager._lock:
                    manager.calls.pop(call_id, None)
                if target:
                    await manager.send_personal_message(target, {
                        'type': 'call_hangup',
                        'call_id': call_id,
                        'from': user_id
                    })
                    logger.debug(f"Call hangup {call_id} from {user_id[:8]} to {target[:8]}")

            elif msg_type == 'call_reject':
                target = data.get('target')
                call_id = data.get('call_id')
                async with manager._lock:
                    manager.calls.pop(call_id, None)
                if target:
                    await manager.send_personal_message(target, {
                        'type': 'call_reject',
                        'call_id': call_id,
                        'from': user_id
                    })
                    logger.debug(f"Call reject {call_id} from {user_id[:8]} to {target[:8]}")

    except WebSocketDisconnect:
        await manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(user_id)