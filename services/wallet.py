"""
services/wallet.py — Стейкинг и майнинг (асинхронная версия для PostgreSQL)
Безопасный анстейкинг с блокировками строк и детальным результатом.
"""
import asyncio
import logging
import threading
import time
from typing import Optional

from config import (
    COIN, MIN_STAKE_AMOUNT, STAKE_LOCK_BLOCKS,
    STAKING_FEE_POOL_ADDRESS, ENABLE_STAKING, ENABLE_MINING , COIN_NAME
)
from database import get_db_cursor

logger = logging.getLogger(__name__)

_blockchain = None
_pow_lock = threading.Lock()

staking_manager = None
REWARD_PRECISION = 10**12


def init_wallet_service(blockchain):
    """Инициализация менеджера стейкинга и создание записи в staking_state."""
    global _blockchain, staking_manager
    _blockchain = blockchain
    if ENABLE_STAKING:
        staking_manager = StakingManager()
        # Создаём запись acc_reward_per_stake, если её нет
        async def ensure_staking_state():
            async with get_db_cursor() as conn:
                await conn.execute("""
                    INSERT INTO staking_state (key, value)
                    VALUES ('acc_reward_per_stake', '0')
                    ON CONFLICT (key) DO NOTHING
                """)
        asyncio.create_task(ensure_staking_state())
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

    # ========== Вспомогательные методы для работы с acc_reward_per_stake ==========
    async def _get_acc_reward_per_stake(self, conn) -> int:
        """Возвращает текущую аккумулированную награду на единицу стейка (с блокировкой строки)."""
        # Блокируем строку для предотвращения гонок при одновременных обновлениях
        row = await conn.fetchval(
            "SELECT value FROM staking_state WHERE key='acc_reward_per_stake' FOR UPDATE"
        )
        if row is None:
            # Если записи нет – создаём
            await conn.execute(
                "INSERT INTO staking_state (key, value) VALUES ('acc_reward_per_stake', '0')"
            )
            return 0
        return int(row)

    async def _set_acc_reward_per_stake(self, conn, value: int):
        await conn.execute(
            "UPDATE staking_state SET value=$1 WHERE key='acc_reward_per_stake'",
            str(value)
        )

    # ========== Пополнение пула от комиссий ==========
    async def add_to_fee_pool(self, amount_sats: int, cursor=None):
        """Добавляет комиссию в пул стейкинга и пересчитывает acc_reward_per_stake."""
        if not ENABLE_STAKING:
            return
        if cursor is None:
            async with get_db_cursor() as cur:
                # Транзакция автоматически управляется get_db_cursor
                await self.add_to_fee_pool(amount_sats, cursor=cur)
            return

        # Блокируем запись staking_state и читаем текущее значение
        current_acc = await self._get_acc_reward_per_stake(cursor)

        # Добавляем средства в пул
        await cursor.execute(
            'INSERT INTO wallets (address, balance) VALUES ($1, $2) '
            'ON CONFLICT(address) DO UPDATE SET balance = wallets.balance + $2',
            self.pool_address, amount_sats
        )

        # Получаем общую сумму активных стейков
        total_staked = await cursor.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM stakes WHERE active=1"
        )
        if total_staked == 0:
            return

        new_acc = current_acc + (amount_sats * REWARD_PRECISION) // total_staked
        await self._set_acc_reward_per_stake(cursor, new_acc)

    # ========== Стейкинг ==========
    async def stake(self, address: str, amount_sats: int) -> int:
        """
        Создаёт новый стейк.
        Возвращает unlock_block при успехе, -1 при ошибке.
        """
        if not ENABLE_STAKING:
            return -1
        if amount_sats < MIN_STAKE_AMOUNT:
            return -1

        async with get_db_cursor() as conn:
            # Проверка лимита стейков (не более 10)
            count = await conn.fetchval(
                'SELECT COUNT(*) FROM stakes WHERE address=$1 AND active=1', address
            )
            if count >= 10:
                logger.warning(f"Stake limit exceeded for {address}")
                return -1

            # Списание средств со счёта пользователя
            result = await conn.execute(
                'UPDATE wallets SET balance = balance - $1 WHERE address = $2 AND balance >= $1',
                amount_sats, address
            )
            affected = 0
            if result and result.startswith('UPDATE'):
                parts = result.split()
                if len(parts) > 1:
                    affected = int(parts[1])
            if affected == 0:
                return -1

            # Переводим средства в пул
            await conn.execute(
                'INSERT INTO wallets (address, balance) VALUES ($1, $2) '
                'ON CONFLICT(address) DO UPDATE SET balance = wallets.balance + $2',
                self.pool_address, amount_sats
            )

            # Определяем текущий блок
            last_block = await _blockchain._last_block_raw(conn)
            current_block = last_block.get('block_index', 0)
            unlock_block = current_block + STAKE_LOCK_BLOCKS

            # Текущая аккумулированная награда
            current_acc = await self._get_acc_reward_per_stake(conn)

            # Вставляем запись о стейке
            await conn.execute(
                'INSERT INTO stakes (address, amount, start_time, start_block, unlock_block, active, reward_debt) '
                'VALUES ($1, $2, $3, $4, $5, 1, $6)',
                address, amount_sats, time.time(), current_block, unlock_block, current_acc
            )

            # Логируем транзакцию
            await conn.execute(
                'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) '
                'VALUES ($1, $2, $3, $4, $5, $6)',
                'stake', address, self.pool_address, amount_sats, time.time(), 'stake'
            )

            # Автоматический COMMIT при выходе из контекста
            return unlock_block

    # ========== Безопасное снятие одного стейка (вспомогательный метод) ==========
    async def _safe_unstake_one(self, conn, stake: dict, current_acc: int):
        """
        Пытается вывести один стейк.
        Возвращает (успех, сумма выплаты).
        Использует блокировку строки пула.
        """
        reward = (stake['amount'] * (current_acc - stake['reward_debt'])) // REWARD_PRECISION
        total_payout = stake['amount'] + reward

        # Блокируем строку пула и проверяем баланс
        pool_balance = await conn.fetchval(
            "SELECT balance FROM wallets WHERE address = $1 FOR UPDATE",
            self.pool_address
        )
        if pool_balance < total_payout:
            logger.warning(
                f"Insufficient pool balance for stake {stake['id']}: "
                f"need {total_payout}, have {pool_balance}"
            )
            return False, 0

        # Списываем principal
        await conn.execute(
            "UPDATE wallets SET balance = balance - $1 WHERE address = $2",
            stake['amount'], self.pool_address
        )
        # Списываем reward
        if reward > 0:
            await conn.execute(
                "UPDATE wallets SET balance = balance - $1 WHERE address = $2",
                reward, self.pool_address
            )

        # Начисляем пользователю
        await conn.execute(
            "INSERT INTO wallets (address, balance) VALUES ($1, $2) "
            "ON CONFLICT(address) DO UPDATE SET balance = wallets.balance + $2",
            stake['address'], total_payout
        )

        # Помечаем стейк как неактивный
        await conn.execute("UPDATE stakes SET active = 0 WHERE id = $1", stake['id'])

        # Логируем транзакции
        await conn.execute(
            "INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            'unstake', self.pool_address, stake['address'], stake['amount'], time.time(), 'unstake principal'
        )
        if reward > 0:
            await conn.execute(
                "INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                'staking_reward', self.pool_address, stake['address'], reward, time.time(), 'staking income'
            )
        return True, total_payout

    # ========== Основной метод анстейкинга ==========
    async def unstake(self, address: str) -> dict:
        """
        Выводит все разблокированные стейки пользователя.
        Возвращает детальный словарь.
        """
        if not ENABLE_STAKING:
            return {'success': False, 'error': 'staking_disabled'}

        async with get_db_cursor() as conn:
            # Блокируем все активные стейки пользователя для обновления
            stakes = await conn.fetch(
                "SELECT id, amount, unlock_block, reward_debt, address "
                "FROM stakes WHERE address = $1 AND active = 1 "
                "FOR UPDATE",
                address
            )
            if not stakes:
                return {'success': False, 'error': 'no_active_stakes'}

            # Получаем текущий номер блока и аккумулированную награду
            last_block = await _blockchain._last_block_raw(conn)
            current_block = last_block.get('block_index', 0)
            current_acc = await self._get_acc_reward_per_stake(conn)

            # Разделяем на разблокированные и заблокированные
            unlocked = []
            locked = []
            for s in stakes:
                if current_block >= s['unlock_block']:
                    unlocked.append(s)
                else:
                    locked.append(s)

            if not unlocked:
                return {'success': False, 'error': 'all_stakes_locked'}

            # Сортируем разблокированные по возрастанию суммы
            unlocked_sorted = sorted(unlocked, key=lambda x: x['amount'])
            unstaked = 0
            total_payout = 0
            failed_pool = 0
            errors = []

            for stake in unlocked_sorted:
                ok, payout = await self._safe_unstake_one(conn, stake, current_acc)
                if ok:
                    unstaked += 1
                    total_payout += payout
                else:
                    failed_pool += 1
                    errors.append(f"Stake {stake['id']} amount {stake['amount']} – pool insufficient")

            # Автоматический COMMIT при успешном выходе
            return {
                'success': unstaked > 0,
                'unstaked_count': unstaked,
                'total_payout': total_payout,
                'still_locked_count': len(locked),
                'failed_due_to_pool': failed_pool,
                'errors': errors,
                'coin_name': COIN_NAME,
                'coin_divisor': COIN,
            }

    # ========== Ожидаемый доход ==========
    async def get_expected_income(self, address: str) -> int:
        """Возвращает ожидаемую награду по всем активным стейкам."""
        if not ENABLE_STAKING:
            return 0
        async with get_db_cursor() as conn:
            stakes = await conn.fetch(
                'SELECT amount, reward_debt FROM stakes WHERE address=$1 AND active=1',
                address
            )
            if not stakes:
                return 0
            current_acc = await self._get_acc_reward_per_stake(conn)
            total = 0
            for s in stakes:
                total += (s['amount'] * (current_acc - s['reward_debt'])) // REWARD_PRECISION
            return total


# ========== Майнинг (оставлен без изменений) ==========
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
    """
    Синхронная заглушка для обратной совместимости.
    В текущей асинхронной версии не используется.
    """
    if not ENABLE_MINING:
        return
    if not _pow_lock.acquire(blocking=False):
        return
    try:
        proof = _blockchain.proof_of_work(last_proof)
        logger.warning("mine_block_async called in sync mode – not implemented for asyncpg")
    except Exception as e:
        logger.error(f"Sync PoW failed: {e}")
    finally:
        _pow_lock.release()