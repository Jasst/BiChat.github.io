// chat.js — полностью переписан на WebSocket (без Long Polling)
// Исправлено: обновление статуса в левой колонке для своих сообщений,
// heartbeat, delivered, polling статусов.
(function() {
    if (window.chatJsLoaded) return;
    window.chatJsLoaded = true;

window.Utils = window.Utils || {};
Utils.escapeHtml = function(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m]))
              .replace(/['"]/g, m => ({ "'": '&#39;', '"': '&quot;' }[m]));
};

// =============================================================================
// === 1. ИНИЦИАЛИЗАЦИЯ И СОСТОЯНИЕ ===
// =============================================================================
if (typeof AppData === 'undefined') {
    window.AppData = {
        userAddress: document.getElementById('app')?.dataset.userAddress || "{{ address }}"
    };
}

const State = {
  currentChatAddress: '',
  currentChatIsGroup: false,
  currentGroupMembers: null,
  currentChatPartnerAddress: '',
  userAddress: AppData.userAddress,
  lastMessageTimestamp: 0,
  allContacts: [],
  lastKnownMessageId: 0,
  pendingImageData: null,
  topObserver: null
};
window.State = State;
let isSending = false;
let userKeys = null;
const pubKeyCache = new Map();

// =============================================================================
// === 2. WEBSOCKET КЛИЕНТ (ВСТРОЕННЫЙ) ===
// =============================================================================
let wsClient = null;
let wsReconnectTimer = null;

class WebSocketClient {
    constructor(options = {}) {
        this.url = options.url || null;
        this.onMessage = options.onMessage || (() => {});
        this.onError = options.onError || (() => {});
        this.onConnect = options.onConnect || (() => {});
        this.onDisconnect = options.onDisconnect || (() => {});
        this.debug = options.debug || false;
        this.ws = null;
        this.isConnected = false;
        this.reconnectDelay = options.reconnectDelay || 3000;
        this.maxReconnectDelay = 30000;
        this.reconnectTimer = null;
        this.shouldReconnect = true;

        this.address = null;
        this.signature = null;
        this.nonce = null;
    }

    setAuth(address, signature, nonce) {
        this.address = address;
        this.signature = signature;
        this.nonce = nonce;
    }

    async connect() {
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            this.log('Already connected or connecting');
            return;
        }
        if (!this.url) {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            this.url = `${protocol}//${window.location.host}/ws`;
        }
        let finalUrl = this.url;
        if (this.address && this.signature && this.nonce) {
            finalUrl += `?address=${encodeURIComponent(this.address)}&signature=${encodeURIComponent(this.signature)}&nonce=${encodeURIComponent(this.nonce)}`;
        }
        this.log('Connecting to WebSocket:', finalUrl);
        this.ws = new WebSocket(finalUrl);
        this.ws.onopen = () => this._onOpen();
        this.ws.onmessage = (event) => this._onMessage(event);
        this.ws.onerror = (error) => this._onError(error);
        this.ws.onclose = (event) => this._onClose(event);
    }

    disconnect() {
        this.shouldReconnect = false;
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.isConnected = false;
    }

    _onOpen() {
        this.isConnected = true;
        this.log('WebSocket connected');
        this.onConnect();
    }

    _onMessage(event) {
        try {
            const data = JSON.parse(event.data);
            this.log('Received:', data);
            this.onMessage(data);
        } catch (e) {
            this.log('Invalid JSON:', event.data);
        }
    }

    _onError(error) {
        this.log('WebSocket error:', error);
        this.onError(error);
    }

    _onClose(event) {
        this.log('WebSocket closed, code:', event.code);
        this.isConnected = false;
        this.onDisconnect();
        if (this.shouldReconnect && event.code !== 1008) {
            this._scheduleReconnect();
        }
    }

    _scheduleReconnect() {
        if (this.reconnectTimer) return;
        this.log(`Scheduling reconnect in ${this.reconnectDelay}ms`);
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.connect();
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
        }, this.reconnectDelay);
    }

    log(...args) {
        if (this.debug) console.log('[WebSocketClient]', ...args);
    }
}

// =============================================================================
// === 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (КРИПТОГРАФИЯ, СЕТЬ) ===
// =============================================================================
async function getPubKey(address) {
  if (pubKeyCache.has(address)) return pubKeyCache.get(address);
  const res = await fetch(`/get_public_key/${address}`);
  if (!res.ok) throw new Error(`Public key not found for ${address}`);
  const data = await res.json();
  const pubKeyBytes = DarkCrypto._fromBase64(data.public_key);
  const hashBuf = await crypto.subtle.digest('SHA-256', pubKeyBytes);
  const computedAddress = Array.from(new Uint8Array(hashBuf))
    .map(b => b.toString(16).padStart(2, '0')).join('');
  if (computedAddress !== address) {
    throw new Error(`⚠️ Public key mismatch for ${address} — possible MITM!`);
  }
  pubKeyCache.set(address, data.public_key);
  return data.public_key;
}

async function compressImage(dataUrl, maxWidth = 800, quality = 0.7) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      let { width, height } = img;
      if (width > maxWidth || height > maxWidth) {
        if (width > height) {
          height = height * (maxWidth / width);
          width = maxWidth;
        } else {
          width = width * (maxWidth / height);
          height = maxWidth;
        }
      }
      canvas.width = width;
      canvas.height = height;
      canvas.getContext('2d').drawImage(img, 0, 0, width, height);
      resolve(canvas.toDataURL('image/jpeg', quality));
    };
    img.onerror = reject;
    img.src = dataUrl;
  });
}

async function ensureKeys() {
    if (userKeys) return userKeys;
    const mnemonic = sessionStorage.getItem('mnemonic');
    if (!mnemonic) throw new Error('No mnemonic in session');
    userKeys = await DarkCrypto.deriveKeyPair(mnemonic);
    return userKeys;
}

// =============================================================================
// === 4. SMART SCROLL И ПАГИНАЦИЯ ===
// =============================================================================
function isUserAtBottom(container, threshold = 50) {
  if (!container) return false;
  return container.scrollHeight - container.scrollTop - container.clientHeight <= threshold;
}

function smartScrollToBottom(container, force = false) {
  if (!container) return;
  if (force || isUserAtBottom(container)) {
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
  } else {
    showNewMessagesBadge();
  }
}

function showNewMessagesBadge() {
  if (document.getElementById('newMessagesBadge')) return;
  const badge = document.createElement('button');
  badge.id = 'newMessagesBadge';
  badge.innerHTML = '↓ New messages';
  badge.style.cssText = 'position:absolute;bottom:90px;right:20px;background:var(--accent);color:var(--text-inverse);border:none;padding:8px 16px;border-radius:20px;font-size:12px;font-weight:600;cursor:pointer;box-shadow:var(--shadow-md);z-index:100;animation:pulse 2s infinite;display:flex;align-items:center;gap:6px;';
  badge.onclick = () => {
    const c = document.getElementById('messagesContainer');
    if (c) { c.scrollTo({ top: c.scrollHeight, behavior: 'smooth' }); badge.remove(); }
  };
  const main = document.querySelector('.main-content');
  if (main) {
    main.style.position = 'relative';
    main.appendChild(badge);
    setTimeout(() => badge?.remove(), 15000);
  }
}

function setupTopObserver() {
  if (State.topObserver) State.topObserver.disconnect();
  const firstMsg = document.querySelector('#messagesContainer .message:first-of-type');
  if (firstMsg) {
    State.topObserver = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && State.currentChatAddress) {
        const oldestId = parseInt(firstMsg.dataset.messageId);
        loadOlderMessages(State.currentChatAddress, oldestId);
      }
    }, { threshold: 0.1 });
    State.topObserver.observe(firstMsg);
  }
}

async function loadOlderMessages(chatId, beforeId) {
  const container = document.getElementById('messagesContainer');
  if (!container) return;
  try {
    const res = await fetch(`/get_conversation?with=${chatId}&before_id=${beforeId}&limit=30`);
    if (!res.ok) throw new Error('Failed');
    const data = await res.json();
    if (data.messages?.length) {
      const fragment = document.createDocumentFragment();
      for (const msg of data.messages) {
        if (document.getElementById('msg-' + msg.id)) continue;
        const decryptedMsg = await processMessageDecryption(msg);
        const div = createMessageElement(decryptedMsg);
        fragment.appendChild(div);
      }
      container.insertBefore(fragment, container.firstChild);
      State.lastKnownMessageId = Math.min(...data.messages.map(m => m.id));
      setupTopObserver();
    }
  } catch (e) { console.error('Older messages error:', e); }
}

function createMessageElement(msg) {
  const messageDiv = document.createElement('div');
  messageDiv.id = 'msg-' + msg.id;
  const ownClass = msg.is_mine ? 'message-own' : '';
  messageDiv.className = `message ${msg.is_mine ? 'sent' : 'received'} ${ownClass} animate-fade`;
  messageDiv.dataset.messageId = msg.id;
  messageDiv.dataset.id = msg.id;
  if (msg.is_mine) messageDiv.dataset.status = msg.status || 'sent';
  else messageDiv.dataset.status = msg.status || 'delivered';

  const initials = (msg.sender || 'U').slice(0, 1).toUpperCase();
  const senderName = msg.is_mine || !State.currentChatIsGroup
    ? ''
    : '<strong>' + Utils.escapeHtml(msg.sender_name || (msg.sender ? msg.sender.slice(0, 10) + '…' : '')) + '</strong><br>';

  let imageHtml = '';
  if (msg.image) {
    imageHtml = `<img src="${Utils.escapeHtml(msg.image)}" alt="Image" loading="lazy" onclick="openImageModal('${Utils.escapeHtml(msg.image)}')" style="cursor:pointer;max-width:100%;border-radius:6px;margin:4px 0;">`;
  }

  const timeStr = Utils.formatTimestamp(msg.timestamp);
  const deleteBtn = msg.is_mine ? `<button class="delete-btn" data-id="${msg.id}" title="Delete">🗑</button>` : '';

  messageDiv.innerHTML = `<div class="avatar">${Utils.escapeHtml(initials)}</div><div class="content">${senderName}<p>${Utils.escapeHtml(msg.content || '')}</p>${imageHtml}<div class="meta"><span>${timeStr}</span>${deleteBtn}</div></div>`;

  if (msg.is_mine) {
    const statusSpan = document.createElement('span');
    statusSpan.className = 'message-status';
    if (msg.status === 'read') {
      statusSpan.textContent = '✓✓';
      statusSpan.style.color = '#4caf50';
    } else if (msg.status === 'delivered') {
      statusSpan.textContent = '✓✓';
      statusSpan.style.color = '#888';
    } else {
      statusSpan.textContent = '✓';
      statusSpan.style.color = '#888';
    }
    statusSpan.style.marginLeft = '8px';
    statusSpan.style.fontSize = '12px';
    const metaDiv = messageDiv.querySelector('.meta');
    if (metaDiv) metaDiv.appendChild(statusSpan);
  }
  return messageDiv;
}

// =============================================================================
// === 5. ЗАГРУЗКА СПИСКА ДИАЛОГОВ И СТАТУСОВ ПОЛЬЗОВАТЕЛЕЙ ===
// =============================================================================
async function loadConversations() {
  const container = document.getElementById('conversationsList');
  if (!container) return;
  try {
    const res = await fetch('/get_conversations');
    const data = await res.json();
    if (!res.ok || !data.conversations?.length) {
      container.innerHTML = '<div class="empty-state"><div class="icon">💬</div><p>No conversations yet</p><button class="btn btn-primary" onclick="openNewChatModal()">Start one</button></div>';
      return;
    }
    container.innerHTML = '';
    data.conversations.forEach(conv => {
      const item = document.createElement('div');
      item.className = 'conversation-item';
      item.dataset.address = conv.address || '';
      item.dataset.isGroup = conv.is_group ? '1' : '0';
      item.setAttribute('role', 'option');

      const displayName = conv.name || conv.address || 'Unknown';
      const shortName = displayName.length > 25 ? displayName.slice(0, 22) + '…' : displayName;
      const initials = displayName.slice(0, 2).toUpperCase();

      let previewText = Utils.escapeHtml(conv.last_preview || 'No messages');
      const existingItem = container.querySelector(`.conversation-item[data-address="${conv.address}"]`);
      if (existingItem) {
        const existingPreviewEl = existingItem.querySelector('.truncate');
        if (existingPreviewEl && existingPreviewEl.textContent.trim() === '✓ Прочитано' && previewText !== '✓ Прочитано') {
          previewText = '✓ Прочитано';
        }
      }

      item.innerHTML = `<div class="avatar ${conv.is_group ? 'group' : ''}">${Utils.escapeHtml(initials)}</div>
        <div class="info">
          <div class="name truncate">${Utils.escapeHtml(shortName)}</div>
          <div class="meta">
            <span class="status"></span>
            <span class="truncate">${previewText}</span>
          </div>
        </div>`;
      item.onclick = () => selectConversation(conv.address, conv.name || conv.address, !!conv.is_group);
      container.appendChild(item);
    });
  } catch (error) {
    console.error('Load conversations error:', error);
    container.innerHTML = '<p class="text-muted text-center">Failed to load</p>';
  }
}

async function updateUsersStatus() {
    const conversationItems = document.querySelectorAll('.conversation-item');
    const addresses = [];
    conversationItems.forEach(item => {
        const address = item.dataset.address;
        if (address && !address.startsWith('group:')) {
            addresses.push(address);
        }
    });
    if (addresses.length === 0) return;
    try {
        const res = await fetch('/get_many_statuses', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ addresses })
        });
        if (!res.ok) return;
        const data = await res.json();
        for (const [address, statusData] of Object.entries(data.statuses)) {
            const item = document.querySelector(`.conversation-item[data-address="${address}"]`);
            if (!item) continue;
            const statusSpan = item.querySelector('.status');
            if (!statusSpan) continue;
            const status = statusData.status;
            const lastSeen = statusData.last_seen;
            statusSpan.classList.remove('online', 'away', 'offline');
            if (status === 'online') {
                statusSpan.classList.add('online');
                statusSpan.title = 'Online';
            } else if (lastSeen) {
                const minutesAgo = Math.floor((Date.now() - (lastSeen * 1000)) / 60000);
                if (minutesAgo < 5) {
                    statusSpan.classList.add('online');
                    statusSpan.title = 'Online recently';
                } else if (minutesAgo < 60) {
                    statusSpan.classList.add('away');
                    statusSpan.title = `Was online ${minutesAgo} min ago`;
                } else {
                    statusSpan.classList.add('offline');
                    statusSpan.title = `Last seen ${new Date(lastSeen * 1000).toLocaleString()}`;
                }
            } else {
                statusSpan.classList.add('offline');
                statusSpan.title = 'Never seen';
            }
        }
    } catch (e) {
        console.error('Failed to update statuses:', e);
    }
}
setInterval(updateUsersStatus, 30000);
setTimeout(updateUsersStatus, 1000);

// =============================================================================
// === 6. ОБРАБОТКА ВХОДЯЩИХ СООБЩЕНИЙ (WebSocket) ===
// =============================================================================
async function handleWebSocketMessage(data) {
    if (data.error) {
        console.error('WebSocket error message:', data.error);
        return;
    }
    if (!data.chatId && data.sender && data.recipient) {
        data.chatId = (data.sender === State.userAddress) ? data.recipient : data.sender;
    }
    if (!data.chatId) return;
    if (document.getElementById('msg-' + data.id)) return;

    const decrypted = await processMessageDecryption(data);
    const chatId = decrypted.chatId;

    // ✅ ОТПРАВЛЯЕМ СТАТУС DELIVERED ДЛЯ ЛЮБОГО ЧУЖОГО СООБЩЕНИЯ
    if (!decrypted.is_mine) {
        fetch(`/message/${decrypted.id}/delivered`, { method: 'POST' }).catch(e => console.warn('Mark delivered failed', e));
    }

    let isCurrent = false;
    if (State.currentChatAddress === chatId) {
        isCurrent = true;
    } else if (decrypted.isGroup && State.currentChatAddress === chatId) {
        isCurrent = true;
    } else if (!decrypted.isGroup && (decrypted.sender === State.currentChatAddress || decrypted.recipient === State.currentChatAddress)) {
        isCurrent = true;
    }

    if (!isCurrent) {
        const existingItem = document.querySelector(`.conversation-item[data-address="${chatId}"]`);
        if (!existingItem) {
            console.log('Новый диалог, обновляем список:', chatId);
            await loadConversations();
        } else {
            updateConversationPreview(chatId, decrypted.preview || '💬 Новое сообщение');
        }
    }

    if (isCurrent) {
        const container = document.getElementById('messagesContainer');
        if (container) {
            const wasAtBottom = isUserAtBottom(container, 30);
            const msgElement = createMessageElement(decrypted);
            container.appendChild(msgElement);
            if (wasAtBottom) {
                setTimeout(() => {
                    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
                }, 50);
            } else {
                showNewMessagesBadge();
            }
            if (!decrypted.is_mine) {
                fetch(`/message/${decrypted.id}/read`, { method: 'POST' }).catch(e => console.warn('Mark read failed', e));
            }
        }
    }

    if (window.NotificationManager && document.visibilityState === 'visible') {
        window.NotificationManager.handleIncomingMessage?.({
            sender: decrypted.sender,
            sender_name: decrypted.sender_name,
            chatId: chatId,
            isGroup: decrypted.isGroup,
            preview: decrypted.preview,
            timestamp: decrypted.timestamp * 1000,
            messageId: decrypted.id
        });
    }
}

// =============================================================================
// === 7. ИНИЦИАЛИЗАЦИЯ WEBSOCKET ===
// =============================================================================
async function initWebSocket() {
    if (wsClient) {
        wsClient.disconnect();
    }
    try {
        const keys = await ensureKeys();
        const nonce = crypto.randomUUID();
        const signatureArray = await DarkCrypto.signData(keys.signPrivateKey, nonce);
        const signatureHex = Array.from(new Uint8Array(signatureArray)).map(b => b.toString(16).padStart(2, '0')).join('');

        wsClient = new WebSocketClient({
            debug: false,
            onMessage: handleWebSocketMessage,
            onConnect: () => {
                console.log('✅ WebSocket connected');
                loadConversations();
            },
            onDisconnect: () => {
                console.warn('⚠️ WebSocket disconnected');
            },
            onError: (err) => {
                console.error('WebSocket error:', err);
            }
        });
        wsClient.setAuth(State.userAddress, signatureHex, nonce);
        wsClient.connect();
    } catch (err) {
        console.error('Failed to init WebSocket:', err);
    }
}

// =============================================================================
// === 8. HEARTBEAT (ОБНОВЛЕНИЕ ОНЛАЙН-СТАТУСА) ===
// =============================================================================
let heartbeatInterval = null;

function startHeartbeat() {
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    heartbeatInterval = setInterval(async () => {
        try {
            const currentChat = State.currentChatAddress || '';
            await fetch('/heartbeat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ current_chat: currentChat })
            });
        } catch (e) {
            console.debug('Heartbeat failed', e);
        }
    }, 30000);
}

function stopHeartbeat() {
    if (heartbeatInterval) {
        clearInterval(heartbeatInterval);
        heartbeatInterval = null;
    }
}

// =============================================================================
// === 9. ВЫБОР ДИАЛОГА И ЗАГРУЗКА СООБЩЕНИЙ ===
// =============================================================================
async function selectConversation(address, name, isGroup) {
  if (State.topObserver) {
      State.topObserver.disconnect();
      State.topObserver = null;
  }
  if (isSending) isSending = false;
  if (State.currentChatUnsub && typeof State.currentChatUnsub === 'function') State.currentChatUnsub();
  State.currentChatUnsub = null;
  State.currentChatAddress = address;
  State.currentChatIsGroup = !!isGroup;
  State.currentChatPartnerAddress = isGroup ? '' : (address === State.userAddress ? '' : address);

  // ✅ ОТПРАВЛЯЕМ HEARTBEAT ПРИ СМЕНЕ ЧАТА
  fetch('/heartbeat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_chat: address })
  }).catch(e => console.debug);

  const aiContainer = document.getElementById('aiChatContainer');
  const mainContainer = document.getElementById('messagesContainer');
  const mainInputArea = document.querySelector('.main-content .input-area');
  const mainChatHeader = document.querySelector('.main-content .chat-header');

  if (address === 'ai_bot') {
    if (mainContainer) mainContainer.style.display = 'none';
    if (mainInputArea) mainInputArea.style.display = 'none';
    if (mainChatHeader) mainChatHeader.style.display = 'none';
    if (aiContainer) aiContainer.classList.remove('hidden');
    if (typeof window.initAiChat === 'function') window.initAiChat();
    const nameEl = document.getElementById('currentChatName');
    if (nameEl) nameEl.textContent = '🤖 AI Assistant';
    const subtitleEl = document.getElementById('chatSubtitle');
    if (subtitleEl) subtitleEl.textContent = 'Streaming response';
    _enableChatControls();
    document.querySelectorAll('.conversation-item').forEach(item => item.classList.remove('active'));
    return;
  } else {
    if (aiContainer) aiContainer.classList.add('hidden');
    if (mainContainer) mainContainer.style.display = '';
    if (mainInputArea) mainInputArea.style.display = '';
    if (mainChatHeader) mainChatHeader.style.display = '';
  }

  if (isGroup) {
    try {
      const res = await fetch('/get_groups');
      const data = await res.json();
      const group = data.groups.find(g => 'group:' + g.id === address);
      if (group) {
        State.currentGroupMembers = group.members;
      } else {
        State.currentGroupMembers = [];
      }
    } catch (e) {
      State.currentGroupMembers = [];
    }
  } else {
    State.currentGroupMembers = null;
  }

  if (window.NotificationManager?.setActiveChat) window.NotificationManager.setActiveChat(address);
  const container = document.getElementById('messagesContainer');
  if (container) { container.innerHTML = '<div class="loading">Loading…</div>'; container.classList.add('loading'); }
  _disableChatControls();
  const nameEl = document.getElementById('currentChatName');
  if (nameEl) nameEl.textContent = name || 'Loading…';
  const subtitleEl = document.getElementById('chatSubtitle');
  if (subtitleEl) subtitleEl.textContent = isGroup ? 'Group chat' : 'Direct message';
  document.querySelectorAll('.conversation-item').forEach(item => item.classList.toggle('active', item.dataset.address === address));
  State.lastKnownMessageId = 0;
  State.lastMessageTimestamp = 0;
  State.pendingImageData = null;
  stopStatusPolling();
  startStatusPolling();
  loadMessagesForConversation(address, false);

  if (window.innerWidth <= 768 && typeof closeSidebar === 'function') closeSidebar();
}

function _disableChatControls() {
  ['messageContent', 'attachImageButton', 'sendButton', 'addToContactsBtn', 'clearConversationBtn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = true;
  });
}

function _enableChatControls() {
  ['messageContent', 'attachImageButton', 'sendButton', 'addToContactsBtn', 'clearConversationBtn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = false;
  });
  const btn = document.getElementById('addToContactsBtn');
  if (btn) {
    if (State.currentChatIsGroup || !State.currentChatPartnerAddress || State.currentChatPartnerAddress === State.userAddress) {
      btn.disabled = true;
      btn.title = "Cannot add group or yourself";
    } else {
      btn.disabled = false;
      btn.title = "Add to contacts";
    }
  }
}

async function processMessageDecryption(msg) {
  if (!msg.content) return msg;
  let content = msg.content;
  let image = msg.image;
  try {
    const parsed = JSON.parse(content);
    if (parsed.encrypted_map) {
      const myAddr = State.userAddress;
      const myEnc = parsed.encrypted_map[myAddr];
      if (!myEnc) return { ...msg, content: '🔒 No access' };
      const keys = await ensureKeys();
      const senderPubKeyBytes = DarkCrypto._fromBase64(myEnc.sender_pubkey);
      try {
        const cipherB64 = myEnc.self_ciphertext || myEnc.ciphertext;
        const ivB64 = myEnc.self_iv || myEnc.iv;
        const ciphertext = DarkCrypto._base64ToArrayBuffer(cipherB64);
        const iv = DarkCrypto._fromBase64(ivB64);
        const shared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, senderPubKeyBytes);
        content = await DarkCrypto.decryptAES(shared, ciphertext, iv);
        image = myEnc.image || null;
      } catch (e) {
        content = '🔒 Encrypted message';
      }
      return { ...msg, content, image };
    }
    if (parsed.ciphertext && parsed.iv && parsed.sender_pubkey) {
      const keys = await ensureKeys();
      try {
        if (msg.is_mine) {
          if (parsed.self_ciphertext && parsed.self_iv) {
            const selfCiphertext = DarkCrypto._base64ToArrayBuffer(parsed.self_ciphertext);
            const selfIv = DarkCrypto._fromBase64(parsed.self_iv);
            const selfShared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, keys.compressedPubKey);
            content = await DarkCrypto.decryptAES(selfShared, selfCiphertext, selfIv);
            image = parsed.image || null;
          } else {
            content = '🔒 Encrypted message (no self-copy)';
          }
        } else {
          const senderPubKeyBytes = DarkCrypto._fromBase64(parsed.sender_pubkey);
          content = await DarkCrypto.decryptMessage(keys.ecdhPrivateKey, senderPubKeyBytes, parsed.iv, parsed.ciphertext);
          image = parsed.image || null;
        }
      } catch (e) {
        console.error('Decryption critical error', msg.id, e);
        return { ...msg, content: '🔒 Ошибка расшифровки', image: null };
      }
    }
  } catch (e) { }
  return { ...msg, content, image };
}

async function loadMessagesForConversation(chatWithAddress, isNewMessage = false) {
  const container = document.getElementById('messagesContainer');
  if (!container) return;

  if (!chatWithAddress) {
    if (!isNewMessage) container.innerHTML = '<div class="empty-state animate-fade"><div class="icon">💬</div><p>Select a conversation to start chatting</p></div>';
    _enableChatControls();
    return;
  }

  const isGroup = chatWithAddress.startsWith('group:');
  const isPersonal = Security.isValidAddress(chatWithAddress);
  if (!isGroup && !isPersonal) {
    container.innerHTML = '<p class="text-muted text-center">Invalid conversation</p>';
    container.classList.remove('loading');
    _enableChatControls();
    return;
  }

  if (!isNewMessage) {
    container.innerHTML = '<div class="loading">Loading messages…</div>';
    container.classList.add('loading');
  }

  try {
    const params = new URLSearchParams({ with: chatWithAddress });
    if (isNewMessage && State.lastKnownMessageId > 0) {
      params.append('last_message_id', State.lastKnownMessageId);
      params.append('limit', '50');
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    const res = await fetch('/get_conversation?' + params.toString(), { signal: controller.signal });
    clearTimeout(timeout);

    const data = await res.json();
    container.classList.remove('loading');
    if (!res.ok) throw new Error(data.error || 'Failed to load');

    const rawMessages = Array.isArray(data.messages) ? data.messages : [];
    const messages = [];
    for (const msg of rawMessages) {
       try {
            const decrypted = await processMessageDecryption(msg);
            messages.push(decrypted);
       } catch (e) {
        console.error('Failed to decrypt message', msg.id, e);
        messages.push({ ...msg, content: '🔒 Ошибка расшифровки', image: null });
       }
    }

    if (!messages.length) {
      if (isNewMessage) { _enableChatControls(); return; }
      container.innerHTML = '<div class="empty-state animate-fade"><div class="icon">👋</div><p>No messages yet</p><p class="text-muted" style="font-size:12px">Start the conversation!</p></div>';
      _enableChatControls();
      return;
    }

    if (!isNewMessage) container.innerHTML = '';

    let maxTimestamp = 0;
    const fragment = document.createDocumentFragment();
    messages.forEach(msg => {
      if (document.getElementById('msg-' + msg.id)) return;
      if (msg.timestamp > maxTimestamp) maxTimestamp = msg.timestamp;
      fragment.appendChild(createMessageElement(msg));
      if (msg.id > State.lastKnownMessageId) State.lastKnownMessageId = msg.id;
      if (!msg.is_mine && isNewMessage) {
        window.NotificationManager?.handleIncomingMessage?.({
          sender: msg.sender,
          chatId: chatWithAddress,
          content: msg.content,
          image: msg.image,
          timestamp: (msg.timestamp || Date.now()/1000) * 1000
        });
      }
    });

    container.appendChild(fragment);
    State.lastMessageTimestamp = maxTimestamp;

    if (messages.length > 0) {
      markConversationAsRead(chatWithAddress, messages[messages.length - 1].id);
    }

    if (!isNewMessage) {
        function smoothScrollToBottom() {
            const prevHeight = container.scrollHeight;
            container.scrollTop = prevHeight;
            requestAnimationFrame(() => {
                if (container.scrollHeight !== prevHeight) {
                    container.scrollTop = container.scrollHeight;
                }
            });
        }
        smoothScrollToBottom();
    } else {
      const wasNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
      if (wasNearBottom) {
        container.scrollTop = container.scrollHeight;
        setTimeout(() => { if (container) container.scrollTop = container.scrollHeight; }, 100);
      } else {
        showNewMessagesBadge();
      }
    }

    if (isNewMessage) {
      setTimeout(() => {
        const otherMessages = document.querySelectorAll('.message-other');
        otherMessages.forEach(msgDiv => {
          const msgId = msgDiv.dataset.id;
          const currentStatus = msgDiv.dataset.status;
          if (msgId && currentStatus !== 'read') {
            fetch(`/message/${msgId}/read`, { method: 'POST' })
              .then(() => {
                msgDiv.dataset.status = 'read';
              })
              .catch(e => console.warn('Failed to mark read', e));
          }
        });
      }, 500);
    }

    _enableChatControls();
    if (!isNewMessage) setupTopObserver();

  } catch (error) {
    console.error('Load messages error:', error);
    container.classList.remove('loading');
    if (error.name === 'AbortError') container.innerHTML = '<p class="text-muted text-center">Request timed out</p>';
    else if (!isNewMessage) container.innerHTML = '<p class="text-muted text-center">Failed to load messages</p>';
    _enableChatControls();
  }
}

// =============================================================================
// === 10. ОТПРАВКА СООБЩЕНИЯ ===
// =============================================================================
async function sendMessage() {
  if (State.currentChatAddress === 'ai_bot') {
    console.log('⛔ sendMessage ignored because AI chat is active');
    return;
  }
  console.log('[CHAT] sendMessage called, State.pendingImageData=', State.pendingImageData);
  const contentEl = document.getElementById('messageContent');
  const sendBtn = document.getElementById('sendButton');
  const attachBtn = document.getElementById('attachImageButton');

  if (isSending) {
    window.NotificationManager?.showToast('Sending in progress...', 'warning');
    return;
  }

  const content = contentEl ? contentEl.value.trim() : '';
  const recipient = State.currentChatAddress;
  if (!recipient || (!content && !State.pendingImageData)) {
    window.NotificationManager?.showToast('Enter a message or attach an image', 'warning');
    return;
  }

  isSending = true;
  if (sendBtn) sendBtn.disabled = true;
  if (attachBtn) attachBtn.disabled = true;
  if (contentEl) contentEl.disabled = true;

  const isGroup = State.currentChatIsGroup;
  const groupId = isGroup && recipient.startsWith('group:') ? recipient.split(':')[1] : null;

  if (contentEl) {
    contentEl.value = '';
    contentEl.style.height = 'auto';
  }
  const attachedImage = State.pendingImageData;
  State.pendingImageData = null;

  const tempId = 'temp-' + Date.now();
  const tempMsg = {
    id: tempId,
    sender: State.userAddress,
    recipient: recipient,
    content: content,
    image: attachedImage,
    timestamp: Date.now() / 1000,
    is_mine: true,
    sender_name: 'You',
    status: 'sent'
  };

  const container = document.getElementById('messagesContainer');
  if (container) {
    const emptyState = container.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
    container.appendChild(createMessageElement(tempMsg));
    smartScrollToBottom(container, true);
  }

  try {
    const keys = await ensureKeys();
    let payload = {};
    if (isGroup && groupId) {
      try {
        const gRes = await fetch('/get_groups');
        const gData = await gRes.json();
        const freshGroup = gData.groups?.find(g => g.id === groupId);
        if (freshGroup && freshGroup.members?.length) {
          State.currentGroupMembers = freshGroup.members;
        }
      } catch (e) {
        console.warn('Could not refresh group members, using cached list:', e);
      }
      const members = State.currentGroupMembers;
      if (!members || members.length === 0) throw new Error('Group members not loaded');

      const encryptedMap = {};
      for (const addr of members) {
        const pubKeyB64 = await getPubKey(addr);
        const pubKeyBytes = DarkCrypto._fromBase64(pubKeyB64);
        const shared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, pubKeyBytes);
        const { ciphertext, iv } = await DarkCrypto.encryptAES(shared, content || '');
        encryptedMap[addr] = {
          ciphertext: DarkCrypto._arrayBufferToBase64(ciphertext),
          iv: DarkCrypto._toBase64(iv),
          sender_pubkey: DarkCrypto._toBase64(keys.compressedPubKey),
          image: attachedImage || null
        };
        if (addr === State.userAddress) {
          encryptedMap[addr].self_ciphertext = encryptedMap[addr].ciphertext;
          encryptedMap[addr].self_iv = encryptedMap[addr].iv;
        }
      }
      payload = {
        message_type: 'group',
        group_id: groupId,
        encrypted_map: encryptedMap
      };
    } else {
      const resPub = await fetch(`/get_public_key/${recipient}`);
      if (!resPub.ok) throw new Error('Recipient public key not found');
      const pubData = await resPub.json();
      const recipientPubKeyBytes = DarkCrypto._fromBase64(pubData.public_key);
      const encrypted = await DarkCrypto.encryptMessage(keys.ecdhPrivateKey, keys.compressedPubKey, recipientPubKeyBytes, content || '');
      const selfShared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, keys.compressedPubKey);
      const selfEnc = await DarkCrypto.encryptAES(selfShared, content || '');
      payload = {
        recipient: recipient,
        payload: {
          ciphertext: encrypted.ciphertext,
          iv: encrypted.iv,
          sender_pubkey: encrypted.myPubKey,
          self_ciphertext: DarkCrypto._arrayBufferToBase64(selfEnc.ciphertext),
          self_iv: DarkCrypto._toBase64(selfEnc.iv),
          image: attachedImage || null
        },
        message_type: 'direct'
      };
    }

    const res = await fetch('/send_message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (res.ok) {
      const tempElem = document.getElementById('msg-' + tempId);
      if (tempElem) {
        const realId = data.tx_id;
        tempElem.id = 'msg-' + realId;
        tempElem.dataset.messageId = realId;
        const deleteBtn = tempElem.querySelector('.delete-btn');
        if (deleteBtn) deleteBtn.dataset.id = realId;
        const statusSpan = tempElem.querySelector('.message-status');
        if (statusSpan) {
          statusSpan.textContent = '✓';
          statusSpan.style.color = '#888';
        }
      }
      await loadConversations();
      updateConversationPreview(recipient, '✓ Отправлено');
      await loadMessagesForConversation(recipient, true);
    } else {
      const tempElem = document.getElementById('msg-' + tempId);
      if (tempElem) tempElem.remove();
      window.NotificationManager?.showToast(data.error || 'Send failed', 'error');
    }
  } catch (error) {
    console.error('Send error:', error);
    const tempElem = document.getElementById('msg-' + tempId);
    if (tempElem) tempElem.remove();
    window.NotificationManager?.showToast(error.message || 'Network error', 'error');
  } finally {
    isSending = false;
    if (sendBtn) sendBtn.disabled = false;
    if (attachBtn) attachBtn.disabled = false;
    if (contentEl) contentEl.disabled = false;
    contentEl?.focus();
  }
}

// =============================================================================
// === 11. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (КОНТАКТЫ, УДАЛЕНИЕ, ОЧИСТКА) ===
// =============================================================================
async function addContactFromChat() {
  if (!State.currentChatPartnerAddress || State.currentChatPartnerAddress === State.userAddress) {
    window.NotificationManager?.showToast('Cannot add this conversation', 'warning');
    return;
  }
  const nameEl = document.getElementById('currentChatName');
  const name = nameEl ? nameEl.textContent : (State.currentChatPartnerAddress.slice(0, 10) + '…');
  try {
    const res = await fetch('/add_contact_from_chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contact_address: State.currentChatPartnerAddress, contact_name: name })
    });
    const data = await res.json();
    if (res.ok) {
      window.NotificationManager?.showToast('Contact added', 'success');
      const btn = document.getElementById('addToContactsBtn');
      if (btn) btn.disabled = true;
    } else {
      window.NotificationManager?.showToast(data.error || 'Failed to add', 'error');
    }
  } catch (error) {
    console.error('Add contact error:', error);
    window.NotificationManager?.showToast('Network error', 'error');
  }
}

async function deleteMessage(messageId, buttonEl) {
  if (!confirm('Delete this message?')) return;
  try {
    if (buttonEl) { buttonEl.disabled = true; buttonEl.textContent = '…'; }
    const res = await fetch('/delete_message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_id: messageId })
    });
    const data = await res.json();
    if (res.ok) {
      const msgEl = document.getElementById('msg-' + messageId);
      if (msgEl) msgEl.remove();
      window.NotificationManager?.showToast('Message deleted', 'success');
    } else {
      window.NotificationManager?.showToast(data.error || 'Delete failed', 'error');
      if (buttonEl) { buttonEl.disabled = false; buttonEl.textContent = '🗑'; }
    }
  } catch (error) {
    console.error('Delete error:', error);
    window.NotificationManager?.showToast('Network error', 'error');
    if (buttonEl) { buttonEl.disabled = false; buttonEl.textContent = '🗑'; }
  }
}

async function clearConversation() {
  if (!State.currentChatAddress) return;
  if (!confirm('Clear all messages in this conversation?')) return;
  try {
    const res = await fetch('/clear_conversation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_with: State.currentChatAddress })
    });
    const data = await res.json();
    if (res.ok) {
      document.getElementById('messagesContainer').innerHTML = '<p class="text-muted text-center">Conversation cleared</p>';
      window.NotificationManager?.showToast('Conversation cleared', 'success');
    } else {
      window.NotificationManager?.showToast(data.error || 'Clear failed', 'error');
    }
  } catch (error) {
    console.error('Clear error:', error);
    window.NotificationManager?.showToast('Network error', 'error');
  }
}

async function handleImageSelection(event) {
  const file = event.target.files[0];
  if (file && file.type?.startsWith('image/')) {
    const reader = new FileReader();
    reader.onload = async (e) => {
      if (e.target?.result) {
        try {
          State.pendingImageData = await compressImage(e.target.result);
          window.NotificationManager?.showToast('Image attached', 'success');
        } catch (err) {
          window.NotificationManager?.showToast('Image processing failed', 'error');
        }
      }
    };
    reader.readAsDataURL(file);
  } else {
    window.NotificationManager?.showToast('Please select an image', 'warning');
  }
  event.target.value = '';
}

function openImageModal(src) {
  const modal = document.getElementById('imageModal');
  const img = document.getElementById('modalImage');
  if (modal && img) {
    img.src = src;
    modal.classList.remove('hidden');
    document.getElementById('downloadImageBtn').onclick = () => {
      const a = document.createElement('a');
      a.href = src;
      a.download = 'image-' + Date.now() + '.png';
      a.click();
    };
  }
}

function closeImageModal() { document.getElementById('imageModal')?.classList.add('hidden'); }

// =============================================================================
// === 12. ПОЛЛИНГ СТАТУСОВ СООБЩЕНИЙ И ОБНОВЛЕНИЕ PREVIEW ===
// =============================================================================
let statusPollingInterval = null;

function startStatusPolling() {
    if (statusPollingInterval) clearInterval(statusPollingInterval);
    statusPollingInterval = setInterval(async () => {
        const myMessages = document.querySelectorAll('.message-own');
        const ids = Array.from(myMessages)
            .map(el => el.dataset.id)
            .filter(id => id && !id.startsWith('temp'));
        if (ids.length === 0) return;
        try {
            const res = await fetch('/message/statuses', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: ids })
            });
            const statuses = await res.json();
            for (const [id, st] of Object.entries(statuses)) {
                const msgDiv = document.querySelector(`.message-own[data-id="${id}"]`);
                if (msgDiv && msgDiv.dataset.status !== st) {
                    msgDiv.dataset.status = st;
                    updateStatusIcon(msgDiv, st);

                    // ✅ ОБНОВЛЯЕМ PREVIEW В ЛЕВОЙ КОЛОНКЕ, ЕСЛИ ЭТО ПОСЛЕДНЕЕ СООБЩЕНИЕ В ДИАЛОГЕ
                    const container = document.getElementById('messagesContainer');
                    const lastMsg = container?.querySelector('.message:last-child');
                    if (lastMsg && lastMsg.dataset.id === id) {
                        const chatId = State.currentChatAddress;
                        let previewText = '';
                        if (st === 'read') previewText = '✓✓ Прочитано';
                        else if (st === 'delivered') previewText = '✓✓ Доставлено';
                        else previewText = '✓ Отправлено';
                        updateConversationPreview(chatId, previewText);
                    }
                }
            }
        } catch (e) {
            console.warn('Status polling error', e);
        }
    }, 30000);
}

function stopStatusPolling() {
    if (statusPollingInterval) {
        clearInterval(statusPollingInterval);
        statusPollingInterval = null;
    }
}

function updateStatusIcon(msgDiv, status) {
    const icon = msgDiv.querySelector('.message-status');
    if (!icon) return;
    if (status === 'sent') {
        icon.textContent = '✓';
        icon.style.color = '#888';
    } else if (status === 'delivered') {
        icon.textContent = '✓✓';
        icon.style.color = '#888';
    } else if (status === 'read') {
        icon.textContent = '✓✓';
        icon.style.color = '#4caf50';
    }
}

// =============================================================================
// === 13. МОДАЛЬНЫЕ ОКНА (НОВЫЙ ЧАТ) ===
// =============================================================================
function openNewChatModal() {
  window.modalOpen = true;
  document.getElementById('newChatModal')?.classList.remove('hidden');
  document.getElementById('newChatSelect').value = '';
  document.getElementById('newChatAddress').value = '';
  loadContactsForModal();
  if (window.QRScanner) QRScanner.close();
}

function closeNewChatModal() {
  window.modalOpen = false;
  document.getElementById('newChatModal')?.classList.add('hidden');
  if (window.QRScanner) QRScanner.close();
}

async function loadContactsForModal() {
  try {
    const res = await fetch('/get_contacts');
    const data = await res.json();
    if (res.ok && data.contacts) {
      State.allContacts = data.contacts;
      const select = document.getElementById('newChatSelect');
      if (select) {
        select.innerHTML = '<option value="">-- Choose a contact --</option>';
        data.contacts.forEach(c => {
          const option = document.createElement('option');
          option.value = c.address;
          const name = c.name.length > 30 ? c.name.slice(0, 27) + '…' : c.name;
          option.textContent = Utils.escapeHtml(name) + ' (' + c.address.slice(0, 10) + '…)';
          select.appendChild(option);
        });
      }
    }
  } catch (error) { console.error('Load contacts error:', error); }
}

async function startNewChat() {
  const select = document.getElementById('newChatSelect');
  const addressInput = document.getElementById('newChatAddress');
  const selected = select?.value.trim() || '';
  const entered = addressInput?.value.trim() || '';
  let address = '', name = '';
  if (selected) {
    address = selected;
    const contact = State.allContacts.find(c => c.address === selected);
    name = contact ? contact.name : selected.slice(0, 10) + '…';
  } else if (entered) {
    if (!Security.isValidAddress(entered)) {
      window.NotificationManager?.showToast('Invalid address format', 'error');
      return;
    }
    if (entered === State.userAddress) {
      window.NotificationManager?.showToast('Cannot chat with yourself', 'warning');
      return;
    }
    address = entered;
    name = entered.slice(0, 10) + '…';
  } else {
    window.NotificationManager?.showToast('Select a contact or enter address', 'warning');
    return;
  }
  closeNewChatModal();
  selectConversation(address, name, false);
}

async function markConversationAsRead(chatId, explicitLastMessageId) {
  const item = document.querySelector(`.conversation-item[data-address="${chatId}"]`);
  if (item) {
    const meta = item.querySelector('.meta .truncate');
    if (meta) {
      meta.textContent = '✓ Прочитано';
      meta.style.color = 'var(--text-secondary)';
      meta.style.fontStyle = 'italic';
    }
  }
  let lastMessageId = explicitLastMessageId;
  if (lastMessageId === undefined) {
    const lastMsg = document.querySelector('#messagesContainer .message:last-of-type');
    lastMessageId = lastMsg ? parseInt(lastMsg.dataset.messageId) : 0;
  }
  try {
    await fetch('/mark_conversation_read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_with: chatId, last_message_id: lastMessageId }),
      cache: 'no-store'
    });
  } catch (e) { console.debug('ℹ️ Read sync skipped'); }
}

function updateConversationPreview(chatId, newPreview) {
  const items = document.querySelectorAll('.conversation-item');
  for (const item of items) {
    if (item.dataset.address === chatId) {
      const meta = item.querySelector('.meta .truncate');
      if (meta) {
        meta.textContent = newPreview;
        meta.classList.add('preview-read');
        item.style.background = '';
        item.style.fontWeight = '';
      }
      break;
    }
  }
}

// =============================================================================
// === 14. DOMContentLoaded (ЗАПУСК ВСЕГО) ===
// =============================================================================
document.addEventListener('DOMContentLoaded', function() {
  loadConversations();
  initWebSocket();
  startHeartbeat();           // ✅ ЗАПУСК HEARTBEAT
  startStatusPolling();      // ✅ ЗАПУСК ПОЛЛИНГА СТАТУСОВ

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && wsClient && !wsClient.isConnected) {
      console.log('📱 Tab active, reconnecting WebSocket...');
      wsClient.connect();
    }
  });
  if (window.NotificationManager?.init) window.NotificationManager.init();

  const msgContainer = document.getElementById('messagesContainer');
  if (msgContainer) {
    msgContainer.addEventListener('click', function(e) {
      const btn = e.target.closest('.delete-btn');
      if (btn) {
        const msgId = parseInt(btn.dataset.id);
        if (msgId) deleteMessage(msgId, btn);
      }
    });
  }

  const params = new URLSearchParams(window.location.search);
  const startWith = params.get('start_with');
  const startName = params.get('name');
  if (startWith && startName) {
    setTimeout(() => {
      selectConversation(startWith, decodeURIComponent(startName), startWith.startsWith('group:'));
      history.replaceState({}, '', location.pathname);
    }, 100);
  }

  const input = document.getElementById('messageContent');
  if (input) {
    input.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
  }

  document.getElementById('newChatBtn')?.addEventListener('click', openNewChatModal);
  document.getElementById('startNewChatBtn')?.addEventListener('click', startNewChat);
  document.getElementById('imageModal')?.addEventListener('click', e => { if (e.target.id === 'imageModal') closeImageModal(); });
  window.addEventListener('click', e => { if (e.target.classList.contains('modal-overlay')) { e.target.classList.add('hidden'); if (window.QRScanner) QRScanner.close(); } });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeNewChatModal(); closeImageModal(); if (window.QRScanner) QRScanner.close(); } });

  const aiBtn = document.getElementById('aiChatBtn');
  if (aiBtn) {
    aiBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (window.innerWidth <= 768 && typeof closeSidebar === 'function') closeSidebar();
        selectConversation('ai_bot', 'AI Assistant', false);
    });
  }
});

window.addEventListener('beforeunload', () => {
    if (wsClient) {
        wsClient.disconnect();
        wsClient = null;
    }
    if (window.QRScanner && typeof QRScanner.close === 'function') {
        try { QRScanner.close(); } catch(e) {}
    }
    if (State.topObserver) {
        State.topObserver.disconnect();
        State.topObserver = null;
    }
    if (window.NotificationManager && typeof window.NotificationManager.destroy === 'function') {
        try { window.NotificationManager.destroy(); } catch(e) {}
    }
    stopHeartbeat();
});

window.selectConversation = selectConversation;
window.loadMessagesForConversation = loadMessagesForConversation;
window.startNewChat = startNewChat;
window.sendMessage = sendMessage;
window.deleteMessage = deleteMessage;
window.openImageModal = openImageModal;
window.closeImageModal = closeImageModal;
window.handleImageSelection = handleImageSelection;
window.addContactFromChat = addContactFromChat;
window.clearConversation = clearConversation;
window.processMessageDecryption = processMessageDecryption;
window.closeNewChatModal = closeNewChatModal;
window.openNewChatModal = openNewChatModal;
})();