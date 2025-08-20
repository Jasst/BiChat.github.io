let lastTimestamp = 0;
const emojis = ['😀', '😂', '❤️', '😍', '😭', '🔥', '💯', '🎉', '🤔', '👍', '👋', '👌', '🙏', '💪', '👀', '🙌', '👏', '🤝', '👍', '👎'];

function formatTime(timestamp) {
    return new Date(timestamp * 1000).toLocaleTimeString();
}

function loadMessages() {
    fetch('/get_messages')
        .then(response => response.json())
        .then(data => {
            const chatArea = document.getElementById('chatArea');
            chatArea.innerHTML = '';

            data.messages.forEach(msg => {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${msg.is_mine ? 'sent' : 'received'}`;

                let content = `<div>${msg.content}</div>`;
                if (msg.image && msg.image.startsWith('data:')) {
                    content += `<img src="${msg.image}" style="max-width: 200px; margin-top: 10px; border-radius: 5px;">`;
                } else if (msg.image) {
                    content += `<img src="${msg.image}" style="max-width: 200px; margin-top: 10px; border-radius: 5px;">`;
                }

                messageDiv.innerHTML = `
                    ${content}
                    <div class="message-meta">
                        ${msg.is_mine ? 'You' : msg.sender.substring(0, 10) + '...'}
                        at ${formatTime(msg.timestamp)}
                    </div>
                `;

                chatArea.appendChild(messageDiv);
            });

            chatArea.scrollTop = chatArea.scrollHeight;
        })
        .catch(error => console.error('Error loading messages:', error));
}

function sendMessage() {
    const recipient = document.getElementById('recipient').value;
    const content = document.getElementById('message').value;

    if (!recipient || !content) return;

    fetch('/send_message', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            recipient: recipient,
            content: content
        })
    })
    .then(response => response.json())
    .then(data => {
        if (response.ok) {
            document.getElementById('message').value = '';
            loadMessages();
        } else {
            alert('Error: ' + data.error);
        }
    })
    .catch(error => console.error('Error sending message:', error));
}

function showMnemonic() {
    fetch('/get_mnemonic')
        .then(response => response.json())
        .then(data => {
            if (data.mnemonic) {
                alert('Your mnemonic phrase:\n\n' + data.mnemonic);
            }
        });
}

function showEmojiPicker() {
    const picker = document.createElement('div');
    picker.className = 'emoji-picker';
    picker.innerHTML = emojis.map(emoji =>
        `<button class="emoji-btn" onclick="addEmoji('${emoji}')">${emoji}</button>`
    ).join('');

    document.getElementById('emojiPickerContainer').innerHTML = '';
    document.getElementById('emojiPickerContainer').appendChild(picker);
}

function addEmoji(emoji) {
    const messageInput = document.getElementById('message');
    messageInput.value += emoji;
    messageInput.focus();
}

function toggleEmojiPicker() {
    const container = document.getElementById('emojiPickerContainer');
    if (container.innerHTML.trim() === '') {
        showEmojiPicker();
    } else {
        container.innerHTML = '';
    }
}

function uploadFile() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];

    if (!file) {
        alert('Please select a file first');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    fetch('/upload_file', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (response.ok) {
            // Добавляем ссылку на файл в поле сообщения
            const messageInput = document.getElementById('message');
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

// Auto-refresh messages every 3 seconds
setInterval(loadMessages, 3000);

// Initial load
document.addEventListener('DOMContentLoaded', function() {
    loadMessages();
    showEmojiPicker();
});