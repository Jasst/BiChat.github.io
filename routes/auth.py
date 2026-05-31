"""
routes/auth.py — Регистрация, вход, выход (асинхронная версия)
"""
import logging
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from cache import cache_public_key, clear_all_caches
from config import AIRDROP_AMOUNT, TEMPLATE_FOLDER
from models import CreateWalletRequest, LoginRequest
from setup import verify_address_matches_pubkey, load_public_key_from_b64
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

logger = logging.getLogger(__name__)
router = APIRouter(tags=['auth'])
templates = Jinja2Templates(directory=TEMPLATE_FOLDER)


@router.get('/', response_class=HTMLResponse)
def index(request: Request):
    if request.session.get('address'):
        return RedirectResponse('/chat')
    return templates.TemplateResponse('index.html', {'request': request})


@router.get('/chat', response_class=HTMLResponse)
def chat(request: Request):
    if not request.session.get('address'):
        return RedirectResponse('/')
    return templates.TemplateResponse('chat.html', {
        'request': request,
        'address': request.session['address'],
    })


@router.get('/contacts', response_class=HTMLResponse)
def contacts_page(request: Request):
    if not request.session.get('address'):
        return RedirectResponse('/')
    return templates.TemplateResponse('contacts.html', {
        'request': request,
        'address': request.session['address'],
    })


@router.get('/groups', response_class=HTMLResponse)
def groups_page(request: Request):
    if not request.session.get('address'):
        return RedirectResponse('/')
    return templates.TemplateResponse('groups.html', {
        'request': request,
        'address': request.session['address'],
    })


@router.get('/profile', response_class=HTMLResponse)
def profile(request: Request):
    if not request.session.get('address'):
        return RedirectResponse('/')
    return templates.TemplateResponse('profile.html', {
        'request': request,
        'address': request.session['address'],
    })


@router.get('/wallet', response_class=HTMLResponse)
def wallet_page(request: Request):
    if not request.session.get('address'):
        return RedirectResponse('/')
    return templates.TemplateResponse('wallet.html', {
        'request': request,
        'address': request.session['address'],
    })


@router.post('/create_wallet', status_code=201)
async def create_wallet(body: CreateWalletRequest, request: Request):
    address = body.address
    pubkey_b64 = body.public_key
    if not verify_address_matches_pubkey(address, pubkey_b64):
        raise HTTPException(400, 'Public key does not match address')
    from database import get_db_cursor
    try:
        async with get_db_cursor() as cursor:
            await cursor.execute(
                'INSERT INTO wallets (address, balance) VALUES ($1, $2) '
                'ON CONFLICT(address) DO NOTHING',
                address, AIRDROP_AMOUNT
            )
            await cursor.execute(
                'INSERT INTO coin_transactions (tx_type, recipient, amount, timestamp) '
                'VALUES ($1, $2, $3, $4)',
                'airdrop', address, AIRDROP_AMOUNT, time.time()
            )
        request.session['address'] = address
        await cache_public_key(address, pubkey_b64, source='self', verified=True)
        logger.info(f"New wallet registered: {address[:16]}...")
        return {'address': address, 'public_key': pubkey_b64}
    except Exception as e:
        logger.error(f"Create wallet error: {e}")
        raise HTTPException(500, 'Wallet creation failed')


@router.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    nonce = secrets.token_hex(32)
    request.session['login_nonce'] = nonce
    return templates.TemplateResponse('login.html', {'request': request, 'nonce': nonce})


@router.post('/login')
async def login(body: LoginRequest, request: Request):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes
    nonce = request.session.pop('login_nonce', None)
    if not nonce:
        raise HTTPException(400, 'No challenge found. Refresh the page.')
    address = body.address
    pubkey_b64 = body.public_key
    signature_hex = body.signature.strip()
    if not verify_address_matches_pubkey(address, pubkey_b64):
        raise HTTPException(400, 'Public key does not match address')
    try:
        raw_signature = bytes.fromhex(signature_hex)
        if len(raw_signature) != 64:
            raise HTTPException(400, 'Invalid signature format (must be 64 bytes raw)')
        r = int.from_bytes(raw_signature[:32], 'big')
        s = int.from_bytes(raw_signature[32:], 'big')
        der_signature = encode_dss_signature(r, s)
        pubkey = load_public_key_from_b64(pubkey_b64)
        pubkey.verify(der_signature, nonce.encode('utf-8'), ec.ECDSA(hashes.SHA256()))
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Signature verification failed: {e}")
        raise HTTPException(403, 'Invalid signature')
    request.session['address'] = address
    await cache_public_key(address, pubkey_b64, source='self', verified=True)
    logger.info(f"User logged in: {address[:16]}...")
    return {'address': address}


@router.get('/check_session')
def check_session(request: Request):
    return {
        'authenticated': 'address' in request.session,
        'address': request.session.get('address'),
    }


@router.get('/logout')
async def logout(request: Request):
    await clear_all_caches()
    request.session.clear()
    return RedirectResponse('/')