"""database_async.py — PostgreSQL с пулом соединений"""
import asyncpg
import json
import logging
from typing import Optional, Any, Dict, List
from contextlib import asynccontextmanager
from datetime import datetime, timedelta   # единый импорт для всего модуля

from config_async import (
    DATABASE_DSN, DB_POOL_MIN_SIZE, DB_POOL_MAX_SIZE,
    DB_POOL_MAX_QUERIES, DB_POOL_MAX_INACTIVE
)

logger = logging.getLogger(__name__)


class AsyncDatabase:
    """Асинхронный менеджер PostgreSQL с пулом соединений"""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def init(self) -> None:
        """Инициализирует пул соединений и создаёт таблицы"""
        self._pool = await asyncpg.create_pool(
            DATABASE_DSN,
            min_size=DB_POOL_MIN_SIZE,
            max_size=DB_POOL_MAX_SIZE,
            max_queries=DB_POOL_MAX_QUERIES,
            max_inactive_connection_lifetime=DB_POOL_MAX_INACTIVE,
            command_timeout=60,
        )
        await self._init_tables()
        await self._init_indexes()
        logger.info(f"✅ PostgreSQL pool ready: {DB_POOL_MIN_SIZE}-{DB_POOL_MAX_SIZE} connections")

    async def close(self) -> None:
        """Закрывает пул соединений"""
        if self._pool:
            await self._pool.close()
            logger.info("PostgreSQL pool closed")

    async def _init_tables(self) -> None:
        """Создаёт все необходимые таблицы"""
        async with self._pool.acquire() as conn:
            await conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

            # Блокчейн
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS blockchain (
                    block_index BIGSERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    transactions JSONB DEFAULT '[]',
                    coin_transactions JSONB DEFAULT '[]',
                    proof INTEGER NOT NULL,
                    previous_hash TEXT NOT NULL
                )
            """)

            # Партиционированная таблица сообщений
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id BIGSERIAL,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    content TEXT,
                    image TEXT,
                    timestamp TIMESTAMPTZ NOT NULL,
                    sender_pubkey TEXT,
                    metadata JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (id, timestamp)
                ) PARTITION BY RANGE (timestamp)
            """)

            await self._create_monthly_partitions(conn, months=3)

            # Кошельки
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS wallets (
                    address TEXT PRIMARY KEY,
                    balance BIGINT NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # Контакты
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS contacts (
                    id BIGSERIAL PRIMARY KEY,
                    user_address TEXT NOT NULL,
                    contact_address TEXT NOT NULL,
                    contact_name TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_address, contact_address)
                )
            """)

            # Группы
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    creator TEXT NOT NULL,
                    members JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # Статусы чтения
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS read_status (
                    user_address TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    last_read_message_id BIGINT NOT NULL DEFAULT 0,
                    read_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (user_address, chat_id)
                )
            """)

            # Стейкинг
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stakes (
                    id BIGSERIAL PRIMARY KEY,
                    address TEXT NOT NULL,
                    amount BIGINT NOT NULL,
                    start_time TIMESTAMPTZ NOT NULL,
                    start_block BIGINT NOT NULL,
                    unlock_block BIGINT NOT NULL,
                    active BOOLEAN DEFAULT TRUE,
                    reward_debt BIGINT DEFAULT 0
                )
            """)

            # Статусы пользователей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_status (
                    address TEXT PRIMARY KEY,
                    last_seen TIMESTAMPTZ NOT NULL,
                    status TEXT DEFAULT 'offline',
                    current_chat TEXT
                )
            """)

            # Кэш публичных ключей
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pubkey_cache (
                    address TEXT PRIMARY KEY,
                    public_key_b64 TEXT NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    source TEXT DEFAULT 'blockchain',
                    verified BOOLEAN DEFAULT FALSE
                )
            """)

            # Транзакции монет
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS coin_transactions (
                    id BIGSERIAL PRIMARY KEY,
                    tx_type TEXT NOT NULL,
                    sender TEXT,
                    recipient TEXT NOT NULL,
                    amount BIGINT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    block_ref BIGINT,
                    note TEXT
                )
            """)

            # Состояние стейкинга
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS staking_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            await conn.execute("""
                INSERT INTO staking_state (key, value)
                VALUES ('acc_reward_per_stake', '0')
                ON CONFLICT (key) DO NOTHING
            """)

            logger.info("✅ Database tables created")

    async def _create_monthly_partitions(self, conn, months: int = 3):
        """
        Создаёт партиции на несколько месяцев вперёд.

        FIX: в оригинале был локальный импорт
            from datetime import datetime, timedelta
        который создавал переменную `datetime` (класс) в локальной области,
        теперь он удалён — используем импорт верхнего уровня.
        """
        now = datetime.now()
        for i in range(months):
            # Первый день месяца через i месяцев
            start = (now.replace(day=1) + timedelta(days=32 * i)).replace(day=1)
            end = (start + timedelta(days=32)).replace(day=1)
            partition_name = f"transactions_{start.strftime('%Y_%m')}"

            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {partition_name} PARTITION OF transactions
                FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')
            """)

    async def _init_indexes(self) -> None:
        """Создаёт индексы для быстрого поиска"""
        async with self._pool.acquire() as conn:
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender)",
                "CREATE INDEX IF NOT EXISTS idx_tx_recipient ON transactions(recipient)",
                "CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_tx_sender_recipient ON transactions(sender, recipient)",
                "CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_address)",
                "CREATE INDEX IF NOT EXISTS idx_stakes_address ON stakes(address)",
                "CREATE INDEX IF NOT EXISTS idx_coin_tx_recipient ON coin_transactions(recipient)",
                "CREATE INDEX IF NOT EXISTS idx_coin_tx_sender ON coin_transactions(sender)",
                # Индекс для фильтрации групп по членству (используется в get_groups)
                "CREATE INDEX IF NOT EXISTS idx_groups_members ON groups USING gin(members)",
            ]
            for idx in indexes:
                await conn.execute(idx)

        logger.info("✅ Database indexes created")

    @asynccontextmanager
    async def transaction(self):
        """Контекстный менеджер для транзакций"""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def fetch_one(self, query: str, *args) -> Optional[Dict]:
        """Выполняет запрос и возвращает одну строку"""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def fetch_all(self, query: str, *args) -> List[Dict]:
        """Выполняет запрос и возвращает все строки"""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    async def execute(self, query: str, *args) -> str:
        """Выполняет запрос без возврата данных"""
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch_val(self, query: str, *args) -> Any:
        """Выполняет запрос и возвращает одно значение"""
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def health_check(self) -> dict:
        """Проверка здоровья БД"""
        try:
            result = await self.fetch_one("SELECT 1 as check, NOW() as time")
            return {'status': 'healthy', 'time': result['time']}
        except Exception as e:
            return {'status': 'error', 'error': str(e)}


# Глобальный экземпляр
db = AsyncDatabase()