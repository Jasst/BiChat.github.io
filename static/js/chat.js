let currentContact = null;
const emojis = ['😀', '😂', '❤️', '😍', '😭', '🔥', '💯', '🎉', '🤔', '👍', '👋', '👌', '🙏', '💪', '👀', '🙌', '👏', '🤝', '👍', '👎', '🙏', '😊', '🥰', '😎', '🤩', '🥳', '😭', '😡', '🤬', '🤯', '🥶', '😱', '🤠', '🥴', '😈', '👻', '👽', '🤖', '👾', '👐', '🙌', '👏', '🤝', '👍', '👎', '👊', '✊', '🤛', '🤜', '🤞', '✌️', '🤟', '🤘', '👌', '👈', '👉', '👆', '👇', '☝️', '✋', '🤚', '🖐', '🖖', '👋', '🤙', '💪', '🦾', '🦿', '🦵', '🦶', '👂', '🦻', '👃', '🧠', '🦷', '🦴', '👀', '👁', '👅', '👄', '👶', '🧒', '👦', '👧', '🧑', '👱', '👨', '🧔', '👨‍🦰', '👨‍🦱', '👨‍🦳', '👨‍🦲', '👩', '👩‍🦰', '👩‍🦱', '👩‍🦳', '👩‍🦲', '🧓', '👴', '👵', '🙍', '🙎', '🙅', '🙆', '💁', '🙋', '🧏', '🙇', '🤦', '🤷', '👮', '🕵', '💂', '🥷', '👷', '🤴', '👸', '👳', '👲', '🧕', '🤵', '👰', '🤰', '🤱', '👼', '🎅', '🤶', '🦸', '🦹', '🧙', '🧚', '🧛', '🧜', '🧝', '🧞', '🧟', '💆', '💇', '🚶', '🧍', '🧎', '🏃', '💃', '🕺', '🕴', '👯', '🧖', '🧗', '🤺', '🏇', '⛷', '🏂', '🏌', '🏄', '🚣', '🏊', '⛹', '🏋', '🚴', '🚵', '🤸', '🤼', '🤽', '🤾', '🤹', '🧘', '🛀', '🛌', '👭', '👫', '👬', '💏', '💑', '👪', '🗣', '👤', '👥', '👣', '🦰', '🦱', '🦳', '🦲'];

function formatTime(timestamp) {
    const date = new Date(timestamp * 1000);
    const now = new Date();

    // Если сегодня
    if (date.toDateString() === now.toDateString()) {
        return date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    }

    // Если вчера
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (date.toDateString() === yesterday.toDateString()) {
        return 'Yesterday ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    }

    // Если эта неделя
    const weekAgo = new Date(now);
    weekAgo.setDate(weekAgo.getDate() - 7);
    if (date > weekAgo) {
        return date.toLocaleDateString([], {weekday: 'short'}) + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    }

    // Иначе полная дата
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
}

function loadMessages() {
    fetch('/get_messages')
        .then(response => response.json())
        .then(data => {
            const messagesContainer = document.getElementById('messagesContainer');
            messagesContainer.innerHTML = '';

            if (!data.messages || data.messages.length === 0) {
                messagesContainer.innerHTML = '<div class="no-messages">No messages yet</div>';
                return;
            }

            // Фильтруем сообщения для текущего контакта
            let filteredMessages = data.messages;
            if (currentContact) {
                filteredMessages = data.messages.filter(msg =>
                    (msg.sender === currentContact && msg.recipient === window.myAddress) ||
                    (msg.sender === window.myAddress && msg.recipient === currentContact)
                );
            }

            filteredMessages.forEach(msg => {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${msg.is_mine ? 'sent' : 'received'}`;

                let content = `<div class="message-content">${msg.content}</div>`;
                if (msg.image && msg.image.startsWith('')) {
                    content += `<img src="${msg.image}" style="max-width: 200px; margin-top: 8px; border-radius: 8px;">`;
                } else if (msg.image) {
                    content += `<img src="${msg.image}" style="max-width: 200px; margin-top: 8px; border-radius: 8px;">`;
                }

                messageDiv.innerHTML = `
                    ${content}
                    <div class="message-meta">
                        ${formatTime(msg.timestamp)}
                    </div>
                `;

                messagesContainer.appendChild(messageDiv);
            });

            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        })
        .catch(error => console.error('Error loading messages:', error));
}

function sendMessage() {
    const messageInput = document.getElementById('messageInput');
    const content = messageInput.value.trim();

    if (!content || !currentContact) return;

    fetch('/send_message', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            recipient: currentContact,
            content: content
        })
    })
    .then(response => response.json())
    .then(data => {
        if (response.ok) {
            messageInput.value = '';
            loadMessages();
        } else {
            alert('Error: ' + data.error);
        }
    })
    .catch(error => console.error('Error sending message:', error));
}

function handleKeyPress(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('active');
}

function toggleEmojiPicker() {
    const picker = document.getElementById('emojiPicker');
    if (picker.style.display === 'none' || picker.style.display === '') {
        showEmojiPicker();
        picker.style.display = 'flex';
    } else {
        picker.style.display = 'none';
    }
}

function showEmojiPicker() {
    const picker = document.getElementById('emojiPicker');
    picker.innerHTML = emojis.slice(0, 50).map(emoji =>
        `<button class="emoji-btn" onclick="addEmoji('${emoji}')">${emoji}</button>`
    ).join('');
}

function addEmoji(emoji) {
    const messageInput = document.getElementById('messageInput');
    messageInput.value += emoji;
    messageInput.focus();
}

function handleFileSelect() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];

    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    fetch('/upload_file', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (response.ok) {
            const messageInput = document.getElementById('messageInput');
            messageInput.value += '\n[File: ' + data.file_url + ']';
        } else {
            alert('Error uploading file: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error uploading file:', error);
        alert('Error uploading file');
    });
}

function showMyAddress() {
    alert('Your address:\n\n' + window.myAddress);
}

function showFullAddress() {
    alert('Your full address:\n\n' + window.myAddress);
}

// Инициализация
document.addEventListener('DOMContentLoaded', function() {
    // Получаем адрес пользователя
    window.myAddress = '{{ address }}';

    // Загружаем сообщения
    loadMessages();

    // Автообновление каждые 3 секунды
    setInterval(loadMessages, 3000);

    // Инициализируем emoji picker
    showEmojiPicker();

    // Проверяем, есть ли выбранный контакт в localStorage
    const savedContact = localStorage.getItem('selectedContact');
    if (savedContact) {
        currentContact = savedContact;
        document.getElementById('current-contact').textContent = savedContact.substring(0, 20) + '...';
    }
});