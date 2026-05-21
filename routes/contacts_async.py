"""routes/contacts_async.py — Асинхронные CRUD контактов"""
import json
import logging
from typing import List, Dict, Optional

from quart import Blueprint, jsonify, request

from database_async import db
from redis_manager import redis_manager
from config_async import MAX_CONTACT_NAME_LENGTH

logger = logging.getLogger(__name__)
contacts_bp = Blueprint('contacts', __name__)


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

async def _invalidate_contact_caches(user_address: str) -> None:
    """Инвалидирует кэш контактов пользователя"""
    await redis_manager.cache_delete(f"contacts:{user_address}")


async def _get_cached_pubkey(address: str) -> Optional[str]:
    """Получает публичный ключ из кэша Redis"""
    return await redis_manager.cache_get(f"pubkey:{address}")


async def _get_contact_name(user_address: str, contact_address: str) -> Optional[str]:
    """Получает имя контакта из БД"""
    row = await db.fetch_one("""
        SELECT contact_name FROM contacts
        WHERE user_address = $1 AND contact_address = $2
    """, user_address, contact_address)
    return row['contact_name'] if row else None


# =============================================================================
# GET CONTACTS
# =============================================================================

@contacts_bp.route('/get_contacts', methods=['GET'])
async def get_contacts():
    """
    Получить список всех контактов пользователя.
    Результат кэшируется в Redis на 60 секунд.
    """
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    # Пытаемся получить из кэша
    cache_key = f"contacts:{user_address}"
    cached = await redis_manager.cache_get(cache_key)
    if cached is not None:
        return jsonify({'contacts': cached}), 200

    # Получаем из БД
    rows = await db.fetch_all("""
        SELECT contact_address, contact_name, created_at
        FROM contacts
        WHERE user_address = $1
        ORDER BY contact_name COLLATE "C"
    """, user_address)

    contacts = []
    for row in rows:
        # Получаем публичный ключ контакта из кэша
        pubkey = await _get_cached_pubkey(row['contact_address'])

        contacts.append({
            'address': row['contact_address'],
            'name': row['contact_name'],
            'pubkey': pubkey,
            'pubkey_verified': bool(pubkey),
            'created_at': row['created_at'].isoformat() if row['created_at'] else None
        })

    # Сохраняем в кэш на 60 секунд
    await redis_manager.cache_set(cache_key, contacts, ttl=60)

    return jsonify({'contacts': contacts}), 200


@contacts_bp.route('/get_contact/<string:contact_address>', methods=['GET'])
async def get_contact(contact_address: str):
    """
    Получить информацию о конкретном контакте.
    """
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    if len(contact_address) != 64:
        return jsonify({'error': 'Invalid address'}), 400

    # Получаем контакт из БД
    contact = await db.fetch_one("""
        SELECT contact_address, contact_name, created_at
        FROM contacts
        WHERE user_address = $1 AND contact_address = $2
    """, user_address, contact_address)

    if not contact:
        return jsonify({'error': 'Contact not found'}), 404

    pubkey = await _get_cached_pubkey(contact_address)

    return jsonify({
        'address': contact['contact_address'],
        'name': contact['contact_name'],
        'pubkey': pubkey,
        'pubkey_verified': bool(pubkey),
        'created_at': contact['created_at'].isoformat() if contact['created_at'] else None
    }), 200


# =============================================================================
# ADD CONTACT
# =============================================================================

@contacts_bp.route('/add_contact', methods=['POST'])
async def add_contact():
    """
    Добавить контакт.
    Тело запроса: {"address": "...", "name": "Имя"}
    """
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    contact_address = data.get('address', '').strip()
    contact_name = data.get('name', '').strip()

    # Валидация адреса
    if len(contact_address) != 64:
        return jsonify({'error': 'Invalid address format (must be 64 hex chars)'}), 400

    # Валидация имени
    if not contact_name:
        contact_name = contact_address[:10] + '...'

    if len(contact_name) > MAX_CONTACT_NAME_LENGTH:
        return jsonify({
            'error': f'Name too long (max {MAX_CONTACT_NAME_LENGTH})'
        }), 400

    # Нельзя добавить себя
    if contact_address == user_address:
        return jsonify({'error': 'Cannot add yourself as a contact'}), 400

    try:
        await db.execute("""
            INSERT INTO contacts (user_address, contact_address, contact_name, created_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (user_address, contact_address) DO UPDATE SET
                contact_name = EXCLUDED.contact_name,
                created_at = NOW()
        """, user_address, contact_address, contact_name)

        # Инвалидируем кэш
        await _invalidate_contact_caches(user_address)

        logger.info(f"➕ Contact added: {user_address[:10]}... → {contact_address[:10]}... ({contact_name})")
        return jsonify({'message': 'Contact added'}), 201

    except Exception as e:
        logger.error(f"Add contact error: {e}")
        return jsonify({'error': 'Failed to add contact'}), 500


@contacts_bp.route('/add_contact_from_chat', methods=['POST'])
async def add_contact_from_chat():
    """
    Добавить контакт из чата (упрощённая версия).
    Тело запроса: {"contact_address": "...", "contact_name": "..."}
    """
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    contact_address = data.get('contact_address', '').strip()
    contact_name = data.get('contact_name', '').strip()

    if len(contact_address) != 64:
        return jsonify({'error': 'Invalid address format (must be 64 hex chars)'}), 400

    if not contact_name:
        contact_name = contact_address[:10] + '...'

    if contact_address == user_address:
        return jsonify({'error': 'Cannot add yourself'}), 400

    try:
        await db.execute("""
            INSERT INTO contacts (user_address, contact_address, contact_name, created_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (user_address, contact_address) DO NOTHING
        """, user_address, contact_address, contact_name)

        await _invalidate_contact_caches(user_address)

        logger.info(f"➕ Contact added from chat: {contact_address[:10]}...")
        return jsonify({'message': 'Contact added'}), 201

    except Exception as e:
        logger.error(f"Add contact from chat error: {e}")
        return jsonify({'error': 'Failed to add contact'}), 500


# =============================================================================
# DELETE CONTACT
# =============================================================================

@contacts_bp.route('/delete_contact', methods=['POST'])
async def delete_contact():
    """
    Удалить контакт.
    Тело запроса: {"address": "..."}
    """
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    contact_address = data.get('address', '').strip()

    if len(contact_address) != 64:
        return jsonify({'error': 'Invalid address format'}), 400

    result = await db.execute("""
        DELETE FROM contacts
        WHERE user_address = $1 AND contact_address = $2
    """, user_address, contact_address)

    # Инвалидируем кэш
    await _invalidate_contact_caches(user_address)

    if 'DELETE 1' in result:
        logger.info(f"➖ Contact deleted: {contact_address[:10]}...")
        return jsonify({'message': 'Contact deleted'}), 200

    return jsonify({'error': 'Contact not found'}), 404


# =============================================================================
# EDIT CONTACT
# =============================================================================

@contacts_bp.route('/edit_contact', methods=['POST'])
async def edit_contact():
    """
    Редактировать имя контакта.
    Тело запроса: {"address": "...", "name": "Новое имя"}
    """
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    contact_address = data.get('address', '').strip()
    new_name = data.get('name', '').strip()

    if len(contact_address) != 64:
        return jsonify({'error': 'Invalid address'}), 400

    if not new_name or len(new_name) > MAX_CONTACT_NAME_LENGTH:
        return jsonify({
            'error': f'Name must be 1-{MAX_CONTACT_NAME_LENGTH} characters'
        }), 400

    # Нельзя редактировать себя
    if user_address.lower() == contact_address.lower():
        return jsonify({'error': 'Cannot edit yourself as a contact'}), 400

    # Получаем старое имя
    old = await db.fetch_one("""
        SELECT contact_name FROM contacts
        WHERE user_address = $1 AND contact_address = $2
    """, user_address, contact_address)

    if not old:
        return jsonify({'error': 'Contact not found'}), 404

    if old['contact_name'] == new_name:
        return jsonify({'message': 'No changes', 'unchanged': True}), 200

    await db.execute("""
        UPDATE contacts SET contact_name = $1
        WHERE user_address = $2 AND contact_address = $3
    """, new_name, user_address, contact_address)

    # Инвалидируем кэш
    await _invalidate_contact_caches(user_address)

    logger.info(f"✏️ Contact renamed: {old['contact_name']} → {new_name}")

    return jsonify({
        'message': 'Contact updated',
        'old_name': old['contact_name'],
        'new_name': new_name
    }), 200


# =============================================================================
# SEARCH CONTACTS
# =============================================================================

@contacts_bp.route('/search_contacts', methods=['GET'])
async def search_contacts():
    """
    Поиск контактов по имени или адресу.
    Параметры: q - поисковый запрос, limit - максимум результатов
    """
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    query = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 20)), 50)

    if not query:
        return jsonify({'contacts': []}), 200

    # Поиск по имени или адресу
    rows = await db.fetch_all("""
        SELECT contact_address, contact_name, created_at
        FROM contacts
        WHERE user_address = $1
          AND (contact_name ILIKE $2 OR contact_address LIKE $3)
        ORDER BY contact_name COLLATE "C"
        LIMIT $4
    """, user_address, f'%{query}%', f'%{query}%', limit)

    contacts = []
    for row in rows:
        pubkey = await _get_cached_pubkey(row['contact_address'])
        contacts.append({
            'address': row['contact_address'],
            'name': row['contact_name'],
            'pubkey': pubkey,
            'pubkey_verified': bool(pubkey),
            'created_at': row['created_at'].isoformat() if row['created_at'] else None
        })

    return jsonify({'contacts': contacts}), 200