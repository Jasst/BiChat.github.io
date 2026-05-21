"""app_async.py — Асинхронное Quart приложение для высоконагруженного сервера"""
import asyncio
import logging
import os
from datetime import datetime

from quart import Quart, jsonify, request, make_response, render_template
from quart_cors import cors
from werkzeug.middleware.proxy_fix import ProxyFix

from config_async import SECRET_KEY, UPLOAD_FOLDER, MAX_UPLOAD_SIZE
from database_async import db
from redis_manager import redis_manager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# КАСТОМНЫЙ КЛАСС ПРИЛОЖЕНИЯ
# =============================================================================

class CustomQuart(Quart):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config['PROVIDE_AUTOMATIC_OPTIONS'] = False


app = CustomQuart(__name__)
app = cors(app, allow_origin=[
    "https://blockcoin.ru",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
])

app.config.update(
    SECRET_KEY=SECRET_KEY,
    UPLOAD_FOLDER=str(UPLOAD_FOLDER),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_SIZE,
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

_start_time = None


# =============================================================================
# LIFECYCLE HOOKS
# =============================================================================

@app.before_serving
async def startup():
    global _start_time
    _start_time = datetime.now()
    logger.info("=" * 50)
    logger.info("🚀 Starting Dark Messenger Async Server...")
    logger.info("=" * 50)

    await db.init()
    logger.info("✅ PostgreSQL connected")

    await redis_manager.connect()
    logger.info("✅ Redis connected")

    logger.info("=" * 50)
    logger.info("✅ Server ready!")
    logger.info("📍 Listening on http://127.0.0.1:8000")
    logger.info("=" * 50)


@app.after_serving
async def shutdown():
    logger.info("🛑 Shutting down...")
    await db.close()
    await redis_manager.close()
    logger.info("✅ Goodbye!")


# =============================================================================
# MIDDLEWARE
# =============================================================================

@app.before_request
async def before_request():
    """Проверка авторизации для защищённых эндпоинтов"""
    PUBLIC_PATHS = {
        '/', '/health', '/health/db', '/health/redis', '/metrics', '/health/ping',
        '/login', '/login/nonce', '/create_wallet',
        '/static', '/uploads',
    }
    PUBLIC_BLUEPRINTS = {
        'auth.login', 'auth.get_nonce', 'auth.create_wallet',
        'auth.index', 'auth.chat', 'auth.contacts_page',
        'auth.groups_page', 'auth.profile', 'auth.wallet_page',
    }

    if request.path in PUBLIC_PATHS:
        return
    if request.endpoint and request.endpoint in PUBLIC_BLUEPRINTS:
        return

    session_id = request.cookies.get('session_id')
    if not session_id:
        return jsonify({'error': 'Unauthorized'}), 401

    user_data = await redis_manager.session_get_all(session_id)
    if not user_data.get('address'):
        return jsonify({'error': 'Unauthorized'}), 401

    request.user_address = user_data['address']
    request.session_id = session_id


@app.after_request
async def after_request(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# =============================================================================
# HEALTH CHECKS
# =============================================================================

async def get_uptime() -> float:
    if _start_time:
        return (datetime.now() - _start_time).total_seconds()
    return 0


@app.route('/health')
async def health_check():
    db_health = await db.health_check()
    redis_stats = await redis_manager.get_stats()

    db_ok = db_health.get('status') == 'healthy'
    redis_ok = redis_stats.get('connected', False)

    if db_ok and redis_ok:
        status, http_status = 'healthy', 200
    elif db_ok or redis_ok:
        status, http_status = 'degraded', 200
    else:
        status, http_status = 'unhealthy', 503

    return jsonify({
        'status': status,
        'service': 'dark-messenger',
        'version': '2.0.0-async',
        'database': db_health,
        'redis': redis_stats,
        'uptime_seconds': await get_uptime(),
        'timestamp': datetime.now().isoformat(),
    }), http_status


@app.route('/health/db')
async def health_db():
    return jsonify(await db.health_check()), 200


@app.route('/health/redis')
async def health_redis():
    stats = await redis_manager.get_stats()
    return jsonify(stats), 200 if stats.get('connected') else 503


@app.route('/metrics')
async def metrics():
    db_health = await db.health_check()
    redis_stats = await redis_manager.get_stats()
    session_keys = await redis_manager.client.keys("session:*")

    return jsonify({
        'service': 'dark-messenger',
        'version': '2.0.0-async',
        'uptime_seconds': await get_uptime(),
        'database': {
            'connected': db_health.get('status') == 'healthy',
            'size_mb': db_health.get('db_size_mb', 0),
            'transactions': db_health.get('table_counts', {}).get('transactions', 0),
            'wallets': db_health.get('table_counts', {}).get('wallets', 0),
        },
        'redis': {
            'connected': redis_stats.get('connected', False),
            'used_memory': redis_stats.get('used_memory', 'N/A'),
            'keys': redis_stats.get('keys', 0),
            'active_sessions': len(session_keys) if session_keys else 0,
        },
    }), 200


@app.route('/health/ping', methods=['GET', 'HEAD'])
async def ping():
    return '', 200


# =============================================================================
# ОБРАБОТКА ОШИБОК
# =============================================================================

@app.errorhandler(404)
async def not_found(error):
    return jsonify({'error': 'Not found', 'path': request.path, 'method': request.method}), 404


@app.errorhandler(500)
async def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({
        'error': 'Internal server error',
        'message': str(error) if app.debug else 'An error occurred',
    }), 500


@app.errorhandler(429)
async def rate_limit_error(error):
    return jsonify({'error': 'Too many requests',
                    'message': 'Please slow down and try again later',
                    'retry_after': 60}), 429


@app.errorhandler(401)
async def unauthorized_error(error):
    return jsonify({'error': 'Unauthorized'}), 401


@app.errorhandler(403)
async def forbidden_error(error):
    return jsonify({'error': 'Forbidden'}), 403


# =============================================================================
# ИМПОРТ РОУТОВ
#
# FIX: в оригинале было `from routes.auth_async import auth_bp` и т.д.
# Это предполагало подпакет routes/, которого нет.
# Если файлы лежат рядом с app_async.py — используем прямой импорт (ниже).
# Если вы хотите сохранить структуру routes/, создайте папку routes/ с
# __init__.py и переместите туда файлы *_async.py.
# =============================================================================

from auth_async import auth_bp          # noqa: E402
from messages_async import messages_bp  # noqa: E402
from contacts_async import contacts_bp  # noqa: E402
from groups_async import groups_bp      # noqa: E402
from wallet_async import wallet_bp      # noqa: E402
from status_async import status_bp      # noqa: E402
from files_async import files_bp        # noqa: E402

app.register_blueprint(auth_bp)
app.register_blueprint(messages_bp)
app.register_blueprint(contacts_bp)
app.register_blueprint(groups_bp)
app.register_blueprint(wallet_bp)
app.register_blueprint(status_bp)
app.register_blueprint(files_bp)

logger.info("✅ All blueprints registered")


# =============================================================================
# ЗАПУСК
# =============================================================================

if __name__ == '__main__':
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='Dark Messenger Async Server')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--reload', action='store_true')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    if args.port < 1024 and sys.platform != 'win32':
        print("⚠️  Warning: Ports below 1024 require root/admin privileges")

    from hypercorn.config import Config
    from hypercorn.asyncio import serve

    config = Config()
    config.bind = [f"{args.host}:{args.port}"]
    config.workers = args.workers
    config.worker_class = "asyncio"
    config.keep_alive_timeout = 30
    config.graceful_timeout = 30
    config.loglevel = "info"
    config.accesslog = "-"
    config.errorlog = "-"

    if args.reload:
        config.reload = True
        config.workers = 1
        config.loglevel = "debug"

    if args.debug:
        app.debug = True
        config.loglevel = "debug"

    print(f"\n{'=' * 60}")
    print("🚀 Dark Messenger Async Server")
    print(f"{'=' * 60}")
    print(f"📍 Host:    {args.host}")
    print(f"🔌 Port:    {args.port}")
    print(f"👥 Workers: {config.workers}")
    print(f"🔄 Reload:  {args.reload}")
    print(f"🐛 Debug:   {args.debug}")
    print(f"{'=' * 60}")
    print(f"🌐 Server URL:    http://{args.host}:{args.port}")
    print(f"❤️  Health check: http://{args.host}:{args.port}/health")
    print(f"{'=' * 60}\n")

    try:
        asyncio.run(serve(app, config))
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
    except Exception as e:
        print(f"\n❌ Server error: {e}")
        sys.exit(1)