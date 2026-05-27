"""
database.py — Асинхронная версия с aiosqlite, без пула соединений.
Полный код без сокращений.
"""
import asyncio
import hashlib
import json
import logging
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional

import aiosqlite

from config import (
    CONFIG, DATABASE_PATH, BLOCK_REWARD, ENABLE_MINING,
    ARCHIVE_OLD_MESSAGES_DAYS, ARCHIVE_ENABLED, FTS_ENABLED, ARCHIVE_BATCH_SIZE
)

logger = logging.getLogger(__name__)


# =============================================================================
# Асинхронный контекстный менеджер подключения
# =============================================================================

@asynccontextmanager
async def get_db_cursor(db_path: str = DATABASE_PATH):
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode = WAL")
        await conn.execute("PRAGMA synchronous = NORMAL")
        await conn.execute("PRAGMA cache_size = -64000")
        await conn.execute("PRAGMA busy_timeout = 30000")
        await conn.execute("PRAGMA temp_store = MEMORY")
        await conn.execute("PRAGMA foreign_keys = ON")
        async with conn.cursor() as cursor:
            yield cursor
            await conn.commit()


# =============================================================================
# Вспомогательные асинхронные функции
# =============================================================================

async def init_sqlite_optimizations(db_path: str) -> None:
    try:
        async with aiosqlite.connect(db_path) as conn:
            await conn.executescript("""
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = NORMAL;
                PRAGMA cache_size = -64000;
                PRAGMA temp_store = MEMORY;
                PRAGMA busy_timeout = 30000;
                PRAGMA foreign_keys = ON;
            """)
            mode = await conn.execute("PRAGMA journal_mode")
            mode_value = await mode.fetchone()
            logger.info(f"✅ SQLite journal_mode: {mode_value[0].upper()}")
    except Exception as e:
        logger.error(f"❌ Failed to apply SQLite optimizations: {e}")


async def warmup_database(db_path: str) -> None:
    try:
        async with get_db_cursor(db_path) as cursor:
            await cursor.execute("SELECT 1")
        logger.debug("✅ Database warmed up")
    except Exception as e:
        logger.warning(f"⚠️ Database warmup skipped: {e}")


# =============================================================================
# Класс Blockchain (асинхронный)
# =============================================================================

class Blockchain:
    _instance = None
    _init_lock = asyncio.Lock()

    def __new__(cls, db_path: str = DATABASE_PATH):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: str = DATABASE_PATH):
        if self._initialized:
            return
        self.db_path = db_path
        self._archive_thread = None
        self._stop_archive = threading.Event()
        self._initialized = True
        logger.info("Blockchain singleton created (async)")

    # ------------------------------------------------------------------
    # Инициализация таблиц и индексов (асинхронно)
    # ------------------------------------------------------------------

    async def initialize_blockchain(self) -> None:
        async with self._init_lock:
            async with get_db_cursor(self.db_path) as cursor:
                await self._create_tables(cursor)
                await self._migrate_schema(cursor)
                await self._create_indexes(cursor)
                chain = await self._get_chain_raw(cursor)
                if not chain:
                    await self._new_block_raw(cursor, proof=100, previous_hash='1', miner_address=None)
                    logger.info("Genesis block created")
                if FTS_ENABLED:
                    await self._setup_fts5(cursor)
                if ARCHIVE_ENABLED:
                    self._start_archive_scheduler()
                else:
                    logger.info("Archiving is disabled by config")

    async def _create_tables(self, cursor: aiosqlite.Cursor) -> None:
        await cursor.execute('''CREATE TABLE IF NOT EXISTS blockchain (
            block_index       INTEGER PRIMARY KEY,
            timestamp         REAL,
            transactions      TEXT,
            coin_transactions TEXT,
            proof             INTEGER,
            previous_hash     TEXT
        )''')
        await cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            sender        TEXT NOT NULL,
            recipient     TEXT NOT NULL,
            content       TEXT,
            image         TEXT,
            timestamp     REAL,
            sender_pubkey TEXT,
            metadata      TEXT
        )''')
        await cursor.execute('''CREATE TABLE IF NOT EXISTS contacts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_address     TEXT NOT NULL,
            contact_address  TEXT NOT NULL,
            contact_name     TEXT NOT NULL,
            contact_pubkey   TEXT,
            created_at       REAL,
            UNIQUE(user_address, contact_address)
        )''')
        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_address)")
        await cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            creator    TEXT NOT NULL,
            members    TEXT NOT NULL,
            created_at REAL
        )''')
        await cursor.execute('''CREATE TABLE IF NOT EXISTS pubkey_cache (
            address        TEXT PRIMARY KEY,
            public_key_b64 TEXT NOT NULL,
            updated_at     REAL,
            source         TEXT DEFAULT 'blockchain',
            verified       INTEGER DEFAULT 0
        )''')
        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_pubkey_updated  ON pubkey_cache(updated_at)")
        await cursor.execute("CREATE INDEX IF NOT EXISTS idx_pubkey_verified ON pubkey_cache(verified)")
        await cursor.execute('''CREATE TABLE IF NOT EXISTS read_status (
            user_address        TEXT NOT NULL,
            chat_id             TEXT NOT NULL,
            last_read_message_id INTEGER NOT NULL DEFAULT 0,
            read_at             REAL,
            PRIMARY KEY (user_address, chat_id)
        )''')
        await cursor.execute('''CREATE TABLE IF NOT EXISTS wallets (
            address TEXT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0
        )''')
        await cursor.execute('''CREATE TABLE IF NOT EXISTS coin_transactions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_type   TEXT NOT NULL CHECK(tx_type IN ('reward','transfer','fee','genesis','block_reward','stake','unstake','airdrop','message_reward','message_fee','staking_reward')),
            sender    TEXT,
            recipient TEXT NOT NULL,
            amount    INTEGER NOT NULL CHECK(amount > 0),
            timestamp REAL NOT NULL,
            block_ref INTEGER,
            note      TEXT
        )''')
        await cursor.execute('''CREATE TABLE IF NOT EXISTS stakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            amount INTEGER NOT NULL,
            start_time REAL NOT NULL,
            start_block INTEGER NOT NULL,
            unlock_block INTEGER NOT NULL,
            active INTEGER DEFAULT 1,
            reward_debt INTEGER DEFAULT 0
        )''')
        await cursor.execute('''CREATE TABLE IF NOT EXISTS staking_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )''')
        await cursor.execute("INSERT OR IGNORE INTO staking_state (key, value) VALUES ('acc_reward_per_stake', '0')")
        await cursor.execute('''CREATE TABLE IF NOT EXISTS user_status (
            address TEXT PRIMARY KEY,
            last_seen REAL NOT NULL,
            status TEXT DEFAULT 'offline',
            current_chat TEXT
        )''')
        await cursor.execute('''CREATE TABLE IF NOT EXISTS transactions_archive (
            id INTEGER PRIMARY KEY,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            content TEXT,
            image TEXT,
            timestamp REAL NOT NULL,
            sender_pubkey TEXT,
            metadata TEXT,
            status TEXT,
            read_at REAL,
            archived_at REAL NOT NULL
        )''')
        await cursor.execute('''CREATE TABLE IF NOT EXISTS archive_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archived_date TEXT NOT NULL,
            messages_count INTEGER,
            created_at REAL NOT NULL
        )''')

    async def _migrate_schema(self, cursor: aiosqlite.Cursor) -> None:
        # blockchain
        await cursor.execute("PRAGMA table_info('blockchain')")
        cols = [row[1] for row in await cursor.fetchall()]
        if 'coin_transactions' not in cols:
            await cursor.execute("ALTER TABLE blockchain ADD COLUMN coin_transactions TEXT DEFAULT '[]'")
            await cursor.execute("UPDATE blockchain SET coin_transactions = '[]' WHERE coin_transactions IS NULL")
        # coin_transactions
        await cursor.execute("PRAGMA table_info('coin_transactions')")
        tx_cols = [row[1] for row in await cursor.fetchall()]
        if 'block_ref' not in tx_cols:
            await cursor.execute("ALTER TABLE coin_transactions ADD COLUMN block_ref INTEGER")
        if 'note' not in tx_cols:
            await cursor.execute("ALTER TABLE coin_transactions ADD COLUMN note TEXT")
        # stakes
        await cursor.execute("PRAGMA table_info('stakes')")
        stakes_cols = [row[1] for row in await cursor.fetchall()]
        if 'reward_debt' not in stakes_cols:
            await cursor.execute("ALTER TABLE stakes ADD COLUMN reward_debt INTEGER DEFAULT 0")
        # transactions
        await cursor.execute("PRAGMA table_info('transactions')")
        trans_cols = [row[1] for row in await cursor.fetchall()]
        if 'status' not in trans_cols:
            await cursor.execute("ALTER TABLE transactions ADD COLUMN status TEXT DEFAULT 'sent'")
            logger.info("✅ Added 'status' column to transactions")
        if 'read_at' not in trans_cols:
            await cursor.execute("ALTER TABLE transactions ADD COLUMN read_at REAL")
            logger.info("✅ Added 'read_at' column to transactions")

    async def _create_indexes(self, cursor: aiosqlite.Cursor) -> None:
        indexes = [
            'CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender)',
            'CREATE INDEX IF NOT EXISTS idx_tx_recipient ON transactions(recipient)',
            'CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)',
            'CREATE INDEX IF NOT EXISTS idx_tx_sender_recipient ON transactions(sender, recipient)',
            'CREATE INDEX IF NOT EXISTS idx_tx_recipient_sender ON transactions(recipient, sender)',
            'CREATE INDEX IF NOT EXISTS idx_read_status_user ON read_status(user_address)',
            'CREATE INDEX IF NOT EXISTS idx_coin_tx_recipient ON coin_transactions(recipient)',
            'CREATE INDEX IF NOT EXISTS idx_coin_tx_sender ON coin_transactions(sender)',
            'CREATE INDEX IF NOT EXISTS idx_coin_tx_block ON coin_transactions(block_ref)',
            'CREATE INDEX IF NOT EXISTS idx_stakes_address ON stakes(address)',
            'CREATE INDEX IF NOT EXISTS idx_archive_timestamp ON transactions_archive(timestamp)',
            'CREATE INDEX IF NOT EXISTS idx_archive_sender ON transactions_archive(sender)',
            'CREATE INDEX IF NOT EXISTS idx_transactions_archive_scan ON transactions(timestamp, status)',
            'CREATE INDEX IF NOT EXISTS idx_tx_sender_recipient_ts ON transactions(sender, recipient, timestamp)',
            'CREATE INDEX IF NOT EXISTS idx_tx_recipient_sender_ts ON transactions(recipient, sender, timestamp)',
            'CREATE INDEX IF NOT EXISTS idx_tx_timestamp_sender ON transactions(timestamp DESC, sender)',
        ]
        await cursor.execute("PRAGMA table_info('transactions')")
        if any(row[1] == 'status' for row in await cursor.fetchall()):
            indexes.append('CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status)')
        for sql in indexes:
            try:
                await cursor.execute(sql)
            except aiosqlite.OperationalError as e:
                logger.warning(f"Could not create index: {e}")

    async def _setup_fts5(self, cursor: aiosqlite.Cursor) -> None:
        if not FTS_ENABLED:
            logger.info("FTS5 disabled by config")
            return
        await cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'")
        if await cursor.fetchone():
            logger.info("FTS5 already configured")
            return
        try:
            await cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content, sender, recipient,
                    content='transactions', content_rowid='id'
                )
            ''')
            await cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS transactions_ai AFTER INSERT ON transactions BEGIN
                    INSERT INTO messages_fts(rowid, content, sender, recipient)
                    VALUES (new.id, new.content, new.sender, new.recipient);
                END
            ''')
            await cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS transactions_ad AFTER DELETE ON transactions BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content, sender, recipient)
                    VALUES ('delete', old.id, old.content, old.sender, old.recipient);
                END
            ''')
            await cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS transactions_au AFTER UPDATE ON transactions BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content, sender, recipient)
                    VALUES ('delete', old.id, old.content, old.sender, old.recipient);
                    INSERT INTO messages_fts(rowid, content, sender, recipient)
                    VALUES (new.id, new.content, new.sender, new.recipient);
                END
            ''')
            await cursor.execute("SELECT COUNT(*) FROM transactions")
            total = (await cursor.fetchone())[0]
            batch_size = ARCHIVE_BATCH_SIZE
            for offset in range(0, total, batch_size):
                await cursor.execute('''
                    INSERT INTO messages_fts(rowid, content, sender, recipient)
                    SELECT id, content, sender, recipient FROM transactions
                    LIMIT ? OFFSET ?
                ''', (batch_size, offset))
                logger.info(f"FTS5 indexing: {min(offset+batch_size, total)}/{total}")
            logger.info("✅ FTS5 full-text search enabled")
        except Exception as e:
            logger.warning(f"FTS5 setup failed (non-critical): {e}")

    # ------------------------------------------------------------------
    # Работа с блоками (асинхронная)
    # ------------------------------------------------------------------

    async def _last_block_raw(self, cursor: aiosqlite.Cursor) -> dict:
        await cursor.execute('SELECT * FROM blockchain ORDER BY block_index DESC LIMIT 1')
        row = await cursor.fetchone()
        if row:
            try:
                coin_txs = json.loads(row['coin_transactions']) if row['coin_transactions'] else []
            except (json.JSONDecodeError, TypeError):
                coin_txs = []
            return {
                'index': row['block_index'],
                'timestamp': row['timestamp'],
                'transactions': json.loads(row['transactions']) if row['transactions'] else [],
                'coin_transactions': coin_txs,
                'proof': row['proof'],
                'previous_hash': row['previous_hash'],
            }
        return {}

    async def _get_chain_raw(self, cursor: aiosqlite.Cursor) -> list:
        await cursor.execute('SELECT * FROM blockchain ORDER BY block_index ASC')
        chain = []
        for row in await cursor.fetchall():
            try:
                coin_txs = json.loads(row['coin_transactions']) if row['coin_transactions'] else []
            except (json.JSONDecodeError, TypeError):
                coin_txs = []
            chain.append({
                'index': row['block_index'],
                'timestamp': row['timestamp'],
                'transactions': json.loads(row['transactions']) if row['transactions'] else [],
                'coin_transactions': coin_txs,
                'proof': row['proof'],
                'previous_hash': row['previous_hash']
            })
        return chain

    async def _new_block_raw(self, cursor: aiosqlite.Cursor, proof: int,
                             previous_hash: Optional[str] = None,
                             miner_address: Optional[str] = None) -> None:
        await cursor.execute(
            "SELECT id, tx_type, sender, recipient, amount, timestamp, note "
            "FROM coin_transactions WHERE block_ref IS NULL"
        )
        coin_txs = [dict(row) for row in await cursor.fetchall()]

        if ENABLE_MINING and miner_address:
            reward = BLOCK_REWARD
            coin_txs.append({
                'tx_type': 'block_reward',
                'sender': None,
                'recipient': miner_address,
                'amount': reward,
                'timestamp': time.time(),
                'note': 'Miner reward'
            })

        last = await self._last_block_raw(cursor)
        block_index = last.get('index', 0) + 1
        block = {
            'index': block_index,
            'timestamp': time.time(),
            'transactions': [],
            'coin_transactions': coin_txs,
            'proof': proof,
            'previous_hash': previous_hash or self._hash_block(last),
        }

        await cursor.execute(
            'INSERT INTO blockchain (block_index, timestamp, transactions, coin_transactions, proof, previous_hash) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (block['index'], block['timestamp'],
             json.dumps(block['transactions']),
             json.dumps(block['coin_transactions']),
             block['proof'], block['previous_hash'])
        )

        for tx in coin_txs:
            await cursor.execute(
                'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, block_ref, note) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (tx['tx_type'], tx.get('sender'), tx['recipient'],
                 tx['amount'], tx['timestamp'], block_index, tx.get('note'))
            )
            if tx['tx_type'] == 'block_reward':
                await cursor.execute(
                    'INSERT INTO wallets (address, balance) VALUES (?, ?) '
                    'ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                    (tx['recipient'], tx['amount'], tx['amount'])
                )

        await cursor.execute(
            'UPDATE coin_transactions SET block_ref = ? WHERE block_ref IS NULL',
            (block_index,)
        )

    def _hash_block(self, block: dict) -> str:
        if not block:
            return '0' * 64
        return hashlib.sha256(json.dumps(block, sort_keys=True).encode()).hexdigest()

    # ------------------------------------------------------------------
    # Асинхронный proof_of_work
    # ------------------------------------------------------------------

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
        raise RuntimeError(f"PoW failed after {CONFIG['POW_MAX_ITERATIONS']} iterations")

    def valid_proof(self, last_proof: int, proof: int) -> bool:
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:CONFIG['POW_DIFFICULTY']] == '0' * CONFIG['POW_DIFFICULTY']

    def valid_proof_with_challenge(self, last_proof: int, proof: int, challenge: str) -> bool:
        guess = f"{last_proof}{challenge}{proof}".encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        target = '0' * CONFIG['POW_DIFFICULTY']
        return guess_hash.startswith(target)

    async def try_mine_block(self, last_proof: int, last_index: int, proof: int, challenge: str,
                             miner_address: str) -> tuple:
        async with get_db_cursor(self.db_path) as cursor:
            try:
                await cursor.execute("BEGIN IMMEDIATE")
                current = await self._last_block_raw(cursor)
                if not current:
                    await cursor.execute("ROLLBACK")
                    return False, "No blockchain", 0, 0
                if current.get('proof') != last_proof or current.get('index') != last_index:
                    await cursor.execute("ROLLBACK")
                    return False, "Blockchain moved, try again", 0, 0
                if not self.valid_proof_with_challenge(last_proof, proof, challenge):
                    await cursor.execute("ROLLBACK")
                    return False, "Invalid proof", 0, 0
                current_again = await self._last_block_raw(cursor)
                if current_again.get('proof') != last_proof or current_again.get('index') != last_index:
                    await cursor.execute("ROLLBACK")
                    return False, "Blockchain changed during validation", 0, 0
                await self._new_block_raw(cursor, proof, miner_address=miner_address)
                new_block = await self._last_block_raw(cursor)
                block_index = new_block.get('index', 0)
                await cursor.execute("COMMIT")
                return True, "Success", BLOCK_REWARD, block_index
            except Exception as e:
                await cursor.execute("ROLLBACK")
                logger.error(f"try_mine_block error: {e}")
                return False, str(e), 0, 0

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    async def new_transaction(self, cursor: aiosqlite.Cursor, sender: str, recipient: str,
                              content: str, image: Optional[str] = None,
                              sender_pubkey: Optional[str] = None,
                              metadata: Optional[dict] = None) -> int:
        await cursor.execute(
            'INSERT INTO transactions (sender, recipient, content, image, timestamp, sender_pubkey, metadata) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (sender, recipient, content, image, time.time(),
             sender_pubkey, json.dumps(metadata) if metadata else None)
        )
        return cursor.lastrowid

    async def new_transactions_batch(self, cursor: aiosqlite.Cursor, transactions: list) -> list:
        await cursor.execute("BEGIN IMMEDIATE")
        ids = []
        for tx in transactions:
            await cursor.execute(
                'INSERT INTO transactions (sender, recipient, content, image, timestamp, sender_pubkey, metadata) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (tx[0], tx[1], tx[2], tx[3], time.time(), tx[4],
                 json.dumps(tx[5]) if tx[5] else None)
            )
            ids.append(cursor.lastrowid)
        await cursor.execute("COMMIT")
        return ids

    async def search_messages(self, user_address: str, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        if not FTS_ENABLED:
            logger.warning("FTS disabled, search unavailable")
            return []
        try:
            async with get_db_cursor(self.db_path) as cursor:
                await cursor.execute('''
                    SELECT t.id, t.sender, t.recipient, t.content, t.image, t.timestamp,
                           highlight(messages_fts, 0, '<mark>', '</mark>') as highlighted_content
                    FROM messages_fts
                    JOIN transactions t ON t.id = messages_fts.rowid
                    WHERE messages_fts MATCH ?
                      AND (t.sender = ? OR t.recipient = ?)
                    ORDER BY t.timestamp DESC
                    LIMIT ?
                ''', (query, user_address, user_address, limit))
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    async def health_check(self, quick: bool = True) -> dict:
        try:
            async with get_db_cursor(self.db_path) as cursor:
                status = {'status': 'healthy'}
                if not quick:
                    await cursor.execute("PRAGMA integrity_check")
                    integrity = (await cursor.fetchone())[0]
                    if integrity != 'ok':
                        status['status'] = 'corrupted'
                        status['integrity'] = integrity
                await cursor.execute("PRAGMA page_count")
                page_count = (await cursor.fetchone())[0]
                await cursor.execute("PRAGMA page_size")
                page_size = (await cursor.fetchone())[0]
                status['db_size_mb'] = round(page_count * page_size / (1024 * 1024), 2)
                tables = ['transactions', 'wallets', 'blockchain', 'contacts', 'groups', 'stakes']
                status['table_counts'] = {}
                for table in tables:
                    await cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    status['table_counts'][table] = (await cursor.fetchone())[0]
                await cursor.execute("PRAGMA wal_checkpoint")
                wal_status = await cursor.fetchone()
                status['wal_status'] = wal_status
                return status
        except Exception as e:
            return {'status': 'error', 'error': str(e)}

    async def get_performance_stats(self) -> dict:
        try:
            async with get_db_cursor(self.db_path) as cursor:
                await cursor.execute("""
                    SELECT name,
                           (SELECT COUNT(*) FROM sqlite_stat1 WHERE idx = name) as stats_available
                    FROM sqlite_master
                    WHERE type = 'index'
                    ORDER BY name
                """)
                indexes = [dict(row) for row in await cursor.fetchall()]
                await cursor.execute("PRAGMA cache_size")
                cache_size = (await cursor.fetchone())[0]
                return {
                    'indexes': indexes,
                    'cache_size_pages': cache_size,
                }
        except Exception as e:
            return {'error': str(e)}

    # ------------------------------------------------------------------
    # Архивация (синхронная, в отдельном потоке)
    # ------------------------------------------------------------------

    def _start_archive_scheduler(self):
        if not ARCHIVE_ENABLED:
            return
        if self._archive_thread and self._archive_thread.is_alive():
            logger.warning("Archive thread already running")
            return

        def archive_worker():
            logger.info("Archive scheduler started")
            while not self._stop_archive.is_set():
                self._stop_archive.wait(24 * 3600)
                if self._stop_archive.is_set():
                    break
                try:
                    sync_conn = sqlite3.connect(self.db_path, timeout=30.0)
                    sync_conn.row_factory = sqlite3.Row
                    sync_cursor = sync_conn.cursor()
                    self._archive_old_messages_sync(sync_cursor, days_old=ARCHIVE_OLD_MESSAGES_DAYS)
                    sync_conn.commit()
                    sync_conn.close()
                except Exception as e:
                    logger.error(f"Archive worker error: {e}")
            logger.info("Archive scheduler stopped")

        self._archive_thread = threading.Thread(target=archive_worker, daemon=False)
        self._archive_thread.start()

    def _archive_old_messages_sync(self, cursor: sqlite3.Cursor, days_old: int = 90) -> int:
        cutoff_time = time.time() - (days_old * 24 * 3600)
        archive_time = time.time()
        cursor.execute('''
            INSERT INTO transactions_archive (
                id, sender, recipient, content, image, timestamp,
                sender_pubkey, metadata, status, read_at, archived_at
            )
            SELECT id, sender, recipient, content, image, timestamp,
                   sender_pubkey, metadata, status, read_at, ?
            FROM transactions
            WHERE timestamp < ?
              AND (status = 'read' OR status IS NULL)
              AND NOT EXISTS (SELECT 1 FROM transactions_archive WHERE id = transactions.id)
        ''', (archive_time, cutoff_time))
        archived_count = cursor.rowcount
        if archived_count > 0:
            batch_size = ARCHIVE_BATCH_SIZE
            total_deleted = 0
            while True:
                cursor.execute('''
                    DELETE FROM transactions
                    WHERE id IN (
                        SELECT id FROM transactions_archive
                        WHERE archived_at = ?
                        LIMIT ?
                    )
                ''', (archive_time, batch_size))
                deleted = cursor.rowcount
                if deleted == 0:
                    break
                total_deleted += deleted
            cursor.execute('''
                INSERT INTO archive_log (archived_date, messages_count, created_at)
                VALUES (date('now', ?), ?, ?)
            ''', (f'-{days_old} days', archived_count, time.time()))
            logger.info(f"Archived {archived_count} old messages, deleted {total_deleted} from main table")
        return archived_count

    def stop_archive(self):
        self._stop_archive.set()
        if self._archive_thread and self._archive_thread.is_alive():
            self._archive_thread.join(timeout=5)
            if self._archive_thread.is_alive():
                logger.warning("Archive thread did not finish within timeout")
            else:
                logger.info("Archive thread stopped")

    async def close(self):
        self.stop_archive()
        logger.info("Blockchain closed")