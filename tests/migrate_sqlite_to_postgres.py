#!/usr/bin/env python3
"""
migrate_sqlite_to_postgres.py — исправленная версия с повторными попытками подключения
"""
import asyncio
import sqlite3
import asyncpg
import os

SQLITE_DB_PATH = "data/blockchain.db"
POSTGRES_DSN = "postgresql://postgres:zXCV123zXCV@localhost:5432/bichat_db"

TABLES = [
    "blockchain", "transactions", "contacts", "groups", "pubkey_cache",
    "read_status", "wallets", "coin_transactions", "stakes", "staking_state",
    "user_status", "transactions_archive", "archive_log", "schema_version"
]

async def create_tables_if_not_exists(pg_conn):
    await pg_conn.execute("""
        CREATE TABLE IF NOT EXISTS blockchain (
            block_index BIGSERIAL PRIMARY KEY,
            timestamp DOUBLE PRECISION NOT NULL,
            transactions TEXT NOT NULL DEFAULT '[]',
            coin_transactions TEXT NOT NULL DEFAULT '[]',
            proof INTEGER NOT NULL,
            previous_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id BIGSERIAL PRIMARY KEY,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            content TEXT,
            image TEXT,
            timestamp DOUBLE PRECISION NOT NULL,
            sender_pubkey TEXT,
            metadata TEXT,
            status TEXT DEFAULT 'sent',
            read_at DOUBLE PRECISION,
            delivered_at DOUBLE PRECISION
        );
        CREATE TABLE IF NOT EXISTS contacts (
            id BIGSERIAL PRIMARY KEY,
            user_address TEXT NOT NULL,
            contact_address TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            contact_pubkey TEXT,
            created_at DOUBLE PRECISION,
            UNIQUE(user_address, contact_address)
        );
        CREATE TABLE IF NOT EXISTS groups (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            creator TEXT NOT NULL,
            members TEXT NOT NULL,
            created_at DOUBLE PRECISION
        );
        CREATE TABLE IF NOT EXISTS pubkey_cache (
            address TEXT PRIMARY KEY,
            public_key_b64 TEXT NOT NULL,
            updated_at DOUBLE PRECISION,
            source TEXT DEFAULT 'blockchain',
            verified INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS read_status (
            user_address TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            last_read_message_id BIGINT NOT NULL DEFAULT 0,
            read_at DOUBLE PRECISION,
            PRIMARY KEY (user_address, chat_id)
        );
        CREATE TABLE IF NOT EXISTS wallets (
            address TEXT PRIMARY KEY,
            balance BIGINT NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS coin_transactions (
            id BIGSERIAL PRIMARY KEY,
            tx_type TEXT NOT NULL,
            sender TEXT,
            recipient TEXT NOT NULL,
            amount BIGINT NOT NULL CHECK(amount > 0),
            timestamp DOUBLE PRECISION NOT NULL,
            block_ref BIGINT,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS stakes (
            id BIGSERIAL PRIMARY KEY,
            address TEXT NOT NULL,
            amount BIGINT NOT NULL,
            start_time DOUBLE PRECISION NOT NULL,
            start_block BIGINT NOT NULL,
            unlock_block BIGINT NOT NULL,
            active INTEGER DEFAULT 1,
            reward_debt BIGINT DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS staking_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_status (
            address TEXT PRIMARY KEY,
            last_seen DOUBLE PRECISION NOT NULL,
            status TEXT DEFAULT 'offline',
            current_chat TEXT
        );
        CREATE TABLE IF NOT EXISTS transactions_archive (
            id BIGINT PRIMARY KEY,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            content TEXT,
            image TEXT,
            timestamp DOUBLE PRECISION NOT NULL,
            sender_pubkey TEXT,
            metadata TEXT,
            status TEXT,
            read_at DOUBLE PRECISION,
            archived_at DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS archive_log (
            id BIGSERIAL PRIMARY KEY,
            archived_date TEXT NOT NULL,
            messages_count INTEGER,
            created_at DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at DOUBLE PRECISION
        );
    """)
    await pg_conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender)")
    await pg_conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_recipient ON transactions(recipient)")
    await pg_conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)")

async def connect_with_retry(dsn, retries=10, delay=2):
    for attempt in range(retries):
        try:
            print(f"Попытка {attempt+1}: подключение к PostgreSQL...")
            conn = await asyncpg.connect(dsn)
            print("✅ Подключение установлено")
            return conn
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            if attempt < retries - 1:
                print(f"Повтор через {delay} секунд...")
                await asyncio.sleep(delay)
            else:
                raise

async def migrate():
    print("=== Миграция из SQLite в PostgreSQL ===")
    print(f"SQLite: {SQLITE_DB_PATH}")
    print(f"PostgreSQL DSN: {POSTGRES_DSN}")

    if not os.path.exists(SQLITE_DB_PATH):
        print(f"❌ Файл SQLite не найден: {SQLITE_DB_PATH}")
        return

    sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    try:
        pg_conn = await connect_with_retry(POSTGRES_DSN)
    except Exception as e:
        print(f"❌ Не удалось подключиться к PostgreSQL: {e}")
        print("Проверьте, запущен ли сервер PostgreSQL и правильность пароля.")
        return

    try:
        await create_tables_if_not_exists(pg_conn)
        await pg_conn.execute("SET session_replication_role = 'replica';")
        for table in TABLES:
            await pg_conn.execute(f"TRUNCATE TABLE {table} CASCADE;")

        for table in TABLES:
            sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not sqlite_cursor.fetchone():
                print(f"⚠️ Таблица '{table}' отсутствует в SQLite, пропускаем.")
                continue
            sqlite_cursor.execute(f"SELECT * FROM {table}")
            rows = sqlite_cursor.fetchall()
            if not rows:
                print(f"ℹ️ Таблица '{table}' пуста, пропускаем.")
                continue
            col_names = [desc[0] for desc in sqlite_cursor.description]
            batch_size = 500
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i+batch_size]
                placeholders = ','.join(f'${j+1}' for j in range(len(col_names)))
                stmt = f'INSERT INTO {table} ({",".join(col_names)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
                for row in batch:
                    values = [row[col] for col in col_names]
                    await pg_conn.execute(stmt, *values)
            print(f"✅ Перенесено {len(rows)} записей в '{table}'")

        await pg_conn.execute("SET session_replication_role = 'origin';")
        print("Обновление последовательностей...")
        await pg_conn.execute("SELECT setval(pg_get_serial_sequence('blockchain', 'block_index'), coalesce(max(block_index), 1)) FROM blockchain;")
        await pg_conn.execute("SELECT setval(pg_get_serial_sequence('transactions', 'id'), coalesce(max(id), 1)) FROM transactions;")
        await pg_conn.execute("SELECT setval(pg_get_serial_sequence('contacts', 'id'), coalesce(max(id), 1)) FROM contacts;")
        await pg_conn.execute("SELECT setval(pg_get_serial_sequence('coin_transactions', 'id'), coalesce(max(id), 1)) FROM coin_transactions;")
        await pg_conn.execute("SELECT setval(pg_get_serial_sequence('stakes', 'id'), coalesce(max(id), 1)) FROM stakes;")
        await pg_conn.execute("SELECT setval(pg_get_serial_sequence('archive_log', 'id'), coalesce(max(id), 1)) FROM archive_log;")
        print("✅ Последовательности обновлены.")
    except Exception as e:
        print(f"❌ Миграция не удалась: {e}")
        raise
    finally:
        sqlite_conn.close()
        await pg_conn.close()
        print("=== Миграция завершена ===")

if __name__ == "__main__":
    asyncio.run(migrate())