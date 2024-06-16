import hashlib
import json
import os
import time
import base64
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

    def new_transaction(self, sender, recipient, content, image):
        self.current_transactions.append({
            'sender': sender,
            'recipient': recipient,
            'content': content,
            'image': image,
            'timestamp': time.time(),
        })
        self.save_chain()
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

    def get_messages(self, address):
        messages = []
        for block in self.chain:
            for transaction in block['transactions']:
                if transaction['sender'] == address or transaction['recipient'] == address:
                    messages.append(transaction)
        return messages

    def save_chain(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.chain, f, indent=4, default=str)

    def load_chain(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        self.chain = json.loads(content)
                    else:
                        self.chain = []
            except json.JSONDecodeError as e:
                print(f"Ошибка загрузки JSON: {e}")
                self.chain = []
        else:
            self.chain = []


class CryptoManager:
    def __init__(self, key):
        self.key = key
        self.cipher = Fernet(key)

    def encrypt_message(self, message):
        if message is None:
            return None
        encrypted_message = self.cipher.encrypt(message.encode())
        return base64.b64encode(encrypted_message).decode()

    def decrypt_message(self, encrypted_message):
        if encrypted_message is None:
            return None
        decoded_encrypted_message = base64.b64decode(encrypted_message.encode())
        decrypted_message = self.cipher.decrypt(decoded_encrypted_message)
        return decrypted_message.decode()


mnemonic = Mnemonic('english')
blockchain = Blockchain()
blockchain.load_chain()
