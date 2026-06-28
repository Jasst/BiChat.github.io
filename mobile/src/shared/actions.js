// shared/actions.js — полностью адаптирован для React Native
// Вся логика отправки сообщений, файлов, записи аудио
// Все DOM-зависимости убраны, возвращают промисы и используют хранилище

import { storage } from '../utils/storage';
import DarkCrypto from './crypto-client';
import { getPubKey, ensureKeys, addMessageToCache } from './core';
import useChatStore from '../store/chatStore';
import useUserStore from '../store/userStore';
import { API_BASE_URL } from '../config/constants';

// ===================== Вспомогательные функции =====================

// Загрузка файла на сервер (зашифрованного)
export async function uploadEncryptedFile(file) {
  const { key, iv } = DarkCrypto.generateFileKeyAndIv();
  const fileData = await file.arrayBuffer();
  const encrypted = await DarkCrypto.encryptFile(new Uint8Array(fileData), key, iv);
  const blob = new Blob([encrypted], { type: 'application/octet-stream' });
  const formData = new FormData();
  formData.append('file', blob, 'encrypted.bin');
  const res = await fetch(`${API_BASE_URL}/upload_encrypted`, { method: 'POST', body: formData });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return {
    url: data.file_url,
    key: DarkCrypto.arrayBufferToBase64(key),
    iv: DarkCrypto.arrayBufferToBase64(iv)
  };
}

// ===================== Отправка сообщения =====================
export async function sendMessage(recipient, content, fileAttachment = null, isGroup = false, groupId = null) {
  const userStore = useUserStore.getState();
  const chatStore = useChatStore.getState();

  if (!content && !fileAttachment) {
    throw new Error('Enter message or attach file');
  }

  const keys = await ensureKeys();

  // Подготовка пейлоада
  let payload = {};
  const myAddress = userStore.address;

  if (isGroup && groupId) {
    // Получаем актуальных участников группы из хранилища или с сервера
    const members = chatStore.getGroupMembers(groupId) || [];
    if (!members.length) throw new Error('Group members not loaded');

    const encryptedMap = {};
    for (const addr of members) {
      const pubKeyB64 = await getPubKey(addr);
      const pubKeyBytes = DarkCrypto._fromBase64(pubKeyB64);
      const shared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, pubKeyBytes);
      let encryptedText = null;
      if (content) {
        const { ciphertext, iv: textIv } = await DarkCrypto.encryptAES(shared, content);
        encryptedText = { ciphertext: DarkCrypto._arrayBufferToBase64(ciphertext), iv: DarkCrypto._toBase64(textIv) };
      }
      let encFileKey = null, encFileIv = null;
      if (fileAttachment) {
        const fileKeyBuffer = DarkCrypto.base64ToArrayBuffer(fileAttachment.key);
        const fileIvBuffer = DarkCrypto.base64ToArrayBuffer(fileAttachment.iv);
        const encKey = await DarkCrypto.encryptAES(shared, DarkCrypto.arrayBufferToBase64(new Uint8Array(fileKeyBuffer)));
        const encIv = await DarkCrypto.encryptAES(shared, DarkCrypto.arrayBufferToBase64(new Uint8Array(fileIvBuffer)));
        encFileKey = { ciphertext: DarkCrypto._arrayBufferToBase64(encKey.ciphertext), iv: DarkCrypto._toBase64(encKey.iv) };
        encFileIv = { ciphertext: DarkCrypto._arrayBufferToBase64(encIv.ciphertext), iv: DarkCrypto._toBase64(encIv.iv) };
      }
      encryptedMap[addr] = {
        text: encryptedText,
        file_url: fileAttachment?.url,
        file_key: encFileKey,
        file_iv: encFileIv,
        file_type: fileAttachment?.type,
        sender_pubkey: DarkCrypto._toBase64(keys.compressedPubKey)
      };
      if (addr === myAddress) {
        encryptedMap[addr].self_text = content ? { ciphertext: encryptedText.ciphertext, iv: encryptedText.iv } : null;
        if (fileAttachment) {
          encryptedMap[addr].self_file_key = fileAttachment.key;
          encryptedMap[addr].self_file_iv = fileAttachment.iv;
        }
      }
    }
    payload = { message_type: 'group', group_id: groupId, encrypted_map: encryptedMap };
  } else {
    // Личный чат
    const pubRes = await fetch(`${API_BASE_URL}/get_public_key/${recipient}`);
    if (!pubRes.ok) throw new Error('Recipient public key not found');
    const pubData = await pubRes.json();
    const recipientPubKeyBytes = DarkCrypto._fromBase64(pubData.public_key);
    const shared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, recipientPubKeyBytes);
    let encryptedText = null;
    if (content) {
      const { ciphertext, iv } = await DarkCrypto.encryptAES(shared, content);
      encryptedText = { ciphertext: DarkCrypto._arrayBufferToBase64(ciphertext), iv: DarkCrypto._toBase64(iv) };
    }
    let encFileKey = null, encFileIv = null;
    if (fileAttachment) {
      const fileKeyBuffer = DarkCrypto.base64ToArrayBuffer(fileAttachment.key);
      const fileIvBuffer = DarkCrypto.base64ToArrayBuffer(fileAttachment.iv);
      const encKey = await DarkCrypto.encryptAES(shared, DarkCrypto.arrayBufferToBase64(new Uint8Array(fileKeyBuffer)));
      const encIv = await DarkCrypto.encryptAES(shared, DarkCrypto.arrayBufferToBase64(new Uint8Array(fileIvBuffer)));
      encFileKey = { ciphertext: DarkCrypto._arrayBufferToBase64(encKey.ciphertext), iv: DarkCrypto._toBase64(encKey.iv) };
      encFileIv = { ciphertext: DarkCrypto._arrayBufferToBase64(encIv.ciphertext), iv: DarkCrypto._toBase64(encIv.iv) };
    }
    const selfShared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, keys.compressedPubKey);
    let selfEncText = null, selfFileKey = null, selfFileIv = null;
    if (content) {
      const { ciphertext, iv } = await DarkCrypto.encryptAES(selfShared, content);
      selfEncText = { ciphertext: DarkCrypto._arrayBufferToBase64(ciphertext), iv: DarkCrypto._toBase64(iv) };
    }
    if (fileAttachment) {
      selfFileKey = fileAttachment.key;
      selfFileIv = fileAttachment.iv;
    }
    payload = {
      recipient: recipient,
      payload: {
        text: encryptedText,
        file_url: fileAttachment?.url,
        file_key: encFileKey,
        file_iv: encFileIv,
        file_type: fileAttachment?.type,
        sender_pubkey: DarkCrypto._toBase64(keys.compressedPubKey),
        self_text: selfEncText,
        self_file_key: selfFileKey,
        self_file_iv: selfFileIv
      },
      message_type: 'direct'
    };
  }

  const res = await fetch(`${API_BASE_URL}/send_message`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Send failed');

  // Создаём объект сообщения для локального добавления
  const sentMessage = {
    id: data.tx_id,
    sender: myAddress,
    recipient: recipient,
    content: content || '',
    timestamp: Date.now() / 1000,
    is_mine: true,
    status: 'sent',
    isDecrypted: true,
    fileUrl: fileAttachment?.url,
    fileKey: fileAttachment?.key,
    fileIv: fileAttachment?.iv,
    fileType: fileAttachment?.type
  };

  addMessageToCache(recipient, sentMessage);
  chatStore.addLocalMessage(recipient, sentMessage);
  chatStore.updateConversationPreview(recipient, content?.slice(0, 40) || '📎 File');

  return data;
}

// ===================== Запись аудио (заглушка для RN) =====================
// В React Native используется react-native-audio-record или expo-av
export async function startRecording() {
  console.warn('Audio recording not implemented for React Native');
}

export async function stopRecording() {
  console.warn('Audio recording stop not implemented');
}

// ===================== Сжатие изображений (заглушка для RN) =====================
// В React Native используйте библиотеку 'react-native-image-resizer'
export async function compressImage(dataUrl, maxWidth = 800, quality = 0.7) {
  console.warn('compressImage not implemented – returning original');
  return dataUrl;
}

// ===================== Обработка выбора файла (для RN) =====================
// В RN выбор файла делается через DocumentPicker или ImagePicker
export function handleFileSelection(file, type) {
  const maxSize = type === 'image' ? 10 * 1024 * 1024 : 2 * 1024 * 1024;
  if (file.size > maxSize) {
    throw new Error(`File too large (max ${maxSize / 1024 / 1024} MB)`);
  }
  const allowedTypes = type === 'image'
    ? ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
    : ['audio/webm', 'audio/mp4', 'audio/ogg'];
  if (!allowedTypes.includes(file.type)) {
    throw new Error(`Unsupported ${type} type`);
  }
  return { file, type };
}