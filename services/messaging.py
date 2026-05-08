"""
services/messaging.py — Расшифровка сообщений и список диалогов
"""
import json
import logging
from typing import Any, Dict, List, Optional

from cache import (
    get_cached_public_key, get_pubkey_cache_version,
    get_contact_name_cached, get_contact_cache_version,
    get_user_groups_cached, get_groups_cache_version,
    fetch_public_key_from_chain, cache_public_key,
)
from crypto_manager import (
    decrypt_hybrid, decrypt_message_aead,
    compute_shared_key_b64, generate_symmetric_key,
    verify_address_matches_pubkey,
)

logger = logging.getLogger(__name__)

_db_path: Optional[str] = None


def set_db_path(path: str) -> None:
    global _db_path
    _db_path = path


def _db():
    from database import get_db_cursor
    return get_db_cursor(_db_path)


# =============================================================================
# Расшифровка одного сообщения
# =============================================================================

def decrypt_message_safe(key: bytes, encrypted_data: Optional[str],
                         fallback: str = "[Decryption Failed]") -> Optional[str]:
    if not encrypted_data:
        return None
    return decrypt_message_aead(key, encrypted_data, fallback=fallback)


def process_message_decryption(msg: Dict, user_address: str, mnemonic: str) -> Dict:
    result = msg.copy()
    try:
        # ── Групповое сообщение ─────────────────────────────────────────────
        if msg['recipient'].startswith('group:'):
            group_id   = msg['recipient'].split(':', 1)[1]
            groups     = get_user_groups_cached(user_address,
                                                cache_version=get_groups_cache_version())
            user_group = next((g for g in groups if g['id'] == group_id), None)
            if not user_group or user_address not in user_group['members']:
                result.update({'content': "[No access to group]", 'image': None})
                return result

            try:
                encrypted_data = (json.loads(msg['content'])
                                  if isinstance(msg['content'], str)
                                  else msg['content'])
            except json.JSONDecodeError:
                result.update({'content': "[Invalid JSON in group message]", 'image': None})
                return result

            if user_address not in encrypted_data:
                result.update({'content': "[Message not available for you]", 'image': None})
                return result

            user_data   = encrypted_data[user_address]
            msg_sender  = msg['sender']
            aad         = msg_sender.encode('utf-8')
            sender_pubkey = msg.get('sender_pubkey')
            if not sender_pubkey:
                sender_pubkey, _ = get_cached_public_key(msg_sender,
                                                         cache_version=get_pubkey_cache_version())
            if not sender_pubkey:
                sender_pubkey, _ = fetch_public_key_from_chain(msg_sender)
            if not sender_pubkey:
                result.update({'content': "[Waiting for sender key exchange...]", 'image': None})
                result['encryption_type'] = 'group-ecdh-pending'
                return result

            try:
                key = compute_shared_key_b64(mnemonic, sender_pubkey, msg_sender)
            except Exception as e:
                logger.error(f"❌ Group ECDH key derivation failed: {e}")
                result.update({'content': "[Decryption Failed]", 'image': None})
                return result

            result['content'] = decrypt_message_aead(key, user_data.get('content'),
                                                      associated_data=aad)
            result['image']   = (decrypt_message_aead(key, user_data.get('image'),
                                                       associated_data=aad)
                                  if user_data.get('image') else None)
            result['encryption_type'] = 'group-ecdh-v4'
            result['group_id']        = group_id
            return result

        # ── P2P сообщение ───────────────────────────────────────────────────
        payload    = None
        raw_content = msg['content']
        if isinstance(raw_content, str):
            try:
                parsed = json.loads(raw_content)
                if isinstance(parsed, dict) and parsed.get('version') in (
                        'hybrid-v1', 'hybrid-v2', 'key_exchange'):
                    payload = parsed
            except json.JSONDecodeError:
                pass
        elif isinstance(raw_content, dict):
            if raw_content.get('version') in ('hybrid-v1', 'hybrid-v2', 'key_exchange'):
                payload = raw_content

        if payload and payload.get('version') == 'key_exchange':
            result.update({
                'content': "[Key exchange request — waiting for response]",
                'image': None,
                'encryption_type': 'key_exchange',
                'peer_pubkey': payload.get('my_pubkey'),
            })
            return result

        if payload and payload.get('version') in ('hybrid-v1', 'hybrid-v2'):
            if not payload.get('enc_session_key'):
                logger.warning("⚠️ Hybrid payload missing enc_session_key!")
                payload = None
            else:
                if msg['sender'] == user_address:
                    peer_address  = msg['recipient']
                    peer_pubkey, peer_verified = get_cached_public_key(
                        peer_address, cache_version=get_pubkey_cache_version())
                    if not peer_pubkey:
                        peer_pubkey, peer_verified = fetch_public_key_from_chain(peer_address)
                else:
                    peer_address  = msg['sender']
                    peer_pubkey   = msg.get('sender_pubkey')
                    peer_verified = False
                    if peer_pubkey:
                        peer_verified = verify_address_matches_pubkey(peer_address, peer_pubkey)
                    if not peer_pubkey:
                        peer_pubkey, peer_verified = get_cached_public_key(
                            peer_address, cache_version=get_pubkey_cache_version())
                    if not peer_pubkey:
                        peer_pubkey, peer_verified = fetch_public_key_from_chain(peer_address)

                if not peer_pubkey:
                    result.update({'content': "[Waiting for key exchange...]",
                                   'image': None,
                                   'encryption_type': payload.get('version')})
                    return result

                cache_public_key(peer_address, peer_pubkey, verified=peer_verified)
                try:
                    decrypted         = decrypt_hybrid(mnemonic, peer_pubkey,
                                                       peer_address, payload)
                    result['content'] = decrypted.get('content') or "[Decryption Failed]"
                    result['image']   = decrypted.get('image')
                    result['encryption_type'] = payload.get('version')
                    result['key_verified']    = peer_verified
                except Exception as e:
                    logger.error(f"❌ decrypt_hybrid failed: {e}")
                    result['content'] = "[Decryption Error]"
                    result['image']   = None
                return result

        # ── Legacy fallback ─────────────────────────────────────────────────
        peer_addr = (msg['sender'] if msg['sender'] != user_address
                     else msg['recipient'])
        peer_pubkey, _ = get_cached_public_key(peer_addr,
                                               cache_version=get_pubkey_cache_version())
        if peer_pubkey:
            try:
                shared_key = compute_shared_key_b64(mnemonic, peer_pubkey, peer_addr)
                content    = decrypt_message_aead(shared_key, msg['content'])
                if content and content != "[Decryption Failed]":
                    result['content']         = content
                    result['image']           = (decrypt_message_aead(shared_key, msg['image'])
                                                 if msg.get('image') else None)
                    result['encryption_type'] = 'legacy-ecdh'
                    return result
            except Exception:
                pass

        try:
            key               = generate_symmetric_key(msg['sender'], msg['recipient'], mnemonic)
            result['content'] = decrypt_message_safe(key, msg['content'])
            result['image']   = decrypt_message_safe(key, msg['image'])
            result['encryption_type'] = 'legacy-symmetric'
            return result
        except Exception:
            pass

        result.update({'content': "[Decryption Failed]", 'image': None,
                       'encryption_type': 'unknown'})
        return result

    except Exception as e:
        logger.error(f"❌ CRITICAL: {type(e).__name__}: {e}", exc_info=True)
        result.update({'content': '[System Error]', 'image': None, 'error': str(e)[:100]})
        return result


# =============================================================================
# Список диалогов
# =============================================================================

def get_conversations_list(user_address: str) -> List[Dict[str, Any]]:
    conversations: Dict[str, Dict] = {}
    try:
        with _db() as cursor:
            cursor.execute('''
                SELECT
                    CASE WHEN sender = :addr THEN recipient ELSE sender END AS partner,
                    content, image, timestamp, sender, id
                FROM transactions
                WHERE (sender = :addr OR recipient = :addr)
                  AND NOT (sender = :addr AND recipient = :addr)
                ORDER BY timestamp DESC
            ''', {'addr': user_address})

            seen_partners: set = set()
            for row in cursor.fetchall():
                partner, raw_content, raw_image, ts, msg_sender, msg_id = row
                if partner == user_address or partner in seen_partners:
                    continue
                seen_partners.add(partner)

                cursor.execute(
                    'SELECT last_read_message_id FROM read_status '
                    'WHERE user_address = ? AND chat_id = ?',
                    (user_address, partner)
                )
                read_row     = cursor.fetchone()
                last_read_id = read_row[0] if read_row else 0

                preview = ("✓ Прочитано" if last_read_id >= msg_id
                           else ("Вы: 💬 Сообщение" if msg_sender == user_address
                                 else "💬 Новое сообщение"))

                if partner.startswith('group:'):
                    group_id = partner.split(':', 1)[1]
                    groups   = get_user_groups_cached(
                        user_address, cache_version=get_groups_cache_version())
                    group    = next((g for g in groups if g['id'] == group_id), None)
                    name     = group['name'] if group else f'Группа {group_id[:8]}...'
                    is_group = True
                else:
                    name     = (get_contact_name_cached(
                        user_address, partner,
                        cache_version=get_contact_cache_version())
                                or partner[:10] + "...")
                    is_group = False

                conversations[partner] = {
                    'address':      partner,
                    'name':         name,
                    'is_group':     is_group,
                    'last_preview': preview,
                    'last_ts':      ts,
                }
    except Exception as e:
        logger.error(f"Get conversations error: {e}")

    return sorted(conversations.values(),
                  key=lambda x: x.get('last_ts', 0), reverse=True)
