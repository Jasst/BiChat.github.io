"""
routes/wallet.py — Баланс, переводы, стейкинг, майнинг, глобальная статистика
"""
import logging
import secrets
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException

from config import (
    COIN, COIN_NAME, TRANSFER_FEE, MIN_STAKE_AMOUNT, BLOCK_REWARD, CONFIG,
    STAKING_FEE_POOL_ADDRESS, ENABLE_MINING, ENABLE_STAKING, MESSAGE_FEE, MAX_SUPPLY,
)
from dependencies import require_auth, make_rate_limit_dep
from models import TransferRequest, StakeRequest, MineRequest
from services.wallet import staking_manager
from setup import general_limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/wallet', tags=['wallet'])

_mining_challenges: dict = defaultdict(dict)
_CHALLENGE_TTL = 60  # seconds

_blockchain = None


def init_wallet_routes(blockchain) -> None:
    global _blockchain
    _blockchain = blockchain


@router.get('/config')
def wallet_config():
    return {
        'enable_mining':    ENABLE_MINING,
        'enable_staking':   ENABLE_STAKING,
        'message_fee':      MESSAGE_FEE,
        'transfer_fee':     TRANSFER_FEE,
        'block_reward':     BLOCK_REWARD if ENABLE_MINING else 0,
        'coin_name':        COIN_NAME,
        'coin_divisor':     COIN,
        'pow_max_iterations': CONFIG['POW_MAX_ITERATIONS'],
        'pow_difficulty':   CONFIG['POW_DIFFICULTY'],
    }


@router.get('/balance')
def wallet_balance(address: str = Depends(require_auth)):
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute('SELECT balance FROM wallets WHERE address = ?', (address,))
        row     = cursor.fetchone()
        balance = row[0] if row else 0
        cursor.execute('SELECT SUM(amount) FROM stakes WHERE address=? AND active=1', (address,))
        stake_row = cursor.fetchone()
        staked    = stake_row[0] if stake_row and stake_row[0] else 0
    return {
        'address':   address,
        'balance':   balance,
        'staked':    staked,
        'coin':      COIN,
        'coin_name': COIN_NAME,
    }


@router.get('/transactions')
def wallet_transactions(address: str = Depends(require_auth)):
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute('''
            SELECT id, tx_type, sender, recipient, amount, timestamp
            FROM coin_transactions
            WHERE sender = ? OR recipient = ?
            ORDER BY timestamp DESC LIMIT 50
        ''', (address, address))
        txs = [
            {'id': r[0], 'type': r[1], 'sender': r[2],
             'recipient': r[3], 'amount': r[4], 'timestamp': r[5]}
            for r in cursor.fetchall()
        ]
    return {'transactions': txs}


@router.post('/send')
def wallet_send(body: TransferRequest, address: str = Depends(require_auth)):
    if body.recipient == address:
        raise HTTPException(400, 'Cannot send to yourself')

    total = body.amount + TRANSFER_FEE
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute('BEGIN IMMEDIATE')
        # --- ВМЕСТО SELECT + UPDATE -> один UPDATE с проверкой ---
        cursor.execute(
            'UPDATE wallets SET balance = balance - ? WHERE address = ? AND balance >= ?',
            (total, address, total)
        )
        if cursor.rowcount == 0:
            cursor.execute('ROLLBACK')
            raise HTTPException(400, f'Insufficient balance. Need {total / COIN} {COIN_NAME}')
        # ---------------------------------------------------------
        cursor.execute(
            'INSERT INTO wallets (address, balance) VALUES (?, ?) '
            'ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
            (body.recipient, body.amount, body.amount)
        )
        ts = time.time()
        cursor.execute(
            'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp) '
            'VALUES (?,?,?,?,?)',
            ('transfer', address, body.recipient, body.amount, ts)
        )
        cursor.execute(
            'INSERT INTO wallets (address, balance) VALUES (?, ?) '
            'ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
            (STAKING_FEE_POOL_ADDRESS, TRANSFER_FEE, TRANSFER_FEE)
        )
        cursor.execute(
            'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) '
            'VALUES (?,?,?,?,?,?)',
            ('fee', address, STAKING_FEE_POOL_ADDRESS, TRANSFER_FEE, ts, 'transfer fee to staking pool')
        )
        if ENABLE_STAKING and staking_manager:
            staking_manager.add_to_fee_pool(TRANSFER_FEE, cursor=cursor)
        cursor.execute('COMMIT')

    return {'message': 'Sent', 'amount': body.amount, 'fee': TRANSFER_FEE, 'coin_name': COIN_NAME}

@router.post('/stake')
def stake(body: StakeRequest, address: str = Depends(require_auth)):
    if not ENABLE_STAKING:
        raise HTTPException(403, 'Staking is disabled')
    if body.amount < MIN_STAKE_AMOUNT:
        raise HTTPException(400, f'Minimum stake is {MIN_STAKE_AMOUNT / COIN:.6f} {COIN_NAME}')
    unlock_block = staking_manager.stake(address, body.amount)
    if unlock_block == -1:
        raise HTTPException(400, 'Insufficient balance')
    return {'message': 'Staked', 'unlock_block': unlock_block}


@router.post('/unstake')
def unstake(address: str = Depends(require_auth)):
    if not ENABLE_STAKING:
        raise HTTPException(403, 'Staking is disabled')
    if staking_manager.unstake(address):
        return {'message': 'Unstaked'}
    raise HTTPException(400, 'No active stake or still locked')


@router.get('/staking/info')
def staking_info(address: str = Depends(require_auth)):
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute(
            'SELECT amount, start_time, start_block, unlock_block '
            'FROM stakes WHERE address=? AND active=1',
            (address,)
        )
        stakes        = [dict(row) for row in cursor.fetchall()]
        current_block = _blockchain._last_block_raw(cursor).get('index', 0)

    expected_income = 0
    if ENABLE_STAKING and staking_manager:
        expected_income = staking_manager.get_expected_income(address)

    return {
        'stakes':          stakes,
        'expected_income': expected_income,
        'current_block':   current_block,
        'coin_name':       COIN_NAME,
        'coin_divisor':    COIN,
    }


@router.get('/last-proof')
def last_proof(address: str = Depends(require_auth)):
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        last = _blockchain._last_block_raw(cursor)

    challenge = secrets.token_hex(16)
    _mining_challenges[address][challenge] = time.time() + _CHALLENGE_TTL
    return {
        'last_proof': last.get('proof', 0),
        'last_index': last.get('index', 0),
        'difficulty': CONFIG['POW_DIFFICULTY'],
        'challenge':  challenge,
    }


@router.post('/mine', dependencies=[Depends(make_rate_limit_dep(general_limiter, limit=3))])
def mine(body: MineRequest, address: str = Depends(require_auth)):
    if not ENABLE_MINING:
        raise HTTPException(403, 'Mining disabled')

    challenges = _mining_challenges.get(address, {})
    if body.challenge not in challenges or time.time() > challenges[body.challenge]:
        raise HTTPException(400, 'Invalid or expired challenge')

    del _mining_challenges[address][body.challenge]

    success, error_msg, reward_amount, block_index = _blockchain.try_mine_block(
        body.last_proof, body.last_index, body.proof, body.challenge, address
    )

    if not success:
        logger.warning(f"Mining failed for {address}: {error_msg}")
        status_code = 409 if error_msg == 'Blockchain moved, try again' else 400
        raise HTTPException(status_code, error_msg)

    logger.info(f"Block {block_index} mined by {address}, reward: {reward_amount}")
    return {
        'message':     'Block mined',
        'reward':      reward_amount,
        'block_index': block_index,
        'coin_name':   COIN_NAME,
    }


@router.get('/global-stats')
def wallet_global_stats():
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute('SELECT SUM(balance) FROM wallets')
        total_supply_raw = cursor.fetchone()[0] or 0

        cursor.execute('SELECT balance FROM wallets WHERE address = ?', (STAKING_FEE_POOL_ADDRESS,))
        row = cursor.fetchone()
        staking_pool_balance = row[0] if row else 0

        cursor.execute('SELECT COUNT(*) FROM blockchain')
        total_blocks = cursor.fetchone()[0] or 0

        cursor.execute('SELECT SUM(amount) FROM stakes WHERE active = 1')
        total_staked_raw = cursor.fetchone()[0] or 0

    remaining = max(0, MAX_SUPPLY - total_supply_raw) if MAX_SUPPLY else None

    return {
        'total_supply':         total_supply_raw,
        'staking_pool_balance': staking_pool_balance,
        'block_reward':         BLOCK_REWARD if ENABLE_MINING else 0,
        'total_blocks':         total_blocks,
        'total_staked':         total_staked_raw,
        'difficulty':           CONFIG['POW_DIFFICULTY'],
        'coin_name':            COIN_NAME,
        'coin_divisor':         COIN,
        'max_supply':           MAX_SUPPLY,
        'remaining_supply':     remaining,
        'message_fee':          MESSAGE_FEE,
    }


@router.get('/stats')
def wallet_stats(address: str = Depends(require_auth)):
    stats    = _blockchain.get_conversation_stats(address)
    db_stats = _blockchain.get_database_stats()
    return {'user_stats': stats, 'database_stats': db_stats}