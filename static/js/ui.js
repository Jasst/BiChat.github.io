// ui.js — все функции, связанные с DOM и интерфейсом чата
(function() {
    if (window._uiLoaded) return;
    window._uiLoaded = true;

    // ========== Умный скролл и бейдж ==========
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
        badge.style.cssText = 'position:absolute;bottom:90px;right:20px;background:var(--accent);color:var(--text-inverse);border:none;padding:8px 16px;border-radius:20px;font-size:12px;font-weight:600;cursor:pointer;box-shadow:var(--shadow-md);z-index:100;display:flex;align-items:center;gap:6px;';
        badge.onclick = () => {
            const c = document.getElementById('messagesContainer');
            if (c) { c.scrollTo({ top: c.scrollHeight, behavior: 'smooth' }); badge.remove(); }
        };
        const main = document.querySelector('.main-content');
        if (main) { main.style.position = 'relative'; main.appendChild(badge); }
        setTimeout(() => badge?.remove(), 15000);
    }

    // ========== Пагинация (загрузка старых сообщений) ==========
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
                    const decrypted = await window.processMessageDecryption(msg);
                    const div = createMessageElement(decrypted);
                    fragment.appendChild(div);
                }
                container.insertBefore(fragment, container.firstChild);
                State.lastKnownMessageId = Math.min(...data.messages.map(m => m.id));
                setupTopObserver();
            }
        } catch (e) { console.error('Older messages error:', e); }
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

    // ========== Создание элемента сообщения ==========
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
            : '<strong>' + Utils.escapeHtml(msg.sender_name || (msg.sender ? msg.sender.slice(0,10)+'…' : '')) + '</strong><br>';

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
            if (msg.status === 'read') { statusSpan.textContent = '✓✓'; statusSpan.style.color = '#4caf50'; }
            else if (msg.status === 'delivered') { statusSpan.textContent = '✓✓'; statusSpan.style.color = '#888'; }
            else { statusSpan.textContent = '✓'; statusSpan.style.color = '#888'; }
            statusSpan.style.marginLeft = '8px';
            statusSpan.style.fontSize = '12px';
            const metaDiv = messageDiv.querySelector('.meta');
            if (metaDiv) metaDiv.appendChild(statusSpan);
        }
        return messageDiv;
    }

    function updateStatusIcon(msgDiv, status) {
        const icon = msgDiv.querySelector('.message-status');
        if (!icon) return;
        if (status === 'sent') { icon.textContent = '✓'; icon.style.color = '#888'; }
        else if (status === 'delivered') { icon.textContent = '✓✓'; icon.style.color = '#888'; }
        else if (status === 'read') { icon.textContent = '✓✓'; icon.style.color = '#4caf50'; }
    }

    // ========== НОВОЕ: получение статусов для массива адресов ==========
    async function fetchUserStatuses(addresses) {
        if (!addresses.length) return {};
        try {
            const res = await fetch('/get_many_statuses', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ addresses })
            });
            const data = await res.json();
            return data.statuses || {};
        } catch (err) {
            console.warn('Failed to fetch statuses:', err);
            return {};
        }
    }

    // ========== Загрузка списка диалогов ==========
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
            const convElements = [];

            for (const conv of data.conversations) {
                const isGroup = !!conv.is_group;
                const address = conv.address || '';
                const item = document.createElement('div');
                item.className = 'conversation-item';
                item.dataset.address = address;
                item.dataset.isGroup = isGroup ? '1' : '0';
                const displayName = conv.name || address || 'Unknown';
                const shortName = displayName.length > 25 ? displayName.slice(0,22)+'…' : displayName;
                const initials = displayName.slice(0,2).toUpperCase();
                let previewText = Utils.escapeHtml(conv.last_preview || 'No messages');
                item.innerHTML = `<div class="avatar ${isGroup ? 'group' : ''}">${Utils.escapeHtml(initials)}</div>
                    <div class="info">
                        <div class="name truncate">${Utils.escapeHtml(shortName)}</div>
                        <div class="meta"><span class="status"></span><span class="truncate">${previewText}</span></div>
                    </div>`;
                item.onclick = () => selectConversation(address, conv.name || address, isGroup);
                container.appendChild(item);
                convElements.push({ el: item, address, isGroup });
            }

            // НОВОЕ: запрашиваем статусы для всех не-групповых диалогов (кроме себя)
            const addressesToCheck = convElements
                .filter(c => !c.isGroup && c.address !== State.userAddress)
                .map(c => c.address);
            if (addressesToCheck.length) {
                const statuses = await fetchUserStatuses(addressesToCheck);
                for (const { el, address } of convElements) {
                    if (addressesToCheck.includes(address)) {
                        const status = statuses[address]?.status || 'offline';
                        const statusSpan = el.querySelector('.status');
                        if (statusSpan) {
                            statusSpan.className = `status ${status}`;
                            statusSpan.title = status === 'online' ? 'Online' : 'Offline';
                        }
                    }
                }
            }
        } catch (error) { console.error('Load conversations error:', error); container.innerHTML = '<p class="text-muted text-center">Failed to load</p>'; }
    }

    // ========== Выбор диалога и загрузка сообщений ==========
    async function selectConversation(address, name, isGroup) {
        if (State.topObserver) { State.topObserver.disconnect(); State.topObserver = null; }
        if (window.isSending) window.isSending = false;
        State.currentChatAddress = address;
        State.currentChatIsGroup = !!isGroup;
        State.currentChatPartnerAddress = isGroup ? '' : (address === State.userAddress ? '' : address);

        fetch('/heartbeat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ current_chat: address }) }).catch(e=>{});

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
            document.getElementById('currentChatName').textContent = '🤖 AI Assistant';
            document.getElementById('chatSubtitle').textContent = 'Streaming response';
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
                State.currentGroupMembers = group ? group.members : [];
            } catch(e) { State.currentGroupMembers = []; }
        } else State.currentGroupMembers = null;

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
        if (window.stopStatusPolling) window.stopStatusPolling();
        if (window.startStatusPolling) window.startStatusPolling();
        await loadMessagesForConversation(address, false);
        if (window.innerWidth <= 768 && typeof closeSidebar === 'function') closeSidebar();
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
        const isPersonal = typeof Security !== 'undefined' ? Security.isValidAddress(chatWithAddress) : /^[a-f0-9]{64}$/.test(chatWithAddress);
        if (!isGroup && !isPersonal) {
            container.innerHTML = '<p class="text-muted text-center">Invalid conversation</p>';
            container.classList.remove('loading');
            _enableChatControls();
            return;
        }
        if (!isNewMessage) { container.innerHTML = '<div class="loading">Loading messages…</div>'; container.classList.add('loading'); }
        try {
            const params = new URLSearchParams({ with: chatWithAddress });
            if (isNewMessage && State.lastKnownMessageId > 0) params.append('last_message_id', State.lastKnownMessageId);
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
                try { messages.push(await window.processMessageDecryption(msg)); }
                catch(e) { messages.push({ ...msg, content: '🔒 Decrypt error', image: null }); }
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
                if (document.getElementById('msg-'+msg.id)) return;
                if (msg.timestamp > maxTimestamp) maxTimestamp = msg.timestamp;
                fragment.appendChild(createMessageElement(msg));
                if (msg.id > State.lastKnownMessageId) State.lastKnownMessageId = msg.id;
                if (!msg.is_mine && isNewMessage) {
                    window.NotificationManager?.handleIncomingMessage?.({ sender: msg.sender, chatId: chatWithAddress, content: msg.content, image: msg.image, timestamp: (msg.timestamp||Date.now()/1000)*1000 });
                }
            });
            container.appendChild(fragment);
            State.lastMessageTimestamp = maxTimestamp;
            if (messages.length) markConversationAsRead(chatWithAddress, messages[messages.length-1].id);
            if (!isNewMessage) { container.scrollTop = container.scrollHeight; }
            else {
                const wasNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
                if (wasNearBottom) container.scrollTop = container.scrollHeight;
                else showNewMessagesBadge();
            }
            _enableChatControls();
            if (!isNewMessage) setupTopObserver();
        } catch (error) {
            console.error('Load messages error:', error);
            container.classList.remove('loading');
            if (!isNewMessage) container.innerHTML = '<p class="text-muted text-center">Failed to load messages</p>';
            _enableChatControls();
        }
    }

    function markConversationAsRead(chatId, explicitLastMessageId) {
        const item = document.querySelector(`.conversation-item[data-address="${chatId}"]`);
        if (item) {
            const meta = item.querySelector('.meta .truncate');
            if (meta) { meta.textContent = '✓ Read'; meta.style.fontStyle = 'italic'; }
        }
        let lastMessageId = explicitLastMessageId;
        if (lastMessageId === undefined) {
            const lastMsg = document.querySelector('#messagesContainer .message:last-of-type');
            lastMessageId = lastMsg ? parseInt(lastMsg.dataset.messageId) : 0;
        }
        fetch('/mark_conversation_read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ chat_with: chatId, last_message_id: lastMessageId }) }).catch(e=>console.debug);
    }

    function updateConversationPreview(chatId, newPreview) {
        const items = document.querySelectorAll('.conversation-item');
        for (const item of items) {
            if (item.dataset.address === chatId) {
                const meta = item.querySelector('.meta .truncate');
                if (meta) meta.textContent = newPreview;
                break;
            }
        }
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
                btn.disabled = true; btn.title = "Cannot add group or yourself";
            } else { btn.disabled = false; btn.title = "Add to contacts"; }
        }
    }

    // Callback для нового сообщения из WebSocket
    window.onNewMessageReceived = function(decrypted) {
        const container = document.getElementById('messagesContainer');
        if (container) {
            const wasAtBottom = isUserAtBottom(container, 30);
            const msgElement = createMessageElement(decrypted);
            container.appendChild(msgElement);
            if (wasAtBottom) { setTimeout(() => { container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' }); }, 50); }
            else { showNewMessagesBadge(); }
            if (!decrypted.is_mine) { fetch(`/message/${decrypted.id}/read`, { method: 'POST' }).catch(e=>console.warn); }
        }
    };

    // НОВОЕ: обновить статус конкретного диалога по WebSocket
    window.updateConversationStatus = function(address, status) {
        const item = document.querySelector(`.conversation-item[data-address="${address}"]`);
        if (item && !item.dataset.isGroup) {
            const statusSpan = item.querySelector('.status');
            if (statusSpan) {
                statusSpan.className = `status ${status}`;
                statusSpan.title = status === 'online' ? 'Online' : 'Offline';
            }
        }
    };

    // Экспорт для других модулей и глобального доступа
    window.loadConversations = loadConversations;
    window.selectConversation = selectConversation;
    window.loadMessagesForConversation = loadMessagesForConversation;
    window.createMessageElement = createMessageElement;
    window.updateStatusIcon = updateStatusIcon;
    window.updateConversationPreview = updateConversationPreview;
    window.markConversationAsRead = markConversationAsRead;
    window.smartScrollToBottom = smartScrollToBottom;
    window.setupTopObserver = setupTopObserver;
    window._enableChatControls = _enableChatControls;
    window._disableChatControls = _disableChatControls;
    window.fetchUserStatuses = fetchUserStatuses; // НОВОЕ
})();