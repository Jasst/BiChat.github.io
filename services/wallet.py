"""
services/wallet.py — Стейкинг с пассивным доходом от комиссий
"""
import atexit
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

_db_path: Optional[str] = None
_blockchain = None
_pow_lock = threading.Lock()
_shutdown_event = threading.Event()

staking_manager = None

REWARD_PRECISION = 10**12   # для целочисленного накопления дохода


def init_wallet_service(db_path: str, blockchain):
    global _db_path, _blockchain, staking_manager
    _db_path = db_path
    _blockchain = blockchain
    if ENABLE_STAKING:
        staking_manager = StakingManager()
        logger.info("Staking manager initialized")
    else:
        staking_manager = None
        logger.info("Staking is DISABLED by config")
    return staking_manager


class StakingManager:
    """Управление стейкингом с накоплением комиссий и пропорциональным доходом."""

    def __init__(self):
        if not ENABLE_STAKING:
            raise RuntimeError("Staking is disabled in config")
        self.pool_address = STAKING_FEE_POOL_ADDRESS
        self.lock = threading.Lock()

    def _get_acc_reward_per_stake(self, cursor):
        cursor.execute("SELECT value FROM staking_state WHERE key='acc_reward_per_stake'")
        return int(cursor.fetchone()[0])

    def _set_acc_reward_per_stake(self, cursor, value: int):
        cursor.execute("UPDATE staking_state SET value=? WHERE key='acc_reward_per_stake'", (str(value),))

    def add_to_fee_pool(self, amount_sats: int, cursor=None):
        """Зачисляет комиссию в стейкинг-пул и обновляет накопленный доход на единицу стейка.
        Если cursor передан, то используется открытая транзакция (без BEGIN/COMMIT).
        """
        if not ENABLE_STAKING:
            return
        if cursor:
            # работаем в уже открытой транзакции
            cursor.execute(
                'INSERT INTO wallets (address, balance) VALUES (?, ?) '
                'ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                (self.pool_address, amount_sats, amount_sats)
            )
            cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM stakes WHERE active=1")
            total_staked = cursor.fetchone()[0]
            if total_staked > 0:
                acc = self._get_acc_reward_per_stake(cursor)
                acc += (amount_sats * REWARD_PRECISION) // total_staked
                self._set_acc_reward_per_stake(cursor, acc)
            return
        # иначе открываем свою транзакцию
        with self.lock:
            with get_db_cursor(_db_path) as cur:
                cur.execute("BEGIN IMMEDIATE")
                self.add_to_fee_pool(amount_sats, cursor=cur)
                cur.execute("COMMIT")

    def stake(self, address: str, amount_sats: int) -> int:
        if not ENABLE_STAKING:
            return -1
        if amount_sats < MIN_STAKE_AMOUNT:
            return -1
        with self.lock:
            with get_db_cursor(_db_path) as cursor:
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute('SELECT balance FROM wallets WHERE address=?', (address,))
                row = cursor.fetchone()
                if not row or row[0] < amount_sats:
                    return -1

                # Блокируем средства
                cursor.execute('UPDATE wallets SET balance = balance - ? WHERE address = ?', (amount_sats, address))
                cursor.execute(
                    'INSERT INTO wallets (address, balance) VALUES (?, ?) '
                    'ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                    (self.pool_address, amount_sats, amount_sats)
                )
                current_block = _blockchain._last_block_raw(cursor).get('index', 0)
                unlock_block = current_block + STAKE_LOCK_BLOCKS
                current_acc = self._get_acc_reward_per_stake(cursor)
                cursor.execute(
                    'INSERT INTO stakes (address, amount, start_time, start_block, unlock_block, active, reward_debt) '
                    'VALUES (?,?,?,?,?,1,?)',
                    (address, amount_sats, time.time(), current_block, unlock_block, current_acc)
                )
                cursor.execute(
                    'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) '
                    'VALUES (?,?,?,?,?,?)',
                    ('stake', address, self.pool_address, amount_sats, time.time(), 'stake')
                )
                return unlock_block

    def unstake(self, address: str) -> bool:
        if not ENABLE_STAKING:
            return False
        with self.lock:
            with get_db_cursor(_db_path) as cursor:
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute(
                    'SELECT id, amount, unlock_block, reward_debt FROM stakes WHERE address=? AND active=1',
                    (address,)
                )
                stakes = cursor.fetchall()
                if not stakes:
                    return False
                current_block = _blockchain._last_block_raw(cursor).get('index', 0)
                any_unlocked = False
                for s in stakes:
                    if current_block >= s['unlock_block']:
                        any_unlocked = True
                        current_acc = self._get_acc_reward_per_stake(cursor)
                        reward = (s['amount'] * (current_acc - s['reward_debt'])) // REWARD_PRECISION
                        total_payout = s['amount'] + reward
                        # Списываем с пула основную сумму и награду (если есть)
                        cursor.execute(
                            'UPDATE wallets SET balance = balance - ? WHERE address = ?',
                            (s['amount'], self.pool_address)
                        )
                        if reward > 0:
                            cursor.execute(
                                'UPDATE wallets SET balance = balance - ? WHERE address = ?',
                                (reward, self.pool_address)
                            )
                        cursor.execute(
                            'INSERT INTO wallets (address, balance) VALUES (?, ?) '
                            'ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                            (address, total_payout, total_payout)
                        )
                        cursor.execute('UPDATE stakes SET active=0 WHERE id=?', (s['id'],))
                        cursor.execute(
                            'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) '
                            'VALUES (?,?,?,?,?,?)',
                            ('unstake', self.pool_address, address, s['amount'], time.time(), 'unstake principal')
                        )
                        if reward > 0:
                            cursor.execute(
                                'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) '
                                'VALUES (?,?,?,?,?,?)',
                                ('staking_reward', self.pool_address, address, reward, time.time(), 'staking income')
                            )
                return any_unlocked

    def get_expected_income(self, address: str) -> int:
        if not ENABLE_STAKING:
            return 0
        with get_db_cursor(_db_path) as cursor:
            cursor.execute('SELECT amount, reward_debt FROM stakes WHERE address=? AND active=1', (address,))
            stakes = cursor.fetchall()
            if not stakes:
                return 0
            current_acc = self._get_acc_reward_per_stake(cursor)
            total = 0
            for s in stakes:
                total += (s['amount'] * (current_acc - s['reward_debt'])) // REWARD_PRECISION
            return total


# Фоновый PoW (майнинг) — используется для асинхронного добора блоков
def mine_block_async(last_proof: int, miner_address: str = None) -> None:
    if not ENABLE_MINING:
        return
    if not _pow_lock.acquire(blocking=False):
        return
    try:
        proof = _blockchain.proof_of_work(last_proof)
        with get_db_cursor(_db_path) as cursor:
            _blockchain._new_block_raw(cursor, proof, miner_address=miner_address)
        logger.debug(f"Block mined by {miner_address or 'system'}, proof={proof}")
    except Exception as e:
        logger.error(f"Async PoW failed: {e}")
    finally:
        _pow_lock.release()