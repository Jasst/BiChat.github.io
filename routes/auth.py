"""
routes/auth.py — Регистрация, вход, выход и страницы приложения
"""
import logging
import time

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from marshmallow import ValidationError
from mnemonic import Mnemonic

from cache import cache_public_key, clear_all_caches
from crypto_manager import generate_address, get_public_key_b64, clear_key_cache, get_cache_info
from schemas import WalletSchema
from config import AIRDROP_AMOUNT

logger      = logging.getLogger(__name__)
auth_bp     = Blueprint('auth', __name__)
mnemonic_gen = Mnemonic('english')


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
                           cache_stats=get_cache_info() if current_app.debug else None)


@auth_bp.route('/wallet')
def wallet_page():
    if 'address' not in session:
        return redirect(url_for('auth.index'))
    return render_template('wallet.html', address=session['address'])


@auth_bp.route('/create_wallet', methods=['POST'])
def create_wallet():
    try:
        phrase  = mnemonic_gen.generate(256)
        address = generate_address(phrase)
        session['address']  = address
        session['mnemonic'] = phrase
        session.permanent   = True
        my_pubkey = get_public_key_b64(phrase)
        cache_public_key(address, my_pubkey, source='self', verified=True)

        # начисляем аирдроп
        from database import get_db_cursor, DATABASE_PATH
        with get_db_cursor(DATABASE_PATH) as cursor:
            cursor.execute('INSERT INTO wallets (address, balance) VALUES (?, ?) ON CONFLICT(address) DO NOTHING',
                           (address, AIRDROP_AMOUNT))
            cursor.execute('INSERT INTO coin_transactions (tx_type, recipient, amount, timestamp) VALUES (?,?,?,?)',
                           ('airdrop', address, AIRDROP_AMOUNT, time.time()))

        return jsonify({
            'mnemonic_phrase': phrase,
            'address':         address,
            'public_key':      my_pubkey,
            'warning': 'Save your mnemonic phrase securely. It will not be shown again.',
        }), 201
    except Exception as e:
        logger.error(f"Create wallet error: {e}")
        return jsonify({'error': 'Wallet creation failed'}), 500


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            data   = WalletSchema().load(request.get_json())
            phrase = data['mnemonic_phrase'].strip()
            try:
                if not mnemonic_gen.check(phrase):
                    return jsonify({'error': 'Invalid mnemonic phrase'}), 400
            except Exception:
                pass
            address = generate_address(phrase)
            session['address']  = address
            session['mnemonic'] = phrase
            session.permanent   = True
            my_pubkey = get_public_key_b64(phrase)
            cache_public_key(address, my_pubkey, source='self', verified=True)
            return jsonify({'address': address, 'public_key': my_pubkey}), 200
        except ValidationError as err:
            return jsonify({'error': err.messages}), 400
        except Exception as e:
            logger.error(f"Login error: {e}")
            return jsonify({'error': 'Login failed'}), 500
    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    clear_key_cache()
    clear_all_caches()
    session.clear()
    return redirect(url_for('auth.index'))


@auth_bp.route('/api/export_mnemonic', methods=['POST'])
def export_mnemonic():
    if 'address' not in session:
        logger.warning(f"Unauthorized mnemonic export from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data         = request.get_json(silent=True) or {}
        confirmation = data.get('confirmation', '').strip().upper()
        if confirmation not in ('I CONFIRM', 'ПОДТВЕРЖДАЮ', 'CONFIRM', 'YES'):
            return jsonify({'error': 'Please type "I CONFIRM" or "YES" to continue'}), 400
        mnemonic = session.get('mnemonic')
        if not mnemonic:
            return jsonify({'error': 'Session expired. Please login again.'}), 401
        response = jsonify({
            'mnemonic':            mnemonic,
            'warning':             'Auto-clears in 30 seconds. Do not share.',
            'auto_clear_seconds':  30,
        })
        response.headers.update({
            'Cache-Control': 'no-store, no-cache, must-revalidate, private',
            'Pragma':        'no-cache',
            'Expires':       '0',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
        })
        logger.info(f"Mnemonic exported for {session.get('address','unknown')[:16]}... "
                    f"from {request.remote_addr}")
        return response, 200
    except Exception as e:
        logger.error(f"Mnemonic export error: {type(e).__name__}")
        return jsonify({'error': 'Export failed'}), 500
