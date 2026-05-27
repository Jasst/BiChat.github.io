"""
main.py — FastAPI-приложение (асинхронная версия с aiosqlite)
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from config import CONFIG, DATABASE_PATH, SECRET_KEY, STATIC_FOLDER, UPLOAD_FOLDER
from database import Blockchain, init_sqlite_optimizations, warmup_database
from setup import setup_logging, get_rate_limit_stats
from setup import balance_cache, contact_cache, group_cache

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting BiChat server (async mode)...")
    await init_sqlite_optimizations(DATABASE_PATH)
    blockchain = Blockchain(DATABASE_PATH)
    await blockchain.initialize_blockchain()
    await warmup_database(DATABASE_PATH)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    import cache as cache_module
    cache_module.set_db_path(DATABASE_PATH)

    import services.contacts as svc_contacts
    svc_contacts.set_db_path(DATABASE_PATH)

    import services.messaging as svc_messaging
    svc_messaging.set_db_path(DATABASE_PATH)

    import services.wallet as svc_wallet
    svc_wallet.init_wallet_service(DATABASE_PATH, blockchain)

    from routes.messages import init_messages
    from routes.contacts import init_contacts
    from routes.groups import init_groups
    from routes.wallet import init_wallet_routes
    from routes.files import init_files

    init_messages(blockchain)
    init_contacts(blockchain)
    init_groups(blockchain)
    init_wallet_routes(blockchain)
    init_files(blockchain)

    app.state.blockchain = blockchain
    logger.info("BiChat server started (async) ✅")
    yield

    logger.info("Shutting down...")
    await blockchain.close()
    logger.info("Shutdown complete")


app = FastAPI(
    title='BiChat Messenger API',
    version='2.0.0-async',
    lifespan=lifespan,
    docs_url='/api/docs',
    redoc_url='/api/redoc',
    openapi_url='/api/openapi.json',
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie='__Secure-session',
    max_age=CONFIG['SESSION_LIFETIME'],
    https_only=os.getenv('FLASK_ENV') == 'production',
    same_site='lax',
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={'error': 'Internal server error'})


if os.path.isdir(STATIC_FOLDER):
    app.mount('/static', StaticFiles(directory=STATIC_FOLDER), name='static')
if os.path.isdir(UPLOAD_FOLDER):
    app.mount('/uploads', StaticFiles(directory=UPLOAD_FOLDER), name='uploads')


from routes.auth import router as auth_router
from routes.messages import router as messages_router
from routes.contacts import router as contacts_router
from routes.groups import router as groups_router
from routes.wallet import router as wallet_router
from routes.files import router as files_router
from routes.status import router as status_router
from routes.ai_assistant import router as ai_router

app.include_router(auth_router)
app.include_router(messages_router)
app.include_router(contacts_router)
app.include_router(groups_router)
app.include_router(wallet_router)
app.include_router(files_router)
app.include_router(status_router)
app.include_router(ai_router)


@app.middleware('http')
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in ['/', '/login', '/create_wallet']:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


@app.get('/health', tags=['health'])
async def health_check(request: Request):
    blockchain: Blockchain = request.app.state.blockchain
    db_health = await blockchain.health_check()
    return {
        'status': 'ok' if db_health.get('status') == 'healthy' else 'degraded',
        'database': db_health,
        'rate_limits': get_rate_limit_stats(),
        'caches': {
            'balance': balance_cache.get_stats(),
            'contacts': contact_cache.get_stats(),
            'groups': group_cache.get_stats(),
        },
        'connection_pool_size': None,
    }


@app.get('/health/db', tags=['health'])
async def health_db(request: Request):
    return await request.app.state.blockchain.health_check()


@app.get('/health/performance', tags=['health'])
async def health_performance(request: Request):
    return await request.app.state.blockchain.get_performance_stats()


@app.get('/health/notifier', tags=['health'])
async def health_notifier():
    from services.notifier import message_notifier
    return {'status': 'ok', 'stats': await message_notifier.get_stats()}