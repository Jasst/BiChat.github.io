"""
routes/messages.py — Отправка/получение сообщений + async Long Polling (асинхронная версия)
"""
import asyncio
import json
import logging
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from cache import (
    get_contact_cache_version, get_contact_name_cached,
    get_groups_cache_version, get_user_groups_cached,
)
from config import MESSAGE_FEE, COIN, COIN_NAME, STAKING_FEE_POOL_ADDRESS, ENABLE_STAKING, CONFIG
from dependencies import require_auth, make_rate_limit_dep
from models import (SendMessageRequest, MarkReadRequest,
                    MessageStatusesRequest, DeleteMessageRequest)
from services.messaging import get_conversations_list_cached, invalidate_conversations_cache
from services.notifier import message_notifier
from services.wallet import staking_manager, mine_block_async_async
from setup import message_limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=['messages'])


def _sanitize_message(msg: dict) -> dict:
    return {
        'id':          msg.get('id'),
        'sender':      msg.get('sender'),
        'sender_name': msg.get('sender_name'),
        'chatId':      msg.get('chatId'),
        'isGroup':     msg.get('isGroup', False),
        'preview':     msg.get('preview', '💬 Новое сообщение'),
        'timestamp':   msg.get('timestamp', time.time()),
        'content':     msg.get('content'),
        'image':       msg.get('image'),
    }


async def _fetch_new_messages_from_db(request: Request, user_addr: str, since_timestamp: float,
                                      limit: int = 50) -> List[dict]:
    blockchain = request.app.state.blockchain
    from database import get_db_cursor
    try:
        async with get_db_cursor(blockchain.db_path) as cursor:
            await cursor.execute('''
                SELECT id, sender, recipient, content, image, timestamp, metadata
                FROM transactions
                WHERE (recipient = ? OR recipient LIKE ?)
                  AND timestamp > ?
                  AND sender != ?
                ORDER BY timestamp ASC
                LIMIT ?
            ''', (user_addr, 'group:%', since_timestamp, user_addr, limit))
            rows = await cursor.fetchall()
        messages = []
        for row in rows:
            is_group = row[2].startswith('group:')
            chat_id = row[2] if is_group else row[1]
            messages.append({
                'id':          row[0],
                'sender':      row[1],
                'sender_name': None,
                'chatId':      chat_id,
                'isGroup':     is_group,
                'preview':     '💬 Новое сообщение',
                'timestamp':   row[5],
                'content':     row[3],
                'image':       row[4],
            })
        return messages
    except Exception as e:
        logger.error(f"_fetch_new_messages_from_db error: {e}")
        return []


@router.get('/wait_for_messages')
async def wait_for_messages(
    request: Request,
    since:   float = Query(default=0.0),
    timeout: int   = Query(default=25),
):
    address = request.session.get('address')
    if not address:
        raise HTTPException(401, 'Unauthorized')
    now = time.time()
    since = max(min(since, now + 60), now - 3600)
    timeout = min(max(timeout, 5), 25)
    messages, waited, triggered = await message_notifier.get_messages(address, since, timeout)
    if messages:
        messages = [_sanitize_message(m) for m in messages[:50]]
        return JSONResponse(
            {'messages': messages, 'has_more': len(messages) >= 50,
             'timestamp': time.time(), 'from_buffer': True, 'waited': waited},
            headers=_no_cache_headers(),
        )
    db_messages = await _fetch_new_messages_from_db(request, address, since)
    if db_messages:
        for msg in db_messages:
            await message_notifier.add_message(address, msg)
        await invalidate_conversations_cache(address)
        out = [_sanitize_message(m) for m in db_messages[:50]]
        return JSONResponse(
            {'messages': out, 'has_more': len(out) >= 50,
             'timestamp': time.time(), 'from_db': True},
            headers=_no_cache_headers(),
        )
    return JSONResponse(
        {'messages': [], 'has_more': False,
         'timestamp': time.time(), 'waited': timeout, 'notified': triggered},
        headers=_no_cache_headers(),
    )


def _no_cache_headers() -> dict:
    return {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma':        'no-cache',
        'Expires':       '0',
    }


@router.post('/send_message', status_code=201,
             dependencies=[Depends(make_rate_limit_dep(message_limiter, limit=30))])
async def send_message(body: SendMessageRequest, request: Request, address: str = Depends(require_auth)):
    blockchain = request.app.state.blockchain
    sender = address
    msg_type = body.message_type
    from database import get_db_cursor
    async with get_db_cursor(blockchain.db_path) as cursor:
        await cursor.execute('BEGIN IMMEDIATE')
        if MESSAGE_FEE > 0:
            await cursor.execute('SELECT balance FROM wallets WHERE address = ?', (sender,))
            row = await cursor.fetchone()
            balance = row[0] if row else 0
            if balance < MESSAGE_FEE:
                await cursor.execute('ROLLBACK')
                raise HTTPException(402, f'Insufficient balance for fee ({MESSAGE_FEE/COIN:.6f} {COIN_NAME})')
            await cursor.execute('UPDATE wallets SET balance = balance - ? WHERE address = ?',
                                 (MESSAGE_FEE, sender))
            await cursor.execute(
                'INSERT INTO wallets (address, balance) VALUES (?, ?) '
                'ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                (STAKING_FEE_POOL_ADDRESS, MESSAGE_FEE, MESSAGE_FEE)
            )
            await cursor.execute(
                'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) '
                'VALUES (?,?,?,?,?,?)',
                ('message_fee', sender, STAKING_FEE_POOL_ADDRESS, MESSAGE_FEE, time.time(), 'message fee')
            )
            if ENABLE_STAKING and staking_manager:
                await staking_manager.add_to_fee_pool(MESSAGE_FEE, cursor=cursor)
        tx_id = None
        group = None
        message_obj = None
        if msg_type == 'group' and body.group_id:
            if not body.encrypted_map:
                await cursor.execute('ROLLBACK')
                raise HTTPException(400, 'Missing encrypted_map')
            groups = await get_user_groups_cached(sender, cache_version=await get_groups_cache_version())
            group = next((g for g in groups if g['id'] == body.group_id), None)
            if not group or sender not in group['members']:
                await cursor.execute('ROLLBACK')
                raise HTTPException(403, 'Access denied')
            tx_id = await blockchain.new_transaction(
                cursor, sender, f"group:{body.group_id}",
                json.dumps({'encrypted_map': body.encrypted_map}), None,
                sender_pubkey=body.sender_pubkey,
                metadata={'encryption': 'group-ecdh-v4', 'group_id': body.group_id}
            )
            message_obj = {
                'id': tx_id, 'sender': sender, 'sender_name': None,
                'chatId': f"group:{body.group_id}", 'isGroup': True,
                'preview': '💬 Новое сообщение в группе',
                'timestamp': time.time(),
                'content': json.dumps({'encrypted_map': body.encrypted_map}),
                'image': None,
            }
            await message_notifier.add_group_messages(body.group_id, group['members'],
                                                      message_obj, exclude_sender=sender)
        else:
            recipient = body.recipient
            if not recipient:
                await cursor.execute('ROLLBACK')
                raise HTTPException(400, 'Missing recipient')
            if sender == recipient:
                await cursor.execute('ROLLBACK')
                raise HTTPException(400, 'Cannot message yourself')
            if not body.payload or not isinstance(body.payload, dict):
                await cursor.execute('ROLLBACK')
                raise HTTPException(400, 'Missing encrypted payload')
            tx_id = await blockchain.new_transaction(
                cursor, sender, recipient,
                json.dumps(body.payload), None,
                sender_pubkey=body.sender_pubkey,
                metadata={'encryption': 'hybrid-v2'}
            )
            message_obj = {
                'id': tx_id, 'sender': sender, 'sender_name': None,
                'chatId': recipient, 'isGroup': False,
                'preview': '💬 Новое сообщение',
                'timestamp': time.time(),
                'content': json.dumps(body.payload),
                'image': None,
            }
            await message_notifier.add_message(recipient, message_obj)
        await cursor.execute('COMMIT')
        if msg_type == 'group' and body.group_id and group:
            for member in group['members']:
                if member != sender:
                    await message_notifier.notify_user(member)
            for member in group['members']:
                await invalidate_conversations_cache(member)
        else:
            await message_notifier.notify_user(body.recipient)
            await invalidate_conversations_cache(sender)
            await invalidate_conversations_cache(body.recipient)
        if CONFIG.get('ENABLE_MINING', False):
            last = await blockchain._last_block_raw(cursor)
            if last:
                asyncio.create_task(mine_block_async_async(last.get('proof', 0), sender))
        return {'message': 'Sent', 'tx_id': tx_id, 'type': msg_type, 'fee': MESSAGE_FEE}


@router.get('/get_conversation')
async def get_conversation(
    request: Request,
    address: str = Depends(require_auth),
    with_:   str = Query(alias='with', default=None),
    last_message_id: Optional[int] = Query(default=None),
    limit:   int = Query(default=30),
    before_id: Optional[int] = Query(default=None),
):
    blockchain = request.app.state.blockchain
    if not with_:
        raise HTTPException(400, 'Missing "with" parameter')
    chat_with = with_
    limit = min(limit, 50)
    from database import get_db_cursor
    async with get_db_cursor(blockchain.db_path) as cursor:
        if chat_with.startswith('group:'):
            group_id = chat_with.split(':', 1)[1]
            groups = await get_user_groups_cached(address, cache_version=await get_groups_cache_version())
            if not any(g['id'] == group_id and address in g['members'] for g in groups):
                raise HTTPException(403, 'No access')
            query = ('SELECT id, sender, recipient, content, image, timestamp, metadata '
                     'FROM transactions WHERE recipient = ?')
            params = [chat_with]
            if last_message_id:
                await cursor.execute("SELECT timestamp FROM transactions WHERE id = ?", (last_message_id,))
                row_ts = await cursor.fetchone()
                if row_ts:
                    query += ' AND timestamp > ?'
                    params.append(row_ts[0])
            if before_id:
                await cursor.execute("SELECT timestamp FROM transactions WHERE id = ?", (before_id,))
                row_ts = await cursor.fetchone()
                if row_ts:
                    query += ' AND timestamp < ?'
                    params.append(row_ts[0])
            query += ' ORDER BY timestamp ASC LIMIT ?'
            params.append(limit)
            await cursor.execute(query, params)
        else:
            base_query = """
                SELECT id, sender, recipient, content, image, timestamp, metadata
                FROM (
                    SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                    UNION ALL
                    SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                ) AS t
            """
            params = [address, chat_with, chat_with, address]
            conditions = []
            if last_message_id:
                conditions.append("id > ?")
                params.append(last_message_id)
            if before_id:
                conditions.append("id < ?")
                params.append(before_id)
            if conditions:
                base_query += " WHERE " + " AND ".join(conditions)
            base_query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            await cursor.execute(base_query, params)
        rows = await cursor.fetchall()
    messages = []
    for r in rows:
        messages.append({
            'id':           r[0],
            'sender':       r[1],
            'recipient':    r[2],
            'content':      r[3],
            'image':        r[4],
            'timestamp':    r[5],
            'sender_pubkey': None,
            'metadata':     r[6],
            'sender_name':  (await get_contact_name_cached(address, r[1],
                             cache_version=await get_contact_cache_version()) or r[1][:10] + '...'),
            'recipient_name': (await get_contact_name_cached(address, r[2],
                               cache_version=await get_contact_cache_version()) or r[2][:10] + '...'),
            'is_mine': (r[1] == address),
        })
    if not chat_with.startswith('group:'):
        messages.reverse()
    return {'messages': messages, 'chat_with': chat_with}


@router.get('/get_conversations')
async def get_conversations(address: str = Depends(require_auth)):
    return {'conversations': await get_conversations_list_cached(address)}


@router.post('/mark_conversation_read')
async def mark_conversation_read(body: MarkReadRequest, request: Request, address: str = Depends(require_auth)):
    blockchain = request.app.state.blockchain
    chat_with = body.chat_with.strip()
    if not chat_with:
        raise HTTPException(400, 'Missing chat_with')
    last_message_id = body.last_message_id
    from database import get_db_cursor
    async with get_db_cursor(blockchain.db_path) as cursor:
        if last_message_id is None:
            if chat_with.startswith('group:'):
                await cursor.execute('SELECT MAX(id) FROM transactions WHERE recipient = ?', (chat_with,))
            else:
                await cursor.execute('''
                    SELECT MAX(id) FROM transactions
                    WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)
                ''', (address, chat_with, chat_with, address))
            row = await cursor.fetchone()
            last_message_id = row[0] if row and row[0] else 0
        await cursor.execute('''
            INSERT INTO read_status (user_address, chat_id, last_read_message_id, read_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_address, chat_id) DO UPDATE
            SET last_read_message_id = excluded.last_read_message_id,
                read_at = excluded.read_at
            WHERE excluded.last_read_message_id > read_status.last_read_message_id
        ''', (address, chat_with, last_message_id, time.time()))
    return {'status': 'ok', 'last_read': last_message_id}


@router.post('/message/{message_id}/delivered')
async def mark_delivered(message_id: int, request: Request, address: str = Depends(require_auth)):
    blockchain = request.app.state.blockchain
    from database import get_db_cursor
    async with get_db_cursor(blockchain.db_path) as cursor:
        await cursor.execute('''
            UPDATE transactions
            SET status = 'delivered'
            WHERE id = ? AND recipient = ? AND status = 'sent'
        ''', (message_id, address))
    return {'status': 'ok'}


@router.post('/message/{message_id}/read')
async def mark_read(message_id: int, request: Request, address: str = Depends(require_auth)):
    blockchain = request.app.state.blockchain
    from database import get_db_cursor
    async with get_db_cursor(blockchain.db_path) as cursor:
        await cursor.execute('''
            UPDATE transactions
            SET status = 'read', read_at = ?
            WHERE id = ? AND recipient = ? AND status IN ('sent', 'delivered')
        ''', (time.time(), message_id, address))
    return {'status': 'ok'}


@router.post('/message/statuses')
async def get_message_statuses(body: MessageStatusesRequest, request: Request, address: str = Depends(require_auth)):
    if not body.ids:
        return {}
    blockchain = request.app.state.blockchain
    from database import get_db_cursor
    async with get_db_cursor(blockchain.db_path) as cursor:
        placeholders = ','.join('?' * len(body.ids))
        await cursor.execute(f'SELECT id, status FROM transactions WHERE id IN ({placeholders})',
                             body.ids)
        rows = await cursor.fetchall()
    return {str(row[0]): row[1] for row in rows}


@router.get('/get_public_key/{addr}')
async def get_public_key(addr: str, address: str = Depends(require_auth)):
    from cache import get_cached_public_key, get_pubkey_cache_version, fetch_public_key_from_chain
    pubkey, verified = await get_cached_public_key(addr, cache_version=await get_pubkey_cache_version())
    if not pubkey:
        pubkey, verified = await fetch_public_key_from_chain(addr)
    if pubkey:
        return {'address': addr, 'public_key': pubkey, 'verified': verified}
    raise HTTPException(404, 'Public key not found')


@router.get('/search_messages')
async def search_messages(
    request: Request,
    q:       str = Query(default=''),
    address: str = Depends(require_auth),
):
    if len(q.strip()) < 2:
        raise HTTPException(400, 'Query too short')
    blockchain = request.app.state.blockchain
    results = await blockchain.search_messages(address, q.strip())
    return {'results': results}


@router.get('/check_new_messages')
async def check_new_messages_legacy(
    request: Request,
    since:   float = Query(default=0.0),
    address: str   = Depends(require_auth),
):
    messages = await _fetch_new_messages_from_db(request, address, since)
    return {'messages': messages}


@router.get('/notifier/stats')
async def notifier_stats(address: str = Depends(require_auth)):
    return await message_notifier.get_stats()


@router.post('/force_check')
async def force_check(address: str = Depends(require_auth)):
    await message_notifier.force_check(address)
    return {'status': 'ok'}