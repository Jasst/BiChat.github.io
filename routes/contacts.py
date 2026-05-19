"""
routes/contacts.py — CRUD-маршруты для контактов
"""
import hmac
import logging

from flask import Blueprint, jsonify, request, session
from marshmallow import ValidationError

from cache import (bump_contact_cache_version, get_cached_public_key,
                    get_pubkey_cache_version)
from setup import ContactSchema, EditContactSchema
from services.contacts import add_contact, get_contacts, update_contact_name

logger      = logging.getLogger(__name__)
contacts_bp = Blueprint('contacts', __name__)

_blockchain = None


def init_contacts(blockchain) -> None:
    global _blockchain
    _blockchain = blockchain


@contacts_bp.route('/add_contact', methods=['POST'])
def add_contact_route():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = ContactSchema().load(request.get_json())
        if add_contact(session['address'], data['address'], data['name']):
            return jsonify({'message': 'Contact added'}), 201
        return jsonify({'error': 'Failed to add contact'}), 500
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Add contact error: {e}")
        return jsonify({'error': 'Server error'}), 500


@contacts_bp.route('/add_contact_from_chat', methods=['POST'])
def add_contact_from_chat():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        raw              = request.get_json() or {}
        contact_address  = raw.get('contact_address', '').strip()
        contact_name     = raw.get('contact_name', '').strip()
        if not contact_address or len(contact_address) != 64:
            return jsonify({'error': 'Invalid address format (must be 64 hex chars)'}), 400
        if not contact_name:
            contact_name = contact_address[:10] + '...'
        if add_contact(session['address'], contact_address, contact_name):
            logger.info(f"Contact {contact_address[:16]}... added from chat")
            return jsonify({'message': 'Contact added'}), 201
        return jsonify({'error': 'Failed to save to database'}), 500
    except Exception as e:
        logger.error(f"add_contact_from_chat error: {e}", exc_info=True)
        return jsonify({'error': 'Server error'}), 500


@contacts_bp.route('/get_contacts', methods=['GET'])
def get_contacts_route():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        user_addr     = session['address']
        user_contacts = get_contacts(user_addr)
        for contact in user_contacts:
            if not contact.get('pubkey'):
                try:
                    pubkey, verified      = get_cached_public_key(
                        contact['address'], cache_version=get_pubkey_cache_version())
                    contact['pubkey']          = pubkey
                    contact['pubkey_verified'] = verified
                except Exception:
                    contact['pubkey']          = None
                    contact['pubkey_verified'] = False
        return jsonify({'contacts': user_contacts}), 200
    except Exception as e:
        logger.error(f"❌ Get contacts error: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': f'Failed: {type(e).__name__}'}), 500


@contacts_bp.route('/delete_contact', methods=['POST'])
def delete_contact_route():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data            = request.get_json() or {}
        contact_address = data.get('address', '').strip()
        if not contact_address or len(contact_address) != 64:
            return jsonify({'error': 'Invalid address format'}), 400
        user_addr = session['address']
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute(
                'DELETE FROM contacts WHERE user_address = ? AND contact_address = ?',
                (user_addr, contact_address)
            )
            deleted = cursor.rowcount
        bump_contact_cache_version()
        if deleted:
            logger.info(f"Contact {contact_address[:16]}... deleted by {user_addr[:16]}...")
            return jsonify({'message': 'Contact deleted'}), 200
        return jsonify({'error': 'Contact not found'}), 404
    except Exception as e:
        logger.error(f"Delete contact error: {e}")
        return jsonify({'error': 'Failed to delete contact'}), 500


@contacts_bp.route('/edit_contact', methods=['POST'])
def edit_contact_route():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data            = EditContactSchema().load(request.get_json(silent=True) or {})
        user_addr       = session['address']
        contact_address = data['address']
        new_name        = data['name']
        if hmac.compare_digest(user_addr, contact_address):
            return jsonify({'error': 'Cannot edit yourself as a contact'}), 400
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute(
                'SELECT contact_name FROM contacts '
                'WHERE user_address = ? AND contact_address = ?',
                (user_addr, contact_address)
            )
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Contact not found'}), 404
            old_name = row[0]
        if old_name == new_name:
            return jsonify({'message': 'No changes', 'unchanged': True}), 200
        if update_contact_name(user_addr, contact_address, new_name):
            return jsonify({'message': 'Contact name updated',
                            'old_name': old_name, 'new_name': new_name}), 200
        return jsonify({'error': 'Failed to update contact name'}), 500
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"❌ edit_contact error: {type(e).__name__}: {e}")
        return jsonify({'error': 'Internal server error'}), 500
