// actions.js — полная версия с поддержкой зашифрованных файлов, аудиозаписи,
// добавленными обработчиками AI, очистки чата, удаления сообщений и добавления контактов
// + авто-расширение textarea и фикс позиционирования #filePreview
// + динамическое переключение кнопок «отправить» / «запись голоса»
(function() {
    if (window._actionsLoaded) return;
    window._actionsLoaded = true;

    // ========== Глобальные переменные ==========
    let pendingFile = null;          // { file, type }
    let mediaRecorder = null;
    let audioChunks = [];
    let isRecording = false;

    // ========== Автоматическое расширение textarea ==========
    function autoResizeTextarea(textarea) {
        if (!textarea) return;
        textarea.style.height = 'auto';
        const newHeight = Math.min(textarea.scrollHeight, 150);
        textarea.style.height = newHeight + 'px';
    }

    // ========== Вспомогательные функции ==========
    async function uploadEncryptedFile(file) {
        const { key, iv } = DarkCrypto.generateFileKeyAndIv();
        const fileData = await file.arrayBuffer();
        const encrypted = await DarkCrypto.encryptFile(new Uint8Array(fileData), key, iv);
        const blob = new Blob([encrypted], { type: 'application/octet-stream' });
        const formData = new FormData();
        formData.append('file', blob, 'encrypted.bin');
        const res = await fetch('/upload_encrypted', { method: 'POST', body: formData });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        return {
            url: data.file_url,
            key: DarkCrypto.arrayBufferToBase64(key),
            iv: DarkCrypto.arrayBufferToBase64(iv)
        };
    }

    function showFilePreview(file, type) {
        const oldPreview = document.getElementById('filePreview');
        if (oldPreview) oldPreview.remove();

        const previewContainer = document.createElement('div');
        previewContainer.id = 'filePreview';
        previewContainer.style.cssText = `
            display: flex; align-items: center; gap: 8px; padding: 8px 12px;
            margin: 0 16px 8px 16px; background: rgba(30,30,30,0.95);
            border-radius: 20px; border: 1px solid rgba(255,255,255,0.1);
        `;

        let previewContent;
        let objectUrl = null;

        if (type.startsWith('image/')) {
            objectUrl = URL.createObjectURL(file);
            previewContent = `<img src="${objectUrl}" style="width: 32px; height: 32px; object-fit: cover; border-radius: 4px;">`;
        } else {
            previewContent = `<span>${type.startsWith('image') ? '🖼️' : '🎵'}</span>`;
        }

        previewContainer.innerHTML = `
            ${previewContent}
            <span style="flex:1; font-size:13px;">${Utils.escapeHtml(file.name)} (${(file.size/1024).toFixed(1)} KB)</span>
            <button id="cancelFileBtn" class="btn-icon-oval">✕</button>
        `;

        const form = document.querySelector('.chat-panel .input-area');
        if (form) {
            form.insertBefore(previewContainer, form.firstChild);
        }

        document.getElementById('cancelFileBtn')?.addEventListener('click', () => {
            if (objectUrl) URL.revokeObjectURL(objectUrl);
            pendingFile = null;
            previewContainer.remove();
            updateSendButtonVisibility();
        });
    }

    // ========== Запись аудио ==========
    async function startRecording() {
        if (isRecording) return;
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
            audioChunks = [];
            mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                if (audioBlob.size > 2 * 1024 * 1024) {
                    window.NotificationManager?.showToast('Audio too long (max 2 MB)', 'error');
                    stream.getTracks().forEach(t => t.stop());
                    isRecording = false;
                    return;
                }
                const file = new File([audioBlob], 'voice.webm', { type: 'audio/webm' });
                pendingFile = { file, type: 'audio/webm' };
                showFilePreview(file, 'audio/webm');
                updateSendButtonVisibility();
                stream.getTracks().forEach(t => t.stop());
                isRecording = false;
                document.getElementById('recordIndicator')?.remove();
            };
            mediaRecorder.start();
            isRecording = true;
            const indicator = document.createElement('div');
            indicator.id = 'recordIndicator';
            indicator.textContent = '🔴 Recording... Click again to stop';
            indicator.style.cssText = 'position:fixed; bottom:80px; left:50%; transform:translateX(-50%); background:#f44336; color:#fff; padding:8px 16px; border-radius:20px; z-index:1000; cursor:pointer;';
            indicator.onclick = () => { if (mediaRecorder?.state === 'recording') mediaRecorder.stop(); };
            document.body.appendChild(indicator);
        } catch (err) {
            window.NotificationManager?.showToast('Microphone access denied', 'error');
        }
    }

    // ========== Выбор файла ==========
    function handleFileSelection(event, type) {
        const file = event.target.files[0];
        if (!file) return;
        const maxSize = type === 'image' ? 5 * 1024 * 1024 : 2 * 1024 * 1024;
        if (file.size > maxSize) {
            window.NotificationManager?.showToast(`File too large (max ${maxSize/1024/1024} MB)`, 'error');
            return;
        }
        const allowedTypes = type === 'image' ? ['image/jpeg','image/png','image/gif','image/webp'] : ['audio/webm','audio/mp4','audio/ogg'];
        if (!allowedTypes.includes(file.type)) {
            window.NotificationManager?.showToast(`Unsupported ${type} type`, 'error');
            return;
        }
        pendingFile = { file, type: file.type };
        showFilePreview(file, file.type);
        updateSendButtonVisibility();
        event.target.value = '';
    }

    // ========== Функция управления видимостью кнопок ==========
    function updateSendButtonVisibility() {
        const sendBtn = document.getElementById('sendButton');
        const recordBtn = document.getElementById('recordAudioButton');
        if (!sendBtn || !recordBtn) return;

        const messageInput = document.getElementById('messageContent');
        const hasText = messageInput && messageInput.value.trim() !== '';
        const hasFile = pendingFile !== null;

        if (hasText || hasFile) {
            sendBtn.style.display = 'flex';
            recordBtn.style.display = 'none';
        } else {
            sendBtn.style.display = 'none';
            recordBtn.style.display = 'flex';
        }
    }

    // ========== Отправка сообщения ==========
    async function sendMessage() {
    if (State.currentChatAddress === 'ai_bot') return;
    if (window.isSending) return;
    const contentEl = document.getElementById('messageContent');
    let content = contentEl ? contentEl.value.trim() : '';
    if (!content && !pendingFile) {
        window.NotificationManager?.showToast('Enter message or attach file', 'warning');
        return;
    }

    window.isSending = true;
    const recipient = State.currentChatAddress;
    const isGroup = State.currentChatIsGroup;
    const groupId = isGroup && recipient.startsWith('group:') ? recipient.split(':')[1] : null;

    if (contentEl) { contentEl.value = ''; contentEl.style.height = 'auto'; }
    const fileToSend = pendingFile;
    pendingFile = null;
    document.getElementById('filePreview')?.remove();

    const tempId = 'temp-' + Date.now();
    const tempMsg = { id: tempId, sender: State.userAddress, recipient, content, timestamp: Date.now()/1000, is_mine: true, status: 'sent' };
    const container = document.getElementById('messagesContainer');
    if (container) {
        const emptyState = container.querySelector('.empty-state');
        if (emptyState) emptyState.remove();
        container.appendChild(window.createMessageElement(tempMsg));

        // ✅ Прокрутка к последнему сообщению (временному)
        const lastMsg = container.querySelector('.message:last-child');
        if (lastMsg) {
            lastMsg.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
    }

    try {
        const keys = await window.ensureKeys();
        let fileAttachment = null;
        if (fileToSend) {
            const { url, key, iv } = await uploadEncryptedFile(fileToSend.file);
            fileAttachment = { url, key, iv, type: fileToSend.type };
        }

        let payload = {};
        if (isGroup && groupId) {
            const gRes = await fetch('/get_groups');
            const gData = await gRes.json();
            const freshGroup = gData.groups?.find(g => g.id === groupId);
            const members = freshGroup?.members || [];
            if (!members.length) throw new Error('Group members not loaded');
            const encryptedMap = {};
            for (const addr of members) {
                const pubKeyB64 = await window.getPubKey(addr);
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
                if (addr === State.userAddress) {
                    encryptedMap[addr].self_text = content ? { ciphertext: encryptedText.ciphertext, iv: encryptedText.iv } : null;
                    if (fileAttachment) {
                        encryptedMap[addr].self_file_key = fileAttachment.key;
                        encryptedMap[addr].self_file_iv = fileAttachment.iv;
                    }
                }
            }
            payload = { message_type: 'group', group_id: groupId, encrypted_map: encryptedMap };
        } else {
            const pubRes = await fetch(`/get_public_key/${recipient}`);
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

        const res = await fetch('/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
            const tempElem = document.getElementById('msg-' + tempId);
            if (tempElem) tempElem.remove();
            const sentMessage = {
                id: data.tx_id,
                sender: State.userAddress,
                recipient: isGroup ? recipient : recipient,
                content: content,
                timestamp: Date.now() / 1000,
                is_mine: true,
                status: 'sent',
                isDecrypted: true
            };
            window.addMessageToCache(recipient, sentMessage, 'end');
            await window.loadConversations();
            window.updateConversationPreview(recipient, '✓ Sent');
            await window.loadMessagesForConversation(recipient, true, true); // forceScroll = true
        } else {
            document.getElementById('msg-' + tempId)?.remove();
            window.NotificationManager?.showToast(data.error || 'Send failed', 'error');
        }
    } catch (err) {
        console.error(err);
        document.getElementById('msg-' + tempId)?.remove();
        window.NotificationManager?.showToast(err.message, 'error');
    } finally {
        window.isSending = false;
        const sendBtn = document.getElementById('sendButton');
        if (sendBtn) sendBtn.disabled = false;
        document.getElementById('messageContent')?.focus();
        updateSendButtonVisibility();
    }
}

    // ========== Модальные окна нового чата (без изменений) ==========
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
            const isValid = typeof Security !== 'undefined' ? Security.isValidAddress(entered) : /^[a-f0-9]{64}$/.test(entered);
            if (!isValid) {
                window.NotificationManager?.showToast('Invalid address format', 'error');
                return;
            }
            if (entered === State.userAddress) {
                window.NotificationManager?.showToast('Cannot chat with yourself', 'warning');
                return;
            }
            address = entered;
            name = entered.slice(0,10)+'…';
        } else {
            window.NotificationManager?.showToast('Select a contact or enter address', 'warning');
            return;
        }
        closeNewChatModal();
        window.selectConversation(address, name, false);
    }

    // ========== Инициализация кнопок и авто-расширения ==========
    function initChatActions() {
        const msgInput = document.getElementById('messageContent');
        const aiInput = document.getElementById('aiMessageInput');
        if (msgInput) {
            msgInput.addEventListener('input', () => {
                autoResizeTextarea(msgInput);
                updateSendButtonVisibility();
            });
            msgInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
        }
        if (aiInput) {
            aiInput.addEventListener('input', () => autoResizeTextarea(aiInput));
        }

        const startChatBtn = document.getElementById('startNewChatBtn');
        if (startChatBtn) startChatBtn.onclick = startNewChat;

        const aiChatBtn = document.getElementById('aiChatBtn');
        if (aiChatBtn) {
            aiChatBtn.onclick = () => {
                window.selectConversation('ai_bot', 'AI Assistant', false);
            };
        }

        const clearConvBtn = document.getElementById('clearConversationBtn');
        if (clearConvBtn) {
            clearConvBtn.onclick = async () => {
                if (!State.currentChatAddress) return;
                const confirmed = await window.showConfirmModal('Clear chat', 'Are you sure you want to delete all messages in this conversation? This cannot be undone.');
                if (confirmed) {
                    const res = await fetch('/clear_conversation', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ chat_with: State.currentChatAddress })
                    });
                    if (res.ok) {
                        window.loadMessagesForConversation(State.currentChatAddress, false);
                        window.NotificationManager?.showToast('Chat cleared', 'success');
                        const msgField = document.getElementById('messageContent');
                        if (msgField) msgField.value = '';
                        pendingFile = null;
                        document.getElementById('filePreview')?.remove();
                        updateSendButtonVisibility();
                    } else {
                        window.NotificationManager?.showToast('Failed to clear', 'error');
                    }
                }
            };
        }

        const addContactBtn = document.getElementById('addToContactsBtn');
        if (addContactBtn) {
          addContactBtn.onclick = async () => {
             const address = State.currentChatPartnerAddress;
             if (!address) return;

              // 1. Проверяем, не добавлен ли уже этот контакт
             try {
                 const res = await fetch('/get_contacts');
                 const data = await res.json();
                 if (res.ok && data.contacts) {
                   const alreadyExists = data.contacts.some(c => c.address === address);
                   if (alreadyExists) {
                     window.NotificationManager?.showToast('This contact is already in your list', 'warning');
                     return;
                   }
                 }
             } catch (err) {
               console.warn('Failed to check contacts', err);
             }

             const name = await window.showPromptModal(
               'Add Contact',
               'Enter name for this contact:',
               address.slice(0, 10) + '...'
             );
             if (!name) return;

             const res = await fetch('/add_contact_from_chat', {
               method: 'POST',
               headers: { 'Content-Type': 'application/json' },
               body: JSON.stringify({ contact_address: address, contact_name: name })
             });
             if (res.ok) {
                window.NotificationManager?.showToast('Contact added', 'success');
                addContactBtn.disabled = true;
             // Обновляем локальный список контактов, чтобы повторная проверка работала
                const refreshRes = await fetch('/get_contacts');
                const refreshData = await refreshRes.json();
                if (refreshRes.ok) State.allContacts = refreshData.contacts;
             } else {
                const err = await res.json();
                window.NotificationManager?.showToast(err.error || 'Failed', 'error');
             }
          };
        }

        const attachImageBtn = document.getElementById('attachImageButton');
        const imageInput = document.getElementById('imageInput');
        if (attachImageBtn && imageInput) {
            attachImageBtn.onclick = () => imageInput.click();
            imageInput.onchange = (e) => handleFileSelection(e, 'image');
        }
        const audioBtn = document.getElementById('attachAudioButton');
        const audioInput = document.getElementById('audioInput');
        if (audioBtn && audioInput) {
            audioBtn.onclick = () => audioInput.click();
            audioInput.onchange = (e) => handleFileSelection(e, 'audio');
        }
        const recordBtn = document.getElementById('recordAudioButton');
        if (recordBtn) recordBtn.onclick = startRecording;

        const sendBtn = document.getElementById('sendButton');
        if (sendBtn) sendBtn.onclick = sendMessage;

        const newChatBtn = document.getElementById('newChatBtn');
        if (newChatBtn) newChatBtn.onclick = openNewChatModal;

        updateSendButtonVisibility();
    }

    document.addEventListener('click', async (e) => {
        const deleteBtn = e.target.closest('.delete-btn');
        if (deleteBtn && deleteBtn.dataset.id) {
            e.preventDefault();
            const msgId = deleteBtn.dataset.id;
            const confirmed = await window.showConfirmModal('Delete message', 'Delete this message?');
            if (confirmed) {
                const res = await fetch('/delete_message', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message_id: parseInt(msgId) })
                });
                if (res.ok) {
                    const msgDiv = document.getElementById('msg-' + msgId);
                    if (msgDiv) msgDiv.remove();
                    window.loadConversations();
                } else {
                    window.NotificationManager?.showToast('Delete failed', 'error');
                }
            }
        }
    });

    document.addEventListener('DOMContentLoaded', initChatActions);
    window.sendMessage = sendMessage;
    window.handleFileSelection = handleFileSelection;
    window.openNewChatModal = openNewChatModal;
    window.closeNewChatModal = closeNewChatModal;
    window.startNewChat = startNewChat;
    window.autoResizeTextarea = autoResizeTextarea;
    window.updateSendButtonVisibility = updateSendButtonVisibility;
})();