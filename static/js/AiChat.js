// AiChat.js — полностью изолированный AI-чат (работает только со своим контейнером)
(function() {
    if (window._aiChatLoaded) return;
    window._aiChatLoaded = true;

    let aiChatActive = false;
    let pendingImageFile = null;
    let currentStreamingMessage = null;
    let currentStreamingText = '';
    let currentStreamReader = null;
    let isSending = false;
    let currentImagePreviewUrl = null;

    // DOM-элементы AI-чата
    let aiMessagesContainer = null;
    let aiMessageInput = null;
    let aiSendBtn = null;
    let aiAttachBtn = null;
    let aiImageInput = null;
    let aiClearHistoryBtn = null;
    let closeAiChatBtn = null;

    const CONFIG = {
        historyMaxLength: 200,
        imageMaxWidth: 800,
        imageQuality: 0.7,
        apiEndpoint: '/ai/chat'
    };

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m]))
                  .replace(/['"]/g, m => ({ "'": '&#39;', '"': '&quot;' }[m]));
    }

    function getStoredHistory() {
        try {
            return JSON.parse(localStorage.getItem('ai_chat_history') || '[]');
        } catch (e) {
            return [];
        }
    }
    function setStoredHistory(history) {
        try {
            localStorage.setItem('ai_chat_history', JSON.stringify(history));
        } catch (e) {}
    }
    function saveAiMessage(role, text, timestamp = Date.now()) {
        let history = getStoredHistory();
        history.push({ role, text, timestamp });
        if (history.length > CONFIG.historyMaxLength) history = history.slice(-CONFIG.historyMaxLength);
        setStoredHistory(history);
    }
    function loadAiHistory() {
        if (!aiMessagesContainer) return;
        const history = getStoredHistory();
        aiMessagesContainer.innerHTML = '';
        history.forEach(msg => {
            displayAiMessage(msg.text, msg.role === 'user', null, false);
        });
        if (history.length === 0) {
            displayAiMessage('Привет! Я AI-ассистент. Задавайте вопросы и прикрепляйте изображения.', false, null, false);
        }
    }

    function clearAiHistory() {
        const modalId = 'confirmClearAiModal';
        let modal = document.getElementById(modalId);
        if (!modal && window.ModalManager) {
            modal = document.createElement('div');
            modal.id = modalId;
            modal.className = 'modal-overlay hidden';
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-modal', 'true');
            modal.innerHTML = `
                <div class="modal" style="max-width: 400px;">
                    <header class="modal-header">
                        <h3>Очистить историю?</h3>
                        <button class="modal-close" onclick="ModalManager.close('${modalId}')">&times;</button>
                    </header>
                    <div class="modal-body">
                        <p>Вы уверены, что хотите очистить всю историю диалога с AI-ботом?</p>
                    </div>
                    <footer class="modal-footer">
                        <button class="btn btn-ghost" onclick="ModalManager.close('${modalId}')">Отмена</button>
                        <button class="btn btn-primary" id="confirmClearAiBtn">Очистить</button>
                    </footer>
                </div>
            `;
            document.body.appendChild(modal);
        }

        if (window.ModalManager) {
            // Устанавливаем обработчик на кнопку подтверждения (убираем старый, чтобы не дублировать)
            const confirmBtn = modal.querySelector('#confirmClearAiBtn');
            const oldHandler = confirmBtn.onclick;
            confirmBtn.onclick = () => {
                if (oldHandler) oldHandler();
                localStorage.removeItem('ai_chat_history');
                if (aiMessagesContainer) {
                    aiMessagesContainer.innerHTML = '';
                    displayAiMessage('История очищена. Начните новый диалог.', false, null, false);
                }
                ModalManager.close(modalId);
                showToast('История очищена', 'success');
            };
            ModalManager.open(modalId);
        } else {
            // fallback
            if (confirm('Очистить всю историю диалога с AI-ботом?')) {
                localStorage.removeItem('ai_chat_history');
                if (aiMessagesContainer) {
                    aiMessagesContainer.innerHTML = '';
                    displayAiMessage('История очищена. Начните новый диалог.', false, null, false);
                }
            }
        }
    }

    async function compressImage(dataUrl, maxWidth = CONFIG.imageMaxWidth, quality = CONFIG.imageQuality) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                let width = img.width, height = img.height;
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

    function showToast(message, type = 'info') {
        if (window.NotificationManager && window.NotificationManager.showToast) {
            window.NotificationManager.showToast(message, type);
        } else {
            alert(message);
        }
    }

    function displayAiMessage(text, isUser, imagePreview = null, saveToStorage = true) {
        if (!aiMessagesContainer) return;
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${isUser ? 'sent' : 'received'} animate-fade`;
        const avatar = isUser ? '👤' : '🤖';
        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const content = escapeHtml(text);
        let imageHtml = '';
        if (imagePreview) {
            imageHtml = `<img src="${escapeHtml(imagePreview)}" alt="Attached" style="max-width:200px;max-height:150px;border-radius:8px;margin-bottom:8px;cursor:pointer;" onclick="window.openImageModal && window.openImageModal('${escapeHtml(imagePreview)}')">`;
        }
        msgDiv.innerHTML = `
            <div class="avatar">${avatar}</div>
            <div class="content">
                ${imageHtml}
                <p>${content}</p>
                <div class="meta"><span>${time}</span></div>
            </div>
        `;
        aiMessagesContainer.appendChild(msgDiv);
        aiMessagesContainer.scrollTop = aiMessagesContainer.scrollHeight;
        if (saveToStorage && text && !(isUser === false && text.includes('Привет! Я AI-ассистент'))) {
            saveAiMessage(isUser ? 'user' : 'assistant', text);
        }
        return msgDiv;
    }

    function showAiTypingIndicator(show) {
        if (!aiMessagesContainer) return;
        let indicator = aiMessagesContainer.querySelector('.typing-indicator-message');
        if (show) {
            if (indicator) indicator.remove();
            indicator = document.createElement('div');
            indicator.className = 'message received typing-indicator-message';
            indicator.innerHTML = `
                <div class="avatar">🤖</div>
                <div class="typing-indicator">
                    <span></span><span></span><span></span>
                </div>
            `;
            aiMessagesContainer.appendChild(indicator);
            aiMessagesContainer.scrollTop = aiMessagesContainer.scrollHeight;
        } else {
            if (indicator) indicator.remove();
        }
    }

    async function sendToAi(messageText, imageFile) {
        if (isSending) {
            showToast('Подождите, предыдущий запрос ещё обрабатывается', 'warning');
            return;
        }
        if (!messageText.trim() && !imageFile) {
            showToast('Введите сообщение или выберите изображение', 'warning');
            return;
        }
        if (currentStreamReader) {
            try { currentStreamReader.cancel(); } catch(e) {}
            currentStreamReader = null;
        }
        if (currentStreamingMessage && currentStreamingMessage.parentNode) {
            const errP = currentStreamingMessage.querySelector('.content p');
            if (errP && !currentStreamingText) errP.textContent = '⚠️ Ответ прерван.';
        }
        currentStreamingMessage = null;
        currentStreamingText = '';
        isSending = true;

        let previewUrl = null;
        if (imageFile) {
            previewUrl = URL.createObjectURL(imageFile);
            displayAiMessage(messageText || '📷 Изображение', true, previewUrl, true);
        } else {
            displayAiMessage(messageText, true, null, true);
        }
        showAiTypingIndicator(true);

        try {
            let imageBase64 = null, imageMime = null;
            if (imageFile) {
                const reader = new FileReader();
                const compressedDataUrl = await new Promise((resolve) => {
                    reader.onload = async (e) => {
                        const compressed = await compressImage(e.target.result);
                        resolve(compressed);
                    };
                    reader.readAsDataURL(imageFile);
                });
                const parts = compressedDataUrl.split(',');
                imageBase64 = parts[1];
                const mimeMatch = parts[0].match(/^data:(image\/[a-zA-Z]+);?/);
                imageMime = mimeMatch ? mimeMatch[1] : 'image/jpeg';
            }

            const response = await fetch(CONFIG.apiEndpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: messageText,
                    image_base64: imageBase64,
                    image_mime: imageMime,
                    stream: true
                })
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || `HTTP ${response.status}`);
            }

            currentStreamingMessage = displayAiMessage('', false, null, false);
            currentStreamingText = '';
            const contentParagraph = currentStreamingMessage.querySelector('.content p');
            let firstTokenReceived = false;
            let streamFinished = false;
            const reader = response.body.getReader();
            currentStreamReader = reader;
            const decoder = new TextDecoder();
            let buffer = '';

            while (!streamFinished) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const dataStr = line.slice(6).trim();
                        if (dataStr === '[DONE]') {
                            streamFinished = true;
                            break;
                        }
                        try {
                            const data = JSON.parse(dataStr);
                            if (data.token) {
                                if (!firstTokenReceived) {
                                    showAiTypingIndicator(false);
                                    firstTokenReceived = true;
                                }
                                currentStreamingText += data.token;
                                contentParagraph.textContent = currentStreamingText;
                                if (aiMessagesContainer) aiMessagesContainer.scrollTop = aiMessagesContainer.scrollHeight;
                            } else if (data.error) {
                                contentParagraph.textContent = '❌ ' + data.error;
                                firstTokenReceived = true;
                                streamFinished = true;
                                break;
                            }
                        } catch(e) {}
                    }
                }
            }

            if (!firstTokenReceived) {
                showAiTypingIndicator(false);
                if (contentParagraph) contentParagraph.textContent = '🤖 Нет ответа от модели.';
            } else if (currentStreamingText) {
                saveAiMessage('assistant', currentStreamingText);
            }
        } catch (err) {
            console.error('AI error:', err);
            showAiTypingIndicator(false);
            if (currentStreamingMessage && currentStreamingMessage.parentNode) {
                const errP = currentStreamingMessage.querySelector('.content p');
                if (errP) errP.textContent = '❌ Ошибка связи с AI-сервером. Проверьте, запущен ли LM Studio.';
            } else {
                displayAiMessage('❌ Ошибка связи с AI-сервером. Проверьте, запущен ли LM Studio.', false, null, true);
            }
        } finally {
            if (previewUrl) URL.revokeObjectURL(previewUrl);
            if (currentStreamReader) {
                try { currentStreamReader.releaseLock(); } catch(e) {}
                currentStreamReader = null;
            }
            currentStreamingMessage = null;
            currentStreamingText = '';
            isSending = false;
        }
    }

    function setupAiUI() {
        if (!aiSendBtn) return;
        aiSendBtn.onclick = () => {
            const text = aiMessageInput ? aiMessageInput.value.trim() : '';
            const image = pendingImageFile;
            if (!text && !image) {
                showToast('Введите сообщение или прикрепите изображение', 'warning');
                return;
            }
            if (aiMessageInput) aiMessageInput.value = '';
            if (pendingImageFile) {
                const previewContainer = document.getElementById('aiImagePreview');
                if (previewContainer) previewContainer.remove();
                if (currentImagePreviewUrl) URL.revokeObjectURL(currentImagePreviewUrl);
                pendingImageFile = null;
                currentImagePreviewUrl = null;
            }
            sendToAi(text, image);
        };
        if (aiMessageInput) {
            aiMessageInput.onkeydown = (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    aiSendBtn?.click();
                }
            };
        }
        if (aiAttachBtn && aiImageInput) {
            aiAttachBtn.onclick = () => aiImageInput.click();
            aiImageInput.onchange = async (e) => {
                const file = e.target.files[0];
                if (file && file.type.startsWith('image/')) {
                    pendingImageFile = file;
                    let previewContainer = document.getElementById('aiImagePreview');
                    if (!previewContainer) {
                        previewContainer = document.createElement('div');
                        previewContainer.id = 'aiImagePreview';
                        previewContainer.style.cssText = 'margin-top:8px;display:flex;align-items:center;gap:8px;';
                        const inputActions = aiAttachBtn.closest('.input-actions');
                        if (inputActions) inputActions.parentNode.insertBefore(previewContainer, inputActions.nextSibling);
                    }
                    const blobUrl = URL.createObjectURL(file);
                    if (currentImagePreviewUrl) URL.revokeObjectURL(currentImagePreviewUrl);
                    currentImagePreviewUrl = blobUrl;
                    previewContainer.innerHTML = `
                        <img src="${blobUrl}" style="max-width:60px;max-height:60px;border-radius:8px;">
                        <button type="button" id="clearAiImage" class="btn btn-icon" style="font-size:14px;">✕</button>
                    `;
                    document.getElementById('clearAiImage')?.addEventListener('click', () => {
                        if (currentImagePreviewUrl) URL.revokeObjectURL(currentImagePreviewUrl);
                        pendingImageFile = null;
                        if (previewContainer) previewContainer.remove();
                        currentImagePreviewUrl = null;
                    });
                } else {
                    showToast('Пожалуйста, выберите изображение', 'warning');
                }
                aiImageInput.value = '';
            };
        }
        if (aiClearHistoryBtn) aiClearHistoryBtn.onclick = clearAiHistory;
        if (closeAiChatBtn) {
            closeAiChatBtn.onclick = () => {
                if (window.selectConversation && window.State && window.State.currentChatAddress === 'ai_bot') {
                    const firstConv = document.querySelector('.conversation-item');
                    if (firstConv && firstConv.dataset.address) {
                        window.selectConversation(firstConv.dataset.address, '', firstConv.dataset.isGroup === '1');
                    } else {
                        window.selectConversation('', '', false);
                    }
                }
            };
        }
    }

    function initAiChat() {
        if (aiChatActive) return;
        aiChatActive = true;
        aiMessagesContainer = document.getElementById('aiMessagesContainer');
        aiMessageInput = document.getElementById('aiMessageInput');
        aiSendBtn = document.getElementById('aiSendBtn');
        aiAttachBtn = document.getElementById('aiAttachBtn');
        aiImageInput = document.getElementById('aiImageInput');
        aiClearHistoryBtn = document.getElementById('aiClearHistoryBtn');
        closeAiChatBtn = document.getElementById('closeAiChatBtn');
        if (!aiMessagesContainer) return;
        loadAiHistory();
        setupAiUI();
    }

    window.initAiChat = initAiChat;
})();