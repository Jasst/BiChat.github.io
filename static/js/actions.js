// actions.js — все действия, инициируемые пользователем (кнопки, формы)
// + добавлено превью изображения над полем ввода
// + ИСПРАВЛЕНО: переход в AI-чат, очистка превью, корректная работа кнопки "Назад"
(function() {
    if (window._actionsLoaded) return;
    window._actionsLoaded = true;

    // ========== Превью изображения для обычного чата ==========
    let mainPendingImageFile = null;
    let mainImagePreviewUrl = null;

    function showMainImagePreview(file, dataUrl) {
        const oldPreview = document.getElementById('mainImagePreview');
        if (oldPreview) oldPreview.remove();

        const previewContainer = document.createElement('div');
        previewContainer.id = 'mainImagePreview';
        previewContainer.style.cssText = `
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            margin: 8px 16px 0 16px;
            background: var(--bg-secondary);
            border-radius: var(--radius-md);
            border: 1px solid var(--border-color);
        `;

        if (mainImagePreviewUrl && !mainImagePreviewUrl.startsWith('data:')) URL.revokeObjectURL(mainImagePreviewUrl);
        mainImagePreviewUrl = dataUrl;

        previewContainer.innerHTML = `
            <img src="${Utils.escapeHtml(dataUrl)}" style="width: 40px; height: 40px; object-fit: cover; border-radius: 6px;">
            <span style="font-size: 13px; color: var(--text-secondary); flex: 1;">${Utils.escapeHtml(file.name)}</span>
            <button type="button" id="clearMainImage" class="btn btn-icon" style="font-size: 16px; padding: 4px;">✕</button>
        `;

        const form = document.querySelector('.chat-panel .input-area');
        if (form) {
            form.parentNode.insertBefore(previewContainer, form);
        } else {
            const main = document.querySelector('.chat-panel');
            if (main) main.appendChild(previewContainer);
        }

        document.getElementById('clearMainImage')?.addEventListener('click', () => {
            if (mainImagePreviewUrl && !mainImagePreviewUrl.startsWith('data:')) URL.revokeObjectURL(mainImagePreviewUrl);
            mainPendingImageFile = null;
            State.pendingImageData = null;
            previewContainer.remove();
            mainImagePreviewUrl = null;
        });
    }

    // ========== Отправка сообщения ==========
    async function sendMessage() {
        if (State.currentChatAddress === 'ai_bot') {
            console.log('AI chat active, use AI input instead');
            return;
        }
        const contentEl = document.getElementById('messageContent');
        const sendBtn = document.getElementById('sendButton');
        const attachBtn = document.getElementById('attachImageButton');

        if (window.isSending) {
            window.NotificationManager?.showToast('Sending in progress...', 'warning');
            return;
        }
        let content = contentEl ? contentEl.value.trim() : '';
        const recipient = State.currentChatAddress;
        if (!recipient || (!content && !State.pendingImageData)) {
            window.NotificationManager?.showToast('Enter a message or attach an image', 'warning');
            return;
        }

        window.isSending = true;
        if (sendBtn) sendBtn.disabled = true;
        if (attachBtn) attachBtn.disabled = true;
        if (contentEl) contentEl.disabled = true;

        const isGroup = State.currentChatIsGroup;
        const groupId = isGroup && recipient.startsWith('group:') ? recipient.split(':')[1] : null;
        if (contentEl) { contentEl.value = ''; contentEl.style.height = 'auto'; }
        const attachedImage = State.pendingImageData;

        // Очищаем превью и данные
        const previewDiv = document.getElementById('mainImagePreview');
        if (previewDiv) previewDiv.remove();
        if (mainImagePreviewUrl && !mainImagePreviewUrl.startsWith('data:')) URL.revokeObjectURL(mainImagePreviewUrl);
        mainPendingImageFile = null;
        State.pendingImageData = null;
        mainImagePreviewUrl = null;

        const tempId = 'temp-' + Date.now();
        const tempMsg = {
            id: tempId, sender: State.userAddress, recipient: recipient,
            content: content, image: attachedImage, timestamp: Date.now() / 1000,
            is_mine: true, sender_name: 'You', status: 'sent'
        };
        const container = document.getElementById('messagesContainer');
        if (container) {
            const emptyState = container.querySelector('.empty-state');
            if (emptyState) emptyState.remove();
            container.appendChild(window.createMessageElement(tempMsg));
            window.smartScrollToBottom(container, true);
        }

        try {
            const keys = await window.ensureKeys();
            let payload = {};
            if (isGroup && groupId) {
                try {
                    const gRes = await fetch('/get_groups');
                    const gData = await gRes.json();
                    const freshGroup = gData.groups?.find(g => g.id === groupId);
                    if (freshGroup && freshGroup.members?.length) State.currentGroupMembers = freshGroup.members;
                } catch(e) { console.warn(e); }
                const members = State.currentGroupMembers;
                if (!members || members.length === 0) throw new Error('Group members not loaded');
                const encryptedMap = {};
                for (const addr of members) {
                    const pubKeyB64 = await window.getPubKey(addr);
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
                payload = { message_type: 'group', group_id: groupId, encrypted_map: encryptedMap };
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
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (res.ok) {
                const tempElem = document.getElementById('msg-' + tempId);
                if (tempElem) {
                    tempElem.id = 'msg-' + data.tx_id;
                    tempElem.dataset.messageId = data.tx_id;
                    const deleteBtn = tempElem.querySelector('.delete-btn');
                    if (deleteBtn) deleteBtn.dataset.id = data.tx_id;
                    const statusSpan = tempElem.querySelector('.message-status');
                    if (statusSpan) { statusSpan.textContent = '✓'; statusSpan.style.color = '#888'; }
                }
                await window.loadConversations();
                window.updateConversationPreview(recipient, '✓ Sent');
                if (!isGroup) {
                    await window.loadMessagesForConversation(recipient, true);
                }
            } else {
                document.getElementById('msg-' + tempId)?.remove();
                window.NotificationManager?.showToast(data.error || 'Send failed', 'error');
            }
        } catch (error) {
            console.error('Send error:', error);
            document.getElementById('msg-' + tempId)?.remove();
            window.NotificationManager?.showToast(error.message || 'Network error', 'error');
        } finally {
            window.isSending = false;
            if (sendBtn) sendBtn.disabled = false;
            if (attachBtn) attachBtn.disabled = false;
            if (contentEl) { contentEl.disabled = false; contentEl.focus(); }
        }
    }

    // ========== Удаление сообщения ==========
    async function deleteMessage(messageId, buttonEl) {
        const confirmed = await window.showConfirmModal('Delete Message', 'Are you sure you want to delete this message?');
        if (!confirmed) return;
        try {
            if (buttonEl) { buttonEl.disabled = true; buttonEl.textContent = '…'; }
            const res = await fetch('/delete_message', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message_id: messageId })
            });
            const data = await res.json();
            if (res.ok) {
                document.getElementById('msg-' + messageId)?.remove();
                window.NotificationManager?.showToast('Message deleted', 'success');
            } else {
                window.NotificationManager?.showToast(data.error || 'Delete failed', 'error');
                if (buttonEl) { buttonEl.disabled = false; buttonEl.textContent = '🗑'; }
            }
        } catch (error) {
            console.error('Delete error:', error);
            window.NotificationManager?.showToast('Network error', 'error');
        }
    }

    // ========== Очистка переписки ==========
    async function clearConversation() {
        if (!State.currentChatAddress) return;
        const confirmed = await window.showConfirmModal('Clear Conversation', 'Are you sure you want to clear all messages in this conversation?');
        if (!confirmed) return;
        try {
            const res = await fetch('/clear_conversation', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ chat_with: State.currentChatAddress })
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

    // ========== Добавление контакта ==========
    async function addContactFromChat() {
        if (!State.currentChatPartnerAddress || State.currentChatPartnerAddress === State.userAddress) {
            window.NotificationManager?.showToast('Cannot add this conversation', 'warning');
            return;
        }
        const nameEl = document.getElementById('currentChatName');
        const name = nameEl ? nameEl.textContent : (State.currentChatPartnerAddress.slice(0,10)+'…');
        try {
            const res = await fetch('/add_contact_from_chat', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contact_address: State.currentChatPartnerAddress, contact_name: name })
            });
            const data = await res.json();
            if (res.ok) {
                window.NotificationManager?.showToast('Contact added', 'success');
                document.getElementById('addToContactsBtn').disabled = true;
            } else {
                window.NotificationManager?.showToast(data.error || 'Failed to add', 'error');
            }
        } catch (error) {
            console.error('Add contact error:', error);
            window.NotificationManager?.showToast('Network error', 'error');
        }
    }

    // ========== Обработка изображений ==========
    async function handleImageSelection(event) {
        const file = event.target.files[0];
        if (file && file.type?.startsWith('image/')) {
            const reader = new FileReader();
            reader.onload = async (e) => {
                if (e.target?.result) {
                    try {
                        const compressedDataUrl = await window.compressImage(e.target.result);
                        State.pendingImageData = compressedDataUrl;
                        mainPendingImageFile = file;
                        showMainImagePreview(file, compressedDataUrl);
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

    // ========== Модальные окна нового чата ==========
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
                        const name = c.name.length > 30 ? c.name.slice(0,27)+'…' : c.name;
                        option.textContent = Utils.escapeHtml(name) + ' (' + c.address.slice(0,10) + '…)';
                        select.appendChild(option);
                    });
                }
            }
        } catch (error) {
            console.error('Load contacts error:', error);
        }
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
            name = contact ? contact.name : selected.slice(0,10)+'…';
        } else if (entered) {
            const isValid = (typeof Security !== 'undefined') ? Security.isValidAddress(entered) : /^[a-f0-9]{64}$/.test(entered);
            if (!isValid) { window.NotificationManager?.showToast('Invalid address format', 'error'); return; }
            if (entered === State.userAddress) { window.NotificationManager?.showToast('Cannot chat with yourself', 'warning'); return; }
            address = entered;
            name = entered.slice(0,10)+'…';
        } else {
            window.NotificationManager?.showToast('Select a contact or enter address', 'warning');
            return;
        }
        closeNewChatModal();
        window.selectConversation(address, name, false);
    }

    // ========== Инициализация чата ==========
    function initChat() {
        window.loadConversations();

        window.startHeartbeat();
        window.startStatusPolling();
        window.startUserStatusPolling();

        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && window.wsClient && !window.wsClient.isConnected) {
                console.log('📱 Tab active, reconnecting WebSocket...');
                window.wsClient.connect();
            }
        });
        if (window.NotificationManager?.init) window.NotificationManager.init();

        const msgContainer = document.getElementById('messagesContainer');
        if (msgContainer) {
            msgContainer.addEventListener('click', function(e) {
                const btn = e.target.closest('.delete-btn');
                if (btn) { const msgId = parseInt(btn.dataset.id); if (msgId) deleteMessage(msgId, btn); }
            });
        }

        const params = new URLSearchParams(window.location.search);
        const startWith = params.get('start_with');
        const startName = params.get('name');
        if (startWith && startName) {
            setTimeout(() => {
                window.selectConversation(startWith, decodeURIComponent(startName), startWith.startsWith('group:'));
                history.replaceState({}, '', location.pathname);
            }, 100);
        }

        const input = document.getElementById('messageContent');
        if (input) {
            input.addEventListener('input', function() { this.style.height = 'auto'; this.style.height = Math.min(this.scrollHeight, 120) + 'px'; });
            input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
        }

        document.getElementById('newChatBtn')?.addEventListener('click', openNewChatModal);
        document.getElementById('startNewChatBtn')?.addEventListener('click', startNewChat);
        document.getElementById('imageModal')?.addEventListener('click', e => { if (e.target.id === 'imageModal') closeImageModal(); });
        window.addEventListener('click', e => { if (e.target.classList.contains('modal-overlay')) { e.target.classList.add('hidden'); if (window.QRScanner) QRScanner.close(); } });
        document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeNewChatModal(); closeImageModal(); if (window.QRScanner) QRScanner.close(); } });

        // ✅ ИСПРАВЛЕНО: обработчик кнопки AI-чата – теперь он корректно переключает интерфейс
        const aiBtn = document.getElementById('aiChatBtn');
        if (aiBtn) {
            aiBtn.addEventListener('click', (e) => {
                e.preventDefault();
                // Если есть сайдбар на мобильных – закрываем
                if (window.innerWidth <= 768 && typeof closeSidebar === 'function') closeSidebar();
                // Переключаемся на AI-бота
                window.selectConversation('ai_bot', 'AI Assistant', false);
            });
        }
    }

    // Очистка перед выгрузкой страницы
    window.addEventListener('beforeunload', () => {
        if (window.wsClient) { window.wsClient.disconnect(); window.wsClient = null; }
        if (window.QRScanner && typeof QRScanner.close === 'function') QRScanner.close();
        if (State.topObserver) { State.topObserver.disconnect(); State.topObserver = null; }
        if (window.NotificationManager && typeof NotificationManager.destroy === 'function') NotificationManager.destroy();
        window.stopHeartbeat();
        window.stopUserStatusPolling();
        window.stopStatusPolling();
    });

    // Экспорт глобальных функций
    window.sendMessage = sendMessage;
    window.deleteMessage = deleteMessage;
    window.clearConversation = clearConversation;
    window.addContactFromChat = addContactFromChat;
    window.handleImageSelection = handleImageSelection;
    window.openImageModal = openImageModal;
    window.closeImageModal = closeImageModal;
    window.openNewChatModal = openNewChatModal;
    window.closeNewChatModal = closeNewChatModal;
    window.startNewChat = startNewChat;

    window.clearMainImagePreview = function() {
        const previewDiv = document.getElementById('mainImagePreview');
        if (previewDiv) previewDiv.remove();
        if (mainImagePreviewUrl && !mainImagePreviewUrl.startsWith('data:')) URL.revokeObjectURL(mainImagePreviewUrl);
        mainPendingImageFile = null;
        State.pendingImageData = null;
        mainImagePreviewUrl = null;
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initChat);
    else initChat();
})();