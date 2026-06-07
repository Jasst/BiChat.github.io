// core.js — ядро мессенджера с поддержкой зашифрованного localStorage и кеша сообщений
// Fully internationalized (i18n)
(function() {
    if (window._coreLoaded) return;
    window._coreLoaded = true;

    // Helper for safe i18n (fallback to English if i18next not ready)
    function t(key, opts) {
        if (typeof i18next !== 'undefined' && i18next.t) {
            return i18next.t(key, opts);
        }
        // Fallback English for keys used in this file
        const fallbacks = {
            'unlock_wallet_title': 'Unlock wallet',
            'unlock_wallet_desc': 'Your encrypted wallet was found. Enter password to unlock.',
            'password': 'Password',
            'log_out': 'Log out',
            'unlock': 'Unlock',
            'please_enter_password': 'Please enter password',
            'wrong_password': 'Wrong password',
            'public_key_not_found': 'Public key not found for {address}',
            'public_key_mismatch': '⚠️ Public key mismatch for {address} — possible MITM!',
            'no_mnemonic_available': 'No mnemonic available',
            'mnemonic_not_found': 'Mnemonic not found',
            'no_access': '🔒 No access',
            'no_sender_pubkey': '🔒 No sender pubkey',
            'decrypt_error': '🔒 Decrypt error',
            'new_message_preview': '💬 New message',
            'read_status': '✓✓ Read',
            'delivered_status': '✓✓ Delivered',
            'sent_status': '✓ Sent',
            'online': 'Online',
            'offline': 'Offline'
        };
        let result = fallbacks[key];
        if (result && opts) {
            if (opts.address) result = result.replace('{address}', opts.address);
        }
        return result || key;
    }

    // ========== Глобальные утилиты ==========
    window.Utils = window.Utils || {};
    Utils.escapeHtml = function(str) {
        if (!str) return '';
        return str.replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m]))
                  .replace(/['"]/g, m => ({ "'": '&#39;', '"': '&quot;' }[m]));
    };
    Utils.formatTimestamp = function(ts) {
        if (!ts) return '';
        const date = new Date(ts * 1000);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    };
    Utils.copyToClipboard = function(text, onSuccess, onError) {
        navigator.clipboard.writeText(text).then(onSuccess).catch(onError);
    };

    // ========== Глобальное состояние ==========
    let initialAddress = '';
    const metaAddress = document.querySelector('meta[name="user-address"]')?.content;
    if (metaAddress && metaAddress !== 'None' && metaAddress !== '') {
        initialAddress = metaAddress;
    }

    window.State = {
        currentChatAddress: '',
        currentChatIsGroup: false,
        currentGroupMembers: null,
        currentChatPartnerAddress: '',
        userAddress: initialAddress || (document.getElementById('app')?.dataset.userAddress) || '',
        lastMessageTimestamp: 0,
        allContacts: [],
        lastKnownMessageId: 0,
        pendingImageData: null,
        topObserver: null,
        _restoringMnemonic: false
    };
    window.isSending = false;
    window.userKeys = null;
    window.pubKeyCache = new Map();

    // ========== Кеш сообщений (в памяти, на время сессии) ==========
    window.messagesCache = new Map();

    window.addMessageToCache = function(chatId, message, position = 'end') {
        if (!chatId || !message || !message.id) return;
        let messages = window.messagesCache.get(chatId);
        if (!messages) {
            messages = [];
            window.messagesCache.set(chatId, messages);
        }
        const exists = messages.some(m => m.id === message.id);
        if (exists) return;
        if (position === 'start') {
            messages.unshift(message);
        } else {
            messages.push(message);
        }
        messages.sort((a, b) => a.id - b.id);
    };

    window.addMessagesToCache = function(chatId, newMessages, position = 'end') {
        if (!chatId || !newMessages?.length) return;
        let messages = window.messagesCache.get(chatId);
        if (!messages) {
            messages = [];
            window.messagesCache.set(chatId, messages);
        }
        if (position === 'start') {
            messages.unshift(...newMessages);
        } else {
            messages.push(...newMessages);
        }
        const unique = new Map();
        for (const msg of messages) unique.set(msg.id, msg);
        const sorted = Array.from(unique.values()).sort((a, b) => a.id - b.id);
        window.messagesCache.set(chatId, sorted);
    };

    window.getCachedMessages = function(chatId) {
        return window.messagesCache.get(chatId) || [];
    };

    window.clearMessageCache = function(chatId) {
        if (chatId) window.messagesCache.delete(chatId);
        else window.messagesCache.clear();
    };

    // ========== Управление зашифрованной мнемоникой ==========
    async function restoreMnemonic() {
        if (sessionStorage.getItem('mnemonic')) return true;
        const publicPaths = ['/login', '/', '/index', '/create_wallet'];
        const currentPath = window.location.pathname;
        if (publicPaths.some(p => currentPath === p || currentPath.startsWith(p + '?'))) {
            console.debug('Public page, skipping mnemonic restore');
            return false;
        }
        if (State._restoringMnemonic) {
            return new Promise(resolve => {
                const interval = setInterval(() => {
                    if (!State._restoringMnemonic) {
                        clearInterval(interval);
                        resolve(!!sessionStorage.getItem('mnemonic'));
                    }
                }, 100);
            });
        }
        State._restoringMnemonic = true;
        const encrypted = localStorage.getItem('encrypted_mnemonic');
        if (!encrypted) {
            window.location.href = '/login';
            State._restoringMnemonic = false;
            return false;
        }
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.className = 'modal-overlay';
            modal.style.zIndex = '10000';
modal.innerHTML = `
    <div class="modal" style="max-width:400px;">
        <div class="modal-header"><h3 data-i18n="unlock_wallet_title">Unlock wallet</h3></div>
        <div class="modal-body">
            <p data-i18n="unlock_wallet_desc">Your encrypted wallet was found. Enter password to unlock.</p>
            <input type="password" id="unlockPassword" class="input" placeholder="Password" style="width:100%;" data-i18n-placeholder="password">
            <div id="unlockError" class="text-error" style="color:var(--danger);margin-top:8px;display:none;"></div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-ghost" id="cancelUnlock" data-i18n="log_out">Log out</button>
            <button class="btn btn-primary" id="confirmUnlock" data-i18n="unlock">Unlock</button>
        </div>
    </div>`;

            if (window.localizePage) window.localizePage();
            document.body.appendChild(modal);
            const passwordInput = modal.querySelector('#unlockPassword');
            const errorDiv = modal.querySelector('#unlockError');
            const confirmBtn = modal.querySelector('#confirmUnlock');
            const cancelBtn = modal.querySelector('#cancelUnlock');
            const attemptUnlock = async () => {
                const pwd = passwordInput.value;
                if (!pwd) {
                    errorDiv.textContent = t('please_enter_password');
                    errorDiv.style.display = 'block';
                    return;
                }
                confirmBtn.disabled = true;
                confirmBtn.textContent = '...';
                const mnemonic = await window.StorageEncryption.decryptMnemonic(encrypted, pwd);
                if (mnemonic) {
                    sessionStorage.setItem('mnemonic', mnemonic);
                    modal.remove();
                    State._restoringMnemonic = false;
                    resolve(true);
                } else {
                    errorDiv.textContent = t('wrong_password');
                    errorDiv.style.display = 'block';
                    confirmBtn.disabled = false;
                    confirmBtn.textContent = t('unlock');
                }
            };
            const clearAndLogout = () => {
                localStorage.removeItem('encrypted_mnemonic');
                sessionStorage.removeItem('mnemonic');
                window.location.href = '/login';
                State._restoringMnemonic = false;
                resolve(false);
            };
            confirmBtn.onclick = attemptUnlock;
            cancelBtn.onclick = clearAndLogout;
            passwordInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') attemptUnlock(); });
        });
    }

    // ========== Криптографические помощники ==========
    async function getPubKey(address) {
        if (pubKeyCache.has(address)) return pubKeyCache.get(address);
        const res = await fetch(`/get_public_key/${address}`);
        if (!res.ok) throw new Error(t('public_key_not_found', { address }));
        const data = await res.json();
        const pubKeyBytes = DarkCrypto._fromBase64(data.public_key);
        const hashBuf = await crypto.subtle.digest('SHA-256', pubKeyBytes);
        const computedAddress = Array.from(new Uint8Array(hashBuf))
            .map(b => b.toString(16).padStart(2, '0')).join('');
        if (computedAddress !== address) {
            throw new Error(t('public_key_mismatch', { address }));
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
        if (window.userKeys) return window.userKeys;
        if (!sessionStorage.getItem('mnemonic')) {
            const restored = await restoreMnemonic();
            if (!restored) throw new Error(t('no_mnemonic_available'));
        }
        const mnemonic = sessionStorage.getItem('mnemonic');
        if (!mnemonic) throw new Error(t('mnemonic_not_found'));
        window.userKeys = await DarkCrypto.deriveKeyPair(mnemonic);
        return window.userKeys;
    }

    // ========== WebSocket клиент ==========
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
            if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
            if (!this.url) {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                this.url = `${protocol}//${window.location.host}/ws`;
            }
            let finalUrl = this.url;
            if (this.address && this.signature && this.nonce) {
                finalUrl += `?address=${encodeURIComponent(this.address)}&signature=${encodeURIComponent(this.signature)}&nonce=${encodeURIComponent(this.nonce)}`;
            }
            this.ws = new WebSocket(finalUrl);
            this.ws.onopen = () => this._onOpen();
            this.ws.onmessage = (event) => this._onMessage(event);
            this.ws.onerror = (error) => this._onError(error);
            this.ws.onclose = (event) => this._onClose(event);
        }
        disconnect() {
            this.shouldReconnect = false;
            if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
            if (this.ws) { this.ws.close(); this.ws = null; }
            this.isConnected = false;
        }
        _onOpen() { this.isConnected = true; this.onConnect(); }
        _onMessage(event) {
            try { this.onMessage(JSON.parse(event.data)); }
            catch (e) { console.debug('Invalid JSON'); }
        }
        _onError(error) { this.onError(error); }
        _onClose(event) {
            this.isConnected = false;
            this.onDisconnect();
            if (this.shouldReconnect && event.code !== 1008) this._scheduleReconnect();
        }
        _scheduleReconnect() {
            if (this.reconnectTimer) return;
            this.reconnectTimer = setTimeout(() => {
                this.reconnectTimer = null;
                this.connect();
                this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
            }, this.reconnectDelay);
        }
        log(...args) { if (this.debug) console.log('[WebSocket]', ...args); }
    }

    async function initWebSocket() {
        if (!sessionStorage.getItem('mnemonic')) {
            const restored = await restoreMnemonic();
            if (!restored) return;
        }
        if (window.wsClient) window.wsClient.disconnect();
        let address = State.userAddress;
        if (!address) {
            const meta = document.querySelector('meta[name="user-address"]')?.content;
            if (meta && meta !== 'None') address = meta;
        }
        if (!address) {
            console.warn('No user address, WebSocket not initialized');
            return;
        }
        try {
            const keys = await ensureKeys();
            const nonce = crypto.randomUUID();
            const signatureArray = await DarkCrypto.signData(keys.signPrivateKey, nonce);
            const signatureHex = Array.from(new Uint8Array(signatureArray)).map(b => b.toString(16).padStart(2, '0')).join('');
            window.wsClient = new WebSocketClient({
                onMessage: window.handleWebSocketMessage,
                onConnect: () => {
                    console.log('✅ WebSocket connected');
                    if (window.loadConversations) window.loadConversations();
                    if (window.initPushNotifications) window.initPushNotifications();
                },
                onDisconnect: () => console.warn('⚠️ WebSocket disconnected'),
                onError: (err) => console.error('WebSocket error:', err)
            });
            window.wsClient.setAuth(address, signatureHex, nonce);
            window.wsClient.connect();

        } catch (err) { console.error('Failed to init WebSocket:', err); }
    }

    // ========== Обработка входящих сообщений (WebSocket + расшифровка файлов) ==========
    async function processMessageDecryption(msg) {
        if (!msg.content) return msg;
        let content = msg.content;
        let image = msg.image;
        let fileUrl = null, fileKey = null, fileIv = null, fileType = null;

        try {
            const parsed = JSON.parse(content);
            const keys = await ensureKeys();
            const arraysEqual = (a, b) => {
                if (!a || !b || a.length !== b.length) return false;
                for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
                return true;
            };

            // ---------- ГРУППОВОЙ ЧАТ ----------
            if (parsed.encrypted_map) {
                const myAddr = State.userAddress;
                const myEnc = parsed.encrypted_map[myAddr];
                if (!myEnc) return { ...msg, content: t('no_access') };
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
                return { ...msg, content, image, fileUrl, fileKey, fileIv, fileType, is_mine: isMine, chatId, isGroup: true, isDecrypted: true };
            }

            // ---------- ЛИЧНЫЙ ЧАТ ----------
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
                const chatId = msg.sender === State.userAddress ? msg.recipient : msg.sender;
                return { ...msg, content: t('no_sender_pubkey'), image: null, fileUrl, fileKey, fileIv, fileType, is_mine: false, chatId, isDecrypted: false };
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

            const chatId = msg.sender === State.userAddress ? msg.recipient : msg.sender;
            return { ...msg, content, image: null, fileUrl, fileKey, fileIv, fileType, is_mine: isMine, chatId, isDecrypted: true };
        } catch (e) {
            console.error('Decryption error', msg.id, e);
            const chatId = msg.sender === State.userAddress ? msg.recipient : msg.sender;
            return { ...msg, content: t('decrypt_error'), image: null, chatId, isDecrypted: false };
        }
    }

    async function handleWebSocketMessage(data) {
        if (data.error) { console.error('WS error:', data.error); return; }
        if (data.type === 'status_update') {
            if (data.address && data.status) {
                if (window.updateConversationStatus) {
                    window.updateConversationStatus(data.address, data.status);
                }
            }
            return;
        }
        if (!data.chatId && data.sender && data.recipient) data.chatId = (data.sender === State.userAddress) ? data.recipient : data.sender;
        if (!data.chatId) return;
        if (document.getElementById('msg-' + data.id)) return;

        const decrypted = await processMessageDecryption(data);
        const chatId = decrypted.chatId;

        if (decrypted && decrypted.id) {
            window.addMessageToCache(chatId, decrypted, 'end');
        }

        if (!decrypted.is_mine) {
            fetch(`/message/${decrypted.id}/delivered`, { method: 'POST' }).catch(e => console.warn);
        }

        let isCurrent = false;
        if (State.currentChatAddress === chatId) {
            isCurrent = true;
        } else if (!decrypted.isGroup && (
            decrypted.sender === State.currentChatAddress ||
            decrypted.recipient === State.currentChatAddress
        )) {
            isCurrent = true;
        }

        if (!isCurrent) {
            const existingItem = document.querySelector(`.conversation-item[data-address="${chatId}"]`);
            if (!existingItem) { if (window.loadConversations) window.loadConversations(); }
            else if (window.updateConversationPreview) window.updateConversationPreview(chatId, decrypted.preview || t('new_message_preview'));
        }

        if (isCurrent && window.onNewMessageReceived) {
            window.onNewMessageReceived(decrypted);
        }

        if (window.NotificationManager) {
            window.NotificationManager.handleIncomingMessage?.({
                sender: decrypted.sender,
                sender_name: decrypted.sender_name,
                chatId: chatId,
                isGroup: decrypted.isGroup,
                preview: decrypted.preview || decrypted.content?.slice(0, 50),
                timestamp: decrypted.timestamp * 1000,
                messageId: decrypted.id
            });
        }
    }

    // ========== Heartbeat ==========
    let heartbeatInterval = null;
    function startHeartbeat() {
        if (heartbeatInterval) clearInterval(heartbeatInterval);
        heartbeatInterval = setInterval(async () => {
            if (!State.userAddress) return;
            try {
                await fetch('/heartbeat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ current_chat: State.currentChatAddress || '' })
                });
            } catch(e) { console.debug('Heartbeat failed', e); }
        }, 30000);
    }
    function stopHeartbeat() { if (heartbeatInterval) { clearInterval(heartbeatInterval); heartbeatInterval = null; } }

    // ========== Поллинг статусов сообщений ==========
    let statusPollingInterval = null;
    function startStatusPolling() {
        if (statusPollingInterval) clearInterval(statusPollingInterval);
        statusPollingInterval = setInterval(async () => {
            const myMessages = document.querySelectorAll('.message-own');
            const ids = Array.from(myMessages).map(el => el.dataset.id).filter(id => id && !id.startsWith('temp'));
            if (ids.length === 0) return;
            try {
                const res = await fetch('/message/statuses', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ids })
                });
                const statuses = await res.json();
                for (const [id, st] of Object.entries(statuses)) {
                    const msgDiv = document.querySelector(`.message-own[data-id="${id}"]`);
                    if (msgDiv && msgDiv.dataset.status !== st) {
                        msgDiv.dataset.status = st;
                        if (window.updateStatusIcon) window.updateStatusIcon(msgDiv, st);
                        if (window.updateConversationPreview) {
                            const container = document.getElementById('messagesContainer');
                            const lastMsg = container?.querySelector('.message:last-child');
                            if (lastMsg && lastMsg.dataset.id === id) {
                                let previewText = '';
                                if (st === 'read') previewText = t('read_status');
                                else if (st === 'delivered') previewText = t('delivered_status');
                                else previewText = t('sent_status');
                                window.updateConversationPreview(State.currentChatAddress, previewText);
                            }
                        }
                    }
                }
            } catch(e) { console.warn('Status polling error', e); }
        }, 30000);
    }
    function stopStatusPolling() { if (statusPollingInterval) clearInterval(statusPollingInterval); }

    // ========== Поллинг статусов пользователей ==========
    let userStatusPollingInterval = null;
    async function pollUserStatuses() {
        const items = document.querySelectorAll('.conversation-item:not([data-is-group="1"])');
        const addresses = Array.from(items)
            .map(el => el.dataset.address)
            .filter(addr => addr && addr !== State.userAddress);
        if (addresses.length === 0) return;
        if (!window.fetchUserStatuses) return;
        const statuses = await window.fetchUserStatuses(addresses);
        for (const el of items) {
            const addr = el.dataset.address;
            const status = statuses[addr]?.status || 'offline';
            const statusSpan = el.querySelector('.status');
            if (statusSpan) {
                statusSpan.className = `status ${status}`;
                statusSpan.title = status === 'online' ? t('online') : t('offline');
            }
        }
    }
    function startUserStatusPolling() {
        if (userStatusPollingInterval) clearInterval(userStatusPollingInterval);
        userStatusPollingInterval = setInterval(() => { pollUserStatuses(); }, 30000);
    }
    function stopUserStatusPolling() {
        if (userStatusPollingInterval) {
            clearInterval(userStatusPollingInterval);
            userStatusPollingInterval = null;
        }
    }

    // ========== Push Notifications ==========
    window.initPushNotifications = initPushNotifications;
    window.urlBase64ToUint8Array = urlBase64ToUint8Array;

    async function initPushNotifications() {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;

        let permission = await Notification.permission;
        if (permission !== 'granted') {
            permission = await Notification.requestPermission();
            if (permission !== 'granted') return;
        }

        const registration = await navigator.serviceWorker.ready;
        const publicKey = 'BPa5fghsHcpAbmlQTdXg6WzoMC_iPaDMzFY4mc2BUipmno6sLxN6KoSfaZfgUFkh9c0B34XhBvC93WXn92xKlkw';
        const applicationServerKey = urlBase64ToUint8Array(publicKey);

        let subscription = await registration.pushManager.getSubscription();
        if (!subscription) {
            subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: applicationServerKey
            });
        }

        await fetch('/push/subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(subscription)
        });
    }

    function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
        const rawData = atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    // Экспорт глобальных функций
    window.getPubKey = getPubKey;
    window.compressImage = compressImage;
    window.ensureKeys = ensureKeys;
    window.initWebSocket = initWebSocket;
    window.startHeartbeat = startHeartbeat;
    window.stopHeartbeat = stopHeartbeat;
    window.startStatusPolling = startStatusPolling;
    window.stopStatusPolling = stopStatusPolling;
    window.processMessageDecryption = processMessageDecryption;
    window.handleWebSocketMessage = handleWebSocketMessage;
    window.startUserStatusPolling = startUserStatusPolling;
    window.stopUserStatusPolling = stopUserStatusPolling;
    window.wsClient = null;
})();