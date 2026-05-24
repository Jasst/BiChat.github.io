"""
database.py — SQLite-инфраструктура: контекстный менеджер, инициализация, Blockchain
Исправленная версия без критических багов.
"""
import hashlib
import json
import logging
import sqlite3
import threading
import time
import atexit
from contextlib import contextmanager
from queue import Queue
from typing import Optional, List, Dict, Any

from config import CONFIG, DATABASE_PATH, BLOCK_REWARD, ENABLE_MINING, DB_POOL_SIZE, DB_TIMEOUT
from config import ARCHIVE_OLD_MESSAGES_DAYS, ARCHIVE_ENABLED, FTS_ENABLED, ARCHIVE_BATCH_SIZE

logger = logging.getLogger(__name__)

# =============================================================================
# ПУЛ СОЕДИНЕНИЙ (исправленный, с валидацией и закрытием)
# =============================================================================

class ConnectionPool:
    """Пул SQLite соединений с автоматическим восстановлением и валидацией"""

    def __init__(self, db_path: str, max_connections: int = None):
        self.db_path = db_path
        self.max_connections = max_connections or DB_POOL_SIZE
        self._pool = Queue(maxsize=self.max_connections)
        self._all_connections = []
        self._lock = threading.Lock()
        self._closed = False
        self._cleanup_thread = None

        # Предсоздаём соединения
        for _ in range(max_connections):
            conn = self._create_connection()
            self._pool.put(conn)
            self._all_connections.append(conn)

        self._start_cleanup_thread()
        atexit.register(self.close_all)

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=DB_TIMEOUT,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA cache_size = -64000")
        # ⭐ ДОБАВИТЬ:
        cursor.execute("PRAGMA wal_autocheckpoint = 1000")  # реже делать чекпоинты
        cursor.execute("PRAGMA mmap_size = 268435456")  # 256 MB memory-mapped I/O
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.execute("PRAGMA temp_store = MEMORY")
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()
        return conn

    def _is_conn_alive(self, conn: sqlite3.Connection) -> bool:
        """Проверка, живо ли соединение"""
        try:
            conn.cursor().execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def _start_cleanup_thread(self):
        def cleanup_worker():
            while not self._closed:
                time.sleep(60)
                with self._lock:
                    for i, conn in enumerate(self._all_connections):
                        if not self._is_conn_alive(conn):
                            try:
                                conn.close()
                            except:
                                pass
                            new_conn = self._create_connection()
                            self._all_connections[i] = new_conn
                            logger.info(f"Replaced dead connection #{i}")

        self._cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        self._cleanup_thread.start()

    def get_connection(self, timeout: float = None) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("Connection pool is closed")
        if timeout is None:
            timeout = DB_TIMEOUT
        try:
            conn = self._pool.get(timeout=timeout)
        except Exception:
            raise RuntimeError("Could not get database connection from pool")
        while True:
            if self._is_conn_alive(conn):
                return conn
            # мёртвое – заменяем
            with self._lock:
                try:
                    conn.close()
                except:
                    pass
                new_conn = self._create_connection()
                if conn in self._all_connections:
                    idx = self._all_connections.index(conn)
                    self._all_connections[idx] = new_conn
                return new_conn

    def return_connection(self, conn: sqlite3.Connection) -> None:
        if not self._closed:
            self._pool.put_nowait(conn)

    def close_all(self) -> None:
        self._closed = True
        for conn in self._all_connections:
            try:
                conn.close()
            except:
                pass
        logger.info("All database connections closed")


_connection_pool: Optional[ConnectionPool] = None

def init_connection_pool(db_path: str, max_connections: int = 10) -> None:
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = ConnectionPool(db_path, max_connections)
        logger.info(f"✅ Connection pool initialized with {max_connections} connections")
    else:
        logger.warning("Connection pool already initialized")


# =============================================================================
# КОНТЕКСТНЫЙ МЕНЕДЖЕР
# =============================================================================

@contextmanager
def get_db_cursor(db_path: str = None):
    if _connection_pool:
        conn = _connection_pool.get_connection(timeout=DB_TIMEOUT)
        use_pool = True
    else:
        conn = sqlite3.connect(
            db_path or DATABASE_PATH,
            timeout=CONFIG['DB_TIMEOUT'],
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        use_pool = False
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        if use_pool:
            _connection_pool.return_connection(conn)
        else:
            conn.close()


# =============================================================================
# ИНИЦИАЛИЗАЦИЯ И ПРОГРЕВ
# =============================================================================

def init_sqlite_optimizations(db_path: str) -> None:
    try:
        conn = sqlite3.connect(db_path, timeout=CONFIG['DB_TIMEOUT'])
        cursor = conn.cursor()
        cursor.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            PRAGMA cache_size = -64000;
            PRAGMA temp_store = MEMORY;
            PRAGMA busy_timeout = 30000;
            PRAGMA foreign_keys = ON;
        """)
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        logger.info(f"✅ SQLite journal_mode: {mode.upper()}")
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Failed to apply SQLite optimizations: {e}")


def warmup_database(db_path: str) -> None:
    try:
        with get_db_cursor(db_path) as cursor:
            cursor.execute("SELECT 1")
        logger.debug("✅ Database warmed up")
    except Exception as e:
        logger.warning(f"⚠️ Database warmup skipped: {e}")


# =============================================================================
# СИНГЛТОН Blockchain (с двойной блокировкой)
# =============================================================================

class Blockchain:
    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls, db_path: str = DATABASE_PATH):
        if cls._instance is None:
            with cls._init_lock:
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
        self._init_lock = threading.Lock()
        self._initialized = True
        self.initialize_blockchain()
        logger.info("Blockchain singleton initialized with optimizations")

    # ------------------------------------------------------------------
    # ИНИЦИАЛИЗАЦИЯ (один раз)
    # ------------------------------------------------------------------

    def initialize_blockchain(self) -> None:
        with self._init_lock:
            with get_db_cursor(self.db_path) as cursor:
                self._create_tables(cursor)
                self._migrate_schema(cursor)
                self._create_indexes(cursor)
                if not self._get_chain_raw(cursor):
                    self._new_block_raw(cursor, proof=100, previous_hash='1', miner_address=None)
                    logger.info("Genesis block created")
                if FTS_ENABLED:
                    self._setup_fts5(cursor)
                if ARCHIVE_ENABLED:
                    self._start_archive_scheduler()
                else:
                    logger.info("Archiving is disabled by config")

    def _migrate_schema(self, cursor: sqlite3.Cursor) -> None:
        # blockchain
        cols = [row[1] for row in cursor.execute("PRAGMA table_info('blockchain')")]
        if 'coin_transactions' not in cols:
            cursor.execute("ALTER TABLE blockchain ADD COLUMN coin_transactions TEXT DEFAULT '[]'")
            cursor.execute("UPDATE blockchain SET coin_transactions = '[]' WHERE coin_transactions IS NULL")

        # coin_transactions
        tx_cols = [row[1] for row in cursor.execute("PRAGMA table_info('coin_transactions')")]
        if 'block_ref' not in tx_cols:
            cursor.execute("ALTER TABLE coin_transactions ADD COLUMN block_ref INTEGER")
        if 'note' not in tx_cols:
            cursor.execute("ALTER TABLE coin_transactions ADD COLUMN note TEXT")

        # stakes
        stakes_cols = [row[1] for row in cursor.execute("PRAGMA table_info('stakes')")]
        if 'reward_debt' not in stakes_cols:
            cursor.execute("ALTER TABLE stakes ADD COLUMN reward_debt INTEGER DEFAULT 0")

        # staking_state
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS staking_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO staking_state (key, value) VALUES ('acc_reward_per_stake', '0')")

        # user_status
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_status'")
        if not cursor.fetchone():
            cursor.execute('''CREATE TABLE user_status (
                    address TEXT PRIMARY KEY,
                    last_seen REAL NOT NULL,
                    status TEXT DEFAULT 'offline',
                    current_chat TEXT
                )''')
            logger.info("✅ Created user_status table")

        # transactions columns
        trans_cols = [row[1] for row in cursor.execute("PRAGMA table_info('transactions')")]
        if 'status' not in trans_cols:
            cursor.execute("ALTER TABLE transactions ADD COLUMN status TEXT DEFAULT 'sent'")
            logger.info("✅ Added 'status' column to transactions")
        if 'read_at' not in trans_cols:
            cursor.execute("ALTER TABLE transactions ADD COLUMN read_at REAL")
            logger.info("✅ Added 'read_at' column to transactions")

        # archive tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions_archive (
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
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS archive_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archived_date TEXT NOT NULL,
                messages_count INTEGER,
                created_at REAL NOT NULL
            )
        ''')

    def _create_tables(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute('''CREATE TABLE IF NOT EXISTS blockchain (
            block_index       INTEGER PRIMARY KEY,
            timestamp         REAL,
            transactions      TEXT,
            coin_transactions TEXT,
            proof             INTEGER,
            previous_hash     TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            sender        TEXT NOT NULL,
            recipient     TEXT NOT NULL,
            content       TEXT,
            image         TEXT,
            timestamp     REAL,
            sender_pubkey TEXT,
            metadata      TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS contacts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_address     TEXT NOT NULL,
            contact_address  TEXT NOT NULL,
            contact_name     TEXT NOT NULL,
            contact_pubkey   TEXT,
            created_at       REAL,
            UNIQUE(user_address, contact_address)
        )''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_address)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            creator    TEXT NOT NULL,
            members    TEXT NOT NULL,
            created_at REAL
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS pubkey_cache (
            address        TEXT PRIMARY KEY,
            public_key_b64 TEXT NOT NULL,
            updated_at     REAL,
            source         TEXT DEFAULT 'blockchain',
            verified       INTEGER DEFAULT 0
        )''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pubkey_updated  ON pubkey_cache(updated_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pubkey_verified ON pubkey_cache(verified)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS read_status (
            user_address        TEXT NOT NULL,
            chat_id             TEXT NOT NULL,
            last_read_message_id INTEGER NOT NULL DEFAULT 0,
            read_at             REAL,
            PRIMARY KEY (user_address, chat_id)
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS wallets (
            address TEXT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS coin_transactions (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_type   TEXT NOT NULL CHECK(tx_type IN ('reward','transfer','fee','genesis','block_reward','stake','unstake','airdrop','message_reward','message_fee','staking_reward')),
            sender    TEXT,
            recipient TEXT NOT NULL,
            amount    INTEGER NOT NULL CHECK(amount > 0),
            timestamp REAL NOT NULL,
            block_ref INTEGER,
            note      TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS stakes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            amount INTEGER NOT NULL,
            start_time REAL NOT NULL,
            start_block INTEGER NOT NULL,
            unlock_block INTEGER NOT NULL,
            active INTEGER DEFAULT 1,
            reward_debt INTEGER DEFAULT 0
        )''')

    def _create_indexes(self, cursor: sqlite3.Cursor) -> None:
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
        ]
        trans_cols = [row[1] for row in cursor.execute("PRAGMA table_info('transactions')")]
        if 'status' in trans_cols:
            indexes.append('CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status)')

        # --- НОВЫЕ ИНДЕКСЫ ---
        indexes.append(
            'CREATE INDEX IF NOT EXISTS idx_tx_sender_recipient_ts ON transactions(sender, recipient, timestamp)')
        indexes.append(
            'CREATE INDEX IF NOT EXISTS idx_tx_recipient_sender_ts ON transactions(recipient, sender, timestamp)')
        indexes.append('CREATE INDEX IF NOT EXISTS idx_tx_timestamp_sender ON transactions(timestamp DESC, sender)')
        # ---------------------

        for sql in indexes:
            try:
                cursor.execute(sql)
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not create index: {e}")

    def _setup_fts5(self, cursor: sqlite3.Cursor) -> None:
        if not FTS_ENABLED:
            logger.info("FTS5 disabled by config")
            return
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'")
        if cursor.fetchone():
            logger.info("FTS5 already configured")
            return
        try:
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content, sender, recipient,
                    content='transactions', content_rowid='id'
                )
            ''')
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS transactions_ai AFTER INSERT ON transactions BEGIN
                    INSERT INTO messages_fts(rowid, content, sender, recipient)
                    VALUES (new.id, new.content, new.sender, new.recipient);
                END
            ''')
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS transactions_ad AFTER DELETE ON transactions BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content, sender, recipient)
                    VALUES ('delete', old.id, old.content, old.sender, old.recipient);
                END
            ''')
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS transactions_au AFTER UPDATE ON transactions BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content, sender, recipient)
                    VALUES ('delete', old.id, old.content, old.sender, old.recipient);
                    INSERT INTO messages_fts(rowid, content, sender, recipient)
                    VALUES (new.id, new.content, new.sender, new.recipient);
                END
            ''')
            
            # Индексация существующих данных пакетами
            cursor.execute("SELECT COUNT(*) FROM transactions")
            total = cursor.fetchone()[0]
            batch_size = ARCHIVE_BATCH_SIZE
            for offset in range(0, total, batch_size):
                cursor.execute('''
                    INSERT INTO messages_fts(rowid, content, sender, recipient)
                    SELECT id, content, sender, recipient FROM transactions
                    LIMIT ? OFFSET ?
                ''', (batch_size, offset))
                logger.info(f"FTS5 indexing: {min(offset+batch_size, total)}/{total}")
            logger.info("✅ FTS5 full-text search enabled")
        except Exception as e:
            logger.warning(f"FTS5 setup failed (non-critical): {e}")

    # ------------------------------------------------------------------
    # АРХИВАЦИЯ (управляемая, с корректным удалением)
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
                self._stop_archive.wait(24 * 3600)  # раз в сутки
                if self._stop_archive.is_set():
                    break
                try:
                    with get_db_cursor(self.db_path) as cursor:
                        self._archive_old_messages(cursor, days_old=ARCHIVE_OLD_MESSAGES_DAYS)
                except Exception as e:
                    logger.error(f"Archive worker error: {e}")
            logger.info("Archive scheduler stopped")
        self._archive_thread = threading.Thread(target=archive_worker, daemon=False)
        self._archive_thread.start()

    def _archive_old_messages(self, cursor: sqlite3.Cursor, days_old: int = 90) -> int:
        """Архивирует старые прочитанные сообщения. Возвращает количество архивированных."""
        if not ARCHIVE_ENABLED:
            return 0
        cutoff_time = time.time() - (days_old * 24 * 3600)
        archive_time = time.time()  # фиксируем время архивации

        # Вставляем в архив
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
            # Удаляем пачками по 1000, используя тот же archive_time
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
            # Логируем результат
            cursor.execute('''
                INSERT INTO archive_log (archived_date, messages_count, created_at)
                VALUES (date('now', ?), ?, ?)
            ''', (f'-{days_old} days', archived_count, time.time()))
            logger.info(f"Archived {archived_count} old messages, deleted {total_deleted} from main table")
        return archived_count

    def stop_archive(self):
        """Останавливает фоновый поток архивации (graceful shutdown)."""
        self._stop_archive.set()
        if self._archive_thread and self._archive_thread.is_alive():
            self._archive_thread.join(timeout=5)
            if self._archive_thread.is_alive():
                logger.warning("Archive thread did not finish within timeout")
            else:
                logger.info("Archive thread stopped")

    # ------------------------------------------------------------------
    # НОВЫЕ МЕТОДЫ
    # ------------------------------------------------------------------

    def search_messages(self, user_address: str, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        if not FTS_ENABLED:
            logger.warning("FTS disabled, search unavailable")
            return []
        try:
            with get_db_cursor(self.db_path) as cursor:
                cursor.execute('''
                    SELECT t.id, t.sender, t.recipient, t.content, t.image, t.timestamp,
                           highlight(messages_fts, 0, '<mark>', '</mark>') as highlighted_content
                    FROM messages_fts
                    JOIN transactions t ON t.id = messages_fts.rowid
                    WHERE messages_fts MATCH ?
                      AND (t.sender = ? OR t.recipient = ?)
                    ORDER BY t.timestamp DESC
                    LIMIT ?
                ''', (query, user_address, user_address, limit))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    # ------------------------------------------------------------------
    # БЛОКЧЕЙН - НИЗКОУРОВНЕВЫЕ МЕТОДЫ
    # ------------------------------------------------------------------

    def _new_block_raw(self, cursor: sqlite3.Cursor, proof: int,
                       previous_hash: Optional[str] = None,
                       miner_address: Optional[str] = None) -> None:
        cursor.execute(
            "SELECT id, tx_type, sender, recipient, amount, timestamp, note "
            "FROM coin_transactions WHERE block_ref IS NULL"
        )
        coin_txs = [dict(row) for row in cursor.fetchall()]

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

        last = self._last_block_raw(cursor)
        block_index = last.get('index', 0) + 1
        block = {
            'index': block_index,
            'timestamp': time.time(),
            'transactions': [],
            'coin_transactions': coin_txs,
            'proof': proof,
            'previous_hash': previous_hash or self._hash_block(last),
        }
        cursor.execute(
            'INSERT INTO blockchain (block_index, timestamp, transactions, coin_transactions, proof, previous_hash) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (block['index'], block['timestamp'],
             json.dumps(block['transactions']),
             json.dumps(block['coin_transactions']),
             block['proof'], block['previous_hash'])
        )

        for tx in coin_txs:
            cursor.execute(
                'INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, block_ref, note) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (tx['tx_type'], tx.get('sender'), tx['recipient'],
                 tx['amount'], tx['timestamp'], block_index, tx.get('note'))
            )
            if tx['tx_type'] == 'block_reward':
                cursor.execute(
                    'INSERT INTO wallets (address, balance) VALUES (?, ?) '
                    'ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                    (tx['recipient'], tx['amount'], tx['amount'])
                )

        cursor.execute(
            'UPDATE coin_transactions SET block_ref = ? WHERE block_ref IS NULL',
            (block_index,)
        )

    def _hash_block(self, block: dict) -> str:
        if not block:
            return '0' * 64
        return hashlib.sha256(json.dumps(block, sort_keys=True).encode()).hexdigest()

    def _last_block_raw(self, cursor: sqlite3.Cursor) -> dict:
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index DESC LIMIT 1')
        row = cursor.fetchone()
        if row:
            try:
                coin_txs = json.loads(row[3]) if isinstance(row[3], str) else []
            except (json.JSONDecodeError, TypeError):
                coin_txs = []
            return {
                'index': row[0], 'timestamp': row[1],
                'transactions': json.loads(row[2]) if row[2] else [],
                'coin_transactions': coin_txs,
                'proof': row[4], 'previous_hash': row[5],
            }
        return {}

    def _get_chain_raw(self, cursor: sqlite3.Cursor) -> list:
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index ASC')
        chain = []
        for r in cursor.fetchall():
            try:
                coin_txs = json.loads(r[3]) if isinstance(r[3], str) else []
            except (json.JSONDecodeError, TypeError):
                coin_txs = []
            chain.append({
                'index': r[0], 'timestamp': r[1],
                'transactions': json.loads(r[2]) if r[2] else [],
                'coin_transactions': coin_txs,
                'proof': r[4], 'previous_hash': r[5]
            })
        return chain

    # ------------------------------------------------------------------
    # ПУБЛИЧНЫЕ МЕТОДЫ
    # ------------------------------------------------------------------

    def new_transaction(self, cursor: sqlite3.Cursor, sender: str, recipient: str,
                        content: str, image: Optional[str] = None,
                        sender_pubkey: Optional[str] = None,
                        metadata: Optional[dict] = None) -> int:
        cursor.execute(
            'INSERT INTO transactions '
            '(sender, recipient, content, image, timestamp, sender_pubkey, metadata) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (sender, recipient, content, image, time.time(),
             sender_pubkey, json.dumps(metadata) if metadata else None)
        )
        return cursor.lastrowid

    def new_transactions_batch(self, cursor: sqlite3.Cursor, transactions: list) -> list:
        """
        transactions: список кортежей (sender, recipient, content, image, sender_pubkey, metadata)
        Возвращает список id вставленных записей.
        """
        cursor.execute("BEGIN IMMEDIATE")
        ids = []
        for tx in transactions:
            cursor.execute(
                'INSERT INTO transactions '
                '(sender, recipient, content, image, timestamp, sender_pubkey, metadata) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (tx[0], tx[1], tx[2], tx[3], time.time(), tx[4],
                 json.dumps(tx[5]) if tx[5] else None)
            )
            ids.append(cursor.lastrowid)
        cursor.execute("COMMIT")
        return ids

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

    def try_mine_block(self, last_proof: int, last_index: int, proof: int, challenge: str,
                       miner_address: str) -> tuple:
        with get_db_cursor(self.db_path) as cursor:
            try:
                cursor.execute("BEGIN IMMEDIATE")

                current = self._last_block_raw(cursor)
                if not current:
                    cursor.execute("ROLLBACK")
                    return False, "No blockchain", 0, 0

                if current.get('proof') != last_proof or current.get('index') != last_index:
                    cursor.execute("ROLLBACK")
                    return False, "Blockchain moved, try again", 0, 0

                if not self.valid_proof_with_challenge(last_proof, proof, challenge):
                    cursor.execute("ROLLBACK")
                    return False, "Invalid proof", 0, 0

                current_again = self._last_block_raw(cursor)
                if current_again.get('proof') != last_proof or current_again.get('index') != last_index:
                    cursor.execute("ROLLBACK")
                    return False, "Blockchain changed during validation", 0, 0

                self._new_block_raw(cursor, proof, miner_address=miner_address)

                new_block = self._last_block_raw(cursor)
                block_index = new_block.get('index', 0)

                cursor.execute("COMMIT")
                return True, "Success", BLOCK_REWARD, block_index

            except Exception as e:
                cursor.execute("ROLLBACK")
                logger.error(f"try_mine_block error: {e}")
                return False, str(e), 0, 0

    def health_check(self, quick: bool = True) -> dict:
        """quick=True пропускает тяжёлый PRAGMA integrity_check"""
        try:
            with get_db_cursor(self.db_path) as cursor:
                status = {'status': 'healthy'}
                if not quick:
                    cursor.execute("PRAGMA integrity_check")
                    integrity = cursor.fetchone()[0]
                    if integrity != 'ok':
                        status['status'] = 'corrupted'
                        status['integrity'] = integrity
                cursor.execute("PRAGMA page_count")
                page_count = cursor.fetchone()[0]
                cursor.execute("PRAGMA page_size")
                page_size = cursor.fetchone()[0]
                status['db_size_mb'] = round(page_count * page_size / (1024 * 1024), 2)
                tables = ['transactions', 'wallets', 'blockchain', 'contacts', 'groups', 'stakes']
                status['table_counts'] = {}
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    status['table_counts'][table] = cursor.fetchone()[0]
                cursor.execute("PRAGMA wal_checkpoint")
                wal_status = cursor.fetchone()
                status['wal_status'] = wal_status
                return status
        except Exception as e:
            return {'status': 'error', 'error': str(e)}

    def get_performance_stats(self) -> dict:
        try:
            with get_db_cursor(self.db_path) as cursor:
                cursor.execute("""
                    SELECT name,
                           (SELECT COUNT(*) FROM sqlite_stat1 WHERE idx = name) as stats_available
                    FROM sqlite_master
                    WHERE type = 'index'
                    ORDER BY name
                """)
                indexes = [dict(row) for row in cursor.fetchall()]
                cursor.execute("PRAGMA cache_size")
                cache_size = cursor.fetchone()[0]
                return {
                    'indexes': indexes,
                    'cache_size_pages': cache_size,
                }
        except Exception as e:
            return {'error': str(e)}

    def close(self):
        """Вызывается при завершении приложения"""
        self.stop_archive()
        if _connection_pool:
            _connection_pool.close_all()