from cryptography.fernet import Fernet
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
import os
import base64


class CryptoManager:
    def __init__(self, key):
        self.key = key
        self.cipher = Fernet(self.key)

    def encrypt_message(self, message):
        if message is None:
            return None
        try:
            encrypted_message = self.cipher.encrypt(message.encode())
            return base64.urlsafe_b64encode(encrypted_message).decode()
        except Exception as e:
            raise ValueError(f'Encryption failed: {str(e)}')

    def decrypt_message(self, encrypted_message):
        if encrypted_message is None:
            return None
        try:
            decoded_encrypted_message = base64.urlsafe_b64decode(encrypted_message.encode())
            decrypted_message = self.cipher.decrypt(decoded_encrypted_message)
            return decrypted_message.decode()
        except Exception as e:
            raise ValueError(f'Decryption failed: {str(e)}')


def encrypt_message(key, message):
    backend = default_backend()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
    encryptor = cipher.encryptor()
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_message = padder.update(message.encode()) + padder.finalize()
    encrypted_message = encryptor.update(padded_message) + encryptor.finalize()
    return base64.b64encode(iv + encrypted_message).decode()


def decrypt_message(key, encrypted_message):
    if encrypted_message is None:
        return None

    backend = default_backend()
    encrypted_message = base64.b64decode(encrypted_message)
    iv = encrypted_message[:16]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
    decryptor = cipher.decryptor()
    decrypted_padded_message = decryptor.update(encrypted_message[16:]) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    decrypted_message = unpadder.update(decrypted_padded_message) + unpadder.finalize()
    return decrypted_message.decode()


def generate_key(sender, recipient):
    shared_secret = ''.join(sorted([sender, recipient]))
    return hashlib.sha256(shared_secret.encode()).digest()


def generate_address(phrase):
    return hashlib.sha256(phrase.encode()).hexdigest()
