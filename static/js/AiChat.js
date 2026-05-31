// AiChat.js — AI-чат с автоматической загрузкой нескольких страниц из поиска
// Версия: поле очищается после отправки, блокируется на время запроса
// + Добавлена возможность скачать сгенерированное изображение
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
    let reasoningEnabled = false;
    let internetEnabled = false;
    let aiMessagesContainer = null;
    let aiMessageInput = null;
    let aiSendBtn = null;
    let aiAttachBtn = null;
    let aiReasoningBtn = null;
    let aiInternetBtn = null;
    let aiImageInput = null;
    let aiClearHistoryBtn = null;
    let closeAiChatBtn = null;
    let aiImageGenBtn = null;

    const CONFIG = {
        historyMaxLength: 200,
        imageMaxWidth: 800,
        imageQuality: 0.7,
        apiEndpoint: '/ai/chat',
        searchEndpoint: '/ai/search',
    };

    // ========== Markdown ==========
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            highlight: function(code, lang) {
                if (lang && hljs.getLanguage(lang)) {
                    return hljs.highlight(code, { language: lang }).value;
                }
                return hljs.highlightAuto(code).value;
            },
            breaks: true, gfm: true,
            headerIds: false, mangle: false, async: false
        });
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m]))
                  .replace(/['"]/g, m => ({ "'": '&#39;', '"': '&quot;' }[m]));
    }

    function enhanceCodeBlocks(container) {
        if (!container) return;
        container.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
        container.querySelectorAll('pre').forEach(pre => {
            if (pre.querySelector('.copy-code-btn')) return;
            const btn = document.createElement('button');
            btn.textContent = '📋 Copy';
            btn.className = 'copy-code-btn';
            btn.style.cssText = 'position:absolute;top:8px;right:8px;background:#3c3c3c;border:none;color:#ccc;border-radius:4px;padding:4px 8px;cursor:pointer;font-size:12px;z-index:1;';
            btn.onclick = (e) => {
                e.stopPropagation();
                const code = pre.querySelector('code');
                if (!code) return;
                navigator.clipboard.writeText(code.innerText).then(() => {
                    btn.textContent = '✅ Copied!';
                    setTimeout(() => btn.textContent = '📋 Copy', 2000);
                });
            };
            pre.style.position = 'relative';
            pre.style.paddingTop = '32px';
            pre.appendChild(btn);
        });
    }

    // ========== Функция добавления кнопок скачивания для изображений ==========
    function addImageDownloadButtons(container) {
        if (!container) return;
        // Находим все изображения внутри контейнера (только в сообщениях ассистента)
        const images = container.querySelectorAll('img');
        images.forEach(img => {
            // Проверяем, не добавлена ли уже кнопка для этого изображения
            if (img.parentNode.querySelector('.download-image-btn')) return;

            const imageUrl = img.src;
            // Поддерживаем любые изображения, но особенно base64 (сгенерированные)
            if (!imageUrl) return;

            // Создаём контейнер для обёртки, чтобы кнопка была под картинкой
            const wrapper = document.createElement('div');
            wrapper.style.cssText = 'position:relative; display:inline-block; margin:0 4px 8px 0;';

            // Копируем атрибуты img
            const parent = img.parentNode;
            const imgClone = img.cloneNode(true);

            // Создаём кнопку скачивания
            const downloadBtn = document.createElement('button');
            downloadBtn.textContent = '💾 Скачать';
            downloadBtn.className = 'download-image-btn';
            downloadBtn.style.cssText = 'display:block; margin-top:4px; background:var(--accent-soft); border:none; border-radius:6px; padding:2px 8px; font-size:11px; cursor:pointer; color:var(--accent); width:100%; text-align:center;';
            downloadBtn.title = 'Сохранить изображение';

            downloadBtn.onclick = (e) => {
                e.stopPropagation();
                downloadImage(imageUrl, 'generated_image.png');
            };

            // Заменяем img на обёртку с кнопкой
            wrapper.appendChild(imgClone);
            wrapper.appendChild(downloadBtn);
            parent.replaceChild(wrapper, img);
        });
    }

    // Вспомогательная функция для скачивания изображения
    async function downloadImage(imageUrl, filename = 'image.png') {
        try {
            let blob;
            if (imageUrl.startsWith('data:image/')) {
                // Преобразуем dataURL в Blob
                const response = await fetch(imageUrl);
                blob = await response.blob();
            } else {
                // Обычный URL — запрашиваем как blob
                const response = await fetch(imageUrl);
                if (!response.ok) throw new Error('Network error');
                blob = await response.blob();
            }
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showToast('Изображение сохранено', 'success');
        } catch (err) {
            console.error('Ошибка скачивания:', err);
            showToast('Не удалось сохранить изображение', 'error');
        }
    }

    function renderMarkdown(text) {
        if (!text) return '';
        try {
            let html = marked.parse(text);
            const reasoningRegex = /💭\s*РАССУЖДЕНИЕ:\s*([\s\S]*?)\s*---/gi;
            if (reasoningRegex.test(html)) {
                reasoningRegex.lastIndex = 0;
                html = html.replace(reasoningRegex, (match, content) => {
                    return `<div class="reasoning-block"><strong>💭 Reasoning:</strong><br>${marked.parse(content)}</div>`;
                });
            }
            return html;
        } catch(e) {
            return escapeHtml(text);
        }
    }

    // ========== История ==========
    function getStoredHistory() {
        try { return JSON.parse(localStorage.getItem('ai_chat_history') || '[]'); }
        catch (e) { return []; }
    }
    function setStoredHistory(history) {
        try { localStorage.setItem('ai_chat_history', JSON.stringify(history)); }
        catch (e) {}
    }
    function saveAiMessage(role, text) {
        let history = getStoredHistory();
        history.push({ role, text, timestamp: Date.now() });
        if (history.length > CONFIG.historyMaxLength) history = history.slice(-CONFIG.historyMaxLength);
        setStoredHistory(history);
    }
    function loadAiHistory() {
        if (!aiMessagesContainer) return;
        const history = getStoredHistory();
        aiMessagesContainer.innerHTML = '';
        history.forEach(msg => displayAiMessage(msg.text, msg.role === 'user', null, false));
        if (history.length === 0) displayWelcome();
    }
    function clearAiHistory() {
        if (confirm('Очистить всю историю диалога с AI?')) {
            localStorage.removeItem('ai_chat_history');
            if (aiMessagesContainer) {
                aiMessagesContainer.innerHTML = '';
                displayWelcome();
            }
            showToast('История очищена', 'success');
        }
    }

    function displayWelcome() {
        displayAiMessage(
            'Привет! Я AI-ассистент с **автоматической загрузкой нескольких страниц из интернета**.\n\n' +
            '- 🌐 Кнопка "Интернет" включает поиск и чтение целых страниц (до 3 результатов)\n' +
            '- 🧠 Режим рассуждений показывает ход мыслей\n' +
            '- 🔗 Вставь ссылку — я прочитаю содержимое\n' +
            '- 📎 Прикрепи изображение для анализа\n' +
            '- 🎨 Генерация изображений — кнопка рядом с полем ввода',
            false, null, false
        );
    }

    async function compressImage(dataUrl, maxWidth = CONFIG.imageMaxWidth, quality = CONFIG.imageQuality) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                let width = img.width, height = img.height;
                if (width > maxWidth || height > maxWidth) {
                    if (width > height) { height = height * (maxWidth / width); width = maxWidth; }
                    else { width = width * (maxWidth / height); height = maxWidth; }
                }
                canvas.width = width; canvas.height = height;
                canvas.getContext('2d').drawImage(img, 0, 0, width, height);
                resolve(canvas.toDataURL('image/jpeg', quality));
            };
            img.onerror = reject;
            img.src = dataUrl;
        });
    }

    function showToast(message, type = 'info') {
        if (window.NotificationManager?.showToast) window.NotificationManager.showToast(message, type);
        else console.log(`[${type}] ${message}`);
    }

    // ========== Отображение сообщений ==========
    function displayAiMessage(text, isUser, imagePreview = null, saveToStorage = true) {
        if (!aiMessagesContainer) return;
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${isUser ? 'sent' : 'received'} animate-fade`;
        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        let imageHtml = '';
        if (imagePreview) {
            imageHtml = `<img src="${escapeHtml(imagePreview)}" alt="Attached" style="max-width:200px;max-height:150px;border-radius:8px;margin-bottom:8px;cursor:pointer;" onclick="window.openImageModal && window.openImageModal('${escapeHtml(imagePreview)}')">`;
        }
        if (isUser) {
            msgDiv.innerHTML = `
                <div class="avatar">👤</div>
                <div class="content">
                    ${imageHtml}
                    <div class="markdown-body">${escapeHtml(text)}</div>
                    <div class="meta"><span>${time}</span></div>
                </div>`;
        } else {
            const html = renderMarkdown(text);
            msgDiv.innerHTML = `
                <div class="avatar">🤖</div>
                <div class="content">
                    ${imageHtml}
                    <div class="markdown-body">${html}</div>
                    <div class="meta"><span>${time}</span></div>
                </div>`;
            const markdownBody = msgDiv.querySelector('.markdown-body');
            if (markdownBody) {
                enhanceCodeBlocks(markdownBody);
                addImageDownloadButtons(markdownBody); // Добавляем кнопки скачивания для изображений
            }
        }
        aiMessagesContainer.appendChild(msgDiv);
        aiMessagesContainer.scrollTop = aiMessagesContainer.scrollHeight;
        if (saveToStorage && text && !text.includes('Привет! Я AI-ассистент')) {
            saveAiMessage(isUser ? 'user' : 'assistant', text);
        }
        return msgDiv;
    }

    function showAiTypingIndicator(show, statusText = '') {
        if (!aiMessagesContainer) return;
        let indicator = aiMessagesContainer.querySelector('.typing-indicator-message');
        if (show) {
            if (indicator) indicator.remove();
            indicator = document.createElement('div');
            indicator.className = 'message received typing-indicator-message';
            if (statusText) {
                indicator.innerHTML = `
                    <div class="avatar">🤖</div>
                    <div class="content">
                        <div style="color:var(--text-secondary);font-size:13px;padding:8px 0;">${escapeHtml(statusText)}</div>
                    </div>`;
            } else {
                indicator.innerHTML = `
                    <div class="avatar">🤖</div>
                    <div class="typing-indicator"><span></span><span></span><span></span></div>`;
            }
            aiMessagesContainer.appendChild(indicator);
            aiMessagesContainer.scrollTop = aiMessagesContainer.scrollHeight;
        } else {
            if (indicator) indicator.remove();
        }
    }

    function displaySearchSources(results) {
        if (!results || !results.length) return;
        const sourcesDiv = document.createElement('div');
        sourcesDiv.className = 'search-sources animate-fade';
        sourcesDiv.style.cssText = `
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px 14px;
            margin: 6px 0 6px 36px;
            font-size: 12px;
            color: var(--text-secondary);
        `;
        const links = results
            .filter(r => r.url)
            .map(r => `<a href="${escapeHtml(r.url)}" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;display:block;margin:2px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(r.title || r.url)}">${escapeHtml((r.title || r.url).slice(0, 80))}</a>`)
            .join('');
        sourcesDiv.innerHTML = `<span style="opacity:.7;">🔍 Источники:</span><div style="margin-top:4px;">${links || '<span style="opacity:.6;">нет прямых ссылок</span>'}</div>`;
        if (aiMessagesContainer) {
            aiMessagesContainer.appendChild(sourcesDiv);
            aiMessagesContainer.scrollTop = aiMessagesContainer.scrollHeight;
        }
    }

    // ========== Основная отправка ==========
    async function sendToAi(messageText, imageFile) {
        if (isSending) { showToast('Подождите, предыдущий запрос обрабатывается', 'warning'); return; }
        if (!messageText.trim() && !imageFile) { showToast('Введите сообщение или выберите изображение', 'warning'); return; }

        if (currentStreamReader) {
            try { currentStreamReader.cancel(); } catch(e) {}
            currentStreamReader = null;
        }
        currentStreamingMessage = null;
        currentStreamingText = '';
        isSending = true;

        const urlMatch = messageText.match(/https?:\/\/[^\s]+/);
        const urlToFetch = urlMatch ? urlMatch[0] : null;

        let previewUrl = null;
        if (imageFile) {
            previewUrl = URL.createObjectURL(imageFile);
            displayAiMessage(messageText || '📷 Изображение', true, previewUrl, true);
        } else {
            displayAiMessage(messageText, true, null, true);
        }

        const useWebSearch = internetEnabled && !urlToFetch;
        const isSearching = useWebSearch || !!urlToFetch;
        showAiTypingIndicator(true, isSearching ? (urlToFetch ? `🔗 Загружаю ${urlToFetch.slice(0, 50)}…` : '🔍 Ищу в интернете и загружаю страницы…') : '');

        try {
            let imageBase64 = null, imageMime = null;
            if (imageFile) {
                const reader = new FileReader();
                const compressedDataUrl = await new Promise((resolve) => {
                    reader.onload = async (e) => resolve(await compressImage(e.target.result));
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
                    stream: true,
                    reasoning: reasoningEnabled,
                    web_search: useWebSearch,
                    url_to_fetch: urlToFetch,
                })
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.detail || `HTTP ${response.status}`);
            }

            currentStreamingMessage = displayAiMessage('', false, null, false);
            currentStreamingText = '';
            const markdownBody = currentStreamingMessage.querySelector('.content .markdown-body');
            if (!markdownBody) throw new Error('UI error');

            let firstTokenReceived = false;
            let streamFinished = false;
            let searchResults = null;

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
                    if (!line.startsWith('data: ')) continue;
                    const dataStr = line.slice(6).trim();
                    if (dataStr === '[DONE]') { streamFinished = true; break; }

                    try {
                        const data = JSON.parse(dataStr);

                        if (data.status === 'searching') {
                            showAiTypingIndicator(true, `🔍 Ищу: ${data.query || '…'}`);
                            continue;
                        }
                        if (data.status === 'search_done') {
                            showAiTypingIndicator(true, '📄 Загружаю содержимое страниц…');
                            continue;
                        }
                        if (data.status === 'search_error') {
                            showAiTypingIndicator(true, '⚠️ Поиск не удался, отвечаю из памяти…');
                            continue;
                        }
                        if (data.status === 'fetching_pages') {
                            showAiTypingIndicator(true, `📖 Читаю ${data.count || 'несколько'} страниц…`);
                            continue;
                        }

                        if (data.token) {
                            if (!firstTokenReceived) {
                                showAiTypingIndicator(false);
                                firstTokenReceived = true;
                            }
                            currentStreamingText += data.token;
                            markdownBody.textContent = currentStreamingText;
                            if (aiMessagesContainer) aiMessagesContainer.scrollTop = aiMessagesContainer.scrollHeight;
                        } else if (data.error) {
                            markdownBody.textContent = '❌ ' + data.error;
                            firstTokenReceived = true;
                            streamFinished = true;
                            break;
                        } else if (data.sources) {
                            searchResults = data.sources;
                        }
                    } catch(e) {}
                }
            }

            if (!firstTokenReceived) {
                showAiTypingIndicator(false);
                if (markdownBody) markdownBody.textContent = '🤖 Нет ответа от модели.';
            } else if (currentStreamingText) {
                const finalHtml = renderMarkdown(currentStreamingText);
                markdownBody.innerHTML = finalHtml;
                enhanceCodeBlocks(markdownBody);
                addImageDownloadButtons(markdownBody); // Добавляем кнопки скачивания после финального рендера
                saveAiMessage('assistant', currentStreamingText);

                if (searchResults && searchResults.length) {
                    displaySearchSources(searchResults);
                } else if (useWebSearch && !searchResults) {
                    _tryFetchSearchSources(messageText);
                }
            }

        } catch (err) {
            console.error('AI error:', err);
            showAiTypingIndicator(false);
            if (currentStreamingMessage?.parentNode) {
                const errDiv = currentStreamingMessage.querySelector('.content .markdown-body');
                if (errDiv) errDiv.textContent = '❌ Ошибка связи с AI-сервером. Проверьте, запущен ли LM Studio.';
            } else {
                displayAiMessage('❌ Ошибка связи с AI-сервером.', false, null, true);
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

    async function _tryFetchSearchSources(query) {
        try {
            const res = await fetch(CONFIG.searchEndpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query })
            });
            if (res.ok) {
                const data = await res.json();
                if (data.results?.length) displaySearchSources(data.results);
            }
        } catch(e) {}
    }

    // ========== Настройка UI ==========
    function updateInternetBtnStyle() {
        if (!aiInternetBtn) return;
        if (internetEnabled) {
            aiInternetBtn.style.opacity = '1';
            aiInternetBtn.style.background = 'var(--accent-soft)';
            aiInternetBtn.style.color = 'var(--accent)';
            aiInternetBtn.title = 'Интернет ВКЛЮЧЁН (буду искать и читать страницы)';
        } else {
            aiInternetBtn.style.opacity = '0.5';
            aiInternetBtn.style.background = '';
            aiInternetBtn.style.color = '';
            aiInternetBtn.title = 'Интернет ВЫКЛЮЧЕН (только мои знания)';
        }
    }

    function setupAiUI() {
        if (!aiSendBtn) return;

        // --- Отправка обычного сообщения AI (блокировка + очистка) ---
        aiSendBtn.onclick = async () => {
            const text = aiMessageInput ? aiMessageInput.value.trim() : '';
            const image = pendingImageFile;
            if (!text && !image) {
                showToast('Введите сообщение или прикрепите изображение', 'warning');
                return;
            }

            // Блокируем поле и все кнопки
            aiMessageInput.disabled = true;
            aiSendBtn.disabled = true;
            aiAttachBtn.disabled = true;
            if (aiImageGenBtn) aiImageGenBtn.disabled = true;
            if (aiInternetBtn) aiInternetBtn.disabled = true;
            if (aiReasoningBtn) aiReasoningBtn.disabled = true;
            if (aiClearHistoryBtn) aiClearHistoryBtn.disabled = true;

            const originalText = text;

            // Удаляем прикреплённое изображение (если есть)
            if (pendingImageFile) {
                document.getElementById('aiImagePreview')?.remove();
                if (currentImagePreviewUrl) URL.revokeObjectURL(currentImagePreviewUrl);
                pendingImageFile = null;
                currentImagePreviewUrl = null;
            }
            if (aiMessageInput) aiMessageInput.value = '';
            try {
                await sendToAi(originalText, image);
            } finally {
                // Разблокируем всё
                aiMessageInput.disabled = false;
                aiSendBtn.disabled = false;
                aiAttachBtn.disabled = false;
                if (aiImageGenBtn) aiImageGenBtn.disabled = false;
                if (aiInternetBtn) aiInternetBtn.disabled = false;
                if (aiReasoningBtn) aiReasoningBtn.disabled = false;
                if (aiClearHistoryBtn) aiClearHistoryBtn.disabled = false;
                aiMessageInput.focus();
            }
        };

        // --- Enter для отправки ---
        if (aiMessageInput) {
            aiMessageInput.onkeydown = (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    aiSendBtn?.click();
                }
            };
        }

        // --- Прикрепление изображения ---
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
                        <span style="font-size:12px;color:var(--text-secondary);">${escapeHtml(file.name)}</span>
                        <button type="button" id="clearAiImage" class="btn btn-icon" style="font-size:14px;">✕</button>`;
                    document.getElementById('clearAiImage')?.addEventListener('click', () => {
                        if (currentImagePreviewUrl) URL.revokeObjectURL(currentImagePreviewUrl);
                        pendingImageFile = null;
                        previewContainer.remove();
                        currentImagePreviewUrl = null;
                    });
                } else {
                    showToast('Пожалуйста, выберите изображение', 'warning');
                }
                aiImageInput.value = '';
            };
        }

        // --- Режим рассуждений (Reasoning) ---
        if (aiReasoningBtn) {
            reasoningEnabled = localStorage.getItem('ai_reasoning_mode') === 'true';
            aiReasoningBtn.style.opacity = reasoningEnabled ? '1' : '0.5';
            aiReasoningBtn.title = reasoningEnabled ? 'Reasoning ON' : 'Reasoning OFF';
            aiReasoningBtn.onclick = () => {
                reasoningEnabled = !reasoningEnabled;
                aiReasoningBtn.style.opacity = reasoningEnabled ? '1' : '0.5';
                aiReasoningBtn.title = reasoningEnabled ? 'Reasoning ON' : 'Reasoning OFF';
                localStorage.setItem('ai_reasoning_mode', reasoningEnabled);
                showToast(`Режим рассуждений ${reasoningEnabled ? 'включён 🧠' : 'выключен'}`, 'info');
            };
        }

        // --- Кнопка Интернета (вкл/выкл) ---
        if (aiInternetBtn) {
            internetEnabled = localStorage.getItem('ai_internet') === 'true';
            updateInternetBtnStyle();
            aiInternetBtn.onclick = () => {
                internetEnabled = !internetEnabled;
                localStorage.setItem('ai_internet', internetEnabled);
                updateInternetBtnStyle();
                showToast(`Интернет-поиск ${internetEnabled ? 'включён 🌐 (буду загружать страницы)' : 'выключен'}`, 'info');
            };
        }

        // --- Кнопка очистки истории ---
        if (aiClearHistoryBtn) aiClearHistoryBtn.onclick = clearAiHistory;

        // --- Кнопка закрытия AI-чата ---
        if (closeAiChatBtn) {
            closeAiChatBtn.onclick = () => {
                if (window.selectConversation && window.State?.currentChatAddress === 'ai_bot') {
                    const firstConv = document.querySelector('.conversation-item');
                    if (firstConv?.dataset.address) {
                        window.selectConversation(firstConv.dataset.address, '', firstConv.dataset.isGroup === '1');
                    } else {
                        window.selectConversation('', '', false);
                    }
                }
            };
        }

        // --- Кнопка генерации изображения (автоматическое улучшение промта + очистка) ---
        aiImageGenBtn = document.getElementById('aiImageGenBtn');
        if (aiImageGenBtn) {
            aiImageGenBtn.onclick = async () => {
                const rawPrompt = aiMessageInput.value.trim();
                if (!rawPrompt) {
                    showToast('Enter a prompt first', 'warning');
                    return;
                }
                if (isSending) {
                    showToast('Please wait, current request in progress', 'warning');
                    return;
                }
                isSending = true;
                if (aiMessageInput) aiMessageInput.value = '';
                // Блокируем поле и все кнопки
                aiMessageInput.disabled = true;
                aiSendBtn.disabled = true;
                aiAttachBtn.disabled = true;
                aiImageGenBtn.disabled = true;
                if (aiInternetBtn) aiInternetBtn.disabled = true;
                if (aiReasoningBtn) aiReasoningBtn.disabled = true;
                if (aiClearHistoryBtn) aiClearHistoryBtn.disabled = true;

                showAiTypingIndicator(true, '🎨 Generating image...');

                let response = null;
                let data = null;

                try {
                    let finalPrompt = rawPrompt;
                    // Всегда улучшаем промт через LLM
                    showAiTypingIndicator(true, '✨ Enhancing prompt with AI...');
                    try {
                        const enhanceResp = await fetch('/ai/enhance_prompt', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ prompt: rawPrompt })
                        });
                        if (enhanceResp.ok) {
                            const enhanceData = await enhanceResp.json();
                            if (enhanceData.enhanced && enhanceData.enhanced !== rawPrompt) {
                                finalPrompt = enhanceData.enhanced;
                                showToast('Prompt enhanced', 'success');
                            }
                        }
                    } catch (enhanceErr) {
                        console.warn('Enhance failed, using original prompt', enhanceErr);
                    }
                    showAiTypingIndicator(true, '🎨 Generating image...');

                    response = await fetch('/ai/generate_image', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ prompt: finalPrompt })
                    });
                    data = await response.json();

                    if (response.ok && data.image_base64) {
                        const imageMarkdown = `![generated](${data.image_base64})`;
                        const finalText = `🎨 *Generated image for:*\n> ${rawPrompt}\n\n${imageMarkdown}`;
                        displayAiMessage(finalText, false, null, true);
                        // Очищаем поле после успешной генерации

                    } else {
                        showToast(data.detail || data.error || 'Generation failed', 'error');
                    }
                } catch (err) {
                    console.error('Image generation error:', err);
                    showToast('Network error or service unavailable', 'error');
                } finally {
                    isSending = false;
                    showAiTypingIndicator(false);

                    // Разблокируем всё
                    aiMessageInput.disabled = false;
                    aiSendBtn.disabled = false;
                    aiAttachBtn.disabled = false;
                    aiImageGenBtn.disabled = false;
                    if (aiInternetBtn) aiInternetBtn.disabled = false;
                    if (aiReasoningBtn) aiReasoningBtn.disabled = false;
                    if (aiClearHistoryBtn) aiClearHistoryBtn.disabled = false;

                    aiMessageInput.focus();
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
        aiReasoningBtn = document.getElementById('aiReasoningBtn');
        aiInternetBtn = document.getElementById('aiInternetBtn');
        aiImageInput = document.getElementById('aiImageInput');
        aiClearHistoryBtn = document.getElementById('aiClearHistoryBtn');
        closeAiChatBtn = document.getElementById('closeAiChatBtn');
        if (!aiMessagesContainer) return;
        loadAiHistory();
        setupAiUI();
    }

    window.initAiChat = initAiChat;
})();