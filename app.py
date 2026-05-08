"""
app.py — Точка входа: создание Flask-приложения, регистрация blueprint'ов, старт.
"""
import os
from datetime import timedelta

from flask import jsonify, request, session
from flask.sessions import SecureCookieSessionInterface
from flask_compress import Compress
from flask_socketio import SocketIO, emit, join_room

from config import (CONFIG, DATABASE_PATH, MAX_CONTENT_LENGTH,
                    SECRET_KEY, STATIC_FOLDER, TEMPLATE_FOLDER, UPLOAD_FOLDER,
                    LOTTERY_INTERVAL, COIN, POOL_FEE_PERCENT)
from database import Blockchain, init_sqlite_optimizations, warmup_database
from logging_setup import setup_logging

# ── Логирование ─────────────────────────────────────────────────────────────
setup_logging()
import logging
logger = logging.getLogger(__name__)

# ── Flask ────────────────────────────────────────────────────────────────────
from flask import Flask

app = Flask(__name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_NAME='__Secure-session',
    PERMANENT_SESSION_LIFETIME=timedelta(seconds=CONFIG['SESSION_LIFETIME']),
)
app.session_interface = SecureCookieSessionInterface()

Compress(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# ── База данных и блокчейн ───────────────────────────────────────────────────
init_sqlite_optimizations(DATABASE_PATH)
blockchain = Blockchain(DATABASE_PATH)
warmup_database(DATABASE_PATH)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── Инициализация модулей ────────────────────────────────────────────────────
import cache
cache.set_db_path(DATABASE_PATH)

import services.contacts as svc_contacts
svc_contacts.set_db_path(DATABASE_PATH)

import services.messaging as svc_messaging
svc_messaging.set_db_path(DATABASE_PATH)

from services.wallet import init_wallet_service, lottery
init_wallet_service(DATABASE_PATH, blockchain, socketio)

# ── Blueprint'ы ──────────────────────────────────────────────────────────────
from routes.auth import auth_bp
from routes.messages import messages_bp, init_messages
from routes.contacts import contacts_bp, init_contacts
from routes.groups import groups_bp, init_groups
from routes.wallet import wallet_bp, init_wallet_routes
from routes.files import files_bp, init_files

init_messages(blockchain, lottery, socketio)
init_contacts(blockchain)
init_groups(blockchain)
init_wallet_routes(blockchain)
init_files(blockchain)

app.register_blueprint(auth_bp)
app.register_blueprint(messages_bp)
app.register_blueprint(contacts_bp)
app.register_blueprint(groups_bp)
app.register_blueprint(wallet_bp)
app.register_blueprint(files_bp)

# ── WebSocket ────────────────────────────────────────────────────────────────
@socketio.on('connect')
def handle_connect():
    if 'address' not in session:
        return False
    join_room(session['address'])
    return True

# ── Before-request: глобальная авторизация ───────────────────────────────────
_PUBLIC_ENDPOINTS = frozenset([
    'auth.index', 'auth.login', 'auth.create_wallet', 'static', 'files.serve_upload',
])

@app.before_request
def require_auth():
    if 'address' in session:
        session.modified = True
    if request.endpoint and request.endpoint not in _PUBLIC_ENDPOINTS:
        if 'address' not in session:
            return jsonify({'error': 'Unauthorized'}), 401

# ── Запуск ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    is_production = os.getenv('FLASK_ENV') == 'production'
    socketio.run(
        app,
        host='127.0.0.1' if is_production else '0.0.0.0',
        port=5000,
        debug=not is_production,
    )