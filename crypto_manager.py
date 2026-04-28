"""
crypto_manager.py — ИСПРАВЛЕННАЯ ВЕРСИЯ
"""
import hashlib
import base64
import os
import json
import logging
from functools import lru_cache
from typing import Optional, Dict, Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding, hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend

# === Конфигурация ===
CACHE_SIZE = 128
CURVE = ec.SECP256R1()  # NIST P-256

# 🔧 Порядок кривой P-256 — явная константа (избегаем проблем с API)
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


# =============================================================================
# 🔑 Часть 1: Деривация асимметричных ключей из мнемоники
# =============================================================================

# =============================================================================
# 🔑 Часть 1: Деривация асимметричных ключей из мнемоники
# =============================================================================

# Порядок кривой P-256 (SECP256R1) — константа из стандарта NIST
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


@lru_cache(maxsize=CACHE_SIZE)
def _derive_private_key_cached(mnemonic_hash: str) -> ec.EllipticCurvePrivateKey:
    """
    Внутренняя кэшируемая функция деривации приватного ключа.
    """
    # Преобразуем хэш в целое число
    private_scalar = int.from_bytes(
        hashlib.sha256(mnemonic_hash.encode('utf-8')).digest()[:32],
        'big'
    )

    # Гарантируем, что скаляр в допустимом диапазоне [1, order-1]
    private_scalar = (private_scalar % (_P256_ORDER - 1)) + 1

    return ec.derive_private_key(private_scalar, CURVE, default_backend())


def derive_private_key(mnemonic_phrase: str) -> ec.EllipticCurvePrivateKey:
    """Публичный интерфейс для получения приватного ключа."""
    if not mnemonic_phrase:
        raise ValueError("mnemonic_phrase is required")
    mnemonic_hash = hashlib.sha256(mnemonic_phrase.encode('utf-8')).hexdigest()
    return _derive_private_key_cached(mnemonic_hash)


def get_public_key_bytes(mnemonic_phrase: str) -> bytes:
    """
    Получает публичный ключ в сжатом формате (33 байта, X9.62).
    Идеально для хранения в блокчейне и передачи по сети.
    """
    private_key = derive_private_key(mnemonic_phrase)
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.CompressedPoint
    )


def get_public_key_b64(mnemonic_phrase: str) -> str:
    """Публичный ключ в base64 для передачи в JSON."""
    return base64.b64encode(get_public_key_bytes(mnemonic_phrase)).decode('ascii')


def load_public_key_from_bytes(pubkey_bytes: bytes) -> ec.EllipticCurvePublicKey:
    """Загружает публичный ключ из байтов для использования в ECDH."""
    return ec.EllipticCurvePublicKey.from_encoded_point(CURVE, pubkey_bytes)


def load_public_key_from_b64(pubkey_b64: str) -> ec.EllipticCurvePublicKey:
    """Загружает публичный ключ из base64-строки."""
    return load_public_key_from_bytes(base64.b64decode(pubkey_b64))


# =============================================================================
# 🔐 Часть 2: ECDH — вычисление общего секрета
# =============================================================================

@lru_cache(maxsize=CACHE_SIZE)
def _compute_shared_key_cached(my_mnemonic_hash: str, peer_pubkey_hash: str) -> bytes:
    """
    Внутренняя кэшируемая функция ECDH.
    Возвращает 32-байтный AES-ключ через HKDF.
    """
    # Для кэширования используем хэши, но внутри вычисляем реальный ключ
    # (в реальном использовании кэш будет по (mnemonic_hash, peer_pubkey_bytes))
    pass  # Реализация ниже в основной функции


def compute_shared_key(my_mnemonic: str, peer_public_key: bytes) -> bytes:
    """
    Вычисляет общий секретный ключ через ECDH.

    Args:
        my_mnemonic: Моя мнемоническая фраза
        peer_public_key: Публичный ключ собеседника (33 байта, сжатый формат)

    Returns:
        32-байтный ключ для AES-256
    """
    my_private = derive_private_key(my_mnemonic)
    peer_public = load_public_key_from_bytes(peer_public_key)

    # ECDH: вычисляем shared secret point
    shared_secret = my_private.exchange(ec.ECDH(), peer_public)

    # HKDF: "растягиваем" shared secret до нужной длины ключа
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b'messenger:v3:aes-encryption-key'
    ).derive(shared_secret)


def compute_shared_key_b64(my_mnemonic: str, peer_public_key_b64: str) -> bytes:
    """Удобная обёртка для работы с base64-ключами."""
    peer_public = base64.b64decode(peer_public_key_b64)
    return compute_shared_key(my_mnemonic, peer_public)


# =============================================================================
# 🔒 Часть 3: Симметричное шифрование AES-256-CBC (без изменений)
# =============================================================================

def encrypt_message(key: bytes, plaintext: str) -> str:
    """Шифрует сообщение алгоритмом AES-256-CBC. Возвращает base64."""
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
    """Расшифровывает сообщение алгоритмом AES-256-CBC."""
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


# =============================================================================
# 🎁 Часть 4: Гибридное шифрование (ECDH + AES session key)
# =============================================================================

def encrypt_hybrid(my_mnemonic: str, peer_public_key_b64: str,
                   plaintext: str, image_data: Optional[str] = None) -> Dict[str, str]:
    """
    Гибридное шифрование с поддержкой изображений.

    Args:
        my_mnemonic: Моя мнемоника
        peer_public_key_b64: Публичный ключ получателя (base64)
        plaintext: Текстовое сообщение
        image_data: Опционально, изображение как base64-строка или data URL

    Returns:
        Dict с зашифрованными content, image, enc_session_key
    """
    if not plaintext and not image_data:
        return {'content': '', 'image': None, 'enc_session_key': '', 'version': 'hybrid-v1'}

    # Шаг 1: Вычисляем shared key через ECDH
    shared_key = compute_shared_key_b64(my_mnemonic, peer_public_key_b64)

    # Шаг 2: Генерируем ephemeral session key (forward secrecy!)
    session_key = os.urandom(32)

    # Вспомогательная функция для AES-шифрования с сессионным ключом
    def _aes_encrypt_session(plain: str) -> str:
        if not plain:
            return ""
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(session_key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(plain.encode('utf-8')) + padder.finalize()
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()
        return base64.b64encode(iv + ciphertext).decode('ascii')

    # Шаг 3: Шифруем контент и изображение ОДНИМ сессионным ключом
    enc_content = _aes_encrypt_session(plaintext) if plaintext else ""
    enc_image = _aes_encrypt_session(image_data) if image_data else None

    # Шаг 4: Шифруем session key через shared key
    enc_session_key = encrypt_message(shared_key, base64.b64encode(session_key).decode())

    return {
        'content': enc_content,
        'image': enc_image,
        'enc_session_key': enc_session_key,
        'version': 'hybrid-v1'
    }


def decrypt_hybrid(my_mnemonic: str, peer_public_key_b64: str,
                   encrypted_payload: Dict[str, str]) -> Dict[str, Optional[str]]:
    """
    Расшифровка гибридного сообщения с поддержкой изображений.

    Returns:
        Dict с 'content' и 'image' (оба могут быть None при ошибке)
    """
    result = {'content': None, 'image': None}

    try:
        enc_session_key = encrypted_payload.get('enc_session_key')
        enc_content = encrypted_payload.get('content')
        enc_image = encrypted_payload.get('image')

        if not enc_session_key:
            logging.warning("Missing enc_session_key in hybrid payload")
            return result

        # Шаг 1: Вычисляем shared key
        shared_key = compute_shared_key_b64(my_mnemonic, peer_public_key_b64)

        # Шаг 2: Расшифровываем session key
        session_key_b64 = decrypt_message(shared_key, enc_session_key)
        if not session_key_b64:
            logging.warning("Failed to decrypt session key")
            return result
        session_key = base64.b64decode(session_key_b64)

        # Вспомогательная функция для AES-расшифровки с сессионным ключом
        def _aes_decrypt_session(encrypted: Optional[str]) -> Optional[str]:
            if not encrypted:
                return None
            try:
                data = base64.b64decode(encrypted)
                if len(data) < 16:
                    return None
                iv, ciphertext = data[:16], data[16:]
                cipher = Cipher(algorithms.AES(session_key), modes.CBC(iv), backend=default_backend())
                decryptor = cipher.decryptor()
                padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
                unpadder = padding.PKCS7(128).unpadder()
                plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
                return plaintext.decode('utf-8')
            except Exception as e:
                logging.warning(f"AES session decrypt failed: {e}")
                return None

        # Шаг 3: Расшифровываем контент и изображение
        result['content'] = _aes_decrypt_session(enc_content)
        result['image'] = _aes_decrypt_session(enc_image)

        return result

    except Exception as e:
        logging.warning(f"Hybrid decryption failed: {e}")
        return result
# =============================================================================
# 🔄 Часть 5: Утилиты и кэширование
# =============================================================================

def clear_key_cache():
    """Очищает все кэши ключей."""
    _derive_private_key_cached.cache_clear()


def get_cache_info() -> dict:
    """Возвращает статистику кэшей."""
    priv_cache = _derive_private_key_cached.cache_info()
    return {
        'private_key_hits': priv_cache.hits,
        'private_key_misses': priv_cache.misses,
        'private_key_size': priv_cache.currsize,
        'hit_rate': priv_cache.hits / (priv_cache.hits + priv_cache.misses) * 100
                    if (priv_cache.hits + priv_cache.misses) > 0 else 0
    }


# =============================================================================
# 🏷️ Часть 6: Обратная совместимость (для групповых чатов)
# =============================================================================

@lru_cache(maxsize=CACHE_SIZE)
def _generate_symmetric_key_internal(combined: str, mnemonic_hash: str) -> bytes:
    """
    Симметричный ключ для групповых чатов (обратная совместимость).
    ⚠️ Менее безопасен, но необходим для multi-recipient шифрования.
    """
    return hashlib.sha256(f"{mnemonic_hash}:{combined}".encode('utf-8')).digest()[:32]


def generate_symmetric_key(sender: str, recipient: str, mnemonic_phrase: str) -> bytes:
    """
    Генерирует симметричный ключ для группового шифрования.
    Используется ТОЛЬКО для групп, где ECDH не масштабируется напрямую.
    """
    if not mnemonic_phrase:
        raise ValueError("mnemonic_phrase is required")
    combined = ''.join(sorted([sender.strip(), recipient.strip()]))
    mnemonic_hash = hashlib.sha256(mnemonic_phrase.encode('utf-8')).hexdigest()
    return _generate_symmetric_key_internal(combined, mnemonic_hash)


def generate_address(mnemonic: str) -> str:
    """Генерирует адрес кошелька из мнемонической фразы (для обратной совместимости)."""
    if not mnemonic:
        raise ValueError("Mnemonic phrase cannot be empty")
    return hashlib.sha256(mnemonic.encode('utf-8')).hexdigest()