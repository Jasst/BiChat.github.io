"""
database.py — Асинхронная версия с asyncpg (PostgreSQL)
"""
import asyncio
import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import List, Dict, Optional

import asyncpg
from asyncpg.pool import Pool

from config import DATABASE_URL, CONFIG, BLOCK_REWARD, ENABLE_MINING

logger = logging.getLogger(__name__)

_pool: Optional[Pool] = None


# ------------------------------------------------------------------
# Инициализация и закрытие пула
# ------------------------------------------------------------------
async def init_db():
    global _pool
    _pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=10,
        max_size=50,
        command_timeout=60,
        max_queries=50000,
        max_inactive_connection_lifetime=300
    )
    async with _pool.acquire() as conn:
        await _create_tables(conn)
        await _apply_migrations(conn)
        await _create_indexes(conn)
        # Создаём генезис-блок, если цепочка пуста
        bc = Blockchain()
        last = await bc._last_block_raw(conn)
        if not last:
            await bc._new_block_raw(conn, proof=100, previous_hash='1', miner_address=None)
            logger.info("Genesis block created")
    logger.info("PostgreSQL pool initialized")


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        logger.info("Database pool closed")


@asynccontextmanager
async def get_db_cursor():
    """Возвращает сырое asyncpg соединение (для совместимости с существующим кодом)."""
    async with _pool.acquire() as conn:
        async with conn.transaction():
            yield conn


# ------------------------------------------------------------------
# Вспомогательные функции создания таблиц и миграций
# ------------------------------------------------------------------
async def _create_tables(conn: asyncpg.Connection):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS blockchain (
            block_index       BIGSERIAL PRIMARY KEY,
            timestamp         DOUBLE PRECISION NOT NULL,
            transactions      TEXT NOT NULL DEFAULT '[]',
            coin_transactions TEXT NOT NULL DEFAULT '[]',
            proof             INTEGER NOT NULL,
            previous_hash     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id            BIGSERIAL PRIMARY KEY,
            sender        TEXT NOT NULL,
            recipient     TEXT NOT NULL,
            content       TEXT,
            image         TEXT,
            timestamp     DOUBLE PRECISION NOT NULL,
            sender_pubkey TEXT,
            metadata      TEXT,
            status        TEXT DEFAULT 'sent',
            read_at       DOUBLE PRECISION
        );
        CREATE TABLE IF NOT EXISTS contacts (
            id              BIGSERIAL PRIMARY KEY,
            user_address    TEXT NOT NULL,
            contact_address TEXT NOT NULL,
            contact_name    TEXT NOT NULL,
            contact_pubkey  TEXT,
            created_at      DOUBLE PRECISION,
            UNIQUE(user_address, contact_address)
        );
        CREATE TABLE IF NOT EXISTS groups (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            creator    TEXT NOT NULL,
            members    TEXT NOT NULL,
            created_at DOUBLE PRECISION
        );
        CREATE TABLE IF NOT EXISTS pubkey_cache (
            address        TEXT PRIMARY KEY,
            public_key_b64 TEXT NOT NULL,
            updated_at     DOUBLE PRECISION,
            source         TEXT DEFAULT 'blockchain',
            verified       INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS read_status (
            user_address         TEXT NOT NULL,
            chat_id              TEXT NOT NULL,
            last_read_message_id BIGINT NOT NULL DEFAULT 0,
            read_at              DOUBLE PRECISION,
            PRIMARY KEY (user_address, chat_id)
        );
        CREATE TABLE IF NOT EXISTS wallets (
            address TEXT PRIMARY KEY,
            balance BIGINT NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS coin_transactions (
            id        BIGSERIAL PRIMARY KEY,
            tx_type   TEXT NOT NULL,
            sender    TEXT,
            recipient TEXT NOT NULL,
            amount    BIGINT NOT NULL CHECK(amount > 0),
            timestamp DOUBLE PRECISION NOT NULL,
            block_ref BIGINT,
            note      TEXT
        );
        CREATE TABLE IF NOT EXISTS stakes (
            id          BIGSERIAL PRIMARY KEY,
            address     TEXT NOT NULL,
            amount      BIGINT NOT NULL,
            start_time  DOUBLE PRECISION NOT NULL,
            start_block BIGINT NOT NULL,
            unlock_block BIGINT NOT NULL,
            active      INTEGER DEFAULT 1,
            reward_debt BIGINT DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS staking_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_status (
            address      TEXT PRIMARY KEY,
            last_seen    DOUBLE PRECISION NOT NULL,
            status       TEXT DEFAULT 'offline',
            current_chat TEXT
        );
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at DOUBLE PRECISION
        );
        CREATE TABLE IF NOT EXISTS push_subscriptions (
              id            SERIAL PRIMARY KEY,
              user_address  TEXT NOT NULL,
              subscription  TEXT NOT NULL,
              created_at    DOUBLE PRECISION DEFAULT (extract(epoch from now())),
             UNIQUE(user_address, subscription)
        );
        CREATE TABLE IF NOT EXISTS offline_messages (
            id            BIGSERIAL PRIMARY KEY,
            user_address  TEXT NOT NULL,
            payload       TEXT NOT NULL,
            created_at    DOUBLE PRECISION NOT NULL
        );
    """)
    await conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (0, extract(epoch from now())) ON CONFLICT DO NOTHING")


async def _apply_migrations(conn: asyncpg.Connection):
    # Получаем текущую максимальную версию
    current_version = await conn.fetchval("SELECT COALESCE(MAX(version), 0) FROM schema_version")

    if current_version < 1:
        await conn.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'sent'")
        await conn.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS read_at DOUBLE PRECISION")
        await conn.execute("""
            INSERT INTO schema_version (version, applied_at)
            VALUES (1, extract(epoch from now()))
            ON CONFLICT (version) DO NOTHING
        """)
        current_version = 1

    if current_version < 2:
        await conn.execute("ALTER TABLE blockchain ADD COLUMN IF NOT EXISTS coin_transactions TEXT DEFAULT '[]'")
        await conn.execute("""
            INSERT INTO schema_version (version, applied_at)
            VALUES (2, extract(epoch from now()))
            ON CONFLICT (version) DO NOTHING
        """)
        current_version = 2

    if current_version < 3:
        await conn.execute("ALTER TABLE coin_transactions ADD COLUMN IF NOT EXISTS block_ref BIGINT")
        await conn.execute("ALTER TABLE coin_transactions ADD COLUMN IF NOT EXISTS note TEXT")
        await conn.execute("""
            INSERT INTO schema_version (version, applied_at)
            VALUES (3, extract(epoch from now()))
            ON CONFLICT (version) DO NOTHING
        """)
        current_version = 3

    if current_version < 4:
        await conn.execute("ALTER TABLE stakes ADD COLUMN IF NOT EXISTS reward_debt BIGINT DEFAULT 0")
        await conn.execute("""
            INSERT INTO schema_version (version, applied_at)
            VALUES (4, extract(epoch from now()))
            ON CONFLICT (version) DO NOTHING
        """)
        current_version = 4

    if current_version < 5:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id            SERIAL PRIMARY KEY,
                user_address  TEXT NOT NULL,
                subscription  TEXT NOT NULL,
                created_at    DOUBLE PRECISION DEFAULT extract(epoch from now()),
                UNIQUE(user_address, subscription)
            )
        """)
        await conn.execute("""
            INSERT INTO schema_version (version, applied_at)
            VALUES (5, extract(epoch from now()))
            ON CONFLICT (version) DO NOTHING
        """)
        current_version = 5

    if current_version < 6:
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status)")
        await conn.execute("""
            INSERT INTO schema_version (version, applied_at)
            VALUES (6, extract(epoch from now()))
            ON CONFLICT (version) DO NOTHING
        """)
        logger.info("Migration 6 applied: created index idx_transactions_status")
    if current_version < 7:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS offline_messages (
                id            BIGSERIAL PRIMARY KEY,
                user_address  TEXT NOT NULL,
                payload       TEXT NOT NULL,
                created_at    DOUBLE PRECISION NOT NULL
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_offline_user ON offline_messages(user_address)")
        await conn.execute("""
            INSERT INTO schema_version (version, applied_at)
            VALUES (7, extract(epoch from now()))
            ON CONFLICT (version) DO NOTHING
        """)
        logger.info("Migration 7 applied: offline_messages table")


async def _create_indexes(conn: asyncpg.Connection):
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender)",
        "CREATE INDEX IF NOT EXISTS idx_tx_recipient ON transactions(recipient)",
        "CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_tx_sender_recipient ON transactions(sender, recipient)",
        "CREATE INDEX IF NOT EXISTS idx_tx_recipient_sender ON transactions(recipient, sender)",
        "CREATE INDEX IF NOT EXISTS idx_read_status_user ON read_status(user_address)",
        "CREATE INDEX IF NOT EXISTS idx_coin_tx_recipient ON coin_transactions(recipient)",
        "CREATE INDEX IF NOT EXISTS idx_coin_tx_sender ON coin_transactions(sender)",
        "CREATE INDEX IF NOT EXISTS idx_coin_tx_block ON coin_transactions(block_ref)",
        "CREATE INDEX IF NOT EXISTS idx_stakes_address ON stakes(address)",
        "CREATE INDEX IF NOT EXISTS idx_offline_user ON offline_messages(user_address)",
    ]
    for sql in indexes:
        try:
            await conn.execute(sql)
        except Exception as e:
            logger.warning(f"Could not create index: {e}")


# ------------------------------------------------------------------
# Класс Blockchain (работа с блоками)
# ------------------------------------------------------------------
class Blockchain:
    def __init__(self):
        logger.info("Blockchain instance created (PostgreSQL)")

    async def _last_block_raw(self, conn: asyncpg.Connection) -> dict:
        row = await conn.fetchrow("SELECT * FROM blockchain ORDER BY block_index DESC LIMIT 1")
        if row:
            return dict(row)
        return {}

    async def _new_block_raw(self, conn: asyncpg.Connection, proof: int,
                             previous_hash: Optional[str] = None,
                             miner_address: Optional[str] = None) -> int:
        # Неподтверждённые coin_transactions
        rows = await conn.fetch("SELECT * FROM coin_transactions WHERE block_ref IS NULL")
        coin_txs = [dict(r) for r in rows]
        if ENABLE_MINING and miner_address:
            coin_txs.append({
                'tx_type': 'block_reward',
                'sender': None,
                'recipient': miner_address,
                'amount': BLOCK_REWARD,
                'timestamp': time.time(),
                'note': 'Miner reward'
            })
        last = await self._last_block_raw(conn)
        block_index = last.get('block_index', 0) + 1
        previous_hash = previous_hash or self._hash_block(last)
        await conn.execute("""
            INSERT INTO blockchain (block_index, timestamp, transactions, coin_transactions, proof, previous_hash)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, block_index, time.time(), '[]', json.dumps(coin_txs), proof, previous_hash)
        # Обновляем coin_transactions
        for tx in coin_txs:
            if 'id' in tx:
                await conn.execute("UPDATE coin_transactions SET block_ref = $1 WHERE id = $2", block_index, tx['id'])
            else:
                await conn.execute("""
                    INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, block_ref, note)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, tx['tx_type'], tx.get('sender'), tx['recipient'], tx['amount'], tx['timestamp'], block_index, tx.get('note'))
                if tx['tx_type'] == 'block_reward':
                    await conn.execute("""
                        INSERT INTO wallets (address, balance) VALUES ($1, $2)
                        ON CONFLICT (address) DO UPDATE SET balance = wallets.balance + $2
                    """, tx['recipient'], tx['amount'])
        return block_index

    def _hash_block(self, block: dict) -> str:
        if not block:
            return '0' * 64
        return hashlib.sha256(json.dumps(block, sort_keys=True).encode()).hexdigest()

    async def proof_of_work_async(self, last_proof: int) -> int:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.proof_of_work, last_proof)

    def proof_of_work(self, last_proof: int) -> int:
        proof = 0
        target = "0" * CONFIG['POW_DIFFICULTY']
        while proof < CONFIG['POW_MAX_ITERATIONS']:
            if hashlib.sha256(f'{last_proof}{proof}'.encode()).hexdigest()[:CONFIG['POW_DIFFICULTY']] == target:
                return proof
            proof += 1
        raise RuntimeError("PoW failed")

    async def new_transaction(self, conn: asyncpg.Connection, sender: str, recipient: str,
                              content: str, image: Optional[str] = None,
                              sender_pubkey: Optional[str] = None,
                              metadata: Optional[dict] = None) -> int:
        row = await conn.fetchrow("""
            INSERT INTO transactions (sender, recipient, content, image, timestamp, sender_pubkey, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """, sender, recipient, content, image, time.time(), sender_pubkey, json.dumps(metadata) if metadata else None)
        return row['id']

    async def search_messages(self, user_address: str, query: str, limit: int = 50) -> List[Dict]:
        async with get_db_cursor() as conn:
            rows = await conn.fetch("""
                SELECT id, sender, recipient, content, image, timestamp
                FROM transactions
                WHERE (sender = $1 OR recipient = $1)
                  AND content ILIKE $2
                ORDER BY timestamp DESC
                LIMIT $3
            """, user_address, f'%{query}%', limit)
            return [dict(r) for r in rows]

    async def health_check(self) -> dict:
        try:
            async with get_db_cursor() as conn:
                status = {'status': 'healthy'}
                row = await conn.fetchrow("SELECT pg_database_size(current_database()) as size")
                status['db_size_mb'] = round(row['size'] / (1024 * 1024), 2)
                tables = ['transactions', 'wallets', 'blockchain', 'contacts', 'groups', 'stakes']
                counts = {}
                for table in tables:
                    cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                    counts[table] = cnt
                status['table_counts'] = counts
                return status
        except Exception as e:
            return {'status': 'error', 'error': str(e)}

    async def get_performance_stats(self) -> dict:
        """Возвращает статистику производительности (для эндпоинта /health/performance)."""
        try:
            async with get_db_cursor() as conn:
                # Количество транзакций за последние 24 часа
                day_ago = time.time() - 86400
                tx_last_day = await conn.fetchval(
                    "SELECT COUNT(*) FROM transactions WHERE timestamp > $1", day_ago
                )
                # Среднее время обработки запроса (пример)
                return {
                    'transactions_last_24h': tx_last_day,
                    'active_connections': _pool.get_size() if _pool else 0,
                    'pool_usage': _pool.get_usage() if _pool else 0,
                }
        except Exception as e:
            return {'error': str(e)}

    async def try_mine_block(self, last_proof: int, last_index: int, proof: int, challenge: str, miner_address: str):
        async with get_db_cursor() as conn:
            try:
                async with conn.transaction():
                    current = await self._last_block_raw(conn)
                    if not current:
                        return False, "No blockchain", 0, 0
                    if current.get('proof') != last_proof or current.get('block_index') != last_index:
                        return False, "Blockchain moved, try again", 0, 0
                    if not self.valid_proof_with_challenge(last_proof, proof, challenge):
                        return False, "Invalid proof", 0, 0
                    current_again = await self._last_block_raw(conn)
                    if current_again.get('proof') != last_proof or current_again.get('block_index') != last_index:
                        return False, "Blockchain changed during validation", 0, 0
                    block_index = await self._new_block_raw(conn, proof, miner_address=miner_address)
                    return True, "Success", BLOCK_REWARD, block_index
            except Exception as e:
                logger.error(f"try_mine_block error: {e}")
                return False, str(e), 0, 0

    def valid_proof_with_challenge(self, last_proof: int, proof: int, challenge: str) -> bool:
        guess = f"{last_proof}{challenge}{proof}".encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        target = '0' * CONFIG['POW_DIFFICULTY']
        return guess_hash.startswith(target)