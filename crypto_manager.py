"""
crypto_manager.py — Гибридное шифрование ECDH + AES
Версия: 3.2 (фикс групповых чатов: детерминированные ключи)
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
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


# =============================================================================
# 🔑 Часть 1: Деривация асимметричных ключей из мнемоники
# =============================================================================

@lru_cache(maxsize=CACHE_SIZE)
def _derive_private_key_cached(mnemonic_hash: str) -> ec.EllipticCurvePrivateKey:
    private_scalar = int.from_bytes(
        hashlib.sha256(mnemonic_hash.encode('utf-8')).digest()[:32],
        'big'
    )
    private_scalar = (private_scalar % (_P256_ORDER - 1)) + 1
    return ec.derive_private_key(private_scalar, CURVE, default_backend())


def derive_private_key(mnemonic_phrase: str) -> ec.EllipticCurvePrivateKey:
    if not mnemonic_phrase:
        raise ValueError("mnemonic_phrase is required")
    mnemonic_hash = hashlib.sha256(mnemonic_phrase.encode('utf-8')).hexdigest()
    return _derive_private_key_cached(mnemonic_hash)


def get_public_key_bytes(mnemonic_phrase: str) -> bytes:
    private_key = derive_private_key(mnemonic_phrase)
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.CompressedPoint
    )


def get_public_key_b64(mnemonic_phrase: str) -> str:
    return base64.b64encode(get_public_key_bytes(mnemonic_phrase)).decode('ascii')


def load_public_key_from_bytes(pubkey_bytes: bytes) -> ec.EllipticCurvePublicKey:
    return ec.EllipticCurvePublicKey.from_encoded_point(CURVE, pubkey_bytes)


def load_public_key_from_b64(pubkey_b64: str) -> ec.EllipticCurvePublicKey:
    return load_public_key_from_bytes(base64.b64decode(pubkey_b64))


# =============================================================================
# 🔐 Часть 2: ECDH — вычисление общего секрета
# =============================================================================

def compute_shared_key(my_mnemonic: str, peer_public_key: bytes) -> bytes:
    my_private = derive_private_key(my_mnemonic)
    peer_public = load_public_key_from_bytes(peer_public_key)
    shared_secret = my_private.exchange(ec.ECDH(), peer_public)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b'messenger:v3:aes-encryption-key'
    ).derive(shared_secret)


def compute_shared_key_b64(my_mnemonic: str, peer_public_key_b64: str) -> bytes:
    return compute_shared_key(my_mnemonic, base64.b64decode(peer_public_key_b64))


# =============================================================================
# 🔒 Часть 3: Симметричное шифрование AES-256-CBC
# =============================================================================

def encrypt_message(key: bytes, plaintext: str) -> str:
    if not plaintext:
        return ""
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError(f"Invalid key: expected 32 bytes")
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
    if not encrypted_data:
        return None
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError(f"Invalid key: expected 32 bytes")
    try:
        data = base64.b64decode(encrypted_data)
        if len(data) < 32:
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
# 🎁 Часть 4: Гибридное шифрование (ECDH + AES ephemeral session key)
# =============================================================================

def _aes_encrypt_with_key(session_key: bytes, plain: str) -> str:
    if not plain:
        return ""
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(session_key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain.encode('utf-8')) + padder.finalize()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode('ascii')


def _aes_decrypt_with_key(session_key: bytes, encrypted: Optional[str]) -> Optional[str]:
    if not encrypted:
        return None
    try:
        data = base64.b64decode(encrypted)
        if len(data) < 32:
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


def encrypt_hybrid(my_mnemonic: str, peer_public_key_b64: str,
                   plaintext: str, image_data: Optional[str] = None) -> Dict[str, Any]:
    if not plaintext and not image_data:
        return {'content': '', 'image': None, 'enc_session_key': '', 'version': 'hybrid-v1'}

    shared_key = compute_shared_key_b64(my_mnemonic, peer_public_key_b64)
    session_key = os.urandom(32)

    enc_content = _aes_encrypt_with_key(session_key, plaintext) if plaintext else ""
    enc_image = _aes_encrypt_with_key(session_key, image_data) if image_data else None
    enc_session_key = encrypt_message(shared_key, base64.b64encode(session_key).decode())

    return {
        'content': enc_content,
        'image': enc_image,
        'enc_session_key': enc_session_key,
        'version': 'hybrid-v1'
    }


def decrypt_hybrid(my_mnemonic: str, peer_public_key_b64: str,
                   encrypted_payload: Dict[str, Any]) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {'content': None, 'image': None}
    try:
        enc_session_key = encrypted_payload.get('enc_session_key')
        if not enc_session_key:
            logging.warning("Missing enc_session_key in hybrid payload")
            return result

        shared_key = compute_shared_key_b64(my_mnemonic, peer_public_key_b64)
        session_key_b64 = decrypt_message(shared_key, enc_session_key)
        if not session_key_b64:
            logging.warning("Failed to decrypt session key")
            return result

        session_key = base64.b64decode(session_key_b64)
        result['content'] = _aes_decrypt_with_key(session_key, encrypted_payload.get('content'))
        result['image'] = _aes_decrypt_with_key(session_key, encrypted_payload.get('image'))
        return result
    except Exception as e:
        logging.warning(f"Hybrid decryption failed: {e}")
        return result


# =============================================================================
# 🔄 Часть 5: Утилиты и кэширование
# =============================================================================

def clear_key_cache():
    _derive_private_key_cached.cache_clear()


def get_cache_info() -> dict:
    info = _derive_private_key_cached.cache_info()
    total = info.hits + info.misses
    return {
        'private_key_hits': info.hits,
        'private_key_misses': info.misses,
        'private_key_size': info.currsize,
        'hit_rate': round(info.hits / total * 100, 1) if total > 0 else 0.0
    }


# =============================================================================
# 🏷️ Часть 6: Симметричные ключи для групповых чатов (ФИКС)
# =============================================================================

def generate_symmetric_key(sender: str, recipient: str, mnemonic_phrase: str) -> bytes:
    """
    Генерирует симметричный ключ для пары участников группы.

    🔧 ИСПРАВЛЕНО: Ключ зависит ТОЛЬКО от адресов + фиксированной соли.
    Все участники вычислят ОДИНАКОВЫЙ ключ для одной пары адресов.
    """
    combined = ':'.join(sorted([sender.strip(), recipient.strip()]))
    domain_separator = "BiChat:group-symmetric-v2"
    return hashlib.sha256(
        f"{domain_separator}:{combined}".encode('utf-8')
    ).digest()[:32]


def generate_address(mnemonic: str) -> str:
    if not mnemonic:
        raise ValueError("Mnemonic phrase cannot be empty")
    return hashlib.sha256(mnemonic.encode('utf-8')).hexdigest()