#!/usr/bin/env python3
"""
migrate_sqlite_to_postgres.py

Перенос данных из SQLite (blockchain.db) в PostgreSQL.
Запускать перед переключением приложения на PostgreSQL.
"""

import asyncio
import sqlite3
import asyncpg
import json
import os
from datetime import datetime

# Конфигурация
SQLITE_DB_PATH = "data/blockchain.db"          # путь к вашей SQLite базе
POSTGRES_DSN = "postgresql://bichat_user:strong_password@localhost/bichat"  # замените на свои данные

# Список таблиц для переноса (порядок важен из-за внешних ключей, но мы отключаем проверки)
TABLES = [
    "schema_version",
    "blockchain",
    "transactions",
    "contacts",
    "groups",
    "pubkey_cache",
    "read_status",
    "wallets",
    "coin_transactions",
    "stakes",
    "staking_state",
    "user_status",
    "transactions_archive",
    "archive_log"
]

async def migrate():
    print("=== Migration from SQLite to PostgreSQL ===")
    print(f"SQLite: {SQLITE_DB_PATH}")
    print(f"PostgreSQL DSN: {POSTGRES_DSN}")

    # Подключение к SQLite
    sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    # Подключение к PostgreSQL
    pg_conn = await asyncpg.connect(POSTGRES_DSN)

    try:
        # Отключаем проверки внешних ключей на время миграции
        await pg_conn.execute("SET session_replication_role = 'replica';")

        for table in TABLES:
            # Проверяем, существует ли таблица в SQLite
            sqlite_cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not sqlite_cursor.fetchone():
                print(f"⚠️ Table '{table}' does not exist in SQLite, skipping.")
                continue

            # Получаем данные из SQLite
            sqlite_cursor.execute(f"SELECT * FROM {table}")
            rows = sqlite_cursor.fetchall()
            if not rows:
                print(f"ℹ️ Table '{table}' is empty, skipping.")
                continue

            # Получаем имена колонок
            col_names = [desc[0] for desc in sqlite_cursor.description]
            # Преобразуем JSON-строки (если колонка содержит JSON) – для простоты оставляем как текст,
            # PostgreSQL принимает текст, позже можно будет привести к JSONB.
            # Также конвертируем типы REAL -> double precision, INTEGER -> bigint и т.д. – asyncpg сам справится.

            # Вставляем данные порциями (batch insert)
            batch_size = 500
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i+batch_size]
                # Формируем запрос
                placeholders = ','.join([f'${j+1}' for j in range(len(col_names))])
                stmt = f'INSERT INTO {table} ({",".join(col_names)}) VALUES ({placeholders})'
                for row in batch:
                    # Преобразуем row в список значений, заменяя None на None
                    values = [row[col] for col in col_names]
                    # Для колонок, которые могут содержать JSON (например, members в groups), оставляем как строку
                    # asyncpg примет строку.
                    await pg_conn.execute(stmt, *values)
            print(f"✅ Migrated {len(rows)} rows to '{table}'")

        # Восстанавливаем проверки внешних ключей
        await pg_conn.execute("SET session_replication_role = 'origin';")

        # Обновляем последовательности (serial / bigserial)
        print("Updating sequences...")
        await pg_conn.execute("""
            SELECT setval(pg_get_serial_sequence('blockchain', 'block_index'), coalesce(max(block_index), 1))
            FROM blockchain;
        """)
        await pg_conn.execute("""
            SELECT setval(pg_get_serial_sequence('transactions', 'id'), coalesce(max(id), 1))
            FROM transactions;
        """)
        await pg_conn.execute("""
            SELECT setval(pg_get_serial_sequence('contacts', 'id'), coalesce(max(id), 1))
            FROM contacts;
        """)
        await pg_conn.execute("""
            SELECT setval(pg_get_serial_sequence('coin_transactions', 'id'), coalesce(max(id), 1))
            FROM coin_transactions;
        """)
        await pg_conn.execute("""
            SELECT setval(pg_get_serial_sequence('stakes', 'id'), coalesce(max(id), 1))
            FROM stakes;
        """)
        await pg_conn.execute("""
            SELECT setval(pg_get_serial_sequence('archive_log', 'id'), coalesce(max(id), 1))
            FROM archive_log;
        """)
        print("✅ Sequences updated.")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise
    finally:
        sqlite_conn.close()
        await pg_conn.close()
        print("=== Migration finished ===")

if __name__ == "__main__":
    # Проверка существования SQLite файла
    if not os.path.exists(SQLITE_DB_PATH):
        print(f"❌ SQLite database not found at {SQLITE_DB_PATH}")
        exit(1)

    # Убедимся, что таблицы в PostgreSQL уже созданы (они будут созданы при запуске приложения с новым database.py)
    print("Make sure PostgreSQL tables are created (run the app once with new database.py or manually).")
    input("Press Enter to continue or Ctrl+C to abort...")

    asyncio.run(migrate())