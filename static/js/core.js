// core.js — ядро мессенджера (состояние, WebSocket, криптоутилиты, сердцебиение)
(function() {
    if (window._coreLoaded) return;
    window._coreLoaded = true;

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
    window.State = {
        currentChatAddress: '',
        currentChatIsGroup: false,
        currentGroupMembers: null,
        currentChatPartnerAddress: '',
        userAddress: (document.getElementById('app')?.dataset.userAddress) || AppData?.userAddress || '',
        lastMessageTimestamp: 0,
        allContacts: [],
        lastKnownMessageId: 0,
        pendingImageData: null,
        topObserver: null
    };
    window.isSending = false;
    window.userKeys = null;
    window.pubKeyCache = new Map();

    // ========== Криптографические помощники ==========
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
        if (window.userKeys) return window.userKeys;
        const mnemonic = sessionStorage.getItem('mnemonic');
        if (!mnemonic) throw new Error('No mnemonic in session');
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
        if (window.wsClient) window.wsClient.disconnect();
        try {
            const keys = await ensureKeys();
            const nonce = crypto.randomUUID();
            const signatureArray = await DarkCrypto.signData(keys.signPrivateKey, nonce);
            const signatureHex = Array.from(new Uint8Array(signatureArray)).map(b => b.toString(16).padStart(2, '0')).join('');
            window.wsClient = new WebSocketClient({
                onMessage: window.handleWebSocketMessage,  // определим в core.js чуть ниже
                onConnect: () => { console.log('✅ WebSocket connected'); if (window.loadConversations) window.loadConversations(); },
                onDisconnect: () => console.warn('⚠️ WebSocket disconnected'),
                onError: (err) => console.error('WebSocket error:', err)
            });
            window.wsClient.setAuth(State.userAddress, signatureHex, nonce);
            window.wsClient.connect();
        } catch (err) { console.error('Failed to init WebSocket:', err); }
    }

    // ========== Обработка входящих сообщений (WebSocket) ==========
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
                    const ciphertext = DarkCrypto._base64ToArrayBuffer(myEnc.self_ciphertext || myEnc.ciphertext);
                    const iv = DarkCrypto._fromBase64(myEnc.self_iv || myEnc.iv);
                    const shared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, senderPubKeyBytes);
                    content = await DarkCrypto.decryptAES(shared, ciphertext, iv);
                    image = myEnc.image || null;
                } catch (e) { content = '🔒 Encrypted message'; }
                return { ...msg, content, image };
            }
            if (parsed.ciphertext && parsed.iv && parsed.sender_pubkey) {
                const keys = await ensureKeys();
                if (msg.is_mine) {
                    if (parsed.self_ciphertext && parsed.self_iv) {
                        const selfCiphertext = DarkCrypto._base64ToArrayBuffer(parsed.self_ciphertext);
                        const selfIv = DarkCrypto._fromBase64(parsed.self_iv);
                        const selfShared = await DarkCrypto.getSharedSecret(keys.ecdhPrivateKey, keys.compressedPubKey);
                        content = await DarkCrypto.decryptAES(selfShared, selfCiphertext, selfIv);
                        image = parsed.image || null;
                    } else content = '🔒 Encrypted message (no self-copy)';
                } else {
                    const senderPubKeyBytes = DarkCrypto._fromBase64(parsed.sender_pubkey);
                    content = await DarkCrypto.decryptMessage(keys.ecdhPrivateKey, senderPubKeyBytes, parsed.iv, parsed.ciphertext);
                    image = parsed.image || null;
                }
            }
        } catch (e) { console.error('Decryption error', msg.id, e); return { ...msg, content: '🔒 Decrypt error', image: null }; }
        return { ...msg, content, image };
    }

    async function handleWebSocketMessage(data) {
        if (data.error) { console.error('WS error:', data.error); return; }
        if (!data.chatId && data.sender && data.recipient) data.chatId = (data.sender === State.userAddress) ? data.recipient : data.sender;
        if (!data.chatId) return;
        if (document.getElementById('msg-' + data.id)) return;

        const decrypted = await processMessageDecryption(data);
        const chatId = decrypted.chatId;

        if (!decrypted.is_mine) {
            fetch(`/message/${decrypted.id}/delivered`, { method: 'POST' }).catch(e => console.warn);
        }

        let isCurrent = false;
        if (State.currentChatAddress === chatId) isCurrent = true;
        else if (decrypted.isGroup && State.currentChatAddress === chatId) isCurrent = true;
        else if (!decrypted.isGroup && (decrypted.sender === State.currentChatAddress || decrypted.recipient === State.currentChatAddress)) isCurrent = true;

        if (!isCurrent) {
            const existingItem = document.querySelector(`.conversation-item[data-address="${chatId}"]`);
            if (!existingItem) { if (window.loadConversations) window.loadConversations(); }
            else if (window.updateConversationPreview) window.updateConversationPreview(chatId, decrypted.preview || '💬 New message');
        }

        if (isCurrent && window.onNewMessageReceived) {
            window.onNewMessageReceived(decrypted);
        }

        if (window.NotificationManager && document.visibilityState === 'visible') {
            window.NotificationManager.handleIncomingMessage?.({ sender: decrypted.sender, sender_name: decrypted.sender_name, chatId, isGroup: decrypted.isGroup, preview: decrypted.preview, timestamp: decrypted.timestamp * 1000, messageId: decrypted.id });
        }
    }

    // ========== Heartbeat (обновление онлайн-статуса) ==========
    let heartbeatInterval = null;
    function startHeartbeat() {
        if (heartbeatInterval) clearInterval(heartbeatInterval);
        heartbeatInterval = setInterval(async () => {
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
                                if (st === 'read') previewText = '✓✓ Read';
                                else if (st === 'delivered') previewText = '✓✓ Delivered';
                                else previewText = '✓ Sent';
                                window.updateConversationPreview(State.currentChatAddress, previewText);
                            }
                        }
                    }
                }
            } catch(e) { console.warn('Status polling error', e); }
        }, 30000);
    }
    function stopStatusPolling() { if (statusPollingInterval) clearInterval(statusPollingInterval); }

    // Экспорт глобальных функций/переменных для других модулей
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
    window.wsClient = null; // будет установлен при вызове initWebSocket
})();