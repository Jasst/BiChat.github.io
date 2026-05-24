"""
routes/files.py — Загрузка файлов, удаление сообщений, очистка диалога
"""
import base64
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from config import UPLOAD_FOLDER, CONFIG
from dependencies import require_auth
from models import DeleteMessageRequest, ClearConversationRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=['files'])

_blockchain = None


def init_files(blockchain) -> None:
    global _blockchain
    _blockchain = blockchain


# =============================================================================
# Image validation via magic bytes
# =============================================================================

IMAGE_MAGIC_BYTES = {
    b'\xFF\xD8\xFF':       'image/jpeg',
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'GIF87a':             'image/gif',
    b'GIF89a':             'image/gif',
}


def validate_image_file(content: bytes) -> Optional[str]:
    for magic, mime_type in IMAGE_MAGIC_BYTES.items():
        if content.startswith(magic):
            return mime_type
    return None


# =============================================================================
# Routes
# =============================================================================

@router.post('/upload_file')
async def upload_file(
    file: UploadFile = File(...),
    address: str = Depends(require_auth),
):
    ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    ALLOWED_MIMES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}

    filepath = None
    try:
        content = await file.read()
        if len(content) > CONFIG['MAX_UPLOAD_SIZE']:
            raise HTTPException(413, 'File too large')
        if not file.filename:
            raise HTTPException(400, 'Empty filename')

        # 1. Проверка MIME по содержимому
        detected_mime = validate_image_file(content[:12])
        if not detected_mime:
            raise HTTPException(400, 'Only image files are allowed')

        # 2. Проверка заявленного MIME (если есть)
        if file.content_type and file.content_type not in ALLOWED_MIMES:
            raise HTTPException(400, 'Invalid image MIME type')

        # 3. Проверка расширения
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, 'Unsupported file extension')

        # 4. Безопасное имя файла (без расширения)
        safe_name = uuid.uuid4().hex
        filepath = os.path.join(UPLOAD_FOLDER, safe_name)

        with open(filepath, 'wb') as f:
            f.write(content)

        # 5. Возвращаем ссылку на файл (можно также вернуть base64, но безопаснее ссылку)
        return {'file_url': f"/uploads/{safe_name}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
        raise HTTPException(500, 'Upload failed')


@router.get('/uploads/{filename}')
def serve_upload(filename: str, address: str = Depends(require_auth)):  # <-- добавить auth
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, 'File not found')

    # Проверим MIME по содержимому
    with open(filepath, 'rb') as f:
        content = f.read(12)
    mime = validate_image_file(content)
    if not mime:
        raise HTTPException(403, 'Forbidden')

    return FileResponse(filepath, media_type=mime, headers={
        'Content-Disposition': 'inline' if mime.startswith('image/') else 'attachment'
    })


@router.post('/delete_message')
def delete_message(body: DeleteMessageRequest, address: str = Depends(require_auth)):
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute('SELECT sender FROM transactions WHERE id = ?', (body.message_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, 'Message not found')
        if row[0] != address:
            raise HTTPException(403, 'Permission denied')
        cursor.execute('DELETE FROM transactions WHERE id = ?', (body.message_id,))

    logger.info(f"Message #{body.message_id} deleted by {address[:16]}...")
    return {'message': 'Deleted'}


@router.post('/clear_conversation')
def clear_conversation(body: ClearConversationRequest, address: str = Depends(require_auth)):
    chat_with = body.chat_with.strip()
    if not chat_with:
        raise HTTPException(400, 'Missing chat_with parameter')

    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        if chat_with.startswith('group:'):
            cursor.execute(
                'DELETE FROM transactions WHERE sender = ? AND recipient = ?',
                (address, chat_with)
            )
        else:
            cursor.execute(
                'DELETE FROM transactions '
                'WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)',
                (address, chat_with, chat_with, address)
            )
        deleted = cursor.rowcount

    logger.info(f"Cleared {deleted} messages for {address[:16]}... in {chat_with[:20]}...")
    return {'message': f'Cleared {deleted} messages'}