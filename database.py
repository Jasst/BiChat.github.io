"""
database.py — SQLite-инфраструктура: контекстный менеджер, инициализация, Blockchain
"""
import hashlib
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from queue import Queue
from typing import Optional

from config import CONFIG, DATABASE_PATH, BLOCK_REWARD, ENABLE_MINING

logger = logging.getLogger(__name__)


# =============================================================================
# ПУЛ СОЕДИНЕНИЙ (простой и эффективный)
# =============================================================================

class ConnectionPool:
    """Пул SQLite соединений с thread-safe доступом"""

    def __init__(self, db_path: str, max_connections: int = 5):
        self.db_path = db_path
        self.max_connections = max_connections
        self._pool = Queue(maxsize=max_connections)
        self._all_connections = []
        self._lock = threading.Lock()

        # Предсоздаем соединения
        for _ in range(max_connections):
            conn = self._create_connection()
            self._pool.put(conn)
            self._all_connections.append(conn)

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=CONFIG['DB_TIMEOUT'],
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA cache_size = -64000")
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.close()
        return conn

    def get_connection(self) -> sqlite3.Connection:
        """Получает соединение из пула (ждет если все заняты)"""
        return self._pool.get()

    def return_connection(self, conn: sqlite3.Connection) -> None:
        """Возвращает соединение обратно в пул"""
        try:
            self._pool.put_nowait(conn)
        except:
            # Пул переполнен (не должно случиться)
            conn.close()

    def close_all(self) -> None:
        """Закрывает все соединения (при завершении приложения)"""
        for conn in self._all_connections:
            try:
                conn.close()
            except:
                pass
        logger.info("All database connections closed")


# Глобальный пул соединений
_connection_pool: Optional[ConnectionPool] = None


def init_connection_pool(db_path: str, max_connections: int = 5) -> None:
    """Инициализирует пул соединений (вызывается один раз при старте)"""
    global _connection_pool
    _connection_pool = ConnectionPool(db_path, max_connections)
    logger.info(f"✅ Connection pool initialized with {max_connections} connections")


# =============================================================================
# Вспомогательные функции создания таблиц
# =============================================================================

def _create_contacts_table(cursor: sqlite3.Cursor) -> None:
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


def _create_group_table(cursor: sqlite3.Cursor) -> None:
    cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
        id         TEXT PRIMARY KEY,
        name       TEXT NOT NULL,
        creator    TEXT NOT NULL,
        members    TEXT NOT NULL,
        created_at REAL
    )''')


def _create_pubkey_cache_table(cursor: sqlite3.Cursor) -> None:
    cursor.execute('''CREATE TABLE IF NOT EXISTS pubkey_cache (
        address        TEXT PRIMARY KEY,
        public_key_b64 TEXT NOT NULL,
        updated_at     REAL,
        source         TEXT DEFAULT 'blockchain',
        verified       INTEGER DEFAULT 0
    )''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pubkey_updated  ON pubkey_cache(updated_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pubkey_verified ON pubkey_cache(verified)')


# =============================================================================
# Контекстный менеджер подключения (ИСПОЛЬЗУЕТ ПУЛ)
# =============================================================================

@contextmanager
def get_db_cursor(db_path: str = None):
    """
    Контекстный менеджер для работы с БД.
    Использует пул соединений если он инициализирован.
    """
    if _connection_pool:
        conn = _connection_pool.get_connection()
        pool_used = True
    else:
        conn = sqlite3.connect(
            db_path or DATABASE_PATH,
            timeout=CONFIG['DB_TIMEOUT'],
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        pool_used = False

    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        if pool_used:
            _connection_pool.return_connection(conn)
        else:
            conn.close()


# =============================================================================
# Инициализация и прогрев
# =============================================================================

def init_sqlite_optimizations(db_path: str) -> None:
    """Однократно применяет PRAGMA-оптимизации при старте."""
    try:
        conn = sqlite3.connect(db_path, timeout=CONFIG['DB_TIMEOUT'])
        cursor = conn.cursor()
        cursor.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            PRAGMA cache_size = -64000;
            PRAGMA temp_store = MEMORY;
            PRAGMA busy_timeout = 30000;
            PRAGMA foreign_keys = OFF;
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
# Класс Blockchain
# =============================================================================

class Blockchain:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path   = db_path
        self._init_lock = threading.Lock()
        self.initialize_blockchain()
        logger.info("Blockchain initialized")

    # ------------------------------------------------------------------
    # Инициализация
    # ------------------------------------------------------------------

    def initialize_blockchain(self) -> None:
        with self._init_lock:
            with get_db_cursor(self.db_path) as cursor:
                self._create_tables(cursor)
                self._create_indexes(cursor)
                self._migrate_schema(cursor)
                if not self._get_chain_raw(cursor):
                    self._new_block_raw(cursor, proof=100, previous_hash='1', miner_address=None)
                    logger.info("Genesis block created")

    def _migrate_schema(self, cursor: sqlite3.Cursor) -> None:
        """Добавляет отсутствующие столбцы / таблицы в старых БД."""
        # Проверяем наличие столбца coin_transactions в blockchain
        cols = [row[1] for row in cursor.execute("PRAGMA table_info('blockchain')")]
        if 'coin_transactions' not in cols:
            cursor.execute("ALTER TABLE blockchain ADD COLUMN coin_transactions TEXT DEFAULT '[]'")
            cursor.execute("UPDATE blockchain SET coin_transactions = '[]' WHERE coin_transactions IS NULL")

        # Проверяем coin_transactions на отсутствие block_ref и note
        tx_cols = [row[1] for row in cursor.execute("PRAGMA table_info('coin_transactions')")]
        if 'block_ref' not in tx_cols:
            cursor.execute("ALTER TABLE coin_transactions ADD COLUMN block_ref INTEGER")
        if 'note' not in tx_cols:
            cursor.execute("ALTER TABLE coin_transactions ADD COLUMN note TEXT")

        # Новые поля для стейкинга
        stakes_cols = [row[1] for row in cursor.execute("PRAGMA table_info('stakes')")]
        if 'reward_debt' not in stakes_cols:
            cursor.execute("ALTER TABLE stakes ADD COLUMN reward_debt INTEGER DEFAULT 0")

        # Таблица состояния стейкинга
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS staking_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO staking_state (key, value) VALUES ('acc_reward_per_stake', '0')")

        # ✅ ДОБАВЬ ПРОВЕРКУ НАЛИЧИЯ ТАБЛИЦЫ user_status
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_status'")
        if not cursor.fetchone():
            cursor.execute('''CREATE TABLE user_status (
                    address TEXT PRIMARY KEY,
                    last_seen REAL NOT NULL,
                    status TEXT DEFAULT 'offline',
                    current_chat TEXT
                )''')
            logger.info("✅ Created user_status table")
        # Добавление колонок статусов для сообщений
        trans_cols = [row[1] for row in cursor.execute("PRAGMA table_info('transactions')")]
        if 'status' not in trans_cols:
            cursor.execute("ALTER TABLE transactions ADD COLUMN status TEXT DEFAULT 'sent'")
            logger.info("✅ Added 'status' column to transactions")
        if 'read_at' not in trans_cols:
            cursor.execute("ALTER TABLE transactions ADD COLUMN read_at REAL")
            logger.info("✅ Added 'read_at' column to transactions")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status)")



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
        _create_contacts_table(cursor)
        _create_group_table(cursor)
        _create_pubkey_cache_table(cursor)

        cursor.execute('''CREATE TABLE IF NOT EXISTS read_status (
            user_address        TEXT NOT NULL,
            chat_id             TEXT NOT NULL,
            last_read_message_id INTEGER NOT NULL DEFAULT 0,
            read_at             REAL,
            PRIMARY KEY (user_address, chat_id)
        )''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_read_status_user ON read_status(user_address)')

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
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_coin_tx_recipient ON coin_transactions(recipient)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_coin_tx_sender    ON coin_transactions(sender)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_coin_tx_block     ON coin_transactions(block_ref)')

        # Новая таблица стейкинга
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
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_stakes_address ON stakes(address)')

    def _create_indexes(self, cursor: sqlite3.Cursor) -> None:
        for sql in [
            'CREATE INDEX IF NOT EXISTS idx_tx_sender           ON transactions(sender)',
            'CREATE INDEX IF NOT EXISTS idx_tx_recipient        ON transactions(recipient)',
            'CREATE INDEX IF NOT EXISTS idx_tx_timestamp        ON transactions(timestamp)',
            'CREATE INDEX IF NOT EXISTS idx_tx_sender_recipient ON transactions(sender, recipient)',
            'CREATE INDEX IF NOT EXISTS idx_tx_recipient_sender ON transactions(recipient, sender)',
        ]:
            cursor.execute(sql)

    # ------------------------------------------------------------------
    # Блокчейн — низкоуровневые методы
    # ------------------------------------------------------------------

    def _new_block_raw(self, cursor: sqlite3.Cursor, proof: int,
                       previous_hash: Optional[str] = None,
                       miner_address: Optional[str] = None) -> None:
        # собираем неподтверждённые coin-транзакции
        cursor.execute(
            "SELECT id, tx_type, sender, recipient, amount, timestamp, note "
            "FROM coin_transactions WHERE block_ref IS NULL"
        )
        coin_txs = [dict(row) for row in cursor.fetchall()]

        # Награда майнеру только если майнинг включён и указан адрес майнера
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
        # Если майнинг отключён, награда не начисляется

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

        # Обрабатываем каждую coin-транзакцию: вставляем запись и обновляем баланс
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

        # Обновляем block_ref у ранее существовавших транзакций (если были)
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
            coin_txs_raw = row[3] if len(row) > 3 else None
            try:
                coin_txs = json.loads(coin_txs_raw) if isinstance(coin_txs_raw, str) else []
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
            coin_txs_raw = r[3] if len(r) > 3 else None
            try:
                coin_txs = json.loads(coin_txs_raw) if isinstance(coin_txs_raw, str) else []
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
    # Публичные методы
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

    def proof_of_work(self, last_proof: int) -> int:
        proof  = 0
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
        """
        Проверяет, что proof удовлетворяет условию Proof-of-Work.

        Алгоритм: хеш от строки f"{last_proof}{challenge}{proof}"
        должен начинаться с '0' * POW_DIFFICULTY

        Args:
            last_proof: proof предыдущего блока
            proof: доказываемое значение (nonce)
            challenge: уникальная строка для каждого сеанса майнинга

        Returns:
            True если proof валидный, иначе False
        """
        import hashlib
        guess = f"{last_proof}{challenge}{proof}".encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        target = '0' * CONFIG['POW_DIFFICULTY']
        return guess_hash.startswith(target)

    def try_mine_block(self, last_proof: int, last_index: int, proof: int, challenge: str,
                           miner_address: str) -> tuple:
            """
            Атомарная попытка создать блок.

            Args:
                last_proof: proof последнего блока (из challenge)
                last_index: индекс последнего блока (из challenge)
                proof: найденный proof (nonce)
                challenge: уникальный challenge для этого сеанса майнинга
                miner_address: адрес майнера для начисления награды

            Returns:
                (success, error_message, reward_amount, block_index)
                - success: bool
                - error_message: str (пусто если success)
                - reward_amount: int (в сатоши)
                - block_index: int (индекс созданного блока)
            """
            from database import get_db_cursor

            with get_db_cursor(self.db_path) as cursor:
                try:
                    cursor.execute("BEGIN IMMEDIATE")

                    # 1. Проверяем актуальность блока
                    current = self._last_block_raw(cursor)
                    if not current:
                        cursor.execute("ROLLBACK")
                        return False, "No blockchain", 0, 0

                    if current.get('proof') != last_proof or current.get('index') != last_index:
                        cursor.execute("ROLLBACK")
                        return False, "Blockchain moved, try again", 0, 0

                    # 2. Проверяем proof
                    if not self.valid_proof_with_challenge(last_proof, proof, challenge):
                        cursor.execute("ROLLBACK")
                        return False, "Invalid proof", 0, 0

                    # 3. Повторная проверка (на случай гонки)
                    current_again = self._last_block_raw(cursor)
                    if current_again.get('proof') != last_proof or current_again.get('index') != last_index:
                        cursor.execute("ROLLBACK")
                        return False, "Blockchain changed during validation", 0, 0

                    # 4. Создаём блок
                    self._new_block_raw(cursor, proof, miner_address=miner_address)

                    # 5. Получаем индекс созданного блока
                    new_block = self._last_block_raw(cursor)
                    block_index = new_block.get('index', 0)

                    cursor.execute("COMMIT")

                    return True, "Success", BLOCK_REWARD, block_index

                except Exception as e:
                    cursor.execute("ROLLBACK")
                    logger.error(f"try_mine_block error: {e}")
                    return False, str(e), 0, 0

    def health_check(self) -> dict:
        """Проверка здоровья базы данных"""
        try:
            with get_db_cursor(self.db_path) as cursor:
                # Проверяем целостность
                cursor.execute("PRAGMA integrity_check")
                integrity = cursor.fetchone()[0]

                # Размер базы
                cursor.execute("PRAGMA page_count")
                page_count = cursor.fetchone()[0]
                cursor.execute("PRAGMA page_size")
                page_size = cursor.fetchone()[0]
                db_size_bytes = page_count * page_size

                # Количество записей в таблицах
                tables = ['transactions', 'wallets', 'blockchain', 'contacts', 'groups', 'stakes']
                counts = {}
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    counts[table] = cursor.fetchone()[0]

                # Статистика WAL
                cursor.execute("PRAGMA wal_checkpoint")
                wal_status = cursor.fetchone()

                return {
                    'status': 'healthy' if integrity == 'ok' else 'corrupted',
                    'integrity': integrity,
                    'db_size_mb': round(db_size_bytes / (1024 * 1024), 2),
                    'table_counts': counts,
                    'wal_status': wal_status,
                }
        except Exception as e:
            return {'status': 'error', 'error': str(e)}

    def get_performance_stats(self) -> dict:
        """Статистика производительности"""
        try:
            with get_db_cursor(self.db_path) as cursor:
                # Статистика индексов
                cursor.execute("""
                    SELECT name, 
                           (SELECT COUNT(*) FROM sqlite_stat1 WHERE idx = name) as stats_available
                    FROM sqlite_master 
                    WHERE type = 'index'
                    ORDER BY name
                """)
                indexes = [dict(row) for row in cursor.fetchall()]

                # Cache hit ratio
                cursor.execute("PRAGMA cache_size")
                cache_size = cursor.fetchone()[0]

                return {
                    'indexes': indexes,
                    'cache_size_pages': cache_size,
                }
        except Exception as e:
            return {'error': str(e)}