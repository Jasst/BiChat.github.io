function createWallet() {
    fetch('/create_wallet', {
        method: 'POST',
    })
    .then(response => response.json())
    .then(data => {
        const walletInfo = `Mnemonic Phrase: ${data.mnemonic_phrase}<br>Address: ${data.address}`;
        document.getElementById('wallet-info').innerHTML = walletInfo;
        document.getElementById('mnemonic').value = data.mnemonic_phrase;
        document.getElementById('mnemonic-get').value = data.mnemonic_phrase;
        getMessages(); // Автоматически получить сообщения при создании кошелька
    });
}

function sendMessage() {
    const mnemonic = document.getElementById('mnemonic').value;
    const recipient = document.getElementById('recipient').value;
    const content = document.getElementById('content').value;

    fetch('/send_message', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            mnemonic_phrase: mnemonic,
            recipient: recipient,
            content: content,
        }),
    })
    .then(response => response.json())
    .then(data => {
        document.getElementById('send-status').textContent = data.message;
        appendMessage('sent', content);
    });
}

function getMessages() {
    const mnemonic = document.getElementById('mnemonic-get').value;

    fetch('/get_messages', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            mnemonic_phrase: mnemonic,
        }),
    })
    .then(response => response.json())
    .then(data => {
        const messagesDiv = document.getElementById('messages');
        messagesDiv.innerHTML = '';
        const chatBox = document.getElementById('chat-box');
        chatBox.innerHTML = '';

        data.forEach(message => {
            appendMessage('received', message.content);
        });
    });
}

function appendMessage(type, content) {
    const chatBox = document.getElementById('chat-box');
    const messageElement = document.createElement('div');
    messageElement.classList.add('message', type);

    const now = new Date();
    const timeString = now.toLocaleTimeString();
    const dateString = now.toLocaleDateString();

    messageElement.innerHTML = `
        <div class="message-content">${content}</div>
        <div class="message-info">
            <span class="message-time">${timeString}</span>
            <span class="message-date">${dateString}</span>
            <span class="message-status">${type === 'sent' ? 'Sent' : 'Получено'}</span>
        </div>`;

    chatBox.appendChild(messageElement);
    chatBox.scrollTop = chatBox.scrollHeight; // Прокрутка вниз для новых сообщений
}

function toggleTheme() {
    document.body.classList.toggle('dark-theme');
}



// Автоматическое обновление сообщений каждые 10 секунд
setInterval(getMessages, 5000);
