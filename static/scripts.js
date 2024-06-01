let mnemonicPhrase = '';
let updateMessagesInterval;
let userAddress = '';
let currentLanguage = 'en';

const translations = {
    'en': {

        toggle_visibility_button: "Toggle Visibility",
        title: "Blockchain Messenger",
        toggle_theme: "Toggle Theme",
        create_wallet: "Create Wallet",
        send_message: "Send Message",
        get_messages: "Get Messages",
        wallet_section: "Create Wallet",
        send_message_section: "Send Message",
        chat_section: "Chat",
        mnemonic_label: "Mnemonic Phrase:",
        recipient_label: "Recipient Address:",
        content_label: "Message:",
        send_button: "Send Message",
        get_messages_button: "Get Messages"
    },
    'ru': {
        toggle_visibility_button: "Разблокировать/заблокировать",
        title: "Блокчейн Мессенджер",
        toggle_theme: "Переключить тему",
        create_wallet: "Создать кошелек",
        send_message: "Отправить сообщение",
        get_messages: "Получить сообщения",
        wallet_section: "Создать кошелек",
        send_message_section: "Отправить сообщение",
        chat_section: "Чат",
        mnemonic_label: "Мнемоническая фраза:",
        recipient_label: "Адрес получателя:",
        content_label: "Сообщение:",
        send_button: "Отправить сообщение",
        get_messages_button: "Получить сообщения"
    }
};

// Применяем текущий язык к запросам
function createWallet() {
    fetch(`/create_wallet?lang=${currentLanguage}`, {
        method: 'POST',
    })
    .then(response => response.json())
    .then(data => {
        mnemonicPhrase = data.mnemonic_phrase;
        userAddress = data.address;
        const walletInfo = `Address: ${data.address}`;
        document.getElementById('wallet-info').innerHTML = walletInfo;

        // Вставка мнемонической фразы в соответствующие поля
        document.getElementById('mnemonic').value = mnemonicPhrase;
        document.getElementById('mnemonic-get').value = mnemonicPhrase;

        // Показать и затем автоматически скрыть мнемоническую фразу
        const mnemonicContainer = document.getElementById('mnemonic-container');
        mnemonicContainer.classList.add('visible');
        setTimeout(() => {
            mnemonicContainer.classList.remove('visible');
        }, 1500);  // Скрыть через 5 секунд

        // Запуск автоматического обновления сообщений
        clearInterval(updateMessagesInterval);
        updateMessagesInterval = setInterval(getMessages, 3000);
    })
    .catch(error => {
        console.error('Error:', error);
    });
}


function toggleMnemonicVisibility() {
    const mnemonicContainer = document.getElementById('mnemonic-container');
    mnemonicContainer.classList.toggle('visible');
    const mnemonicVisibilityButton = document.getElementById('toggle-mnemonic-visibility');
    mnemonicVisibilityButton.innerText = mnemonicContainer.classList.contains('visible') ? translations[currentLanguage]["toggle_visibility_button"] : "Toggle Visibility";
}

function sendMessage() {
    const mnemonic = document.getElementById('mnemonic').value;
    const recipient = document.getElementById('recipient').value;
    const content = document.getElementById('content').value;

    fetch(`/send_message?lang=${currentLanguage}`, {
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
        document.getElementById('content').value = ''; // Очистка поля сообщения
    })
    .catch(error => {
        console.error('Error:', error);
        document.getElementById('send-status').innerText = 'Error sending message';
    });
}

function getMessages() {
    const mnemonic = document.getElementById('mnemonic-get').value;

    fetch(`/get_messages?lang=${currentLanguage}`, {
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

// Переводим интерфейс при переключении языка
function switchLanguage() {
    const languageToggle = document.getElementById('language-toggle');
    currentLanguage = currentLanguage === 'en' ? 'ru' : 'en';
    languageToggle.innerText = currentLanguage === 'en' ? 'Переключить на русский' : 'Switch to English';

    const selectedTranslations = translations[currentLanguage];
    const elementsToTranslate = document.querySelectorAll('[data-translate]');
    elementsToTranslate.forEach(element => {
        const translationKey = element.dataset.translate;
        element.innerText = selectedTranslations[translationKey];
    });
}
