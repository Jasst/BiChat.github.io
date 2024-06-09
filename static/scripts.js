let mnemonicPhrase = '';
let userAddress = '';
let currentLanguage = 'en';

function toggleSettings() {
    const settingsMenu = document.getElementById('settings-menu');
    const hideMnemonicButton = document.getElementById('hide-mnemonic-button');
    const showMnemonicButton = document.getElementById('show-mnemonic-button');
    if (showMnemonicButton.style.display !== 'none') {
        hideMnemonicButton.style.display = 'none';
    }

    settingsMenu.classList.toggle('visible');
    settingsMenu.style.display = settingsMenu.style.display === 'none' ? 'block' : 'none';
}

document.addEventListener('click', function(event) {
    const settingsMenu = document.getElementById('settings-menu');
    const settingsToggle = document.getElementById('settings-toggle');
    if (settingsMenu.style.display === 'block' && !settingsMenu.contains(event.target) && !settingsToggle.contains(event.target)) {
        settingsMenu.style.display = 'none';
    }
});

function createWallet() {
    fetch(`/create_wallet?lang=${currentLanguage}`, {
        method: 'POST',
    })
    .then(response => response.json())
    .then(data => {
        mnemonicPhrase = data.mnemonic_phrase;
        userAddress = data.address;
        document.getElementById('wallet-info').innerHTML = `Address: ${data.address}`;

        document.getElementById('wallet-section').style.display = 'none';
        document.getElementById('mnemonic-login').value = mnemonicPhrase;
        document.getElementById('create-wallet-container').style.display = 'none';
        document.getElementById('send-message-section').style.display = 'block';
        document.getElementById('chat-section').style.display = 'block';
        document.getElementById('logout-button').style.display = 'block';

        checkIncomingMessages();
        getMessages();
    })
    .catch(error => {
        console.error('Error:', error);
        showAlert('Error creating wallet');
    });
}

function loginWallet() {
    const mnemonic = document.getElementById('mnemonic-login').value;

    fetch(`/login_wallet?lang=${currentLanguage}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ mnemonic_phrase: mnemonic }),
    })
    .then(response => response.json())
    .then(data => {
        mnemonicPhrase = mnemonic;
        userAddress = data.address;

        document.getElementById('wallet-section').style.display = 'none';
        document.getElementById('create-wallet-container').style.display = 'none';
        document.getElementById('login-status').innerHTML = data.message;
        document.getElementById('login-wallet-container').style.display = 'none';
        document.getElementById('send-message-section').style.display = 'block';
        document.getElementById('chat-section').style.display = 'block';
        document.getElementById('logout-button').style.display = 'block';

        checkIncomingMessages();
        getMessages();
    })
    .catch(error => {
        console.error('Error:', error);
        showAlert('Error logging in');
    });
}

function sendMessage() {
    const recipient = document.getElementById('recipient').value;
    const content = document.getElementById('content').value;

    fetch(`/send_message?lang=${currentLanguage}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            mnemonic_phrase: mnemonicPhrase,
            recipient: recipient,
            content: content,
        }),
    })
    .then(response => response.json())
    .then(data => {
        document.getElementById('send-status').innerHTML = data.message || 'Message sent successfully';
        document.getElementById('content').value = '';
        getMessages();
    })
    .catch(error => {
        console.error('Error:', error);
        showAlert('Error sending message');
    });
}

function getMessages() {
    fetch(`/get_messages?lang=${currentLanguage}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ mnemonic_phrase: mnemonicPhrase }),
    })
    .then(response => response.json())
    .then(data => {
        const dialogTabs = document.getElementById('dialog-tabs');
        dialogTabs.innerHTML = '';

        const dialogContainer = document.getElementById('current-dialog');
        dialogContainer.innerHTML = '';

        // Создаем объект для группировки сообщений по диалогам
        const dialogs = {};
        data.forEach(message => {
            const sender = message.sender;
            const recipient = message.recipient;

            // Определяем адреса отправителя и получателя для данного пользователя
            const [currentAddress, otherAddress] = userAddress === sender ? [sender, recipient] : [recipient, sender];

            // Определяем ключ для группировки сообщений
            const dialogKey = currentAddress + "_" + otherAddress;

            // Проверяем, есть ли диалог между отправителем и получателем
            if (!dialogs[dialogKey]) {
                dialogs[dialogKey] = [];
            }

            // Добавляем сообщение в соответствующий диалог
            dialogs[dialogKey].push(message);
        });

        // Создаем вкладки для каждого диалога
        for (const dialogKey in dialogs) {
            if (dialogs.hasOwnProperty(dialogKey)) {
                const dialogMessages = dialogs[dialogKey];
                const [sender, recipient] = dialogKey.split('_');

                const tabButton = document.createElement('button');
                tabButton.textContent = `Dialog with ${recipient}`;
                tabButton.onclick = function() {
                    displayDialog(dialogMessages, recipient);
                };
                dialogTabs.appendChild(tabButton);
            }
        }

        // При первой загрузке отображаем первый диалог, если он есть
        const firstDialogKey = Object.keys(dialogs)[0];
        if (firstDialogKey) {
            const [sender, recipient] = firstDialogKey.split('_');
            displayDialog(dialogs[firstDialogKey], recipient);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showAlert('Error fetching messages');
    });
}

function displayDialog(messages, recipient) {
    const dialogContainer = document.getElementById('current-dialog');
    dialogContainer.innerHTML = '';

    messages.forEach(message => {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message');
        if (message.sender === userAddress) {
            messageElement.classList.add('sent');
        } else {
            messageElement.classList.add('received');
        }
        const timestamp = new Date(message.timestamp * 1000).toLocaleString();
        messageElement.innerHTML = `
            <div class="message-content">${message.content}</div>
            <div class="message-sender">From: ${message.sender}</div>
            <div class="message-timestamp">${timestamp}</div>
        `;
        dialogContainer.appendChild(messageElement);
    });

    // Копируем адрес получателя в поле отправителя
    copyRecipientAddress(recipient);
}

function copyRecipientAddress(recipient) {
    document.getElementById('recipient').value = recipient;
}

function toggleTheme() {
    document.body.classList.toggle('dark-theme');
}

function showAlert(message) {
    alert(message);
}

function handleKeyPress(event, callback) {
    if (event.key === 'Enter') {
        event.preventDefault();
        callback();
    }
}

function checkIncomingMessages() {
    setInterval(() => {
        getMessages();
    }, 5000); // Check for new messages every 5 seconds
}

function logout() {
    location.reload();
}

function showMnemonic() {
    const walletInfo = document.getElementById('wallet-info');
    walletInfo.style.display = 'block';
    walletInfo.innerHTML = `<label data-translate="address_label">Address:</label>
                            <span id="address-content">${userAddress}</span>`;

    const mnemonicDisplay = document.getElementById('mnemonic-display');
    mnemonicDisplay.innerHTML = `<label for="mnemonic-display" data-translate="mnemonic_label">Mnemonic Phrase:</label>
                                 <input type="text" id="mnemonic-display" value="${mnemonicPhrase}" readonly>`;

    const sendMessageSection = document.getElementById('send-message-section');
    sendMessageSection.style.display = 'block';

    document.getElementById('hide-mnemonic-button').style.display = 'block';
    document.getElementById('show-mnemonic-button').style.display = 'none';
}

function hideMnemonic() {
    const walletInfo = document.getElementById('wallet-info');
    walletInfo.style.display = 'none';

    const mnemonicDisplay = document.getElementById('mnemonic-display');
    mnemonicDisplay.innerHTML = '';

    document.getElementById('hide-mnemonic-button').style.display = 'none';
    document.getElementById('show-mnemonic-button').style.display = 'block';
}

function switchLanguage() {
    const languageToggle = document.getElementById('language-toggle');
    currentLanguage = currentLanguage === 'en' ? 'ru' : 'en';
    languageToggle.innerText = currentLanguage === 'en' ? 'Switch to Russian' : 'Переключить на английский';

    const translations = {
        en: {
            address_label
