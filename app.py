"""
app.py — Точка входа: создание Flask-приложения, регистрация blueprint'ов, старт.
"""
import os
from datetime import timedelta

from flask import jsonify, request, session
from flask.sessions import SecureCookieSessionInterface
from flask_compress import Compress

from config import (CONFIG, DATABASE_PATH, MAX_CONTENT_LENGTH,
                    SECRET_KEY, STATIC_FOLDER, TEMPLATE_FOLDER, UPLOAD_FOLDER)
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

# Инициализируем стейкинг-менеджер (возвращает объект StakingManager или None, если отключён)
import services.wallet
staking_manager = services.wallet.init_wallet_service(DATABASE_PATH, blockchain)

# ── Blueprint'ы ──────────────────────────────────────────────────────────────
from routes.auth import auth_bp
from routes.messages import messages_bp, init_messages
from routes.contacts import contacts_bp, init_contacts
from routes.groups import groups_bp, init_groups
from routes.wallet import wallet_bp, init_wallet_routes
from routes.files import files_bp, init_files

# Инициализация маршрутов: сообщения без отдельного объекта лотереи (списание fee идёт через staking_manager)
init_messages(blockchain)           # изменено: убран второй аргумент
init_contacts(blockchain)
# Если groups или files используют staking_manager, нужно передать его:
init_groups(blockchain)            # при необходимости добавить staking_manager вторым параметром
init_wallet_routes(blockchain)
init_files(blockchain)             # аналогично

app.register_blueprint(auth_bp)
app.register_blueprint(messages_bp)
app.register_blueprint(contacts_bp)
app.register_blueprint(groups_bp)
app.register_blueprint(wallet_bp)
app.register_blueprint(files_bp)

# ── Before-request: глобальная авторизация ───────────────────────────────────
_PUBLIC_ENDPOINTS = frozenset([
    'auth.index', 'auth.login', 'auth.create_wallet', 'static', 'files.serve_upload','auth.logout',
])

@app.before_request
def require_auth():
    if 'address' in session:
        session.modified = True
    if request.endpoint and request.endpoint not in _PUBLIC_ENDPOINTS:
        if 'address' not in session:
            return jsonify({'error': 'Unauthorized'}), 401

@app.after_request
def add_cache_headers(response):
    # Запрещаем кэширование для страниц с nonce, чтобы после логаута браузер
    # всегда загружал свежую копию, а не закэшированную с устаревшим nonce.
    if request.path in ['/', '/login', '/create_wallet']:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# ── Запуск (для локального тестирования) ───────────────────────────────────
if __name__ == '__main__':
    is_production = os.getenv('FLASK_ENV') == 'production'
    app.run(
        host='127.0.0.1' if is_production else '0.0.0.0',
        port=5000,
        debug=not is_production,
    )