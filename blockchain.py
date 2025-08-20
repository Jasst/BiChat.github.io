import sqlite3
import time
import hashlib
import json
import logging


class Blockchain:
    def __init__(self, db_path='blockchain.db'):
        self.db_path = db_path
        self.initialize_blockchain()
        logging.info("Blockchain initialized")

    def initialize_blockchain(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            self.create_table(cursor)
            self.create_transaction_table(cursor)
            if not self.get_chain(cursor):
                self.new_block(cursor, previous_hash='1', proof=100)
                logging.info("Genesis block created")

    def create_table(self, cursor):
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blockchain (
                block_index INTEGER PRIMARY KEY,
                timestamp REAL,
                transactions TEXT,
                proof INTEGER,
                previous_hash TEXT
            )
        ''')

    def create_transaction_table(self, cursor):
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                content TEXT,
                image TEXT,
                timestamp REAL
            )
        ''')

    def new_block(self, cursor, proof, previous_hash=None):
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

    def hash_block(self, block):
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def last_block(self, cursor):
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

    def get_chain(self, cursor):
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index ASC')
        rows = cursor.fetchall()
        return [{
            'index': row[0],
            'timestamp': row[1],
            'transactions': json.loads(row[2]),
            'proof': row[3],
            'previous_hash': row[4],
        } for row in rows]

    def new_transaction(self, cursor, sender, recipient, content, image):
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
        logging.info(f"Transaction added from {sender} to {recipient}")
        return self.last_block(cursor).get('index', 0) + 1

    def get_messages(self, cursor, address):
        cursor.execute('''
            SELECT sender, recipient, content, image, timestamp
            FROM transactions
            WHERE sender = ? OR recipient = ? OR recipient LIKE 'group:%'
            ORDER BY timestamp ASC
        ''', (address, address))
        rows = cursor.fetchall()
        return [{
            'sender': row[0],
            'recipient': row[1],
            'content': row[2],
            'image': row[3],
            'timestamp': row[4],
        } for row in rows]

    def proof_of_work(self, last_proof):
        proof = 0
        while not self.valid_proof(last_proof, proof):
            proof += 1
        logging.debug(f"Proof of work found: {proof}")
        return proof

    @staticmethod
    def valid_proof(last_proof, proof):
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"