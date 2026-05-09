"""
services/wallet.py — Лотерея на стейкинге + опциональный фоновый PoW
"""
import atexit
import logging
import random
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional

from config import (
    COIN, COIN_NAME, LOTTERY_INTERVAL, MIN_STAKE_AMOUNT, STAKE_LOCK_BLOCKS,
    STAKE_WEIGHT_POWER, MAX_WEIGHT_PER_ADDRESS, LOTTERY_INITIAL_REWARD,
    LOTTERY_HALVING_INTERVAL, MESSAGE_REWARD, MESSAGE_REWARD_LIMIT_PER_HOUR
)

logger = logging.getLogger(__name__)

_db_path:   Optional[str] = None
_blockchain = None
_pow_lock   = threading.Lock()
_shutdown_event = threading.Event()

lottery = None


def init_wallet_service(db_path: str, blockchain):
    global _db_path, _blockchain, lottery
    _db_path    = db_path
    _blockchain = blockchain
    lottery = CoinLottery(interval_seconds=LOTTERY_INTERVAL, initial_reward=LOTTERY_INITIAL_REWARD)
    atexit.register(_shutdown_event.set)
    return lottery      # <-- теперь возвращаем объект


class CoinLottery:
    def __init__(self, interval_seconds: int = 1800, initial_reward: int = 100 * COIN):
        self.interval        = interval_seconds
        self.reward          = initial_reward
        self.halving_count   = 0
        self.halving_interval = LOTTERY_HALVING_INTERVAL
        self.lock            = threading.Lock()
        self.pool_address    = "lottery_pool"

        # --- НОВОЕ: пул наград за сообщения ---
        self.message_pool_address = "message_reward_pool"
        self.message_reward = MESSAGE_REWARD
        self.msg_limit_per_hour = MESSAGE_REWARD_LIMIT_PER_HOUR
        self._msg_reward_times: Dict[str, List[float]] = defaultdict(list)
        self._msg_lock = threading.Lock()

        self._start_timer()

    def stake(self, address: str, amount: int) -> int:
        with self.lock:
            from database import get_db_cursor
            with get_db_cursor(_db_path) as cursor:
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute('SELECT balance FROM wallets WHERE address = ?', (address,))
                row = cursor.fetchone()
                if not row or row[0] < amount:
                    return -1
                cursor.execute('UPDATE wallets SET balance = balance - ? WHERE address = ?', (amount, address))
                cursor.execute('INSERT INTO wallets (address, balance) VALUES (?, ?) ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                               (self.pool_address, amount, amount))
                current_block = _blockchain._last_block_raw(cursor).get('index', 0)
                unlock_block = current_block + STAKE_LOCK_BLOCKS
                cursor.execute(
                    'INSERT INTO stakes (address, amount, start_time, start_block, unlock_block, active) VALUES (?,?,?,?,?,1)',
                    (address, amount, time.time(), current_block, unlock_block))
                cursor.execute(
                    'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) VALUES (?,?,?,?,?,?)',
                    ('stake', address, self.pool_address, amount, time.time(), 'stake'))
                return unlock_block

    def unstake(self, address: str) -> bool:
        with self.lock:
            from database import get_db_cursor
            with get_db_cursor(_db_path) as cursor:
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute('SELECT id, amount, unlock_block FROM stakes WHERE address=? AND active=1', (address,))
                stakes = cursor.fetchall()
                if not stakes:
                    return False
                current_block = _blockchain._last_block_raw(cursor).get('index', 0)
                for s in stakes:
                    if current_block >= s['unlock_block']:
                        cursor.execute('UPDATE wallets SET balance = balance - ? WHERE address = ?', (s['amount'], self.pool_address))
                        cursor.execute('INSERT INTO wallets (address, balance) VALUES (?, ?) ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                                       (address, s['amount'], s['amount']))
                        cursor.execute('UPDATE stakes SET active=0 WHERE id=?', (s['id'],))
                        cursor.execute(
                            'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) VALUES (?,?,?,?,?,?)',
                            ('unstake', self.pool_address, address, s['amount'], time.time(), 'unstake'))
                        return True
                return False

    def get_active_stakes(self):
        from database import get_db_cursor
        with get_db_cursor(_db_path) as cursor:
            cursor.execute('SELECT address, amount, start_time, start_block, unlock_block FROM stakes WHERE active=1')
            return [dict(row) for row in cursor.fetchall()]

    def _draw(self):
        with self.lock:
            stakes = self.get_active_stakes()
            if not stakes:
                return
            current_block = _blockchain._last_block_raw(None).get('index', 0) or 0

            weights = []
            for s in stakes:
                locked_blocks = max(0, min(current_block - s['start_block'], STAKE_LOCK_BLOCKS))
                weighted_amount = s['amount'] ** STAKE_WEIGHT_POWER
                weight = weighted_amount * locked_blocks
                if MAX_WEIGHT_PER_ADDRESS is not None:
                    weight = min(weight, MAX_WEIGHT_PER_ADDRESS)
                weights.append(weight)

            total_weight = sum(weights)
            if total_weight == 0:
                return
            pick = random.uniform(0, total_weight)
            cumsum = 0
            for i, w in enumerate(weights):
                cumsum += w
                if cumsum >= pick:
                    winner_addr = stakes[i]['address']
                    break
            else:
                return

            from database import get_db_cursor
            with get_db_cursor(_db_path) as cursor:
                cursor.execute('SELECT balance FROM wallets WHERE address=?', (self.pool_address,))
                row = cursor.fetchone()
                if not row or row[0] < self.reward:
                    return
                cursor.execute('UPDATE wallets SET balance = balance - ? WHERE address = ?',
                               (self.reward, self.pool_address))
                cursor.execute('INSERT INTO wallets (address, balance) VALUES (?, ?) ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                               (winner_addr, self.reward, self.reward))
                cursor.execute(
                    'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp) VALUES (?,?,?,?,?)',
                    ('reward', self.pool_address, winner_addr, self.reward, time.time()))
            self.halving_count += 1
            if self.halving_count % self.halving_interval == 0:
                self.reward = max(self.reward // 2, 1)

    def _start_timer(self):
        def run():
            while not _shutdown_event.is_set():
                if _shutdown_event.wait(self.interval):
                    break
                self._draw()
        threading.Thread(target=run, daemon=True).start()

    # ===================================================================
    # НОВЫЙ МЕТОД: награда за сообщение из пула
    # ===================================================================
    def claim_message_reward(self, address: str) -> int:
        """
        Попытаться выплатить награду за сообщение.
        Возвращает сумму в сатоши (0, если не удалось).
        """
        now = time.time()
        with self._msg_lock:
            # Очищаем устаревшие записи (старше 1 часа)
            times = self._msg_reward_times[address]
            one_hour_ago = now - 3600
            self._msg_reward_times[address] = [t for t in times if t > one_hour_ago]
            if len(self._msg_reward_times[address]) >= self.msg_limit_per_hour:
                return 0   # лимит исчерпан

        reward = self.message_reward
        with self.lock:   # блокировка доступа к БД и кошелькам
            from database import get_db_cursor
            with get_db_cursor(_db_path) as cursor:
                cursor.execute("BEGIN IMMEDIATE")
                # Проверяем баланс пула сообщений
                cursor.execute('SELECT balance FROM wallets WHERE address = ?',
                               (self.message_pool_address,))
                row = cursor.fetchone()
                pool_balance = row[0] if row else 0
                if pool_balance < reward:
                    return 0

                # Списание из пула
                cursor.execute('UPDATE wallets SET balance = balance - ? WHERE address = ?',
                               (reward, self.message_pool_address))
                # Зачисление отправителю
                cursor.execute('INSERT INTO wallets (address, balance) VALUES (?, ?) '
                               'ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                               (address, reward, reward))
                # Запись транзакции
                cursor.execute(
                    'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) '
                    'VALUES (?,?,?,?,?,?)',
                    ('message_reward', self.message_pool_address, address, reward, now,
                     f'Message reward ({reward/COIN:.6f} {COIN_NAME})')
                )

        # Фиксируем время награды после успешной выплаты
        with self._msg_lock:
            self._msg_reward_times[address].append(now)

        logger.debug(f"Message reward {reward} sat paid to {address[:10]}...")
        return reward


# Фоновый PoW (не используется по умолчанию, клиент майнит самостоятельно)
def mine_block_async(last_proof: int, miner_address: str = None) -> None:
    if not _pow_lock.acquire(blocking=False):
        return
    try:
        proof = _blockchain.proof_of_work(last_proof)
        from database import get_db_cursor
        with get_db_cursor(_db_path) as cursor:
            _blockchain._new_block_raw(cursor, proof, miner_address=miner_address)
        logger.debug(f"Block mined by {miner_address or 'system'}, proof={proof}")
    except Exception as e:
        logger.error(f"Async PoW failed: {e}")
    finally:
        _pow_lock.release()