# crypto_manager.py
# Оптимизированный модуль шифрования с кэшированием ключей
# Версия: 2.2 (Безопасная деривация через HKDF + мнемонику)

import hashlib
import base64
import os
import logging
from functools import lru_cache
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from typing import Optional

# === Конфигурация ===
CACHE_SIZE = 128  # Размер кэша для ключей

# === Кэшированная генерация ключа ===
@lru_cache(maxsize=CACHE_SIZE)
def _generate_key_secure(combined: str, mnemonic: str) -> bytes:
    """
    Внутренняя функция с кэшированием.
    Использует HKDF для криптографически стойкой деривации ключа.
    Без мнемоники ключ невозможно воспроизвести.
    """
    # Преобразуем мнемонику в начальное зерно
    seed = hashlib.sha256(mnemonic.encode('utf-8')).digest()
    
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'messenger-v2-secure-salt',
        info=combined.encode('utf-8'),  # Уникальный info для пары адресов
        backend=default_backend()
    )
    return kdf.derive(seed)

def generate_key(sender: str, recipient: str, mnemonic_phrase: str) -> bytes:
    """
    Генерирует общий ключ шифрования на основе адресов И мнемонической фразы.
    ⚠️ Обязательно передавайте session['mnemonic'] из app.py!
    """
    if not mnemonic_phrase or not isinstance(mnemonic_phrase, str):
        raise ValueError("mnemonic_phrase is required for secure key generation")
        
    # Сортируем адреса для симметричности: key(A,B) == key(B,A)
    combined = ''.join(sorted([sender.strip(), recipient.strip()]))
    return _generate_key_secure(combined, mnemonic_phrase)

def generate_address(mnemonic: str) -> str:
    """Генерирует адрес кошелька из мнемонической фразы (SHA256)."""
    if not mnemonic:
        raise ValueError("Mnemonic phrase cannot be empty")
    return hashlib.sha256(mnemonic.encode('utf-8')).hexdigest()

def encrypt_message(key: bytes, plaintext: str) -> str:
    """
    Шифрует сообщение алгоритмом AES-256-CBC.
    Сохранён формат IV + ciphertext для обратной совместимости с существующей БД.
    """
    if not plaintext:
        return ""

    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError(f"Invalid key: expected 32 bytes, got {type(key)}")

    try:
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()

        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(plaintext.encode('utf-8')) + padder.finalize()

        ciphertext = encryptor.update(padded_data) + encryptor.finalize()
        return base64.b64encode(iv + ciphertext).decode('ascii')

    except Exception as e:
        logging.error(f"Encryption error: {e}")
        raise

def decrypt_message(key: bytes, encrypted_data: Optional[str]) -> Optional[str]:
    """
    Расшифровывает сообщение алгоритмом AES-256-CBC.
    Возвращает None при ошибке или неверном ключе.
    """
    if not encrypted_data:
        return None

    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError(f"Invalid key: expected 32 bytes, got {type(key)}")

    try:
        data = base64.b64decode(encrypted_data)
        if len(data) < 16:
            raise ValueError("Encrypted data too short")

        iv, ciphertext = data[:16], data[16:]

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()

        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

        return plaintext.decode('utf-8')

    except Exception as e:
        logging.warning(f"Decryption failed: {e}")
        return None

def clear_key_cache():
    """Очищает кэш сгенерированных ключей (вызывать при выходе из системы)."""
    _generate_key_secure.cache_clear()

def get_cache_info() -> dict:
    """Возвращает статистику кэша ключей (для отладки)."""
    cache = _generate_key_secure.cache_info()
    return {
        'hits': cache.hits,
        'misses': cache.misses,
        'size': cache.currsize,
        'maxsize': cache.maxsize,
        'hit_rate': cache.hits / (cache.hits + cache.misses) * 100 if (cache.hits + cache.misses) > 0 else 0
    }

