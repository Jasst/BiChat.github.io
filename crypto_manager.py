import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
import os
import base64
import logging


def encrypt_message(key: bytes, message: str) -> str:
    if not message:
        return ""
    try:
        backend = default_backend()
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
        encryptor = cipher.encryptor()

        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        padded_data = padder.update(message.encode('utf-8')) + padder.finalize()

        encrypted = encryptor.update(padded_data) + encryptor.finalize()
        return base64.b64encode(iv + encrypted).decode()
    except Exception as e:
        logging.error(f"Encryption error: {e}")
        raise


def decrypt_message(key: bytes, encrypted_message: str) -> str:
    if not encrypted_message:
        return ""
    try:
        backend = default_backend()
        raw_data = base64.b64decode(encrypted_message.encode())
        iv = raw_data[:16]
        ciphertext = raw_data[16:]

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
        decryptor = cipher.decryptor()

        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

        return plaintext.decode('utf-8')
    except Exception as e:
        logging.warning(f"Decryption error: {e}")
        return "[Decryption Failed]"


def generate_key(sender: str, recipient: str) -> bytes:
    shared_secret = ''.join(sorted([sender, recipient]))
    return hashlib.sha256(shared_secret.encode()).digest()


def generate_address(phrase: str) -> str:
    return hashlib.sha256(phrase.encode()).hexdigest()