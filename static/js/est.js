<script>
// =============================================================================
// === Utilities ===
// =============================================================================
const Utils = {
  escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  },

  copyToClipboard(text, feedbackEl) {
    navigator.clipboard.writeText(text).then(() => {
      if (feedbackEl) {
        feedbackEl.textContent = 'Copied';
        feedbackEl.style.opacity = '1';
        setTimeout(() => feedbackEl.style.opacity = '0', 2000);
      }
    }).catch(() => {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      if (feedbackEl) {
        feedbackEl.textContent = 'Copied';
        feedbackEl.style.opacity = '1';
        setTimeout(() => feedbackEl.style.opacity = '0', 2000);
      }
    });
  },

  formatTimestamp(ts) {
    const date = new Date(ts * 1000);
    const now = new Date();
    const diff = now - date;
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return date.toLocaleDateString();
  }
};

// =============================================================================
// === State ===
// =============================================================================
const State = {
  currentChatAddress: '',
  currentChatIsGroup: false,
  currentChatPartnerAddress: '',
  userAddress: "{{ address }}",
  lastMessageTimestamp: 0,
  pollInterval: null,
  allContacts: [],
  lastKnownMessageId: 0,
  currentChatUnsub: null,
  pendingImageData: null
};

// =============================================================================
// === 🔧 УМНЫЙ СКРОЛЛ — ИСПРАВЛЕННЫЙ ===
// =============================================================================
function isUserAtBottom(container, threshold = 50) {
  if (!container) return false;
  const scrollOffset = container.scrollHeight - container.scrollTop - container.clientHeight;
  return scrollOffset <= threshold;
}

function smartScrollToBottom(container, force = false) {
  if (!container) return;

  if (force) {
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    return;
  }

  if (isUserAtBottom(container)) {
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
  badge.style.cssText = `
    position: absolute;
    bottom: 90px;
    right: 20px;
    background: var(--accent);
    color: var(--text-inverse);
    border: none;
    padding: 8px 16px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    box-shadow: var(--shadow-md);
    z-index: 100;
    animation: pulse 2s infinite;
    display: flex;
    align-items: center;
    gap: 6px;
  `;

  badge.onclick = () => {
    const container = document.getElementById('messagesContainer');
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
      badge.remove();
    }
  };

  const mainContent = document.querySelector('.main-content');
  if (mainContent) {
    mainContent.style.position = 'relative';
    mainContent.appendChild(badge);
    setTimeout(() => badge?.remove(), 15000);
  }
}

// =============================================================================
// === QR Scanner ===
// =============================================================================
const QRScanner = {
  stream: null,
  interval: null,
  active: false,

  openInModal() {
    if (this.active) return;
    const container = document.getElementById('qrScannerContainerModal');
    const video = document.getElementById('qrVideoModal');
    const result = document.getElementById('scanResultModal');
    if (!container || !video) return;

    this.active = true;
    container.classList.remove('hidden');
    result.classList.add('hidden');

    if (navigator.mediaDevices?.getUserMedia) {
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment', width: { ideal: 640 } } })
      .then(stream => {
        if (!this.active) { stream.getTracks().forEach(t => t.stop()); return; }
        this.stream = stream;
        video.srcObject = stream;
        video.play().then(() => this.startScanning()).catch(() => this.close());
      })
      .catch(err => {
        console.error('Camera error:', err);
        window.NotificationManager?.showToast?.('Camera access denied', 'error');
        this.close();
      });
    } else {
      window.NotificationManager?.showToast?.('Camera not supported', 'error');
      this.close();
    }
  },

  startScanning() {
    const video = document.getElementById('qrVideoModal');
    const result = document.getElementById('scanResultModal');
    if (!video || !this.active) return;

    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');

    this.interval = setInterval(() => {
      if (!this.active || video.readyState !== video.HAVE_ENOUGH_DATA) return;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      ctx.drawImage(video, 0, 0);

      try {
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const code = jsQR(imageData.data, imageData.width, imageData.height);
        if (code?.data) {
          let address = '';
          if (code.data.length === 64 && /^[a-fA-F0-9]{64}$/.test(code.data)) {
            address = code.data;
          } else if (code.data.toLowerCase().startsWith('bitcoin:')) {
            const match = code.data.match(/bitcoin:([a-zA-Z0-9]{64})/i);
            if (match?.[1]) address = match[1];
          }
          if (address) {
            this.close();
            document.getElementById('newChatAddress').value = address;
            result.textContent = '✓ Address scanned';
            result.classList.remove('hidden');
            window.NotificationManager?.showToast?.('Address scanned successfully', 'success');
          }
        }
      } catch (e) { /* continue */ }
    }, 300);
  },

  close() {
    this.active = false;
    if (this.interval) { clearInterval(this.interval); this.interval = null; }
    if (this.stream) { this.stream.getTracks().forEach(t => t.stop()); this.stream = null; }
    const container = document.getElementById('qrScannerContainerModal');
    const video = document.getElementById('qrVideoModal');
    if (container) container.classList.add('hidden');
    if (video) { video.pause(); video.srcObject = null; }
  }
};

// =============================================================================
// === Chat Functions ===
// =============================================================================
async function loadConversations() {
  const container = document.getElementById('conversationsList');
  try {
    const res = await fetch('/get_conversations');
    const data = await res.json();
    if (!res.ok || !data.conversations?.length) {
      container.innerHTML = `<div class="empty-state"><div class="icon">💬</div><p>No conversations yet</p><button class="btn btn-primary" onclick="openNewChatModal()">Start one</button></div>`;
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
      item.innerHTML = `<div class="avatar ${conv.is_group ? 'group' : ''}">${Utils.escapeHtml(initials)}</div><div class="info"><div class="name truncate">${Utils.escapeHtml(shortName)}</div><div class="meta"><span class="status"></span><span class="truncate">${conv.last_preview || 'No messages'}</span></div></div>`;
      item.onclick = () => selectConversation(conv.address, conv.name || conv.address, !!conv.is_group);
      container.appendChild(item);
    });
  } catch (error) {
    console.error('Load conversations error:', error);
    container.innerHTML = '<p class="text-muted text-center">Failed to load</p>';
  }
}

function selectConversation(address, name, isGroup) {
  stopPolling();
  State.currentChatUnsub?.();
  State.currentChatUnsub = null;

  State.currentChatAddress = address;
  State.currentChatIsGroup = !!isGroup;
  State.currentChatPartnerAddress = isGroup ? '' : (address === State.userAddress ? '' : address);

  window.NotificationManager?.setActiveChat?.(address);

  const container = document.getElementById('messagesContainer');
  container.innerHTML = '<div class="loading">Loading…</div>';
  container.classList.add('loading');
  _disableChatControls();

  document.getElementById('currentChatName').textContent = name || 'Loading…';
  document.getElementById('chatSubtitle').textContent = isGroup ? 'Group chat' : 'Direct message';

  document.querySelectorAll('.conversation-item').forEach(item => {
    item.classList.toggle('active', item.dataset.address === address);
  });

  State.lastKnownMessageId = 0;
  State.lastMessageTimestamp = 0;
  State.pendingImageData = null;

  loadMessagesForConversation(address, false);
  _subscribeToCurrentChat(address);

  setTimeout(() => { if (State.currentChatAddress === address) startPolling(); }, 500);
}

function _subscribeToCurrentChat(chatId) {
  if (!window.p2p?.subscribe) { console.warn('⚠️ P2P not available'); return; }
  console.log('🔗 Subscribing to:', chatId.slice(0, 16) + '…');

  State.currentChatUnsub = window.p2p.subscribe(chatId, async (msg) => {
    console.log('📥 P2P message via', msg.via);
    try {
      const res = await fetch('/decrypt_message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ encrypted_payload: msg.encryptedPayload, peer_address: msg.sender }),
        cache: 'no-store'
      });
      const decrypted = await res.json();
      if (res.ok && decrypted?.content !== undefined) {
        appendMessageToUI({
          sender: msg.sender,
          content: decrypted.content,
          image: decrypted.image,
          timestamp: msg.timestamp ? (msg.timestamp > 1e10 ? msg.timestamp / 1000 : msg.timestamp) : Date.now() / 1000,
          is_mine: false,
          id: 'p2p_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8),
          chatId: chatId
        });
      } else {
        console.warn('⚠️ Decrypt failed:', decrypted.error);
        loadMessagesForConversation(chatId, true);
      }
    } catch (e) {
      console.warn('⚠️ P2P error, falling back to polling:', e);
      loadMessagesForConversation(chatId, true);
    }
  });
}

function _disableChatControls() {
  document.getElementById('messageContent').disabled = true;
  document.getElementById('attachImageButton').disabled = true;
  document.getElementById('sendButton').disabled = true;
  document.getElementById('addToContactsBtn').disabled = true;
  document.getElementById('clearConversationBtn').disabled = true;
}

function _enableChatControls() {
  document.getElementById('messageContent').disabled = false;
  document.getElementById('attachImageButton').disabled = false;
  document.getElementById('sendButton').disabled = false;
  document.getElementById('clearConversationBtn').disabled = false;
  const btn = document.getElementById('addToContactsBtn');
  if (State.currentChatIsGroup || !State.currentChatPartnerAddress || State.currentChatPartnerAddress === State.userAddress) {
    btn.disabled = true; btn.title = "Cannot add group or yourself";
  } else { btn.disabled = false; btn.title = "Add to contacts"; }
}

// =============================================================================
// === 🔧 ИСПРАВЛЕННЫЙ: loadMessagesForConversation — НЕ мигает "No messages" ===
// =============================================================================
async function loadMessagesForConversation(chatWithAddress, isNewMessage = false) {
  const container = document.getElementById('messagesContainer');

  if (!chatWithAddress) {
    if (!isNewMessage) {
      container.innerHTML = `<div class="empty-state animate-fade"><div class="icon">💬</div><p>Select a conversation to start chatting</p></div>`;
    }
    _enableChatControls();
    return;
  }

  const isGroup = chatWithAddress.startsWith('group:');
  const isPersonal = /^[a-fA-F0-9]{64}$/.test(chatWithAddress);

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

    const res = await fetch(`/get_conversation?${params}`, { signal: controller.signal });
    clearTimeout(timeout);

    const data = await res.json();
    container.classList.remove('loading');

    if (!res.ok) throw new Error(data.error || 'Failed to load');

    const messages = Array.isArray(data.messages) ? data.messages : [];
    const shouldScroll = isNewMessage || (container.scrollTop + container.clientHeight >= container.scrollHeight - 50);

    // 🔧 КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: не очищаем при добавлении новых сообщений!
    if (!isNewMessage || State.lastKnownMessageId === 0) {
      container.innerHTML = '';
      if (!messages.length) {
        container.innerHTML = `<div class="empty-state animate-fade"><div class="icon">👋</div><p>No messages yet</p><p class="text-muted" style="font-size:12px">Start the conversation!</p></div>`;
        _enableChatControls();
        return;
      }
    }

    if (messages.length) {
  let maxTimestamp = 0;
  const fragment = document.createDocumentFragment();

  messages.forEach(msg => {
    if (document.getElementById(`msg-${msg.id}`)) return;
    if (msg.timestamp > maxTimestamp) maxTimestamp = msg.timestamp;

    // ... создание messageDiv ...
    fragment.appendChild(messageDiv);
    if (msg.id > State.lastKnownMessageId) State.lastKnownMessageId = msg.id;
  });

  container.appendChild(fragment);
  State.lastMessageTimestamp = maxTimestamp;

  // ✅ ПЕРЕсчитываем shouldScroll ПОСЛЕ добавления сообщений!
  const shouldScroll = isNewMessage || isUserAtBottom(container);
  if (shouldScroll) {
    smartScrollToBottom(container, !isNewMessage); // force=true только при первой загрузке
  }
}

    // 🎯 УМНЫЙ СКРОЛЛ
    if (!isNewMessage) {
      smartScrollToBottom(container, true);
    } else {
      smartScrollToBottom(container, false);
    }

    _enableChatControls();
  } catch (error) {
    console.error('Load messages error:', error);
    container.classList.remove('loading');
    if (error.name === 'AbortError') {
      container.innerHTML = '<p class="text-muted text-center">Request timed out</p>';
    } else if (!isNewMessage) {
      container.innerHTML = '<p class="text-muted text-center">Failed to load messages</p>';
    }
    _enableChatControls();
  }
}

// =============================================================================
// === 🔧 ИСПРАВЛЕННЫЙ: appendMessageToUI — НЕ прыгает вниз ===
// =============================================================================
function appendMessageToUI(msg) {
  const container = document.getElementById('messagesContainer');
  if (!container) { console.warn('⚠️ appendMessageToUI: container not found'); return; }
  if (document.getElementById(`msg-${msg.id}`)) { console.debug('🔄 Skipping duplicate:', msg.id); return; }

  // 🔧 Запоминаем, был ли пользователь внизу ДО добавления
  const wasAtBottom = isUserAtBottom(container);

  const messageDiv = document.createElement('div');
  messageDiv.id = `msg-${msg.id}`;
  messageDiv.className = `message ${msg.is_mine ? 'sent' : 'received'} animate-fade`;
  messageDiv.dataset.messageId = msg.id;

  const initials = (msg.sender || 'U').slice(0, 1).toUpperCase();
  const senderName = msg.is_mine || !State.currentChatIsGroup ? '' : `<strong>${Utils.escapeHtml(msg.sender_name || msg.sender?.slice(0, 10) + '…')}</strong><br>`;

  let imageHtml = '';
  if (msg.image) {
    imageHtml = `<img src="${Utils.escapeHtml(msg.image)}" alt="Image" onclick="openImageModal('${Utils.escapeHtml(msg.image)}')" style="cursor:pointer;max-width:100%;border-radius:6px;margin:4px 0;">`;
  }

  const timeStr = Utils.formatTimestamp(msg.timestamp);

  messageDiv.innerHTML = `<div class="avatar">${Utils.escapeHtml(initials)}</div><div class="content">${senderName}<p>${Utils.escapeHtml(msg.content || '')}</p>${imageHtml}<div class="meta"><span>${timeStr}</span></div></div>`;
  container.appendChild(messageDiv);

  // 🔔 Notifications — only if tab hidden or not in active chat
  const shouldNotify = document.visibilityState !== 'visible' || !window.NotificationManager?._isInActiveChat?.(msg.chatId);
  if (shouldNotify && window.NotificationManager?.handleIncomingMessage) {
    window.NotificationManager.handleIncomingMessage({
      sender: msg.sender,
      chatId: msg.chatId || State.currentChatAddress,
      content: msg.content,
      image: msg.image,
      timestamp: (msg.timestamp || Date.now()/1000) * 1000
    });
  }

  // 🎯 УМНЫЙ СКРОЛЛ: только если пользователь был внизу
  if (wasAtBottom) {
    smartScrollToBottom(container, false);
  } else {
    showNewMessagesBadge();
  }
}

async function sendMessage() {
  const content = document.getElementById('messageContent').value.trim();
  const recipient = State.currentChatAddress;
  if (!recipient || (!content && !State.pendingImageData)) {
    window.NotificationManager?.showToast?.('Enter a message or attach an image', 'warning');
    return;
  }

  const isGroup = State.currentChatIsGroup;
  const messageType = isGroup ? 'group' : 'direct';
  const groupId = isGroup && recipient.startsWith('group:') ? recipient.split(':')[1] : null;

  const payload = {
    recipient,
    content: content || '',
    message_type: messageType,
    ...(groupId && { group_id: groupId }),
    ...(State.pendingImageData && { image: State.pendingImageData })
  };

  try {
    const res = await fetch('/send_message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (res.ok) {
      document.getElementById('messageContent').value = '';
      State.pendingImageData = null;
      loadMessagesForConversation(recipient, true);

      if (window.p2p && window.GunConfig?.encryptMessage) {
        const txId = 'tx_' + Date.now() + '_' + Math.random().toString(36).slice(2);
        const encrypted = await window.GunConfig.encryptMessage(content, recipient, State.pendingImageData);
        window.p2p.send(recipient, encrypted, txId);
      }
    } else {
      window.NotificationManager?.showToast?.(data.error || 'Send failed', 'error');
    }
  } catch (error) {
    console.error('Send error:', error);
    window.NotificationManager?.showToast?.('Network error', 'error');
  }
}

async function addContactFromChat() {
  if (!State.currentChatPartnerAddress || State.currentChatPartnerAddress === State.userAddress) {
    window.NotificationManager?.showToast?.('Cannot add this conversation', 'warning');
    return;
  }
  const name = document.getElementById('currentChatName')?.textContent || State.currentChatPartnerAddress.slice(0, 10) + '…';
  try {
    const res = await fetch('/add_contact_from_chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contact_address: State.currentChatPartnerAddress, contact_name: name })
    });
    const data = await res.json();
    if (res.ok) {
      window.NotificationManager?.showToast?.('Contact added', 'success');
      document.getElementById('addToContactsBtn').disabled = true;
    } else {
      window.NotificationManager?.showToast?.(data.error || 'Failed to add', 'error');
    }
  } catch (error) {
    console.error('Add contact error:', error);
    window.NotificationManager?.showToast?.('Network error', 'error');
  }
}

async function deleteMessage(messageId, buttonEl) {
  if (!confirm('Delete this message?')) return;
  try {
    buttonEl.disabled = true; buttonEl.textContent = '…';
    const res = await fetch('/delete_message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_id: messageId })
    });
    const data = await res.json();
    if (res.ok) {
      document.getElementById(`msg-${messageId}`)?.remove();
      window.NotificationManager?.showToast?.('Message deleted', 'success');
    } else {
      window.NotificationManager?.showToast?.(data.error || 'Delete failed', 'error');
      buttonEl.disabled = false; buttonEl.textContent = '🗑';
    }
  } catch (error) {
    console.error('Delete error:', error);
    window.NotificationManager?.showToast?.('Network error', 'error');
    buttonEl.disabled = false; buttonEl.textContent = '🗑';
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
      window.NotificationManager?.showToast?.('Conversation cleared', 'success');
    } else {
      window.NotificationManager?.showToast?.(data.error || 'Clear failed', 'error');
    }
  } catch (error) {
    console.error('Clear error:', error);
    window.NotificationManager?.showToast?.('Network error', 'error');
  }
}

// =============================================================================
// === Polling ===
// =============================================================================
function startPolling() {
  if (State.pollInterval) clearInterval(State.pollInterval);
  if (!State.currentChatAddress) return;
  const chatAtStart = State.currentChatAddress;
  State.pollInterval = setInterval(() => {
    if (State.currentChatAddress === chatAtStart) {
      loadMessagesForConversation(State.currentChatAddress, true);
    } else { stopPolling(); }
  }, 3000);
}

function stopPolling() {
  if (State.pollInterval) { clearInterval(State.pollInterval); State.pollInterval = null; }
}

// =============================================================================
// === Image Handling ===
// =============================================================================
function handleImageSelection(event) {
  const file = event.target.files[0];
  if (file?.type?.startsWith('image/')) {
    const reader = new FileReader();
    reader.onload = (e) => { State.pendingImageData = e.target.result; };
    reader.readAsDataURL(file);
    window.NotificationManager?.showToast?.('Image attached', 'success');
  } else {
    window.NotificationManager?.showToast?.('Please select an image', 'warning');
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
      const link = document.createElement('a');
      link.href = src;
      link.download = `image-${Date.now()}.png`;
      link.click();
    };
  }
}

function closeImageModal() { document.getElementById('imageModal')?.classList.add('hidden'); }

// =============================================================================
// === Modal Controls ===
// =============================================================================
function openNewChatModal() {
  const modal = document.getElementById('newChatModal');
  if (modal) modal.classList.remove('hidden');
  document.getElementById('newChatSelect').value = '';
  document.getElementById('newChatAddress').value = '';
  loadContactsForModal();
  QRScanner.close();
}

function closeNewChatModal() {
  document.getElementById('newChatModal')?.classList.add('hidden');
  QRScanner.close();
}

async function loadContactsForModal() {
  try {
    const res = await fetch('/get_contacts');
    const data = await res.json();
    if (res.ok && data.contacts) {
      State.allContacts = data.contacts;
      const select = document.getElementById('newChatSelect');
      select.innerHTML = '<option value="">-- Choose a contact --</option>';
      data.contacts.forEach(c => {
        const option = document.createElement('option');
        option.value = c.address;
        const name = c.name.length > 30 ? c.name.slice(0, 27) + '…' : c.name;
        option.textContent = `${Utils.escapeHtml(name)} (${c.address.slice(0, 10)}…)`;
        select.appendChild(option);
      });
    }
  } catch (error) { console.error('Load contacts error:', error); }
}

async function startNewChat() {
  const selected = document.getElementById('newChatSelect')?.value?.trim();
  const entered = document.getElementById('newChatAddress')?.value?.trim();
  let address = '', name = '';

  if (selected) {
    address = selected;
    const contact = State.allContacts.find(c => c.address === selected);
    name = contact?.name || selected.slice(0, 10) + '…';
  } else if (entered) {
    if (entered.length !== 64 || !/^[a-fA-F0-9]{64}$/.test(entered)) {
      window.NotificationManager?.showToast?.('Invalid address format', 'error');
      return;
    }
    if (entered === State.userAddress) {
      window.NotificationManager?.showToast?.('Cannot chat with yourself', 'warning');
      return;
    }
    address = entered;
    name = entered.slice(0, 10) + '…';
  } else {
    window.NotificationManager?.showToast?.('Select a contact or enter address', 'warning');
    return;
  }

  closeNewChatModal();
  selectConversation(address, name, false);
}

// =============================================================================
// === Init ===
// =============================================================================
document.addEventListener('DOMContentLoaded', function() {
  window.NotificationManager?.init?.();
  if (State.currentChatAddress) window.NotificationManager?.setActiveChat?.(State.currentChatAddress);
  loadConversations();

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
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
  }

  document.getElementById('messagesContainer')?.addEventListener('click', (e) => {
    if (e.target.tagName === 'IMG' && e.target.closest('.message')) {
      openImageModal(e.target.dataset.fullSrc || e.target.src);
    }
    if (e.target.classList.contains('delete-btn')) {
      const id = parseInt(e.target.dataset.id, 10);
      if (id) deleteMessage(id, e.target);
    }
  });

  document.getElementById('newChatBtn')?.addEventListener('click', openNewChatModal);
  document.querySelector('#newChatModal .modal-close')?.addEventListener('click', closeNewChatModal);
  document.getElementById('startNewChatBtn')?.addEventListener('click', startNewChat);

  window.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) {
      e.target.classList.add('hidden');
      QRScanner.close();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeNewChatModal(); closeImageModal(); QRScanner.close(); }
  });
});

// =============================================================================
// === Cleanup ===
// =============================================================================
window.addEventListener('beforeunload', function() {
  QRScanner.close();
  stopPolling();
  State.currentChatUnsub?.();
  window.p2p?.unsubscribeAll?.();
  window.NotificationManager?.destroy?.();
});

// Export for external use
window.selectConversation = selectConversation;
window.appendMessageToUI = appendMessageToUI;
window.loadMessagesForConversation = loadMessagesForConversation;
</script>