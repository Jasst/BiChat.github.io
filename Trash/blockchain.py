import sqlite3
import time
import hashlib
import json
import logging

DATABASE_PATH = 'blockchain.db'

class Blockchain:
    """Класс для работы с блокчейном."""

    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.initialize_blockchain()
        logging.info("Blockchain initialized")

    def initialize_blockchain(self) -> None:
        """Инициализирует блокчейн, создает таблицы и генезис-блок."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            self.create_table(cursor)
            self.create_transaction_table(cursor)

            # ИСПРАВЛЕНО: Создаем таблицы контактов и групп ДО создания индексов
            create_contacts_table(self.db_path)  # <-- Передаем db_path
            create_group_table(self.db_path)  # <-- Передаем db_path

            # ИСПРАВЛЕНО: Теперь таблицы существуют, можно создавать индексы
            # Добавляем индексы для производительности
            self.create_indexes(cursor)

            if not self.get_chain(cursor):
                self.new_block(cursor, previous_hash='1', proof=100)
                logging.info("Genesis block created")

    def create_table(self, cursor: sqlite3.Cursor) -> None:
        """Создает таблицу блокчейна."""
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blockchain (
                block_index INTEGER PRIMARY KEY,
                timestamp REAL,
                transactions TEXT,
                proof INTEGER,
                previous_hash TEXT
            )
        ''')

    def create_transaction_table(self, cursor: sqlite3.Cursor) -> None:
        """Создает таблицу транзакций."""
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                content TEXT,
                image TEXT,
                timestamp REAL
            )
        ''')

    def create_indexes(self, cursor: sqlite3.Cursor) -> None:
        """Создает индексы для ускорения запросов."""
        # Удаляем старые индексы, если они существуют (на случай конфликта имен/определений)
        cursor.execute('DROP INDEX IF EXISTS idx_transactions_sender_recipient')
        cursor.execute('DROP INDEX IF EXISTS idx_transactions_recipient_group')
        cursor.execute('DROP INDEX IF EXISTS idx_transactions_timestamp')
        # Индексы для таблицы transactions
        cursor.execute('CREATE INDEX idx_transactions_sender_recipient ON transactions(sender, recipient)')
        cursor.execute('CREATE INDEX idx_transactions_recipient_group ON transactions(recipient)')
        cursor.execute('CREATE INDEX idx_transactions_timestamp ON transactions(timestamp)')
        # Индекс для таблицы contacts создается в create_contacts_table

    def new_block(self, cursor: sqlite3.Cursor, proof: int, previous_hash: Optional[str] = None) -> None:
        """Создает новый блок."""
        block_index = self.last_block(cursor).get('index', 0) + 1
        previous_block = self.last_block(cursor)
        block = {
            'index': block_index,
            'timestamp': time.time(),
            'transactions': [],  # Transactions will be stored in DB
            'proof': proof,
            'previous_hash': previous_hash or self.hash_block(previous_block),
        }
        cursor.execute('''
            INSERT INTO blockchain (block_index, timestamp, transactions, proof, previous_hash)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            block['index'],
            block['timestamp'],
            json.dumps(block['transactions']),
            block['proof'],
            block['previous_hash']
        ))
        logging.info(f"New block added: {block['index']}")

    def hash_block(self, block: Dict[str, Any]) -> str:
        """Хэширует блок."""
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def last_block(self, cursor: sqlite3.Cursor) -> Dict[str, Any]:
        """Возвращает последний блок."""
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index DESC LIMIT 1')
        row = cursor.fetchone()
        if row:
            return {
                'index': row[0],
                'timestamp': row[1],
                'transactions': json.loads(row[2]),
                'proof': row[3],
                'previous_hash': row[4],
            }
        return {}

    def get_chain(self, cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
        """Возвращает всю цепочку блоков."""
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index ASC')
        rows = cursor.fetchall()
        return [{
            'index': row[0],
            'timestamp': row[1],
            'transactions': json.loads(row[2]),
            'proof': row[3],
            'previous_hash': row[4],
        } for row in rows]

    def new_transaction(self, cursor: sqlite3.Cursor, sender: str, recipient: str, content: str,
                        image: Optional[str]) -> int:
        """Создает новую транзакцию."""
        transaction = {
            'sender': sender,
            'recipient': recipient,
            'content': content,
            'image': image,
            'timestamp': time.time(),
        }
        cursor.execute('''
            INSERT INTO transactions (sender, recipient, content, image, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            transaction['sender'],
            transaction['recipient'],
            transaction['content'],
            transaction['image'],
            transaction['timestamp']
        ))
        tx_id = cursor.lastrowid
        logging.info(f"Transaction added from {sender} to {recipient}, ID: {tx_id}")
        return tx_id  # Возвращаем ID транзакции

    def get_messages(self, cursor: sqlite3.Cursor, address: str) -> List[Dict[str, Any]]:
        """Получает сообщения для конкретного адреса."""
        cursor.execute('''
            SELECT id, sender, recipient, content, image, timestamp
            FROM transactions
            WHERE sender = ? OR recipient = ? OR recipient LIKE 'group:%'
            ORDER BY timestamp ASC
        ''', (address, address))
        rows = cursor.fetchall()
        return [{
            'id': row[0],
            'sender': row[1],
            'recipient': row[2],
            'content': row[3],
            'image': row[4],
            'timestamp': row[5],
        } for row in rows]

    def proof_of_work(self, last_proof: int) -> int:
        """Алгоритм доказательства работы."""
        proof = 0
        while not self.valid_proof(last_proof, proof):
            proof += 1
        logging.debug(f"Proof of work found: {proof}")
        return proof

    @staticmethod
    def valid_proof(last_proof: int, proof: int) -> bool:
        """Проверяет правильность доказательства работы."""
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"