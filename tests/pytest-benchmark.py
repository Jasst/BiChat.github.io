# tests/load_test.py
import time
import sqlite3
from database import get_db_cursor, init_connection_pool
import tempfile
import os

def create_test_db(num_messages=50000):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_connection_pool(path, max_connections=5)
    # создаём таблицы и индексы (имитируем реальную БД)
    # ... (код инициализации схемы)
    with get_db_cursor(path) as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
        # вставляем сообщения
        for i in range(num_messages):
            cursor.execute("INSERT INTO transactions (sender, recipient, content, timestamp) VALUES (?,?,?,?)",
                           ("a"*64, "b"*64, "test", time.time()+i))
    return path

def run_query(path):
    with get_db_cursor(path) as cursor:
        start = time.perf_counter()
        cursor.execute("""
            SELECT * FROM transactions
            WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)
            ORDER BY timestamp DESC LIMIT 50
        """, ("a"*64, "b"*64, "b"*64, "a"*64))
        rows = cursor.fetchall()
        elapsed = time.perf_counter() - start
        return elapsed

if __name__ == "__main__":
    for size in [1000, 5000, 10000, 50000, 100000]:
        path = create_test_db(size)
        elapsed = run_query(path)
        print(f"{size} messages: {elapsed*1000:.2f} ms")
        os.unlink(path)