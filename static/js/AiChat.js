// AiChat.js — AI Assistant с потоковым отображением ответа (исправленная версия)
(function() {
    let aiChatActive = false;
    let originalSelectConversation = null;
    let typingIndicator = null;
    let pendingImageFile = null;
    let currentStreamingMessage = null;
    let currentStreamingText = '';
    let currentStreamReader = null;

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/[&<>]/g, function(m) {
            if (m === '&') return '&amp;';
            if (m === '<') return '&lt;';
            if (m === '>') return '&gt;';
            return m;
        });
    }

    function saveAiMessage(role, text, timestamp = Date.now()) {
        const chatId = 'ai_bot';
        let history = JSON.parse(localStorage.getItem(`ai_chat_${chatId}`) || '[]');
        history.push({ role, text, timestamp });
        if (history.length > 200) history = history.slice(-200);
        localStorage.setItem(`ai_chat_${chatId}`, JSON.stringify(history));
    }

    function loadAiHistory() {
        const container = document.getElementById('messagesContainer');
        if (!container) return;
        const history = JSON.parse(localStorage.getItem('ai_chat_ai_bot') || '[]');
        container.innerHTML = '';
        history.forEach(msg => {
            displayAiMessage(msg.text, msg.role === 'user', null, false);
        });
        if (history.length === 0) {
            displayAiMessage('Привет! Я AI-ассистент. Задавайте вопросы и прикрепляйте изображения.', false, null, false);
        }
    }

    function clearAiHistory() {
        if (confirm('Очистить всю историю диалога с AI-ботом?')) {
            localStorage.removeItem('ai_chat_ai_bot');
            const container = document.getElementById('messagesContainer');
            if (container) {
                container.innerHTML = '';
                displayAiMessage('История очищена. Начните новый диалог.', false, null, false);
            }
        }
    }

    async function compressImage(dataUrl, maxWidth = 800, quality = 0.7) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                let width = img.width;
                let height = img.height;
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
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, width, height);
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
        const container = document.getElementById('messagesContainer');
        if (!container) return;

        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${isUser ? 'sent' : 'received'} animate-fade`;
        const avatar = isUser ? '👤' : '🤖';
        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const content = escapeHtml(text);

        let imageHtml = '';
        if (imagePreview) {
            imageHtml = `<img src="${escapeHtml(imagePreview)}" alt="Attached" style="max-width: 200px; max-height: 150px; border-radius: 8px; margin-bottom: 8px; cursor: pointer;" onclick="window.openImageModal && window.openImageModal('${escapeHtml(imagePreview)}')">`;
        }

        msgDiv.innerHTML = `
            <div class="avatar">${avatar}</div>
            <div class="content">
                ${imageHtml}
                <p>${content}</p>
                <div class="meta"><span>${time}</span></div>
            </div>
        `;
        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;

        if (saveToStorage && text && !(isUser === false && text.includes('Привет! Я AI-ассистент'))) {
            saveAiMessage(isUser ? 'user' : 'assistant', text);
        }
        return msgDiv;
    }

    function showAiTypingIndicator(show) {
        const container = document.getElementById('messagesContainer');
        if (!container) return;
        if (show) {
            if (typingIndicator) typingIndicator.remove();
            typingIndicator = document.createElement('div');
            typingIndicator.className = 'message received typing-indicator-message';
            typingIndicator.innerHTML = `
                <div class="avatar">🤖</div>
                <div class="typing-indicator">
                    <span></span><span></span><span></span>
                </div>
            `;
            container.appendChild(typingIndicator);
            container.scrollTop = container.scrollHeight;
        } else {
            if (typingIndicator) {
                typingIndicator.remove();
                typingIndicator = null;
            }
        }
    }

    async function sendToAi(messageText, imageFile) {
        console.log('[AI] sendToAi called', { messageText, imageFile });
        if (!messageText.trim() && !imageFile) {
            showToast('Введите сообщение или выберите изображение', 'warning');
            return;
        }

        let previewUrl = null;
        if (imageFile) {
            previewUrl = URL.createObjectURL(imageFile);
            displayAiMessage(messageText || '📷 Изображение', true, previewUrl, true);
        } else {
            displayAiMessage(messageText, true, null, true);
        }

        showAiTypingIndicator(true);

        if (currentStreamReader) {
            try { currentStreamReader.cancel(); } catch(e) {}
            currentStreamReader = null;
        }

        try {
            let imageBase64 = null;
            let imageMime = null;
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
                console.log('[AI] Image prepared', { mime: imageMime, base64Len: imageBase64?.length });
            }

            const response = await fetch('/ai/chat', {
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

            const reader = response.body.getReader();
            currentStreamReader = reader;
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const dataStr = line.slice(6);
                        if (dataStr === '[DONE]') {
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
                                const container = document.getElementById('messagesContainer');
                                if (container) container.scrollTop = container.scrollHeight;
                            } else if (data.error) {
                                contentParagraph.textContent = '❌ ' + data.error;
                                firstTokenReceived = true;
                            }
                        } catch (e) {}
                    }
                }
            }
            if (!firstTokenReceived) {
                showAiTypingIndicator(false);
                contentParagraph.textContent = '🤖 Нет ответа от модели.';
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
        }
    }

    function setupAiInputUI() {
        let inputActions = document.querySelector('.input-actions');
        if (!inputActions) {
            setTimeout(setupAiInputUI, 100);
            return;
        }

        // Удаляем старые кнопки AI, чтобы не дублировать
        const oldAttach = document.getElementById('aiAttachBtn');
        if (oldAttach) oldAttach.remove();
        const oldFileInput = document.getElementById('aiImageInput');
        if (oldFileInput) oldFileInput.remove();
        const oldClearBtn = document.getElementById('aiClearHistoryBtn');
        if (oldClearBtn) oldClearBtn.remove();

        const attachBtn = document.createElement('button');
        attachBtn.type = 'button';
        attachBtn.id = 'aiAttachBtn';
        attachBtn.className = 'btn btn-icon';
        attachBtn.innerHTML = '📎';
        attachBtn.title = 'Attach image';

        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.id = 'aiImageInput';
        fileInput.accept = 'image/*';
        fileInput.style.display = 'none';

        attachBtn.onclick = () => fileInput.click();

        fileInput.onchange = async (e) => {
            const file = e.target.files[0];
            console.log('[AI] File selected', file);
            if (file && file.type.startsWith('image/')) {
                pendingImageFile = file;
                let previewContainer = document.getElementById('aiImagePreview');
                if (!previewContainer) {
                    previewContainer = document.createElement('div');
                    previewContainer.id = 'aiImagePreview';
                    previewContainer.style.cssText = 'margin-top: 8px; display: flex; align-items: center; gap: 8px;';
                    inputActions.parentNode.insertBefore(previewContainer, inputActions.nextSibling);
                }
                previewContainer.innerHTML = `
                    <img src="${URL.createObjectURL(file)}" style="max-width: 60px; max-height: 60px; border-radius: 8px;">
                    <button type="button" id="clearAiImage" class="btn btn-icon" style="font-size: 14px;">✕</button>
                `;
                document.getElementById('clearAiImage')?.addEventListener('click', () => {
                    pendingImageFile = null;
                    if (previewContainer) previewContainer.remove();
                });
            } else {
                showToast('Пожалуйста, выберите изображение', 'warning');
            }
            fileInput.value = '';
        };

        const clearHistoryBtn = document.createElement('button');
        clearHistoryBtn.type = 'button';
        clearHistoryBtn.id = 'aiClearHistoryBtn';
        clearHistoryBtn.className = 'btn btn-icon';
        clearHistoryBtn.innerHTML = '🗑';
        clearHistoryBtn.title = 'Clear AI history';
        clearHistoryBtn.onclick = clearAiHistory;

        inputActions.insertBefore(attachBtn, inputActions.firstChild);
        inputActions.insertBefore(fileInput, inputActions.firstChild);
        inputActions.insertBefore(clearHistoryBtn, inputActions.firstChild);
    }

    function activateAiChat() {
        if (aiChatActive) return;
        aiChatActive = true;
        // ✅ Устанавливаем флаг для блокировки обычной отправки
        if (window.State) {
        window.State.currentChatAddress = 'ai_bot';
        window.State.currentChatIsGroup = false;
        window.isAiChatActive = true;

    }
        pendingImageFile = null;

        const oldPreview = document.getElementById('aiImagePreview');
        if (oldPreview) oldPreview.remove();

        const addBtn = document.getElementById('addToContactsBtn');
        const clearBtn = document.getElementById('clearConversationBtn');
        if (addBtn) addBtn.disabled = true;
        if (clearBtn) clearBtn.disabled = true;

        const messageInput = document.getElementById('messageContent');
        const sendBtn = document.getElementById('sendButton');
        const originalAttachBtn = document.getElementById('attachImageButton');
        if (messageInput) messageInput.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
        if (originalAttachBtn) originalAttachBtn.disabled = true;

        loadAiHistory();

        const nameEl = document.getElementById('currentChatName');
        const subEl = document.getElementById('chatSubtitle');
        if (nameEl) nameEl.textContent = '🤖 AI Assistant';
        if (subEl) subEl.textContent = 'Streaming response';

        setupAiInputUI();

        if (!window.__aiOriginalSendHandler) {
            window.__aiOriginalSendHandler = sendBtn?.onclick;
            window.__aiOriginalKeydown = messageInput?.onkeydown;
        }

        const newSendHandler = () => {
            const text = messageInput.value.trim();
            const image = pendingImageFile;
            console.log('[AI] Send clicked', { text, image });
            console.log('[AI] Send clicked, text="%s", image=%o, pendingImageFile=%o', text, image, pendingImageFile);
            if (!text && !image) {
                showToast('Введите сообщение или прикрепите изображение', 'warning');
                return;
            }
            messageInput.value = '';
            if (pendingImageFile) {
                const previewContainer = document.getElementById('aiImagePreview');
                if (previewContainer) previewContainer.remove();
                pendingImageFile = null;
            }
            sendToAi(text, image);
        };
        sendBtn.onclick = newSendHandler;
        messageInput.onkeydown = (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendBtn.click();
            }
        };

        if (window.longPollingClient && window.longPollingClient.stop) {
            window.longPollingClient.stop();
        }

        if (window.innerWidth <= 768 && typeof closeSidebar === 'function') {
            closeSidebar();
        }

        document.querySelectorAll('.conversation-item').forEach(item => item.classList.remove('active'));
    }

    function deactivateAiChat() {
    if (!aiChatActive) return;
    aiChatActive = false;
    window.isAiChatActive = false;
    // НЕ меняем window.State.currentChatAddress – он перезапишется при выборе другого чата.

    const aiAttachBtn = document.getElementById('aiAttachBtn');
    const aiImageInput = document.getElementById('aiImageInput');
    const previewContainer = document.getElementById('aiImagePreview');
    const aiClearHistoryBtn = document.getElementById('aiClearHistoryBtn');
    if (aiAttachBtn) aiAttachBtn.remove();
    if (aiImageInput) aiImageInput.remove();
    if (previewContainer) previewContainer.remove();
    if (aiClearHistoryBtn) aiClearHistoryBtn.remove();

    const sendBtn = document.getElementById('sendButton');
    const messageInput = document.getElementById('messageContent');
    if (window.__aiOriginalSendHandler) {
        sendBtn.onclick = window.__aiOriginalSendHandler;
        messageInput.onkeydown = window.__aiOriginalKeydown;
    }

    if (typeof setupLongPolling === 'function') {
        setupLongPolling();
    } else if (window.setupLongPolling) {
        window.setupLongPolling();
    }
}

    function interceptSelectConversation() {
        if (window.selectConversation && !window._aiIntercepted) {
            originalSelectConversation = window.selectConversation;
            window.selectConversation = function(address, name, isGroup) {
                if (address === 'ai_bot') {
                    deactivateAiChat();
                    activateAiChat();
                    return;
                } else {
                    deactivateAiChat();
                    originalSelectConversation(address, name, isGroup);
                }
            };
            window._aiIntercepted = true;
        }
    }

    function init() {
        interceptSelectConversation();
        const aiBtn = document.getElementById('aiChatBtn');
        if (aiBtn) {
            aiBtn.addEventListener('click', () => {
                deactivateAiChat();
                activateAiChat();
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();