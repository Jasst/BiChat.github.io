"""routes/groups_async.py — Асинхронные групповые чаты (CRUD)"""
import json
import logging
import uuid
from typing import List

from quart import Blueprint, jsonify, request

from database_async import db
from redis_manager import redis_manager
from config_async import MAX_GROUP_MEMBERS, MAX_GROUP_NAME_LENGTH

logger = logging.getLogger(__name__)
groups_bp = Blueprint('groups', __name__)


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

async def _invalidate_group_caches(group_id: str, members: List[str]) -> None:
    """Инвалидирует кэши групп для всех участников"""
    for member in members:
        await redis_manager.cache_delete(f"groups:{member}")
    await redis_manager.cache_delete(f"group:{group_id}")


async def _check_group_access(group_id: str, user_address: str) -> bool:
    """Проверяет, имеет ли пользователь доступ к группе"""
    group = await db.fetch_one(
        "SELECT members FROM groups WHERE id = $1", group_id
    )
    if not group:
        return False
    members = json.loads(group['members'])
    return user_address in members


async def _get_group_members(group_id: str) -> List[str]:
    """Получает список участников группы"""
    group = await db.fetch_one(
        "SELECT members FROM groups WHERE id = $1", group_id
    )
    if not group:
        return []
    return json.loads(group['members'])


# =============================================================================
# GET GROUPS
# =============================================================================

@groups_bp.route('/get_groups', methods=['GET'])
async def get_groups():
    """
    Получить список всех групп, в которых состоит пользователь.
    Результат кэшируется в Redis на 30 секунд.

    FIX: раньше загружались ВСЕ группы и фильтровались в Python (O(N)).
    Теперь фильтрация происходит в SQL через оператор @> (contains) JSONB.
    """
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    cache_key = f"groups:{user_address}"
    cached = await redis_manager.cache_get(cache_key)
    if cached is not None:
        return jsonify({'groups': cached}), 200

    # FIX: фильтрация по членству прямо в SQL
    rows = await db.fetch_all("""
        SELECT id, name, creator, members, created_at
        FROM groups
        WHERE members::jsonb @> jsonb_build_array($1::text)
        ORDER BY created_at DESC
    """, user_address)

    groups = [
        {
            'id': row['id'],
            'name': row['name'],
            'creator': row['creator'],
            'members': json.loads(row['members']),
            'member_count': len(json.loads(row['members'])),
            'created_at': row['created_at'].isoformat() if row['created_at'] else None,
        }
        for row in rows
    ]

    await redis_manager.cache_set(cache_key, groups, ttl=30)
    return jsonify({'groups': groups}), 200


@groups_bp.route('/get_group/<string:group_id>', methods=['GET'])
async def get_group(group_id: str):
    """Получить информацию о конкретной группе."""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    if len(group_id) != 32:
        return jsonify({'error': 'Invalid group ID'}), 400

    if not await _check_group_access(group_id, user_address):
        return jsonify({'error': 'Access denied'}), 403

    cache_key = f"group:{group_id}"
    cached = await redis_manager.cache_get(cache_key)
    if cached:
        return jsonify({'group': cached}), 200

    group = await db.fetch_one("""
        SELECT id, name, creator, members, created_at FROM groups WHERE id = $1
    """, group_id)

    if not group:
        return jsonify({'error': 'Group not found'}), 404

    members = json.loads(group['members'])
    result = {
        'id': group['id'],
        'name': group['name'],
        'creator': group['creator'],
        'members': members,
        'member_count': len(members),
        'created_at': group['created_at'].isoformat() if group['created_at'] else None,
    }

    await redis_manager.cache_set(cache_key, result, ttl=30)
    return jsonify({'group': result}), 200


# =============================================================================
# CREATE GROUP
# =============================================================================

@groups_bp.route('/create_group', methods=['POST'])
async def create_group():
    """
    Создать новую группу.
    Тело запроса: {"name": "Название", "members": ["addr1", "addr2", ...]}
    """
    session_id = request.cookies.get('session_id')
    creator = await redis_manager.session_get(session_id, 'address')

    if not creator:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    name = data.get('name', '').strip()
    members = [m.strip() for m in data.get('members', []) if m.strip()]

    if not name or len(name) > MAX_GROUP_NAME_LENGTH:
        return jsonify({'error': f'Name must be 1-{MAX_GROUP_NAME_LENGTH} characters'}), 400

    if len(members) > MAX_GROUP_MEMBERS:
        return jsonify({'error': f'Maximum {MAX_GROUP_MEMBERS} members'}), 400

    members_set = set(members)
    members_set.add(creator)
    members_clean = sorted(members_set)

    invalid = [m for m in members_clean if len(m) != 64]
    if invalid:
        return jsonify({'error': f'Invalid addresses: {invalid[:3]}'}), 400

    group_id = uuid.uuid4().hex

    await db.execute("""
        INSERT INTO groups (id, name, creator, members, created_at)
        VALUES ($1, $2, $3, $4, NOW())
    """, group_id, name, creator, json.dumps(members_clean))

    await _invalidate_group_caches(group_id, members_clean)

    logger.info(f"👥 Group '{name}' created by {creator[:10]}... with {len(members_clean)} members")

    return jsonify({
        'message': 'Group created',
        'group_id': group_id,
        'name': name,
        'members': members_clean,
        'member_count': len(members_clean),
    }), 201


# =============================================================================
# DELETE GROUP
# =============================================================================

@groups_bp.route('/delete_group', methods=['POST'])
async def delete_group():
    """Удалить группу (только создатель)."""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    group_id = data.get('group_id', '').strip()

    if not group_id or len(group_id) != 32:
        return jsonify({'error': 'Invalid group ID'}), 400

    group = await db.fetch_one(
        "SELECT name, creator, members FROM groups WHERE id = $1", group_id
    )

    if not group:
        return jsonify({'error': 'Group not found'}), 404

    if group['creator'] != user_address:
        return jsonify({'error': 'Only creator can delete group'}), 403

    await db.execute("DELETE FROM groups WHERE id = $1", group_id)

    members = json.loads(group['members'])
    await _invalidate_group_caches(group_id, members)

    logger.info(f"🗑️ Group '{group['name']}' deleted by {user_address[:10]}...")

    return jsonify({
        'message': 'Group deleted',
        'group_id': group_id,
        'group_name': group['name'],
    }), 200


# =============================================================================
# RENAME GROUP
# =============================================================================

@groups_bp.route('/rename_group', methods=['POST'])
async def rename_group():
    """Переименовать группу (только создатель)."""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    group_id = data.get('group_id', '').strip()
    new_name = data.get('name', '').strip()

    if not group_id or len(group_id) != 32:
        return jsonify({'error': 'Invalid group ID'}), 400

    if not new_name or len(new_name) > MAX_GROUP_NAME_LENGTH:
        return jsonify({'error': f'Name must be 1-{MAX_GROUP_NAME_LENGTH} characters'}), 400

    group = await db.fetch_one(
        "SELECT creator, members FROM groups WHERE id = $1", group_id
    )

    if not group:
        return jsonify({'error': 'Group not found'}), 404

    if group['creator'] != user_address:
        return jsonify({'error': 'Only creator can rename'}), 403

    await db.execute("UPDATE groups SET name = $1 WHERE id = $2", new_name, group_id)

    members = json.loads(group['members'])
    await _invalidate_group_caches(group_id, members)

    logger.info(f"✏️ Group {group_id[:8]} renamed to '{new_name}'")

    return jsonify({'message': 'Group renamed', 'name': new_name}), 200


# =============================================================================
# ADD MEMBER
# =============================================================================

@groups_bp.route('/add_group_member', methods=['POST'])
async def add_group_member():
    """Добавить участника в группу (только создатель)."""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    group_id = data.get('group_id', '').strip()
    new_member = data.get('address', '').strip()

    if not group_id or len(group_id) != 32:
        return jsonify({'error': 'Invalid group ID'}), 400

    if len(new_member) != 64:
        return jsonify({'error': 'Invalid address (must be 64 hex chars)'}), 400

    group = await db.fetch_one(
        "SELECT creator, members FROM groups WHERE id = $1", group_id
    )

    if not group:
        return jsonify({'error': 'Group not found'}), 404

    if group['creator'] != user_address:
        return jsonify({'error': 'Only creator can add members'}), 403

    members = json.loads(group['members'])

    if new_member in members:
        return jsonify({'error': 'Already in group'}), 400

    if len(members) >= MAX_GROUP_MEMBERS:
        return jsonify({'error': f'Group limit ({MAX_GROUP_MEMBERS}) reached'}), 400

    members.append(new_member)
    members.sort()

    await db.execute(
        "UPDATE groups SET members = $1 WHERE id = $2",
        json.dumps(members), group_id
    )

    await _invalidate_group_caches(group_id, members)

    logger.info(f"👤 {new_member[:10]}... added to group {group_id[:8]}")

    return jsonify({
        'message': 'Member added',
        'members': members,
        'member_count': len(members),
    }), 200


# =============================================================================
# REMOVE MEMBER
# =============================================================================

@groups_bp.route('/remove_group_member', methods=['POST'])
async def remove_group_member():
    """Удалить участника из группы (только создатель)."""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    group_id = data.get('group_id', '').strip()
    target = data.get('address', '').strip()

    if not group_id or len(group_id) != 32:
        return jsonify({'error': 'Invalid group ID'}), 400

    if len(target) != 64:
        return jsonify({'error': 'Invalid address'}), 400

    group = await db.fetch_one(
        "SELECT creator, members FROM groups WHERE id = $1", group_id
    )

    if not group:
        return jsonify({'error': 'Group not found'}), 404

    if group['creator'] != user_address:
        return jsonify({'error': 'Only creator can remove members'}), 403

    if target == group['creator']:
        return jsonify({'error': 'Creator cannot be removed'}), 400

    members = json.loads(group['members'])

    if target not in members:
        return jsonify({'error': 'Address not in group'}), 404

    if len(members) <= 2:
        return jsonify({'error': 'Group must have at least 2 members'}), 400

    members.remove(target)

    await db.execute(
        "UPDATE groups SET members = $1 WHERE id = $2",
        json.dumps(members), group_id
    )

    await _invalidate_group_caches(group_id, members + [target])

    logger.info(f"👋 {target[:10]}... removed from group {group_id[:8]}")

    return jsonify({
        'message': 'Member removed',
        'members': members,
        'member_count': len(members),
    }), 200


# =============================================================================
# LEAVE GROUP
# =============================================================================

@groups_bp.route('/leave_group', methods=['POST'])
async def leave_group():
    """Выйти из группы (самостоятельно)."""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    group_id = data.get('group_id', '').strip()

    if not group_id or len(group_id) != 32:
        return jsonify({'error': 'Invalid group ID'}), 400

    group = await db.fetch_one(
        "SELECT creator, members FROM groups WHERE id = $1", group_id
    )

    if not group:
        return jsonify({'error': 'Group not found'}), 404

    members = json.loads(group['members'])

    if user_address not in members:
        return jsonify({'error': 'Not a member of this group'}), 400

    if group['creator'] == user_address:
        return jsonify({'error': 'Creator cannot leave, delete group instead'}), 400

    if len(members) <= 2:
        return jsonify({'error': 'Cannot leave, group would have only 1 member'}), 400

    members.remove(user_address)

    await db.execute(
        "UPDATE groups SET members = $1 WHERE id = $2",
        json.dumps(members), group_id
    )

    await _invalidate_group_caches(group_id, members + [user_address])

    logger.info(f"🚪 {user_address[:10]}... left group {group_id[:8]}")

    return jsonify({
        'message': 'Left group',
        'members': members,
        'member_count': len(members),
    }), 200