# crypto_manager.py
# Оптимизированный модуль шифрования с кэшированием ключей

import hashlib
import base64
import os
import logging
from functools import lru_cache
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from typing import Optional

# === Конфигурация ===
CACHE_SIZE = 128  # Размер кэша для ключей


# === Кэшированная генерация ключа ===
@lru_cache(maxsize=CACHE_SIZE)
def _generate_key_hashed(combined: str) -> bytes:
    """Внутренняя функция для кэширования хэша ключа."""
    return hashlib.sha256(combined.encode()).digest()[:32]


def generate_key(sender: str, recipient: str) -> bytes:
    """
    Генерирует общий ключ шифрования на основе адресов отправителя и получателя.
    Использует LRU-кэш для ускорения повторных вызовов.
    """
    # Сортируем адреса для симметричности: key(A,B) == key(B,A)
    combined = ''.join(sorted([sender.strip(), recipient.strip()]))
    return _generate_key_hashed(combined)


def generate_address(mnemonic: str) -> str:
    """Генерирует адрес кошелька из мнемонической фразы (SHA256)."""
    if not mnemonic:
        raise ValueError("Mnemonic phrase cannot be empty")
    return hashlib.sha256(mnemonic.encode('utf-8')).hexdigest()


def encrypt_message(key: bytes, plaintext: str) -> str:
    """
    Шифрует сообщение алгоритмом AES-256-CBC.

    Args:
        key: 32-байтный ключ шифрования
        plaintext: Исходный текст сообщения

    Returns:
        Base64-строка с зашифрованными данными (IV + ciphertext)
    """
    if not plaintext:
        return ""

    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError(f"Invalid key: expected 32 bytes, got {type(key)}")

    try:
        # Генерируем случайный IV для каждого сообщения
        iv = os.urandom(16)

        # Создаём шифр
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()

        # Дополняем данные до кратности 16 байт (PKCS7)
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(plaintext.encode('utf-8')) + padder.finalize()

        # Шифруем
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()

        # Возвращаем IV + ciphertext в base64
        return base64.b64encode(iv + ciphertext).decode('ascii')

    except Exception as e:
        logging.error(f"Encryption error: {e}")
        raise


def decrypt_message(key: bytes, encrypted_data: Optional[str]) -> Optional[str]:
    """
    Расшифровывает сообщение алгоритмом AES-256-CBC.

    Args:
        key: 32-байтный ключ шифрования
        encrypted_data: Base64-строка с зашифрованными данными

    Returns:
        Расшифрованный текст или None при ошибке
    """
    if not encrypted_data:
        return None

    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError(f"Invalid key: expected 32 bytes, got {type(key)}")

    try:
        # Декодируем base64
        data = base64.b64decode(encrypted_data)

        if len(data) < 16:
            raise ValueError("Encrypted data too short")

        # Извлекаем IV и ciphertext
        iv, ciphertext = data[:16], data[16:]

        # Создаём шифр для расшифровки
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()

        # Расшифровываем
        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

        # Убираем паддинг
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

        return plaintext.decode('utf-8')

    except Exception as e:
        logging.warning(f"Decryption failed: {e}")
        return None


def clear_key_cache():
    """Очищает кэш сгенерированных ключей (вызывать при выходе из системы)."""
    _generate_key_hashed.cache_clear()


def get_cache_info() -> dict:
    """Возвращает статистику кэша ключей (для отладки)."""
    cache = _generate_key_hashed.cache_info()
    return {
        'hits': cache.hits,
        'misses': cache.misses,
        'size': cache.currsize,
        'maxsize': cache.maxsize,
        'hit_rate': cache.hits / (cache.hits + cache.misses) * 100 if (cache.hits + cache.misses) > 0 else 0
    }