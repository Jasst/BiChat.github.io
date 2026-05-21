"""routes/auth_async.py — Асинхронная аутентификация"""
import logging
import secrets
import hashlib
import hmac
import base64

from quart import Blueprint, jsonify, request, make_response, render_template
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from database_async import db
from redis_manager import redis_manager
from config_async import AIRDROP_AMOUNT, COIN
from setup_async import rate_limit

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__)


# =============================================================================
# КРИПТОГРАФИЧЕСКИЕ ФУНКЦИИ
# =============================================================================

def verify_address_matches_pubkey(address: str, pubkey_b64: str) -> bool:
    """Проверяет соответствие адреса публичному ключу"""
    try:
        pubkey_bytes = base64.b64decode(pubkey_b64)
        computed = hashlib.sha256(pubkey_bytes).hexdigest()
        return hmac.compare_digest(computed, address)
    except Exception:
        return False


def load_public_key_from_b64(pubkey_b64: str):
    """Загружает публичный ключ из base64"""
    curve = ec.SECP256R1()
    pubkey_bytes = base64.b64decode(pubkey_b64)
    return ec.EllipticCurvePublicKey.from_encoded_point(curve, pubkey_bytes)


# =============================================================================
# СТРАНИЦЫ (рендеринг HTML)
# =============================================================================

@auth_bp.route('/')
async def index():
    """Главная страница"""
    session_id = request.cookies.get('session_id')
    if session_id:
        address = await redis_manager.session_get(session_id, 'address')
        if address:
            return await chat()
    return await render_template('index.html')


@auth_bp.route('/chat')
async def chat():
    """Страница чата"""
    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')
    if not address:
        return await render_template('index.html')
    return await render_template('chat.html', address=address)


@auth_bp.route('/contacts')
async def contacts_page():
    """Страница контактов"""
    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')
    if not address:
        return await render_template('index.html')
    return await render_template('contacts.html', address=address)


@auth_bp.route('/groups')
async def groups_page():
    """Страница групп"""
    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')
    if not address:
        return await render_template('index.html')
    return await render_template('groups.html', address=address)


@auth_bp.route('/profile')
async def profile():
    """Страница профиля"""
    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')
    if not address:
        return await render_template('index.html')
    return await render_template('profile.html', address=address)


@auth_bp.route('/wallet')
async def wallet_page():
    """Страница кошелька"""
    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')
    if not address:
        return await render_template('index.html')
    return await render_template('wallet.html', address=address)


# =============================================================================
# API ЭНДПОИНТЫ
# =============================================================================

@auth_bp.route('/login/nonce', methods=['GET'])
async def get_nonce():
    """
    Возвращает nonce для подписи.
    Nonce действителен 5 минут.
    """
    address = request.args.get('address', '').strip()

    if len(address) != 64 or not all(c in '0123456789abcdef' for c in address):
        return jsonify({'error': 'Invalid address (must be 64 hex chars)'}), 400

    nonce = secrets.token_hex(32)
    await redis_manager.cache_set(f"nonce:{address}", nonce, ttl=300)

    logger.debug(f"🔑 Nonce generated for {address[:16]}...")

    return jsonify({'nonce': nonce}), 200


@auth_bp.route('/login', methods=['POST'])
@rate_limit(limit=10)
async def login():
    """
    Аутентификация через подпись.
    Проверяет nonce, подпись и создаёт сессию.
    """
    try:
        data = await request.get_json()
        address = data.get('address', '').strip()
        pubkey_b64 = data.get('public_key', '').strip()
        signature_hex = data.get('signature', '').strip()
        nonce = data.get('nonce', '').strip()

        # Валидация обязательных полей
        if not all([address, pubkey_b64, signature_hex, nonce]):
            return jsonify({'error': 'Missing required fields'}), 400

        # Проверка формата адреса
        if len(address) != 64 or not all(c in '0123456789abcdef' for c in address):
            return jsonify({'error': 'Invalid address format'}), 400

        # 1. Проверяем nonce в Redis
        stored_nonce = await redis_manager.cache_get(f"nonce:{address}")
        if not stored_nonce or stored_nonce != nonce:
            return jsonify({'error': 'Invalid or expired nonce'}), 400

        # 2. Проверяем соответствие адреса публичному ключу
        if not verify_address_matches_pubkey(address, pubkey_b64):
            return jsonify({'error': 'Public key does not match address'}), 400

        # 3. Проверяем существование кошелька
        wallet = await db.fetch_one(
            "SELECT address FROM wallets WHERE address = $1", address
        )
        if not wallet:
            return jsonify({'error': 'Wallet not found. Please register first.'}), 404

        # 4. Проверяем подпись (ECDSA P-256)
        try:
            raw_signature = bytes.fromhex(signature_hex)
            if len(raw_signature) != 64:
                return jsonify({'error': 'Invalid signature length'}), 400

            r = int.from_bytes(raw_signature[:32], 'big')
            s = int.from_bytes(raw_signature[32:], 'big')
            der_signature = encode_dss_signature(r, s)

            pubkey = load_public_key_from_b64(pubkey_b64)
            pubkey.verify(der_signature, nonce.encode(), ec.ECDSA(hashes.SHA256()))

        except Exception as e:
            logger.warning(f"Signature verification failed for {address[:16]}...: {e}")
            return jsonify({'error': 'Invalid signature'}), 403

        # 5. Создаём сессию в Redis
        session_id = secrets.token_hex(32)
        await redis_manager.session_set(session_id, 'address', address)
        await redis_manager.session_set(session_id, 'pubkey', pubkey_b64)

        # 6. Кэшируем публичный ключ
        await redis_manager.cache_set(f"pubkey:{address}", pubkey_b64, ttl=3600)

        # 7. Удаляем использованный nonce
        await redis_manager.cache_delete(f"nonce:{address}")

        # 8. Создаём ответ с cookie
        response = await make_response(jsonify({
            'address': address,
            'success': True,
            'message': 'Login successful'
        }))
        response.set_cookie(
            'session_id', session_id,
            httponly=True,
            secure=True,
            samesite='Lax',
            max_age=31536000
        )

        logger.info(f"✅ User logged in: {address[:16]}...")
        return response

    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': 'Login failed'}), 500


@auth_bp.route('/create_wallet', methods=['POST'])
@rate_limit(limit=5)
async def create_wallet():
    """
    Создаёт новый кошелёк.
    Клиент присылает готовый адрес и публичный ключ.
    """
    try:
        data = await request.get_json()
        address = data.get('address', '').strip()
        pubkey_b64 = data.get('public_key', '').strip()

        # Валидация
        if len(address) != 64 or not pubkey_b64:
            return jsonify({'error': 'Missing or invalid address/public_key'}), 400

        if not verify_address_matches_pubkey(address, pubkey_b64):
            return jsonify({'error': 'Public key does not match address'}), 400

        # Проверяем, существует ли кошелёк
        existing = await db.fetch_one(
            "SELECT address, balance FROM wallets WHERE address = $1", address
        )

        if not existing:
            # Создаём кошелёк с аирдропом
            async with db.transaction() as conn:
                await conn.execute("""
                    INSERT INTO wallets (address, balance) VALUES ($1, $2)
                """, address, AIRDROP_AMOUNT)

                await conn.execute("""
                    INSERT INTO coin_transactions (tx_type, recipient, amount, timestamp)
                    VALUES ('airdrop', $1, $2, NOW())
                """, address, AIRDROP_AMOUNT)

            logger.info(f"💰 New wallet created with airdrop: {address[:16]}...")
        else:
            logger.info(f"👛 Existing wallet logged in: {address[:16]}...")

        # Создаём сессию
        session_id = secrets.token_hex(32)
        await redis_manager.session_set(session_id, 'address', address)
        await redis_manager.session_set(session_id, 'pubkey', pubkey_b64)

        # Кэшируем публичный ключ
        await redis_manager.cache_set(f"pubkey:{address}", pubkey_b64, ttl=3600)

        # Создаём ответ
        response = await make_response(jsonify({
            'address': address,
            'public_key': pubkey_b64,
            'airdrop': AIRDROP_AMOUNT if not existing else 0,
            'message': 'Wallet ready'
        }))
        response.set_cookie(
            'session_id', session_id,
            httponly=True,
            secure=True,
            samesite='Lax',
            max_age=31536000
        )

        return response, 201 if not existing else 200

    except Exception as e:
        logger.error(f"Create wallet error: {e}")
        return jsonify({'error': 'Wallet creation failed'}), 500


@auth_bp.route('/check_session', methods=['GET'])
async def check_session():
    """
    Проверка статуса сессии.
    Возвращает authenticated и address если есть.
    """
    session_id = request.cookies.get('session_id')

    if not session_id:
        return jsonify({'authenticated': False}), 200

    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'authenticated': False}), 200

    return jsonify({
        'authenticated': True,
        'address': address
    }), 200


@auth_bp.route('/logout', methods=['POST'])
async def logout():
    """
    Выход из системы.
    Удаляет сессию из Redis и очищает куку.
    """
    session_id = request.cookies.get('session_id')

    if session_id:
        address = await redis_manager.session_get(session_id, 'address')
        await redis_manager.session_delete(session_id)
        logger.info(f"👋 User logged out: {address[:16] if address else 'unknown'}...")

    response = await make_response(jsonify({'message': 'Logged out'}))
    response.delete_cookie('session_id')

    return response