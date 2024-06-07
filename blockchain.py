import hashlib
import json
import os
import time
import threading
from cryptography.fernet import Fernet
from mnemonic import Mnemonic


class Blockchain:
    def __init__(self):
        self.chain = []
        self.current_transactions = []
        self.lock = threading.Lock()
        self.data_file = 'blockchain.json'
        self.load_chain()
        if len(self.chain) == 0:
            self.new_block(previous_hash='1', proof=100)

    def new_block(self, proof, previous_hash=None):
        with self.lock:
            block = {
                'index': len(self.chain) + 1,
                'timestamp': time.time(),
                'transactions': self.current_transactions,
                'proof': proof,
                'previous_hash': previous_hash or self.hash(self.chain[-1]),
            }
            self.current_transactions = []
            self.chain.append(block)
            self.save_chain()
        return block

    def new_transaction(self, sender, recipient, content):
        with self.lock:
            self.current_transactions.append({
                'sender': sender,
                'recipient': recipient,
                'content': content,
                'timestamp': time.time(),
            })
        return self.last_block['index'] + 1

    @property
    def last_block(self):
        with self.lock:
            return self.chain[-1]

    @staticmethod
    def hash(block):
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def proof_of_work(self, last_proof):
        proof = 0
        while self.valid_proof(last_proof, proof) is False:
            proof += 1
        return proof

    @staticmethod
    def valid_proof(last_proof, proof):
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"

    def get_messages(self, key_hex):
        messages = []
        with self.lock:
            for block in self.chain:
                for transaction in block['transactions']:
                    if transaction['sender'] == key_hex or transaction['recipient'] == key_hex:
                        messages.append(transaction)
        return messages

    def save_chain(self):
        with open('blockchain.json', 'w') as f:
            json.dump(self.chain, f, indent=4)

    def load_chain(self):
        if os.path.exists('blockchain.json'):
            with open('blockchain.json', 'r') as f:
                self.chain = json.load(f)


class CryptoManager:
    def __init__(self, key):
        self.key = key

    def encrypt_message(self, message):
        cipher = Fernet(self.key)
        encrypted_message = cipher.encrypt(message.encode())
        return encrypted_message

    def decrypt_message(self, encrypted_message):
        cipher = Fernet(self.key)
        decrypted_message = cipher.decrypt(encrypted_message).decode()
        return decrypted_message


mnemonic = Mnemonic('english')
blockchain = Blockchain()
blockchain.load_chain()

# Остальной код вашего приложения, включая Flask-маршруты, HTML-шаблоны и JavaScript-код, остается без изменений
