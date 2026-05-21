"""routes/files_async.py — Загрузка файлов (асинхронная версия)"""
import base64
import logging
import os
import uuid
from typing import Optional

from quart import Blueprint, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from config_async import UPLOAD_FOLDER, MAX_UPLOAD_SIZE
from database_async import db
from redis_manager import redis_manager

logger = logging.getLogger(__name__)
files_bp = Blueprint('files', __name__)

# =============================================================================
# Валидация MIME по магическим байтам
# =============================================================================

IMAGE_MAGIC_BYTES = {
    b'\xFF\xD8\xFF': 'image/jpeg',
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF....WEBP': 'image/webp',
}


def validate_image_file(file_content: bytes) -> Optional[str]:
    """Проверяет тип файла по магическим байтам"""
    for magic, mime_type in IMAGE_MAGIC_BYTES.items():
        if file_content.startswith(magic):
            return mime_type
    return None


# =============================================================================
# Маршруты
# =============================================================================

@files_bp.route('/upload_file', methods=['POST'])
async def upload_file():
    """Загрузка файла (асинхронная)"""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    filepath = None
    try:
        # Получаем файл
        files = await request.files
        if 'file' not in files:
            return jsonify({'error': 'No file provided'}), 400

        file = files['file']
        if not file.filename:
            return jsonify({'error': 'Empty filename'}), 400

        # Проверяем размер (асинхронно)
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        if file_size > MAX_UPLOAD_SIZE:
            return jsonify({'error': 'File too large'}), 413

        # Сохраняем файл
        filename = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, unique_name)

        # Асинхронное сохранение (в отдельном потоке)
        await file.save(filepath)

        # Проверяем MIME
        with open(filepath, 'rb') as f:
            header = f.read(12)

        detected_mime = validate_image_file(header)
        declared_mime = file.content_type

        # Для изображений возвращаем base64
        if declared_mime and declared_mime.startswith('image/'):
            if detected_mime and detected_mime != declared_mime:
                logger.warning(f"MIME mismatch: declared={declared_mime}, detected={detected_mime}")

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
async def serve_upload(filename):
    """Отдача загруженных файлов"""
    return await send_from_directory(str(UPLOAD_FOLDER), filename)


@files_bp.route('/delete_message', methods=['POST'])
async def delete_message():
    """Удаление сообщения"""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    message_id = data.get('message_id')

    if not message_id:
        return jsonify({'error': 'Missing message_id'}), 400

    # Проверяем, что сообщение принадлежит пользователю
    row = await db.fetch_one(
        "SELECT sender FROM transactions WHERE id = $1", message_id
    )

    if not row:
        return jsonify({'error': 'Message not found'}), 404

    if row['sender'] != user_address:
        return jsonify({'error': 'Permission denied'}), 403

    # Удаляем
    await db.execute("DELETE FROM transactions WHERE id = $1", message_id)

    logger.info(f"🗑️ Message {message_id} deleted by {user_address[:10]}")

    return jsonify({'message': 'Deleted'}), 200


@files_bp.route('/clear_conversation', methods=['POST'])
async def clear_conversation():
    """Очистка диалога"""
    session_id = request.cookies.get('session_id')
    user_address = await redis_manager.session_get(session_id, 'address')

    if not user_address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json() or {}
    chat_with = data.get('chat_with', '').strip()

    if not chat_with:
        return jsonify({'error': 'Missing chat_with parameter'}), 400

    if chat_with.startswith('group:'):
        # Удаляем сообщения в группе
        result = await db.execute("""
            DELETE FROM transactions 
            WHERE sender = $1 AND recipient = $2
        """, user_address, chat_with)
    else:
        # Удаляем диалог между двумя пользователями
        result = await db.execute("""
            DELETE FROM transactions 
            WHERE (sender = $1 AND recipient = $2) 
               OR (sender = $2 AND recipient = $1)
        """, user_address, chat_with)

    # Парсим количество удалённых строк
    deleted = int(result.split()[-1]) if result else 0

    logger.info(f"🧹 Cleared {deleted} messages for {user_address[:10]} with {chat_with[:20]}")

    return jsonify({'message': f'Cleared {deleted} messages'}), 200