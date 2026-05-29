"""
services/wallet.py — Стейкинг и майнинг (асинхронная версия для PostgreSQL)
"""
import asyncio
import logging
import threading
import time
from typing import Optional

from config import (
    COIN, MIN_STAKE_AMOUNT, STAKE_LOCK_BLOCKS,
    STAKING_FEE_POOL_ADDRESS, ENABLE_STAKING, ENABLE_MINING
)
from database import get_db_cursor

logger = logging.getLogger(__name__)

_blockchain = None
_pow_lock = threading.Lock()

staking_manager = None
REWARD_PRECISION = 10**12


def init_wallet_service(blockchain):
    global _blockchain, staking_manager
    _blockchain = blockchain
    if ENABLE_STAKING:
        staking_manager = StakingManager()
        logger.info("Staking manager initialized")
    else:
        staking_manager = None
        logger.info("Staking is DISABLED by config")
    return staking_manager


class StakingManager:
    def __init__(self):
        if not ENABLE_STAKING:
            raise RuntimeError("Staking is disabled in config")
        self.pool_address = STAKING_FEE_POOL_ADDRESS
        self.lock = threading.Lock()

    async def _get_acc_reward_per_stake(self, cursor):
        await cursor.execute("SELECT value FROM staking_state WHERE key='acc_reward_per_stake'")
        row = await cursor.fetchone()
        return int(row[0])

    async def _set_acc_reward_per_stake(self, cursor, value: int):
        await cursor.execute("UPDATE staking_state SET value=$1 WHERE key='acc_reward_per_stake'", str(value))

    async def add_to_fee_pool(self, amount_sats: int, cursor=None):
        if not ENABLE_STAKING:
            return
        if cursor is None:
            async with get_db_cursor() as cur:
                await cur.execute("BEGIN")
                await self.add_to_fee_pool(amount_sats, cursor=cur)
                await cur.execute("COMMIT")
            return
        await cursor.execute('INSERT INTO wallets (address, balance) VALUES ($1, $2) '
                             'ON CONFLICT(address) DO UPDATE SET balance = wallets.balance + $2',
                             self.pool_address, amount_sats)
        await cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM stakes WHERE active=1")
        total_staked = (await cursor.fetchone())[0]
        if total_staked == 0:
            return
        acc = await self._get_acc_reward_per_stake(cursor)
        acc += (amount_sats * REWARD_PRECISION) // total_staked
        await self._set_acc_reward_per_stake(cursor, acc)

    async def stake(self, address: str, amount_sats: int) -> int:
        if not ENABLE_STAKING:
            return -1
        if amount_sats < MIN_STAKE_AMOUNT:
            return -1
        async with get_db_cursor() as cursor:
            await cursor.execute("BEGIN")
            await cursor.execute('SELECT COUNT(*) FROM stakes WHERE address=$1 AND active=1', address)
            if (await cursor.fetchone())[0] >= 10:
                logger.warning(f"Stake limit exceeded for {address}")
                return -1
            # ✅ корректная проверка результата UPDATE
            result = await cursor.execute(
                'UPDATE wallets SET balance = balance - $1 WHERE address = $2 AND balance >= $1',
                amount_sats, address
            )
            # В asyncpg результат операции — строка типа "UPDATE X"
            # Если строка не начинается с "UPDATE" или количество изменённых строк = 0 — ошибка
            affected = 0
            if result and result.startswith('UPDATE'):
                parts = result.split()
                if len(parts) > 1:
                    affected = int(parts[1])
            if affected == 0:
                await cursor.execute("ROLLBACK")
                return -1
            # остальной код без изменений...
            await cursor.execute(
                'INSERT INTO wallets (address, balance) VALUES ($1, $2) '
                'ON CONFLICT(address) DO UPDATE SET balance = wallets.balance + $2',
                self.pool_address, amount_sats
            )
            current_block = (await _blockchain._last_block_raw(cursor)).get('index', 0)
            unlock_block = current_block + STAKE_LOCK_BLOCKS
            current_acc = await self._get_acc_reward_per_stake(cursor)
            await cursor.execute(
                'INSERT INTO stakes (address, amount, start_time, start_block, unlock_block, active, reward_debt) '
                'VALUES ($1, $2, $3, $4, $5, 1, $6)',
                address, amount_sats, time.time(), current_block, unlock_block, current_acc
            )
            await cursor.execute(
                'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) '
                'VALUES ($1, $2, $3, $4, $5, $6)',
                'stake', address, self.pool_address, amount_sats, time.time(), 'stake'
            )
            await cursor.execute("COMMIT")
            return unlock_block

    async def unstake(self, address: str) -> bool:
        if not ENABLE_STAKING:
            return False
        async with get_db_cursor() as cursor:
            await cursor.execute("BEGIN")
            await cursor.execute(
                'SELECT id, amount, unlock_block, reward_debt FROM stakes WHERE address=$1 AND active=1',
                address
            )
            stakes = await cursor.fetchall()
            if not stakes:
                return False
            current_block = (await _blockchain._last_block_raw(cursor)).get('index', 0)
            any_unlocked = False
            for s in stakes:
                if current_block >= s['unlock_block']:
                    any_unlocked = True
                    current_acc = await self._get_acc_reward_per_stake(cursor)
                    reward = (s['amount'] * (current_acc - s['reward_debt'])) // REWARD_PRECISION
                    total_payout = s['amount'] + reward
                    await cursor.execute('SELECT balance FROM wallets WHERE address = $1', self.pool_address)
                    pool_balance = (await cursor.fetchone())[0]
                    if pool_balance < total_payout:
                        logger.error(f"Pool underfunded: need {total_payout}, have {pool_balance}")
                        continue
                    await cursor.execute('UPDATE wallets SET balance = balance - $1 WHERE address = $2',
                                         s['amount'], self.pool_address)
                    if reward > 0:
                        await cursor.execute('UPDATE wallets SET balance = balance - $1 WHERE address = $2',
                                             reward, self.pool_address)
                    await cursor.execute(
                        'INSERT INTO wallets (address, balance) VALUES ($1, $2) '
                        'ON CONFLICT(address) DO UPDATE SET balance = wallets.balance + $2',
                        address, total_payout
                    )
                    await cursor.execute('UPDATE stakes SET active=0 WHERE id=$1', s['id'])
                    await cursor.execute(
                        'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) '
                        'VALUES ($1, $2, $3, $4, $5, $6)',
                        'unstake', self.pool_address, address, s['amount'], time.time(), 'unstake principal'
                    )
                    if reward > 0:
                        await cursor.execute(
                            'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) '
                            'VALUES ($1, $2, $3, $4, $5, $6)',
                            'staking_reward', self.pool_address, address, reward, time.time(), 'staking income'
                        )
            return any_unlocked

    async def get_expected_income(self, address: str) -> int:
        if not ENABLE_STAKING:
            return 0
        async with get_db_cursor() as cursor:
            await cursor.execute('SELECT amount, reward_debt FROM stakes WHERE address=$1 AND active=1', address)
            stakes = await cursor.fetchall()
            if not stakes:
                return 0
            current_acc = await self._get_acc_reward_per_stake(cursor)
            total = 0
            for s in stakes:
                total += (s['amount'] * (current_acc - s['reward_debt'])) // REWARD_PRECISION
            return total


async def mine_block_async_async(last_proof: int, miner_address: str = None) -> None:
    if not ENABLE_MINING:
        return
    try:
        proof = await _blockchain.proof_of_work_async(last_proof)
        async with get_db_cursor() as cursor:
            await _blockchain._new_block_raw(cursor, proof, miner_address=miner_address)
        logger.debug(f"Block mined by {miner_address or 'system'}, proof={proof}")
    except Exception as e:
        logger.error(f"Async PoW failed: {e}")


def mine_block_async(last_proof: int, miner_address: str = None) -> None:
    """Синхронная заглушка для обратной совместимости (не используется в async коде)."""
    if not ENABLE_MINING:
        return
    if not _pow_lock.acquire(blocking=False):
        return
    try:
        proof = _blockchain.proof_of_work(last_proof)
        with get_db_cursor() as cursor:
            _blockchain._new_block_raw(cursor, proof, miner_address=miner_address)
        logger.debug(f"Block mined by {miner_address or 'system'}, proof={proof}")
    except Exception as e:
        logger.error(f"Sync PoW failed: {e}")
    finally:
        _pow_lock.release()