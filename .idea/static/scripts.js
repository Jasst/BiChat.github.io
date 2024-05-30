let mnemonicPhrase = '';
let updateMessagesInterval;
let userAddress = '';

function createWallet() {
    fetch('/create_wallet', {
        method: 'POST',
    })
    .then(response => response.json())
    .then(data => {
        mnemonicPhrase = data.mnemonic_phrase;
        userAddress = data.address;
        const walletInfo = `Mnemonic Phrase: ${mnemonicPhrase}<br>Address: ${data.address}`;
        document.getElementById('wallet-info').innerHTML = walletInfo;

        // Вставка мнемонической фразы в соответствующие поля
        document.getElementById('mnemonic').value = mnemonicPhrase;
        document.getElementById('mnemonic-get').value = mnemonicPhrase;

        // Запуск автоматического обновления сообщений
        clearInterval(updateMessagesInterval);
        updateMessagesInterval = setInterval(getMessages, 3000);
    })
    .catch(error => {
        console.error('Error:', error);
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
        const sendStatus = document.getElementById('send-status');
        sendStatus.innerHTML = data.message || 'Message sent successfully';
        sendStatus.style.opacity = 1;

        // Плавное исчезновение сообщения
        setTimeout(() => {
            sendStatus.style.transition = 'opacity 0.5s';
            sendStatus.style.opacity = 0;
        }, 500);

        // Удаление текста после завершения анимации
        setTimeout(() => {
            sendStatus.innerText = '';
            sendStatus.style.transition = '';
            sendStatus.style.opacity = 1;
        }, 1000);

        getMessages();  // Обновление сообщений после отправки
    })
    .catch(error => {
        console.error('Error:', error);
        document.getElementById('send-status').innerText = 'Error sending message';
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
        const chatBox = document.getElementById('chat-box');
        chatBox.innerHTML = '';
        data.forEach(message => {
            const messageElement = document.createElement('div');
            messageElement.classList.add('message');
            if (message.sender === userAddress) {
                messageElement.classList.add('sent');
            } else {
                messageElement.classList.add('received');
            }
            messageElement.innerHTML = `
                <div class="message-content">${message.content}</div>
                <div class="message-sender">From: ${message.sender}</div>
                <!-- <div class="message-timestamp">Timestamp</div> -->
            `;
            chatBox.appendChild(messageElement);
        });
    })
    .catch(error => {
        console.error('Error:', error);
    });
}



function formatTime(date) {
    const hours = date.getHours().toString().padStart(2, '0');
    const minutes = date.getMinutes().toString().padStart(2, '0');
    return `${hours}:${minutes}`;
}





function handleKeyPress(event, callback) {
    if (event.key === 'Enter') {
        event.preventDefault();
        callback();
        if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
            const inputElement = event.target;
            inputElement.style.transition = 'opacity 0.5s';  // Ускоряем анимацию до 0.5 секунды
            setTimeout(() => {
                inputElement.style.opacity = 0;
            }, 500);  // Ускоряем начало исчезновения до 0.5 секунды
            setTimeout(() => {
                inputElement.value = '';
                inputElement.style.opacity = 1;
                inputElement.style.transition = '';
            }, 1000);  // Полное завершение через 1 секунду
        }
    }
}

function toggleTheme() {
    document.body.classList.toggle('dark-theme');
}
