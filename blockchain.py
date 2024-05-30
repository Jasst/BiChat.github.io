import hashlib
import time
from mnemonic import Mnemonic
from cryptography.fernet import Fernet

mnemonic = Mnemonic('english')
cipher_suite = Fernet(Fernet.generate_key())

class Blockchain:
    def __init__(self):
        self.chain = []
        self.current_transactions = []
        self.new_block(previous_hash='1', proof=100)  # Создаем блок genesis

    def new_block(self, proof, previous_hash=None):
        block = {
            'index': len(self.chain) + 1,
            'timestamp': time.time(),  # Текущее время
            'transactions': self.current_transactions,
            'proof': proof,
            'previous_hash': previous_hash or self.hash(self.chain[-1]),
        }
        self.current_transactions = []
        self.chain.append(block)
        return block

    def new_transaction(self, sender, recipient, content):
        self.current_transactions.append({
            'sender': sender,
            'recipient': recipient,
            'content': content,
            'timestamp': time.time(),  # Текущее время
        })
        return self.last_block['index'] + 1

    @property
    def last_block(self):
        return self.chain[-1]

    @staticmethod
    def hash(block):
        block_string = f"{block['index']}{block['timestamp']}{block['transactions']}{block['proof']}{block['previous_hash']}"
        return hashlib.sha256(block_string.encode()).hexdigest()

    def generate_address(self, phrase):
        return hashlib.sha256(phrase.encode()).hexdigest()

    def generate_key_from_phrase(self, phrase):
        return hashlib.sha256(phrase.encode()).digest()

    def get_messages(self, key_hex):
        messages = []
        for block in self.chain:
            for transaction in block['transactions']:
                if transaction['sender'] == key_hex or transaction['recipient'] == key_hex:
                    messages.append(transaction)
        return messages
