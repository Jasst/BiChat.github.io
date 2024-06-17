import sqlite3

# Путь к файлу базы данных SQLite
db_path = "blockchain.db"  # Замените на путь к вашей базе данных SQLite

# Функция для открытия соединения с базой данных
def open_database():
    try:
        conn = sqlite3.connect(db_path)
        return conn
    except sqlite3.Error as e:
        print(f"Error connecting to SQLite database: {e}")
        return None

# Пример использования функции для открытия базы данных
conn = open_database()

if conn:
    print("Database connection successful!")

    # Создание курсора для выполнения SQL-запросов
    cursor = conn.cursor()

    try:
        # Выполнение SQL-запроса для выборки данных из столбца content
        cursor.execute("SELECT content FROM transactions")
        rows = cursor.fetchall()

        # Вывод данных из столбца content
        for row in rows:
            content = row[0]  # Предполагается, что content находится в первом столбце
            print(f"Content: {content}")

    except sqlite3.Error as e:
        print(f"Error executing SQL query: {e}")

    # Важно закрыть соединение после использования
    conn.close()
else:
    print("Failed to connect to the database.")
