import os
import sys
import sqlite3
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from database import init_connection_pool, get_db_cursor
from config import CONFIG

# ----------------------------------------------------------------------
# Сброс синглтона Blockchain (чтобы не мешал)
# ----------------------------------------------------------------------
def reset_blockchain_singleton():
    from database import Blockchain
    if Blockchain._instance is not None:
        try:
            Blockchain._instance.stop_archive()
        except:
            pass
        Blockchain._instance = None
        Blockchain._init_lock = type(Blockchain)._init_lock

# ----------------------------------------------------------------------
# Создание схемы БД без использования Blockchain
# ----------------------------------------------------------------------
def init_empty_db(cursor):
    """Создаёт все необходимые таблицы и индексы."""
    # Таблицы
    cursor.execute('''CREATE TABLE IF NOT EXISTS blockchain (
        block_index INTEGER PRIMARY KEY,
        timestamp REAL,
        transactions TEXT,
        coin_transactions TEXT,
        proof INTEGER,
        previous_hash TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT NOT NULL,
        recipient TEXT NOT NULL,
        content TEXT,
        image TEXT,
        timestamp REAL,
        sender_pubkey TEXT,
        metadata TEXT,
        status TEXT DEFAULT 'sent',
        read_at REAL
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_address TEXT NOT NULL,
        contact_address TEXT NOT NULL,
        contact_name TEXT NOT NULL,
        contact_pubkey TEXT,
        created_at REAL,
        UNIQUE(user_address, contact_address)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        creator TEXT NOT NULL,
        members TEXT NOT NULL,
        created_at REAL
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS pubkey_cache (
        address TEXT PRIMARY KEY,
        public_key_b64 TEXT NOT NULL,
        updated_at REAL,
        source TEXT DEFAULT 'blockchain',
        verified INTEGER DEFAULT 0
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS read_status (
        user_address TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        last_read_message_id INTEGER NOT NULL DEFAULT 0,
        read_at REAL,
        PRIMARY KEY (user_address, chat_id)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS wallets (
        address TEXT PRIMARY KEY,
        balance INTEGER NOT NULL DEFAULT 0
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS coin_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tx_type TEXT NOT NULL,
        sender TEXT,
        recipient TEXT NOT NULL,
        amount INTEGER NOT NULL,
        timestamp REAL NOT NULL,
        block_ref INTEGER,
        note TEXT
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
    cursor.execute('''CREATE TABLE IF NOT EXISTS staking_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')
    cursor.execute("INSERT OR IGNORE INTO staking_state (key, value) VALUES ('acc_reward_per_stake', '0')")
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_status (
        address TEXT PRIMARY KEY,
        last_seen REAL NOT NULL,
        status TEXT DEFAULT 'offline',
        current_chat TEXT
    )''')

    # Индексы (без дублирования)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_recipient ON transactions(recipient)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_address)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pubkey_updated ON pubkey_cache(updated_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_sender_recipient ON transactions(sender, recipient)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_recipient_sender ON transactions(recipient, sender)")
    # Новые составные индексы для ускорения диалогов
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_tx_sender_recipient_ts ON transactions(sender, recipient, timestamp)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_tx_recipient_sender_ts ON transactions(recipient, sender, timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_timestamp_sender ON transactions(timestamp DESC, sender)")

    # Обновляем статистику для оптимизатора
    cursor.execute("ANALYZE")


# ----------------------------------------------------------------------
# Фикстура временной БД
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def temp_db():
    reset_blockchain_singleton()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    init_connection_pool(path, max_connections=5)

    with get_db_cursor(path) as cursor:
        init_empty_db(cursor)

    yield path

    from database import _connection_pool
    if _connection_pool:
        _connection_pool.close_all()
    os.unlink(path)
    reset_blockchain_singleton()


# ----------------------------------------------------------------------
# Вспомогательные функции
# ----------------------------------------------------------------------
def create_test_wallets(cursor, count=100):
    for i in range(count):
        addr = f"testaddr{i:064d}"
        cursor.execute(
            "INSERT OR IGNORE INTO wallets (address, balance) VALUES (?, ?)",
            (addr, 1000000)
        )

def create_test_contacts(cursor, user_addr, contact_addrs):
    for contact in contact_addrs[:50]:
        cursor.execute(
            "INSERT OR REPLACE INTO contacts (user_address, contact_address, contact_name, created_at) VALUES (?, ?, ?, ?)",
            (user_addr, contact, f"Contact_{contact[:8]}", time.time())
        )


# ----------------------------------------------------------------------
# Бенчмарки
# ----------------------------------------------------------------------
def test_single_insert_benchmark(benchmark, temp_db):
    path = temp_db
    def insert_one():
        with get_db_cursor(path) as cursor:
            cursor.execute(
                "INSERT INTO transactions (sender, recipient, content, timestamp) VALUES (?, ?, ?, ?)",
                ("alice", "bob", "Hello", time.time())
            )
            return cursor.lastrowid
    benchmark(insert_one)


def test_bulk_insert_messages(benchmark, temp_db):
    path = temp_db
    def bulk_insert():
        with get_db_cursor(path) as cursor:
            for i in range(100):
                cursor.execute(
                    "INSERT INTO transactions (sender, recipient, content, timestamp) VALUES (?, ?, ?, ?)",
                    (f"sender{i}", f"recipient{i}", f"Content {i}", time.time())
                )
    benchmark(bulk_insert)


def test_read_conversation(benchmark, temp_db):
    path = temp_db
    alice = "a" * 64
    bob   = "b" * 64
    with get_db_cursor(path) as cursor:
        create_test_wallets(cursor, 2)
        for i in range(20000):
            sender = alice if i % 2 == 0 else bob
            recipient = bob if sender == alice else alice
            cursor.execute(
                "INSERT INTO transactions (sender, recipient, content, timestamp) VALUES (?, ?, ?, ?)",
                (sender, recipient, f"Msg {i}", time.time() + i)
            )
    def read_conversation():
        with get_db_cursor(path) as cursor:
            cursor.execute("""
                SELECT id, sender, recipient, content, timestamp
                FROM (
                    SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                    UNION ALL
                    SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                )
                ORDER BY timestamp DESC
                LIMIT 50
            """, (alice, bob, bob, alice))
            rows = cursor.fetchall()
        return len(rows)
    result = benchmark(read_conversation)
    assert result == 50


def test_balance_update_concurrently(temp_db):
    path = temp_db
    addr = "c" * 64
    with get_db_cursor(path) as cursor:
        cursor.execute("INSERT OR IGNORE INTO wallets (address, balance) VALUES (?, ?)", (addr, 10000))
    def update_balance(amount_delta):
        with get_db_cursor(path) as cursor:
            cursor.execute("SELECT balance FROM wallets WHERE address = ?", (addr,))
            bal = cursor.fetchone()[0]
            new_bal = bal + amount_delta
            cursor.execute("UPDATE wallets SET balance = ? WHERE address = ?", (new_bal, addr))
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(update_balance, 1) for _ in range(50)]
        for f in as_completed(futures):
            f.result()
    with get_db_cursor(path) as cursor:
        cursor.execute("SELECT balance FROM wallets WHERE address = ?", (addr,))
        final_bal = cursor.fetchone()[0]
    assert final_bal == 10050


@pytest.mark.parametrize("num_messages", [1000, 5000, 10000, 50000])
def test_read_conversation_scaling(benchmark, temp_db, num_messages):
    path = temp_db
    alice = "a" * 64
    bob   = "b" * 64
    with get_db_cursor(path) as cursor:
        create_test_wallets(cursor, 2)
        for i in range(num_messages):
            sender = alice if i % 2 == 0 else bob
            recipient = bob if sender == alice else alice
            cursor.execute(
                "INSERT INTO transactions (sender, recipient, content, timestamp) VALUES (?, ?, ?, ?)",
                (sender, recipient, f"Msg {i}", time.time() + i)
            )
    def read_conversation():
        with get_db_cursor(path) as cursor:
            cursor.execute("""
                SELECT id, sender, recipient, content, timestamp
                FROM (
                    SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                    UNION ALL
                    SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                )
                ORDER BY timestamp DESC
                LIMIT 50
            """, (alice, bob, bob, alice))
            return len(cursor.fetchall())
    result = benchmark(read_conversation)
    assert result == 50


def test_mixed_load_benchmark(benchmark, temp_db):
    path = temp_db
    alice = "d" * 64
    bob   = "e" * 64
    with get_db_cursor(path) as cursor:
        create_test_wallets(cursor, 2)
        create_test_contacts(cursor, alice, [bob])
        for i in range(5000):
            cursor.execute(
                "INSERT INTO transactions (sender, recipient, content, timestamp) VALUES (?, ?, ?, ?)",
                (alice if i%2==0 else bob, bob if i%2==0 else alice, f"Old {i}", time.time() - 1000 + i)
            )
    def mixed_operation():
        with get_db_cursor(path) as cursor:
            cursor.execute(
                "INSERT INTO transactions (sender, recipient, content, timestamp) VALUES (?, ?, ?, ?)",
                (alice, bob, "New message", time.time())
            )
            # Используем UNION ALL для скорости
            cursor.execute("""
                SELECT id, sender, content FROM (
                    SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                    UNION ALL
                    SELECT * FROM transactions WHERE sender = ? AND recipient = ?
                )
                ORDER BY timestamp DESC LIMIT 30
            """, (alice, bob, bob, alice))
            rows = cursor.fetchall()
            cursor.execute("UPDATE wallets SET balance = balance - 10 WHERE address = ?", (alice,))
            cursor.execute("UPDATE wallets SET balance = balance + 10 WHERE address = ?", (bob,))
            cursor.execute("SELECT contact_name FROM contacts WHERE user_address = ?", (alice,))
            contacts = cursor.fetchall()
            return len(rows) + len(contacts)
    total = benchmark(mixed_operation)
    assert total > 0


def test_connection_pool_no_leak(temp_db):
    path = temp_db
    from database import _connection_pool
    initial_size = _connection_pool._pool.qsize()
    for _ in range(100):
        with get_db_cursor(path) as cursor:
            cursor.execute("SELECT 1")
    final_size = _connection_pool._pool.qsize()
    assert final_size == initial_size