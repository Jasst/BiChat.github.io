let state = {
    mnemonicPhrase: '',
    userAddress: '',
    currentLanguage: 'en',
    activeDialog: '',
    theme: 'light'
};

function saveState() {
    localStorage.setItem('appState', JSON.stringify(state));
}

document.addEventListener('DOMContentLoaded', function() {
    
    if (localStorage.getItem('appState')) {
        loadState(); // Загрузка сохраненного состояния
        // Если требуется отправить сообщение после загрузки чатов
        sendMessage().then(r => {});
    }

    // Другие действия при загрузке страницы
    if (localStorage.getItem('currentLanguage')) {
        state.currentLanguage = localStorage.getItem('currentLanguage');
        switchLanguage();
    }
    switchLanguage();
    // Переключаем язык на сохраненный
    // Показываем или скрываем мнемоническую фразу в зависимости от сохраненного состояния
    if (localStorage.getItem('showMnemonic')) {
        if (localStorage.getItem('showMnemonic') === 'true') {
            showMnemonic();
        } else {
            hideMnemonic();
        }
    }
    
    document.getElementById('create-wallet-button').onclick = createWallet;
    document.getElementById('login-button').onclick = loginWallet;
    document.getElementById('send-button').onclick = sendMessage;
    document.getElementById('language-toggle').onclick = switchLanguage;
    document.getElementById('toggle-theme-button').onclick = toggleTheme;
    document.getElementById('show-mnemonic-button').onclick = showMnemonic;
    document.getElementById('hide-mnemonic-button').onclick = hideMnemonic;
    document.getElementById('logout-button').onclick = logout;

    document.getElementById('content').addEventListener('keypress', function(event) {
        handleKeyPress(event, sendMessage);
    });

    checkIncomingMessages();
});

function loadState() {
    const storedState = localStorage.getItem('appState');
    if (storedState) {
        const parsedState = JSON.parse(storedState);
        state = { ...state, ...parsedState };
        if (state.userAddress) {
            document.getElementById('wallet-section').style.display = 'none';
            document.getElementById('create-wallet-container').style.display = 'none';
            document.getElementById('send-message-section').style.display = 'block';
            document.getElementById('chat-section').style.display = 'block';
            document.getElementById('logout-button').style.display = 'block';
        }
    
        if (state.theme === 'dark') {
            toggleTheme();
        }
    }
}

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

function toggleTheme() {
    document.body.classList.toggle('dark-theme');
    state.theme = document.body.classList.contains('dark-theme') ? 'dark' : 'light';
    saveState();
}

async function createWallet() {
    try {
        const response = await fetch(`/create_wallet?lang=${state.currentLanguage}`, { method: 'POST' });
        const data = await response.json();

        state.mnemonicPhrase = data.mnemonic_phrase;
        state.userAddress = data.address;
        document.getElementById('wallet-info').innerHTML = `Address: ${data.address}`;

        document.getElementById('wallet-section').style.display = 'none';
        document.getElementById('mnemonic-login').value = state.mnemonicPhrase;
        document.getElementById('create-wallet-container').style.display = 'none';
        document.getElementById('send-message-section').style.display = 'block';
        document.getElementById('chat-section').style.display = 'block';
        document.getElementById('logout-button').style.display = 'block';

        saveState();

        checkIncomingMessages();
        await getMessages();
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error creating wallet');
    }
}

async function sendMessage() {
    try {
        const recipient = document.getElementById('recipient').value;
        const content = document.getElementById('content').value;

        const response = await fetch(`/send_message?lang=${state.currentLanguage}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mnemonic_phrase: state.mnemonicPhrase,
                recipient: recipient,
                content: content,
            })
        });
        const data = await response.json();

        // Переводы сообщений
        const translations = {
            en: 'Message sent successfully',
            ru: 'Сообщение успешно отправлено'
        };

        // Показываем сообщение об успешной отправке
        const sendStatus = document.getElementById('send-status');
        sendStatus.innerHTML = data.message || translations[state.currentLanguage];
        sendStatus.style.display = 'block';

        // Скрываем сообщение через 3 секунды
        setTimeout(() => {
            sendStatus.style.display = 'none';
        }, 3000);

        document.getElementById('content').value = '';

        await getMessages();
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error sending message');
    }
}
async function loginWallet() {
    try {
        const mnemonic = document.getElementById('mnemonic-login').value;

        const response = await fetch(`/login_wallet?lang=${state.currentLanguage}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mnemonic_phrase: mnemonic })
        });
        const data = await response.json();

        state.mnemonicPhrase = mnemonic;
        state.userAddress = data.address;

        document.getElementById('wallet-section').style.display = 'none';
        document.getElementById('create-wallet-container').style.display = 'none';
        document.getElementById('login-status').innerHTML = data.message;
        document.getElementById('login-wallet-container').style.display = 'none';
        document.getElementById('send-message-section').style.display = 'block';
        document.getElementById('chat-section').style.display = 'block';
        document.getElementById('logout-button').style.display = 'block';

        saveState();

        checkIncomingMessages();
        await getMessages();
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error logging in');
    }
}



async function getMessages(recipientAddress) {
    try {
        const response = await fetch(`/get_messages?lang=${state.currentLanguage}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mnemonic_phrase: state.mnemonicPhrase })
        });
        const data = await response.json();

        const dialogTabs = document.getElementById('dialog-tabs');
        dialogTabs.innerHTML = '';

        const dialogContainer = document.getElementById('current-dialog');
        dialogContainer.innerHTML = '';

        const dialogs = {};
        data.forEach(message => {
            const sender = message.sender;
            const recipient = message.recipient;
            const [currentAddress, otherAddress] = state.userAddress === sender ? [sender, recipient] : [recipient, sender];
            const dialogKey = `${currentAddress}_${otherAddress}`;

            if (!dialogs[dialogKey]) {
                dialogs[dialogKey] = [];
            }

            dialogs[dialogKey].push(message);
        });

        for (const dialogKey in dialogs) {
            if (dialogs.hasOwnProperty(dialogKey)) {
                const dialogMessages = dialogs[dialogKey];
                const [sender, recipient] = dialogKey.split('_');

                const tabButton = document.createElement('button');
                tabButton.textContent = `Dialog with ${recipient}`;
                tabButton.onclick = function () {
                    state.activeDialog = dialogKey;
                    displayDialog(dialogMessages, recipient);
                    copyRecipientAddress(recipient);
                    saveState();
                };
                dialogTabs.appendChild(tabButton);
            }
        }

        // Проверяем, есть ли переданный адрес получателя и отображаем соответствующий диалог
        if (recipientAddress) {
            const dialogKey = `${state.userAddress}_${recipientAddress}`;
            if (dialogs.hasOwnProperty(dialogKey)) {
                state.activeDialog = dialogKey;
                displayDialog(dialogs[dialogKey], recipientAddress);
                saveState();
            }
        } else if (!state.activeDialog) {
            // Если нет активного диалога, выбираем первый диалог
            const firstDialogKey = Object.keys(dialogs)[0];
            if (firstDialogKey) {
                const [sender, recipient] = firstDialogKey.split('_');
                state.activeDialog = firstDialogKey;
                displayDialog(dialogs[firstDialogKey], recipient);
                copyRecipientAddress(recipient);
                saveState();
            }
        } else {
            const [sender, recipient] = state.activeDialog.split('_');
            displayDialog(dialogs[state.activeDialog], recipient);
        }

        if (localStorage.getItem('activeDialog')) {
            state.activeDialog = localStorage.getItem('activeDialog');
            saveState();
        }
    } catch (error) {
        console.error('Error:', error);
        //showAlert('Error fetching messages');
    }
}


function displayDialog(messages, recipient) {
    const dialogContainer = document.getElementById('current-dialog');
    dialogContainer.innerHTML = '';

    messages.forEach(message => {
        const { sender, recipient, content, timestamp } = message;
        const messageElement = document.createElement('div');
        messageElement.classList.add('message');
        if (sender === state.userAddress) {
            messageElement.classList.add('sent');
        } else {
            messageElement.classList.add('received');
        }
        const formattedTimestamp = new Date(timestamp * 1000).toLocaleString();
        messageElement.innerHTML = `
            <div class="message-content">${content}</div>
            <div class="message-sender">From: ${shortenAddressForDisplay(sender)}</div>
            <div class="message-recipient">To: ${shortenAddressForDisplay(recipient)}</div>
            <div class="message-timestamp">${formattedTimestamp}</div>
        `;
        dialogContainer.appendChild(messageElement);
    });
}

function shortenAddressForDisplay(address) {
    return address.slice(0, 6) + '...' + address.slice(-4);
}

function copyRecipientAddress(recipient) {
    document.getElementById('recipient').value = recipient;
    getMessages().then(r => {});
}

function logout() {
    hideMnemonic();
    state.mnemonicPhrase = '';
    state.userAddress = '';
    state.activeDialog = '';
    document.getElementById('wallet-section').style.display = 'block';
    document.getElementById('create-wallet-container').style.display = 'block';
    document.getElementById('send-message-section').style.display = 'none';
    document.getElementById('chat-section').style.display = 'none';
    document.getElementById('logout-button').style.display = 'none';
    localStorage.removeItem('appState');
    localStorage.removeItem('activeDialog'); // Remove active dialog from localStorage
}

function showMnemonic() {
    // Добавляем сохранение состояния кнопки при ее клике
    localStorage.setItem('showMnemonic', 'true');

    const walletInfo = document.getElementById('wallet-info');
    walletInfo.style.display = 'block';
    walletInfo.innerHTML = `<label data-translate="address_label">Address:</label>
                            <span id="address-content">${state.userAddress}</span>`;

    const mnemonicDisplay = document.getElementById('mnemonic-display');
    mnemonicDisplay.innerHTML = `<label for="mnemonic-display" data-translate="mnemonic_label">Mnemonic Phrase:</label>
                                 <input type="text" id="mnemonic-display" value="${state.mnemonicPhrase}" readonly>`;

    const sendMessageSection = document.getElementById('send-message-section');
    sendMessageSection.style.display = 'block';

    document.getElementById('hide-mnemonic-button').style.display = 'block';
    document.getElementById('show-mnemonic-button').style.display = 'none';
}

function hideMnemonic() {
    // Добавляем сохранение состояния кнопки при ее клике
    localStorage.setItem('showMnemonic', 'false');


    const walletInfo = document.getElementById('wallet-info');
    walletInfo.style.display = 'none';

    const mnemonicDisplay = document.getElementById('mnemonic-display');
    mnemonicDisplay.innerHTML = '';

    document.getElementById('hide-mnemonic-button').style.display = 'none';
    document.getElementById('show-mnemonic-button').style.display = 'block';
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
        try {
            getMessages().then(r => {});
        } catch (error) {
            console.error('Error fetching messages:', error);
        }
    }, 5000);
}


