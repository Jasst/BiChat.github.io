import hashlib
import json
from time import time

class blockchain:
    def __init__(self):
        self.chain = []
        self.current_messages = []
        self.create_block(previous_hash='1', proof=100)

    def create_block(self, proof, previous_hash):
        block = {
            'index': len(self.chain) + 1,
            'timestamp': time(),
            'messages': self.current_messages,
            'proof': proof,
            'previous_hash': previous_hash,
        }
        self.current_messages = []
        self.chain.append(block)
        return block

    def get_previous_block(self):
        return self.chain[-1]

    def proof_of_work(self, previous_proof):
        new_proof = 1
        check_proof = False
        while not check_proof:
            hash_operation = hashlib.sha256(str(new_proof**2 - previous_proof**2).encode()).hexdigest()
            if hash_operation[:4] == '0000':
                check_proof = True
            else:
                new_proof += 1
        return new_proof

    def hash(self, block):
        encoded_block = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(encoded_block).hexdigest()

    def is_chain_valid(self, chain):
        previous_block = chain[0]
        block_index = 1
        while block_index < len(chain):
            block = chain[block_index]
            if block['previous_hash'] != self.hash(previous_block):
                return False
            previous_proof = previous_block['proof']
            proof = block['proof']
            hash_operation = hashlib.sha256(str(proof**2 - previous_proof**2).encode()).hexdigest()
            if hash_operation[:4] != '0000':
                return False
            previous_block = block
            block_index += 1
        return True

    def create_wallet(self):
        # Реализуйте логику создания кошелька
        return {
            'mnemonic_phrase': 'example mnemonic phrase',
            'address': 'example_address'
        }

    def send_message(self, mnemonic, recipient, content):
        # Реализуйте логику отправки сообщения
        message = {
            'sender': 'example_address',
            'recipient': recipient,
            'content': content
        }
        self.current_messages.append(message)
        return message

    def get_messages(self, mnemonic):
        # Реализуйте логику получения сообщений
        return self.current_messages
