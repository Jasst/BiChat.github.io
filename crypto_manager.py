"""
crypto_manager.py — Гибридное шифрование ECDH + AES-GCM
Версия: 3.3 (исправлены уязвимости: групповые ключи, аутентификация, валидация)
"""
import hashlib
import base64
import os
import json
import logging
import hmac
from functools import lru_cache
from typing import Optional, Dict, Any, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend

# === Конфигурация ===
CACHE_SIZE = 128
CURVE = ec.SECP256R1()  # NIST P-256
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
PBKDF2_ITERATIONS = 600_000  # NIST рекомендация для 2024+
DOMAIN_SEPARATOR = "BiChat:crypto:v3.3"
GROUP_KEY_SALT = b"group-symmetric-salt-v2"

# === Логирование ===
logger = logging.getLogger(__name__)


# =============================================================================
# 🔑 Часть 1: Деривация асимметричных ключей из мнемоники (УСИЛЕННАЯ)
# =============================================================================

# ✅ СТАЛО — PBKDF2 делает брутфорс в ~600 000 раз дороже
# Меняем сигнатуру: принимаем сырую мнемонику, хэшируем внутри с усилением

@lru_cache(maxsize=CACHE_SIZE)
def _derive_private_key_cached(mnemonic_hash: str) -> ec.EllipticCurvePrivateKey:
    """
    mnemonic_hash — hex SHA256 от мнемоники (для кэш-ключа).
    Внутри — PBKDF2 поверх него для защиты от брутфорса.
    """
    key_material = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'BiChat:private-key-v1',
        iterations=PBKDF2_ITERATIONS,
        backend=default_backend()
    ).derive(mnemonic_hash.encode('utf-8'))

    private_scalar = int.from_bytes(key_material, 'big')
    private_scalar = (private_scalar % (_P256_ORDER - 1)) + 1
    return ec.derive_private_key(private_scalar, CURVE, default_backend())

def derive_private_key(mnemonic_phrase: str) -> ec.EllipticCurvePrivateKey:
    """Деривация приватного ключа с валидацией ввода."""
    if not mnemonic_phrase or not isinstance(mnemonic_phrase, str):
        raise ValueError("mnemonic_phrase is required and must be a non-empty string")

    mnemonic_phrase = mnemonic_phrase.strip()
    if len(mnemonic_phrase) < 24:  # Минимальная длина для 256-битной мнемоники
        raise ValueError("mnemonic_phrase appears too short")

    mnemonic_hash = hashlib.sha256(mnemonic_phrase.encode('utf-8')).hexdigest()
    return _derive_private_key_cached(mnemonic_hash)


def get_public_key_bytes(mnemonic_phrase: str) -> bytes:
    """Получение публичного ключа в сжатом формате."""
    private_key = derive_private_key(mnemonic_phrase)
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.CompressedPoint
    )


def get_public_key_b64(mnemonic_phrase: str) -> str:
    """Публичный ключ в base64 для передачи."""
    return base64.b64encode(get_public_key_bytes(mnemonic_phrase)).decode('ascii')


def load_public_key_from_bytes(pubkey_bytes: bytes) -> ec.EllipticCurvePublicKey:
    """Загрузка публичного ключа с валидацией (совместимо с cryptography >= 2.5)."""
    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(CURVE, pubkey_bytes)

        # 🔒 Валидация: проверяем наличие метода (cryptography >= 3.4)
        if hasattr(public_key, 'check_valid'):
            public_key.check_valid()
        # Для старых версий: from_encoded_point уже выполняет базовую проверку

        return public_key
    except Exception as e:
        raise ValueError(f"Invalid public key: {e}")


def load_public_key_from_b64(pubkey_b64: str) -> ec.EllipticCurvePublicKey:
    """Загрузка публичного ключа из base64."""
    return load_public_key_from_bytes(base64.b64decode(pubkey_b64))


def verify_address_matches_pubkey(address: str, pubkey_b64: str) -> bool:
    """
    Проверка: соответствует ли адрес данному публичному ключу.
    Адрес должен быть SHA256(public_key_compressed).
    """
    try:
        pubkey_bytes = base64.b64decode(pubkey_b64)
        computed_address = hashlib.sha256(pubkey_bytes).hexdigest()
        return hmac.compare_digest(computed_address, address)
    except Exception:
        return False


# =============================================================================
# 🔐 Часть 2: Усиленная деривация симметричных ключей
# =============================================================================

def _derive_key_material(password: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    """Внутренняя функция для безопасной деривации ключей."""
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=length,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
        backend=default_backend()
    ).derive(password + info)


# ✅ СТАЛО — мнемоника участвует в деривации как секретный компонент
def generate_symmetric_key(sender: str, recipient: str, mnemonic_phrase: str) -> bytes:
    """
    Симметричный ключ для пары адресов.
    Ключ вычислим только тем, у кого есть мнемоника одного из участников.
    Используется HKDF чтобы мнемоника не была напрямую в ключевом материале.
    """
    if not mnemonic_phrase:
        raise ValueError("mnemonic_phrase is required for key derivation")

    combined = ':'.join(sorted([sender.strip(), recipient.strip()]))
    domain = f"{DOMAIN_SEPARATOR}:group-symmetric-v4"

    # Мнемоника → стойкий секрет через PBKDF2
    secret = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=GROUP_KEY_SALT,
        iterations=100_000,   # меньше чем для логина, т.к. вызывается часто
        backend=default_backend()
    ).derive(mnemonic_phrase.encode('utf-8'))

    # Смешиваем секрет с парой адресов через HKDF
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=combined.encode('utf-8'),
        info=domain.encode('utf-8'),
        backend=default_backend()
    ).derive(secret)

# =============================================================================
# 🔐 Часть 3: ECDH — вычисление общего секрета (с валидацией)
# =============================================================================

def compute_shared_key(my_mnemonic: str, peer_public_key: bytes,
                       peer_address: Optional[str] = None) -> bytes:
    """
    Вычисление общего секрета ECDH с валидацией публичного ключа.

    🔒 Если передан peer_address — проверяем соответствие ключа адресу.
    """
    my_private = derive_private_key(my_mnemonic)
    peer_public = load_public_key_from_bytes(peer_public_key)

    # 🔒 Проверка соответствия ключа адресу (защита от MITM)
    if peer_address is not None:
        pubkey_b64 = base64.b64encode(peer_public_key).decode('ascii')
        if not verify_address_matches_pubkey(peer_address, pubkey_b64):
            raise ValueError(f"Public key does not match address {peer_address[:16]}...")

    shared_secret = my_private.exchange(ec.ECDH(), peer_public)

    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f'{DOMAIN_SEPARATOR}:aes-gcm-key'.encode()
    ).derive(shared_secret)


def compute_shared_key_b64(my_mnemonic: str, peer_public_key_b64: str,
                           peer_address: Optional[str] = None) -> bytes:
    """Обёртка для работы с base64-ключами."""
    return compute_shared_key(
        my_mnemonic,
        base64.b64decode(peer_public_key_b64),
        peer_address
    )


# =============================================================================
# 🔒 Часть 4: Симметричное шифрование AES-256-GCM (AEAD)
# =============================================================================

def encrypt_message_aead(key: bytes, plaintext: str, associated_data: Optional[bytes] = None) -> str:
    """
    🔧 ИСПРАВЛЕНО: Шифрование с аутентификацией (AES-GCM).

    Возвращает: base64(nonce + ciphertext + tag)
    """
    if not plaintext:
        return ""
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError(f"Invalid key: expected 32 bytes, got {len(key) if isinstance(key, bytes) else type(key)}")

    try:
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)  # 96-bit nonce для GCM
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), associated_data)
        # GCM автоматически добавляет 16-байтный тег в конец ciphertext
        return base64.b64encode(nonce + ciphertext).decode('ascii')
    except Exception as e:
        logger.error(f"AEAD encryption error: {e}")
        raise


def decrypt_message_aead(key: bytes, encrypted_data: Optional[str],
                         associated_data: Optional[bytes] = None,
                         fallback: str = "[Decryption Failed]") -> Optional[str]:
    """
    Расшифровка AES-GCM с унифицированной обработкой ошибок.

    🔒 Все ошибки возвращают fallback — защита от padding oracle.
    """
    if not encrypted_data:
        return None
    if not isinstance(key, bytes) or len(key) != 32:
        logger.warning(f"Invalid key in decrypt: {type(key)}")
        return fallback

    try:
        data = base64.b64decode(encrypted_data)
        if len(data) < 28:  # 12 (nonce) + 16 (tag) минимум
            raise ValueError("Encrypted data too short")

        nonce, ciphertext_with_tag = data[:12], data[12:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, associated_data)
        return plaintext.decode('utf-8')

    except Exception as e:
        # 🔒 Унифицированный ответ при любой ошибке — защита от oracle-атак
        logger.debug(f"AEAD decryption failed: {type(e).__name__}")
        return fallback


# =============================================================================
# 🎁 Часть 5: Гибридное шифрование (ECDH + AES-GCM ephemeral session key)
# =============================================================================

# ✅ СТАЛО — убираем peer_address из payload
def encrypt_hybrid(my_mnemonic: str, peer_public_key_b64: str, peer_address: str,
                   plaintext: str, image_data: Optional[str] = None) -> Dict[str, Any]:
    if not plaintext and not image_data:
        return {
            'content': '', 'image': None,
            'enc_session_key': '', 'nonce': '',
            'version': 'hybrid-v2'
        }

    shared_key = compute_shared_key_b64(my_mnemonic, peer_public_key_b64, peer_address)
    session_key = os.urandom(32)

    enc_content = encrypt_message_aead(session_key, plaintext) if plaintext else ""
    enc_image = encrypt_message_aead(session_key, image_data) if image_data else None
    enc_session_key = encrypt_message_aead(shared_key, base64.b64encode(session_key).decode())
    nonce = base64.b64encode(os.urandom(16)).decode()

    return {
        'content': enc_content,
        'image': enc_image,
        'enc_session_key': enc_session_key,
        'nonce': nonce,
        'version': 'hybrid-v2'
        # peer_address убран — он уже есть в поле recipient транзакции
    }



def decrypt_hybrid(my_mnemonic: str, peer_public_key_b64: str, peer_address: str,
                   encrypted_payload: Dict[str, Any]) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {'content': None, 'image': None}

    try:
        # 🔒 Валидация входных данных
        if not peer_public_key_b64 or not peer_address:
            logger.error(f"❌ decrypt_hybrid: missing peer_public_key_b64 or peer_address")
            return result

        enc_session_key = encrypted_payload.get('enc_session_key')
        if not enc_session_key:
            logger.warning("❌ Missing enc_session_key in payload")
            return result

        # 🔍 Лог для отладки
        logger.debug(f"🔓 Decrypt attempt: peer={peer_address[:16]}...")

        # 🔒 Вычисляем общий секрет (проверка адреса встроена)
        shared_key = compute_shared_key_b64(my_mnemonic, peer_public_key_b64, peer_address)

        session_key_b64 = decrypt_message_aead(shared_key, enc_session_key)
        if not session_key_b64 or session_key_b64 == "[Decryption Failed]":
            logger.warning(f"❌ Session key decryption failed for peer={peer_address[:16]}...")
            return result

        session_key = base64.b64decode(session_key_b64)

        result['content'] = decrypt_message_aead(session_key, encrypted_payload.get('content'))
        result['image'] = decrypt_message_aead(session_key, encrypted_payload.get('image'))

        if result['content'] == "[Decryption Failed]":
            logger.warning(f"❌ Content decryption failed for message from {peer_address[:16]}...")

        return result

    except ValueError as e:
        if "Public key does not match" in str(e):
            logger.error(f"❌ Key verification failed: {e}")
        else:
            logger.error(f"❌ Decryption ValueError: {e}")
        return result
    except Exception as e:
        logger.error(f"❌ Hybrid decryption unexpected error: {type(e).__name__}: {e}", exc_info=True)
        return result

# =============================================================================
# 🔄 Часть 6: Утилиты и кэширование
# =============================================================================

def clear_key_cache():
    """Очистка всех кэшей ключей."""
    _derive_private_key_cached.cache_clear()


def get_cache_info() -> dict:
    """Статистика кэша приватных ключей."""
    info = _derive_private_key_cached.cache_info()
    total = info.hits + info.misses
    return {
        'private_key_hits': info.hits,
        'private_key_misses': info.misses,
        'private_key_size': info.currsize,
        'hit_rate': round(info.hits / total * 100, 1) if total > 0 else 0.0
    }


def generate_address_from_pubkey(pubkey_b64: str) -> str:
    """Генерация адреса из публичного ключа (для верификации)."""
    pubkey_bytes = base64.b64decode(pubkey_b64)
    return hashlib.sha256(pubkey_bytes).hexdigest()


def generate_address(mnemonic: str) -> str:
    """Генерация адреса из мнемоники."""
    if not mnemonic:
        raise ValueError("Mnemonic phrase cannot be empty")
    pubkey_bytes = get_public_key_bytes(mnemonic)
    return hashlib.sha256(pubkey_bytes).hexdigest()