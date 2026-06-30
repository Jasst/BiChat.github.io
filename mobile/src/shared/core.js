// shared/core.js — полностью адаптирован для React Native
// Вся логика работы с сообщениями, ключами, WebSocket, кешем, шифрованием

import { storage } from '../utils/storage';
import useUserStore from '../store/userStore';
import useChatStore from '../store/chatStore';
import DarkCrypto from './crypto-client';
import WebSocketClient from './WebSocketClient';
import { API_BASE_URL } from '../config/constants';
import * as Crypto from 'expo-crypto';
import { sha256 } from '@noble/hashes/sha256';
import { v4 as uuidv4 } from 'uuid';

// ===================== Глобальное состояние модуля =====================
let wsClient = null;
let pubKeyCache = new Map();
let _mnemonicResolveQueue = [];
let _restoringMnemonic = false;
let heartbeatInterval = null;
let statusPollingInterval = null;
let userStatusPollingInterval = null;
let _pendingCallHandled = false;

// ===================== Хелперы для получения хранилищ =====================
const getUserStore = () => useUserStore.getState();
const getChatStore = () => useChatStore.getState();

// ===================== Вспомогательные утилиты =====================
function arraysEqual(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

// ===================== Криптографические функции =====================
export async function getPubKey(address) {
  if (pubKeyCache.has(address)) return pubKeyCache.get(address);
  const res = await fetch(`${API_BASE_URL}/get_public_key/${address}`);
  if (!res.ok) throw new Error(`Public key not found for ${address}`);
  const data = await res.json();
  const pubKeyBytes = DarkCrypto._fromBase64(data.public_key);
  const hash = sha256(pubKeyBytes);
  const computedAddress = Array.from(hash).map(b => b.toString(16).padStart(2, '0')).join('');
  if (computedAddress !== address) {
    throw new Error(`Public key mismatch for ${address}`);
  }
  pubKeyCache.set(address, data.public_key);
  return data.public_key;
}

export async function ensureKeys() {
  let mnemonic = await storage.getItem('mnemonic');
  if (!mnemonic) {
    const restored = await restoreMnemonic();
    if (!restored) throw new Error('No mnemonic available');
    mnemonic = await storage.getItem('mnemonic');
  }
  const keys = await DarkCrypto.deriveKeyPair(mnemonic);
  return keys;
}

// ===================== Восстановление мнемоники (без UI) =====================
export async function restoreMnemonic() {
  let mnemonic = await storage.getItem('mnemonic');
  if (mnemonic) return true;

  const encrypted = await storage.getItem('encrypted_mnemonic');
  if (!encrypted) {
    return false;
  }

  const userStore = getUserStore();
  userStore.setNeedsUnlock(true, encrypted);
  return false;
}

// ===================== WebSocket =====================
export async function initWebSocket() {
  const userStore = getUserStore();
  const address = userStore.address;
  if (!address) {
    console.warn('No user address, WebSocket not initialized');
    return;
  }

  if (wsClient) {
    wsClient.disconnect();
    wsClient = null;
  }

  try {
    const keys = await ensureKeys();

    // ✅ Генерируем валидный UUID v4
    const nonce = uuidv4();

    const signatureArray = await DarkCrypto.signData(keys.signPrivateKey, nonce);
    const signatureHex = Array.from(new Uint8Array(signatureArray))
      .map(b => b.toString(16).padStart(2, '0')).join('');

    const WebSocketClientClass = require('./WebSocketClient').default || WebSocketClient;
    wsClient = new WebSocketClientClass({
      url: `${API_BASE_URL.replace('http', 'ws')}/ws`,
      onMessage: handleWebSocketMessage,
      onConnect: () => {
        console.log('✅ WebSocket connected');
        const chatStore = getChatStore();
        chatStore.loadConversations();
        handlePendingCall();
      },
      onDisconnect: () => console.warn('⚠️ WebSocket disconnected'),
      onError: (err) => console.error('WebSocket error:', err?.message || err),
    });
    wsClient.setAuth(address, signatureHex, nonce);
    wsClient.connect();
  } catch (err) {
    console.error('Failed to init WebSocket:', err?.message || err);
  }
}

export function getWsClient() {
  return wsClient;
}

// ===================== Обработка входящих сообщений WebSocket =====================
export async function handleWebSocketMessage(data) {
  if (data.error) {
    console.error('WS error:', data.error);
    return;
  }

  if (['incoming_call', 'call_answer', 'call_ice', 'call_hangup', 'call_reject'].includes(data.type)) {
    if (globalThis.CallManager) {
      globalThis.CallManager.handleCallSignal(data);
    } else {
      console.warn('CallManager not available');
    }
    return;
  }

  if (data.type === 'call_not_found') {
    console.warn('[WS] Call not found:', data.call_id);
    await storage.removeItem('pending_call_id');
    return;
  }

  if (data.type === 'message') {
    const decrypted = await processMessageDecryption(data);
    const chatId = decrypted.chatId;
    if (decrypted?.id) {
      addMessageToCache(chatId, decrypted);
    }
    if (!decrypted.is_mine) {
      fetch(`${API_BASE_URL}/message/${decrypted.id}/delivered`, { method: 'POST' }).catch(() => {});
    }
    const chatStore = getChatStore();
    chatStore.addIncomingMessage(decrypted);
    return;
  }

  if (data.type === 'status_update') {
    if (data.address && data.status) {
      const chatStore = getChatStore();
      chatStore.updateUserStatus(data.address, data.status);
    }
    return;
  }

  if (data.type === 'message_status') {
    const chatStore = getChatStore();
    chatStore.updateMessageStatus(data.message_id, data.status);
    return;
  }

  if (!data.chatId && data.sender && data.recipient) {
    const userStore = getUserStore();
    data.chatId = (data.sender === userStore.address) ? data.recipient : data.sender;
  }
  if (!data.chatId) return;

  const decrypted = await processMessageDecryption(data);
  const chatId = decrypted.chatId;
  if (decrypted && decrypted.id) addMessageToCache(chatId, decrypted);
  if (!decrypted.is_mine) {
    fetch(`${API_BASE_URL}/message/${decrypted.id}/delivered`, { method: 'POST' }).catch(() => {});
  }
  const chatStore = getChatStore();
  chatStore.addIncomingMessage(decrypted);
}

// ===================== Обработка входящего звонка из push =====================
export function handlePendingCall() {
  if (_pendingCallHandled) return;

  storage.getItem('pending_call_id').then(callId => {
    if (!callId) return;
    storage.removeItem('pending_call_id');

    if (wsClient && wsClient.isConnected) {
      console.log('[App] Sending get_call for', callId);
      wsClient.send({ type: 'get_call', call_id: callId });
      _pendingCallHandled = true;
    } else {
      console.warn('[App] WebSocket not ready, pending call will be retried on connect');
    }
  });
}

// ===================== Расшифровка входящих сообщений =====================
export async function processMessageDecryption(msg) {
  if (!msg.content) return msg;
  let content = msg.content;
  let image = msg.image;
  let fileUrl = null, fileKey = null, fileIv = null, fileType = null;
  const originalStatus = msg.status || (msg.is_mine ? 'sent' : null);

  try {
    const parsed = JSON.parse(content);
    const keys = await ensureKeys();
    const userStore = getUserStore();
    const myAddress = userStore.address;

    if (parsed.encrypted_map) {
      const myEnc = parsed.encrypted_map[myAddress];
      if (!myEnc) return { ...msg, content: '🔒 No access', status: originalStatus };

      const senderPubKeyBytes = DarkCrypto._fromBase64(myEnc.sender_pubkey);
      const isMine = arraysEqual(senderPubKeyBytes, keys.compressedPubKey);

      if (isMine && myEnc.self_text) {
        const selfShared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, keys.compressedPubKey);
        const ciphertext = DarkCrypto._base64ToArrayBuffer(myEnc.self_text.ciphertext);
        const iv = DarkCrypto._fromBase64(myEnc.self_text.iv);
        content = await DarkCrypto.decryptAES(selfShared, ciphertext, iv);
      } else if (myEnc.text) {
        const shared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, senderPubKeyBytes);
        const ciphertext = DarkCrypto._base64ToArrayBuffer(myEnc.text.ciphertext);
        const iv = DarkCrypto._fromBase64(myEnc.text.iv);
        content = await DarkCrypto.decryptAES(shared, ciphertext, iv);
      } else {
        content = '';
      }

      if (myEnc.file_url) {
        fileUrl = myEnc.file_url;
        fileType = myEnc.file_type;
        if (isMine && myEnc.self_file_key && myEnc.self_file_iv) {
          fileKey = myEnc.self_file_key;
          fileIv = myEnc.self_file_iv;
        } else if (myEnc.file_key && myEnc.file_iv) {
          const shared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, senderPubKeyBytes);
          const keyCipher = DarkCrypto._base64ToArrayBuffer(myEnc.file_key.ciphertext);
          const keyIv = DarkCrypto._fromBase64(myEnc.file_key.iv);
          const decKey = await DarkCrypto.decryptAES(shared, keyCipher, keyIv);
          const ivCipher = DarkCrypto._base64ToArrayBuffer(myEnc.file_iv.ciphertext);
          const ivIv = DarkCrypto._fromBase64(myEnc.file_iv.iv);
          const decIv = await DarkCrypto.decryptAES(shared, ivCipher, ivIv);
          fileKey = decKey;
          fileIv = decIv;
        }
      }

      const chatId = msg.recipient;
      return {
        ...msg,
        content,
        image,
        fileUrl,
        fileKey,
        fileIv,
        fileType,
        is_mine: isMine,
        chatId,
        isGroup: true,
        isDecrypted: true,
        status: originalStatus
      };
    }

    const senderPubKeyB64 = parsed.sender_pubkey || (parsed.myPubKey ? parsed.myPubKey : null);
    if (!senderPubKeyB64) {
      if (parsed.file_url) {
        fileUrl = parsed.file_url;
        fileType = parsed.file_type;
        if (parsed.self_file_key && parsed.self_file_iv) {
          fileKey = parsed.self_file_key;
          fileIv = parsed.self_file_iv;
        }
      }
      const chatId = msg.sender === myAddress ? msg.recipient : msg.sender;
      return {
        ...msg,
        content: '🔒 No sender pubkey',
        image: null,
        fileUrl,
        fileKey,
        fileIv,
        fileType,
        is_mine: false,
        chatId,
        isDecrypted: false,
        status: originalStatus
      };
    }

    const senderPubKeyBytes = DarkCrypto._fromBase64(senderPubKeyB64);
    const isMine = arraysEqual(senderPubKeyBytes, keys.compressedPubKey);

    let decryptedText = '';
    if (parsed.text && parsed.text.ciphertext && parsed.text.iv) {
      if (isMine && parsed.self_text && parsed.self_text.ciphertext) {
        const selfShared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, keys.compressedPubKey);
        const ciphertext = DarkCrypto._base64ToArrayBuffer(parsed.self_text.ciphertext);
        const iv = DarkCrypto._fromBase64(parsed.self_text.iv);
        decryptedText = await DarkCrypto.decryptAES(selfShared, ciphertext, iv);
      } else {
        const shared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, senderPubKeyBytes);
        const ciphertext = DarkCrypto._base64ToArrayBuffer(parsed.text.ciphertext);
        const iv = DarkCrypto._fromBase64(parsed.text.iv);
        decryptedText = await DarkCrypto.decryptAES(shared, ciphertext, iv);
      }
      content = decryptedText;
    } else if (parsed.ciphertext && parsed.iv) {
      if (isMine && parsed.self_text && parsed.self_text.ciphertext) {
        const selfShared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, keys.compressedPubKey);
        const ciphertext = DarkCrypto._base64ToArrayBuffer(parsed.self_text.ciphertext);
        const iv = DarkCrypto._fromBase64(parsed.self_text.iv);
        decryptedText = await DarkCrypto.decryptAES(selfShared, ciphertext, iv);
      } else {
        const shared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, senderPubKeyBytes);
        const ciphertext = DarkCrypto._base64ToArrayBuffer(parsed.ciphertext);
        const iv = DarkCrypto._fromBase64(parsed.iv);
        decryptedText = await DarkCrypto.decryptAES(shared, ciphertext, iv);
      }
      content = decryptedText;
    } else {
      content = '';
    }

    if (parsed.file_url) {
      fileUrl = parsed.file_url;
      fileType = parsed.file_type;
      if (isMine && parsed.self_file_key && parsed.self_file_iv) {
        fileKey = parsed.self_file_key;
        fileIv = parsed.self_file_iv;
      } else if (parsed.file_key && parsed.file_iv) {
        const shared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, senderPubKeyBytes);
        const keyCipher = DarkCrypto._base64ToArrayBuffer(parsed.file_key.ciphertext);
        const keyIv = DarkCrypto._fromBase64(parsed.file_key.iv);
        const decKey = await DarkCrypto.decryptAES(shared, keyCipher, keyIv);
        const ivCipher = DarkCrypto._base64ToArrayBuffer(parsed.file_iv.ciphertext);
        const ivIv = DarkCrypto._fromBase64(parsed.file_iv.iv);
        const decIv = await DarkCrypto.decryptAES(shared, ivCipher, ivIv);
        fileKey = decKey;
        fileIv = decIv;
      }
    }

    const chatId = msg.sender === myAddress ? msg.recipient : msg.sender;
    return {
      ...msg,
      content,
      image: null,
      fileUrl,
      fileKey,
      fileIv,
      fileType,
      is_mine: isMine,
      chatId,
      isDecrypted: true,
      status: originalStatus
    };
  } catch (e) {
    console.error('Decryption error', msg.id, e?.message || e);
    const userStore = getUserStore();
    const chatId = msg.sender === userStore.address ? msg.recipient : msg.sender;
    return {
      ...msg,
      content: '🔒 Decrypt error',
      image: null,
      chatId,
      isDecrypted: false,
      status: originalStatus
    };
  }
}

// ===================== Кеш сообщений (в памяти) =====================
const messagesCache = new Map();
const messageIdSets = new Map();

export function addMessageToCache(chatId, message) {
  if (!chatId || !message || !message.id) return;
  let idSet = messageIdSets.get(chatId);
  let messages = messagesCache.get(chatId);
  if (!messages) {
    messages = [];
    messagesCache.set(chatId, messages);
    idSet = new Set();
    messageIdSets.set(chatId, idSet);
  }
  if (idSet.has(message.id)) return;
  idSet.add(message.id);
  messages.push(message);
  messages.sort((a, b) => a.id - b.id);
}

export function addMessagesToCache(chatId, newMessages, position = 'end') {
  if (!chatId || !newMessages?.length) return;
  let idSet = messageIdSets.get(chatId);
  let messages = messagesCache.get(chatId);
  if (!messages) {
    messages = [];
    messagesCache.set(chatId, messages);
    idSet = new Set();
    messageIdSets.set(chatId, idSet);
  }
  if (position === 'start') {
    messages.unshift(...newMessages);
  } else {
    messages.push(...newMessages);
  }
  const unique = new Map();
  for (const msg of messages) unique.set(msg.id, msg);
  const sorted = Array.from(unique.values()).sort((a, b) => a.id - b.id);
  messagesCache.set(chatId, sorted);
  messageIdSets.set(chatId, new Set(sorted.map(m => m.id)));
}

export function getCachedMessages(chatId) {
  return messagesCache.get(chatId) || [];
}

export function clearMessageCache(chatId) {
  if (chatId) {
    messagesCache.delete(chatId);
    messageIdSets.delete(chatId);
  } else {
    messagesCache.clear();
    messageIdSets.clear();
  }
}

// ===================== Heartbeat =====================
export function startHeartbeat() {
  if (heartbeatInterval) clearInterval(heartbeatInterval);
  heartbeatInterval = setInterval(async () => {
    const userStore = getUserStore();
    if (!userStore.address) return;
    try {
      await fetch(`${API_BASE_URL}/heartbeat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_chat: userStore.currentChatAddress || '' })
      });
    } catch (e) {
      // ignore
    }
  }, 30000);
}

export function stopHeartbeat() {
  if (heartbeatInterval) {
    clearInterval(heartbeatInterval);
    heartbeatInterval = null;
  }
}

// ===================== Поллинг статусов сообщений =====================
export function startStatusPolling() {
  if (statusPollingInterval) clearInterval(statusPollingInterval);
  statusPollingInterval = setInterval(async () => {
    const chatStore = getChatStore();
    const myMessages = chatStore.getMyPendingMessages();
    const ids = myMessages.map(m => m.id).filter(id => !String(id).startsWith('temp'));
    if (ids.length === 0) return;
    try {
      const res = await fetch(`${API_BASE_URL}/message/statuses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids })
      });
      if (!res.ok) return;
      const statuses = await res.json();
      for (const [id, st] of Object.entries(statuses)) {
        chatStore.updateMessageStatus(Number(id), st);
      }
    } catch (e) {
      // ignore
    }
  }, 30000);
}

export function stopStatusPolling() {
  if (statusPollingInterval) {
    clearInterval(statusPollingInterval);
    statusPollingInterval = null;
  }
}

// ===================== Поллинг статусов пользователей =====================
export async function fetchUserStatuses(addresses) {
  if (!addresses.length) return {};
  try {
    const res = await fetch(`${API_BASE_URL}/get_many_statuses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ addresses })
    });
    const data = await res.json();
    return data.statuses || {};
  } catch (err) {
    console.warn('Failed to fetch statuses:', err?.message || err);
    return {};
  }
}

export async function pollUserStatuses() {
  const chatStore = getChatStore();
  const conversations = chatStore.conversations || [];
  const addresses = conversations
    .filter(c => !c.is_group && c.address && c.address !== chatStore.myAddress)
    .map(c => c.address);
  if (addresses.length === 0) return;
  const statuses = await fetchUserStatuses(addresses);
  for (const [addr, st] of Object.entries(statuses)) {
    chatStore.updateUserStatus(addr, st.status || 'offline');
  }
}

export function startUserStatusPolling() {
  if (userStatusPollingInterval) clearInterval(userStatusPollingInterval);
  userStatusPollingInterval = setInterval(() => {
    pollUserStatuses();
  }, 30000);
}

export function stopUserStatusPolling() {
  if (userStatusPollingInterval) {
    clearInterval(userStatusPollingInterval);
    userStatusPollingInterval = null;
  }
}

// ===================== Push-уведомления (заглушка для RN) =====================
export async function initPushNotifications() {
  console.log('[Push] Not implemented for React Native – use native modules');
}

// ===================== Компрессия изображений (для RN) =====================
export async function compressImage(dataUrl, maxWidth = 800, quality = 0.7) {
  console.warn('compressImage not implemented for RN – returning original');
  return dataUrl;
}

// ===================== Экспорты =====================
export {
  wsClient,
  pubKeyCache,
};