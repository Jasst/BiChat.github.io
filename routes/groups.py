"""
routes/groups.py — CRUD-маршруты групповых чатов
"""
import json
import logging
import time
import uuid

from flask import Blueprint, jsonify, request, session
from marshmallow import ValidationError

from cache import bump_groups_cache_version, get_groups_cache_version, get_user_groups_cached
from setup import GroupSchema

logger    = logging.getLogger(__name__)
groups_bp = Blueprint('groups', __name__)

_blockchain = None


def init_groups(blockchain) -> None:
    global _blockchain
    _blockchain = blockchain


@groups_bp.route('/get_groups', methods=['GET'])
def get_groups():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        groups = get_user_groups_cached(session['address'],
                                        cache_version=get_groups_cache_version())
        return jsonify({'groups': groups}), 200
    except Exception as e:
        logger.error(f"Get groups error: {e}")
        return jsonify({'error': 'Failed to load groups'}), 500


@groups_bp.route('/create_group', methods=['POST'])
def create_group():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data    = GroupSchema().load(request.get_json())
        creator = session['address']
        name    = data['name'].strip()
        members_set   = {m.strip() for m in data['members'] if m.strip()}
        members_set.add(creator)
        members_clean = sorted(members_set)
        invalid = [m for m in members_clean if len(m) != 64]
        if invalid:
            return jsonify({'error': f'Invalid member addresses: {invalid[:3]}'}), 400
        group_id = uuid.uuid4().hex
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute(
                'INSERT INTO groups (id, name, creator, members, created_at) VALUES (?, ?, ?, ?, ?)',
                (group_id, name, creator, json.dumps(members_clean), time.time())
            )
        bump_groups_cache_version()
        logger.info(f"Group '{name}' created by {creator[:16]}... with {len(members_clean)} members")
        return jsonify({
            'message': 'Group created', 'group_id': group_id, 'name': name,
            'members': members_clean, 'member_count': len(members_clean),
        }), 201
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Create group error: {e}")
        return jsonify({'error': 'Failed to create group'}), 500


@groups_bp.route('/delete_group', methods=['POST'])
def delete_group():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data     = request.get_json(silent=True) or {}
        group_id = data.get('group_id', '').strip()
        if not group_id or len(group_id) != 32:
            return jsonify({'error': 'Invalid group ID format'}), 400
        user_addr = session['address']
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute('SELECT id, name, creator FROM groups WHERE id = ?', (group_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Group not found'}), 404
            if row[2] != user_addr:
                return jsonify({'error': 'Only the group creator can delete this group'}), 403
            group_name = row[1]
            cursor.execute('DELETE FROM groups WHERE id = ?', (group_id,))
        bump_groups_cache_version()
        logger.info(f"Group '{group_name}' (ID: {group_id}) deleted by {user_addr[:16]}...")
        return jsonify({'message': 'Group deleted', 'group_id': group_id,
                        'group_name': group_name}), 200
    except Exception as e:
        logger.error(f"Delete group error: {type(e).__name__}")
        return jsonify({'error': 'Failed to delete group'}), 500


@groups_bp.route('/rename_group', methods=['POST'])
def rename_group():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data     = request.get_json(silent=True) or {}
        group_id = data.get('group_id', '').strip()
        new_name = data.get('name', '').strip()
        if not group_id or len(group_id) != 32:
            return jsonify({'error': 'Invalid group ID'}), 400
        if not new_name or len(new_name) > 100:
            return jsonify({'error': 'Name must be 1–100 characters'}), 400
        user_addr = session['address']
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute('SELECT creator FROM groups WHERE id = ?', (group_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Group not found'}), 404
            if row[0] != user_addr:
                return jsonify({'error': 'Only the creator can rename this group'}), 403
            cursor.execute('UPDATE groups SET name = ? WHERE id = ?', (new_name, group_id))
        bump_groups_cache_version()
        logger.info(f"Group {group_id} renamed to '{new_name}' by {user_addr[:16]}...")
        return jsonify({'message': 'Group renamed', 'name': new_name}), 200
    except Exception as e:
        logger.error(f"Rename group error: {type(e).__name__}")
        return jsonify({'error': 'Failed to rename group'}), 500


@groups_bp.route('/add_group_member', methods=['POST'])
def add_group_member():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data       = request.get_json(silent=True) or {}
        group_id   = data.get('group_id', '').strip()
        new_member = data.get('address', '').strip()
        if not group_id or len(group_id) != 32:
            return jsonify({'error': 'Invalid group ID'}), 400
        if not new_member or len(new_member) != 64:
            return jsonify({'error': 'Invalid address (must be 64 hex chars)'}), 400
        user_addr = session['address']
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute('SELECT creator, members FROM groups WHERE id = ?', (group_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Group not found'}), 404
            if row[0] != user_addr:
                return jsonify({'error': 'Only the creator can add members'}), 403
            members = json.loads(row[1])
            if new_member in members:
                return jsonify({'error': 'Address already in group'}), 400
            if len(members) >= 50:
                return jsonify({'error': 'Group member limit (50) reached'}), 400
            members.append(new_member)
            members.sort()
            cursor.execute('UPDATE groups SET members = ? WHERE id = ?',
                           (json.dumps(members), group_id))
        bump_groups_cache_version()
        logger.info(f"Member {new_member[:16]}... added to group {group_id} by {user_addr[:16]}...")
        return jsonify({'message': 'Member added', 'members': members}), 200
    except Exception as e:
        logger.error(f"Add group member error: {type(e).__name__}")
        return jsonify({'error': 'Failed to add member'}), 500


@groups_bp.route('/remove_group_member', methods=['POST'])
def remove_group_member():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data     = request.get_json(silent=True) or {}
        group_id = data.get('group_id', '').strip()
        target   = data.get('address', '').strip()
        if not group_id or len(group_id) != 32:
            return jsonify({'error': 'Invalid group ID'}), 400
        if not target or len(target) != 64:
            return jsonify({'error': 'Invalid address'}), 400
        user_addr = session['address']
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute('SELECT creator, members FROM groups WHERE id = ?', (group_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Group not found'}), 404
            creator = row[0]
            members = json.loads(row[1])
            if creator != user_addr:
                return jsonify({'error': 'Only the creator can remove members'}), 403
            if target == creator:
                return jsonify({'error': 'Creator cannot be removed'}), 400
            if target not in members:
                return jsonify({'error': 'Address not in group'}), 404
            if len(members) <= 2:
                return jsonify({'error': 'Group must have at least 2 members'}), 400
            members.remove(target)
            cursor.execute('UPDATE groups SET members = ? WHERE id = ?',
                           (json.dumps(members), group_id))
        bump_groups_cache_version()
        logger.info(f"Member {target[:16]}... removed from group {group_id} by {user_addr[:16]}...")
        return jsonify({'message': 'Member removed', 'members': members}), 200
    except Exception as e:
        logger.error(f"Remove group member error: {type(e).__name__}")
        return jsonify({'error': 'Failed to remove member'}), 500
