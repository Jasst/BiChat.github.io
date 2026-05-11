"""
routes/auth.py — Регистрация, вход, выход и страницы приложения
"""
import logging
import time
import secrets

from flask import Blueprint, jsonify, render_template, request, session, url_for, redirect

from cache import cache_public_key, clear_all_caches
from crypto_manager import verify_address_matches_pubkey, load_public_key_from_b64
from config import AIRDROP_AMOUNT

# Новый импорт для кодирования сырой подписи в DER
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    if 'address' in session:
        return redirect(url_for('auth.chat'))
    return render_template('index.html')


@auth_bp.route('/chat')
def chat():
    if 'address' not in session:
        return redirect(url_for('auth.index'))
    return render_template('chat.html', address=session['address'])


@auth_bp.route('/contacts')
def contacts_page():
    if 'address' not in session:
        return redirect(url_for('auth.index'))
    return render_template('contacts.html', address=session['address'])


@auth_bp.route('/groups')
def groups_page():
    if 'address' not in session:
        return redirect(url_for('auth.index'))
    return render_template('groups.html', address=session['address'])


@auth_bp.route('/profile')
def profile():
    if 'address' not in session:
        return redirect(url_for('auth.index'))
    from flask import current_app
    return render_template('profile.html',
                           address=session.get('address'),
                           cache_stats=None)


@auth_bp.route('/wallet')
def wallet_page():
    if 'address' not in session:
        return redirect(url_for('auth.index'))
    return render_template('wallet.html', address=session['address'])


@auth_bp.route('/create_wallet', methods=['POST'])
def create_wallet():
    """
    Клиент присылает готовый адрес и публичный ключ (base64).
    Сервер сохраняет их, создаёт сессию и начисляет аирдроп.
    """
    try:
        data = request.get_json(silent=True) or {}
        address = data.get('address', '').strip()
        pubkey_b64 = data.get('public_key', '').strip()

        # Проверка формата
        if len(address) != 64 or not pubkey_b64:
            return jsonify({'error': 'Missing or invalid address/public_key'}), 400

        # Проверяем, что адрес соответствует публичному ключу
        if not verify_address_matches_pubkey(address, pubkey_b64):
            return jsonify({'error': 'Public key does not match address'}), 400

        # Создаём сессию (мнемоники на сервере нет!)
        session['address'] = address
        session.permanent = True

        # Кэшируем публичный ключ
        cache_public_key(address, pubkey_b64, source='self', verified=True)

        # Начисляем аирдроп
        from database import get_db_cursor, DATABASE_PATH
        with get_db_cursor(DATABASE_PATH) as cursor:
            cursor.execute(
                'INSERT INTO wallets (address, balance) VALUES (?, ?) '
                'ON CONFLICT(address) DO NOTHING',
                (address, AIRDROP_AMOUNT)
            )
            cursor.execute(
                'INSERT INTO coin_transactions (tx_type, recipient, amount, timestamp) '
                'VALUES (?,?,?,?)',
                ('airdrop', address, AIRDROP_AMOUNT, time.time())
            )

        logger.info(f"New wallet registered: {address[:16]}...")
        return jsonify({
            'address': address,
            'public_key': pubkey_b64
        }), 201

    except Exception as e:
        logger.error(f"Create wallet error: {e}")
        return jsonify({'error': 'Wallet creation failed'}), 500


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            data = request.get_json(silent=True) or {}
            address = data.get('address', '').strip()
            pubkey_b64 = data.get('public_key', '').strip()
            signature_hex = data.get('signature', '').strip()
            nonce = session.pop('login_nonce', None)

            if not nonce:
                return jsonify({'error': 'No challenge found. Refresh the page.'}), 400
            if not address or len(address) != 64 or not pubkey_b64 or not signature_hex:
                return jsonify({'error': 'Missing required fields'}), 400

            # 1. Соответствие адреса публичному ключу
            if not verify_address_matches_pubkey(address, pubkey_b64):
                return jsonify({'error': 'Public key does not match address'}), 400

            # 2. Проверка подписи (ECDSA P-256)
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import hashes

            try:
                # Клиент передаёт сырую подпись (64 байта: r || s)
                raw_signature = bytes.fromhex(signature_hex)
                if len(raw_signature) != 64:
                    return jsonify({'error': 'Invalid signature format (must be 64 bytes raw)'}), 400

                # Разделяем на r и s (по 32 байта)
                r = int.from_bytes(raw_signature[:32], 'big')
                s = int.from_bytes(raw_signature[32:], 'big')

                # Кодируем в DER
                der_signature = encode_dss_signature(r, s)

                # Загружаем открытый ключ и проверяем DER-подпись
                pubkey = load_public_key_from_b64(pubkey_b64)
                pubkey.verify(
                    der_signature,
                    nonce.encode('utf-8'),
                    ec.ECDSA(hashes.SHA256())
                )
            except Exception as e:
                logger.warning(f"Signature verification failed: {e}")
                return jsonify({'error': 'Invalid signature'}), 403

            # Успешно
            session['address'] = address
            session.permanent = True
            cache_public_key(address, pubkey_b64, source='self', verified=True)
            logger.info(f"User logged in: {address[:16]}...")
            return jsonify({'address': address}), 200

        except Exception as e:
            logger.error(f"Login error: {e}")
            return jsonify({'error': 'Login failed'}), 500

    # GET: отдаём страницу с nonce
    nonce = secrets.token_hex(32)
    session['login_nonce'] = nonce
    return render_template('login.html', nonce=nonce)

@auth_bp.route('/check_session')
def check_session():
    """Проверка статуса авторизации (для клиентской логики)"""
    return jsonify({
        'authenticated': 'address' in session,
        'address': session.get('address')
    })

@auth_bp.route('/logout')
def logout():
    clear_all_caches()
    session.clear()
    return redirect(url_for('auth.index'))