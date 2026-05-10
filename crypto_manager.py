# crypto_manager.py (server-side only: pubkey verification)
import hashlib
import base64
import hmac
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend

CURVE = ec.SECP256R1()

def load_public_key_from_bytes(pubkey_bytes):
    return ec.EllipticCurvePublicKey.from_encoded_point(CURVE, pubkey_bytes)

def load_public_key_from_b64(pubkey_b64):
    return load_public_key_from_bytes(base64.b64decode(pubkey_b64))

def verify_address_matches_pubkey(address, pubkey_b64):
    try:
        pubkey_bytes = base64.b64decode(pubkey_b64)
        computed = hashlib.sha256(pubkey_bytes).hexdigest()
        return hmac.compare_digest(computed, address)
    except Exception:
        return False

def get_cache_info():
    # заглушка, чтобы profile не падал
    return {"status": "crypto moved to client"}