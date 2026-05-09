"""
routes/files.py — Загрузка файлов, удаление сообщений, очистка диалога, GunDB
"""
import base64
import logging
import os
import uuid

from flask import Blueprint, jsonify, request, send_from_directory, session
from marshmallow import ValidationError
from werkzeug.utils import secure_filename

from config import UPLOAD_FOLDER, CONFIG
from schemas import DeleteMessageSchema
from typing import Optional


logger   = logging.getLogger(__name__)
files_bp = Blueprint('files', __name__)

_blockchain = None


def init_files(blockchain) -> None:
    global _blockchain
    _blockchain = blockchain


# =============================================================================
# Валидация MIME по магическим байтам
# =============================================================================

IMAGE_MAGIC_BYTES = {
    b'\xFF\xD8\xFF':        'image/jpeg',
    b'\x89PNG\r\n\x1a\n':  'image/png',
    b'GIF87a':              'image/gif',
    b'GIF89a':              'image/gif',
    b'RIFF....WEBP':        'image/webp',
}


def validate_image_file(file_content: bytes) -> Optional[str]:
    for magic, mime_type in IMAGE_MAGIC_BYTES.items():
        if file_content.startswith(magic):
            return mime_type
    return None


# =============================================================================
# Маршруты
# =============================================================================

@files_bp.route('/upload_file', methods=['POST'])
def upload_file():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    filepath = None
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'Empty filename'}), 400

        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        if file_size > CONFIG['MAX_UPLOAD_SIZE']:
            return jsonify({'error': 'File too large'}), 413

        filename    = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        filepath    = os.path.join(UPLOAD_FOLDER, unique_name)
        file.save(filepath)

        with open(filepath, 'rb') as f:
            header = f.read(12)
        detected_mime = validate_image_file(header)
        declared_mime = file.content_type

        if declared_mime and declared_mime.startswith('image/'):
            if detected_mime and detected_mime != declared_mime:
                logger.warning(f"MIME mismatch: declared={declared_mime}, "
                               f"detected={detected_mime}")
            if detected_mime:
                with open(filepath, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode()
                os.remove(filepath)
                return jsonify({'file_url': f"{detected_mime};base64,{b64}"}), 200

        return jsonify({'file_url': f"/uploads/{unique_name}"}), 200

    except Exception as e:
        logger.error(f"Upload error: {e}")
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'error': 'Upload failed'}), 500


@files_bp.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@files_bp.route('/delete_message', methods=['POST'])
def delete_message():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data      = DeleteMessageSchema().load(request.get_json())
        user_addr = session['address']
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            cursor.execute('SELECT sender FROM transactions WHERE id = ?',
                           (data['message_id'],))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Message not found'}), 404
            if row[0] != user_addr:
                return jsonify({'error': 'Permission denied'}), 403
            cursor.execute('DELETE FROM transactions WHERE id = ?', (data['message_id'],))
        logger.info(f"Message #{data['message_id']} deleted by {user_addr[:16]}...")
        return jsonify({'message': 'Deleted'}), 200
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Delete message error: {e}")
        return jsonify({'error': 'Failed'}), 500


@files_bp.route('/clear_conversation', methods=['POST'])
def clear_conversation():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data      = request.get_json() or {}
        chat_with = data.get('chat_with', '').strip()
        if not chat_with:
            return jsonify({'error': 'Missing chat_with parameter'}), 400
        user_addr = session['address']
        from database import get_db_cursor
        with get_db_cursor(_blockchain.db_path) as cursor:
            if chat_with.startswith('group:'):
                cursor.execute(
                    'DELETE FROM transactions WHERE sender = ? AND recipient = ?',
                    (user_addr, chat_with)
                )
            else:
                cursor.execute(
                    'DELETE FROM transactions '
                    'WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)',
                    (user_addr, chat_with, chat_with, user_addr)
                )
            deleted = cursor.rowcount
        logger.info(f"Cleared {deleted} messages for {user_addr[:16]}... "
                    f"in {chat_with[:20]}...")
        return jsonify({'message': f'Cleared {deleted} messages'}), 200
    except Exception as e:
        logger.error(f"Clear conversation error: {e}")
        return jsonify({'error': 'Failed to clear'}), 500


@files_bp.route('/gun-config')
def gun_config():
    peers = [
        'https://gun.robins.one/gun',
        'https://relic.eastus.cloudapp.azure.com/gun',
        'https://gun-manhattan.herokuapp.com/gun',
        'https://gundb-relay-eb4x.onrender.com/gun',
        'https://gun-relay-7q2w.onrender.com/gun',
    ]
    return jsonify({'peers': peers, 'room_prefix': 'dm_v1:',
                    'version': '1.0', 'fallback': 'localStorage'})


try:
    from gun import Gun  # noqa: F401

    @files_bp.route('/gun', methods=['GET', 'POST', 'OPTIONS'])
    def gun_relay():
        if request.method == 'OPTIONS':
            return '', 204
        return jsonify({'ok': True})
except ImportError:
    pass
