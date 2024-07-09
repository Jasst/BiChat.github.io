document.addEventListener('click', handleClickOutsideSettings);
document.addEventListener('DOMContentLoaded', initializeApp);

document.getElementById('image-input').addEventListener('change', updateFileName);

let state = {
    mnemonicPhrase: '',
    userAddress: '',
    currentLanguage: 'ru',
    activeDialog: '',
    theme: 'dark'
};

function handleClickOutsideSettings(event) {
    const settingsMenu = document.getElementById('settings-menu');
    const settingsToggle = document.getElementById('settings-toggle');
    if (settingsMenu.style.display === 'block' && !settingsMenu.contains(event.target) && !settingsToggle.contains(event.target)) {
        settingsMenu.style.display = 'none';
    }
}

function initializeApp() {
    const savedMnemonic = localStorage.getItem('mnemonicPhrase');
    if (savedMnemonic) {
        document.getElementById('mnemonic-login').value = savedMnemonic;
        loginWallet();
    }

    if (localStorage.getItem('appState')) {
        loadState();
    }

    const currentLanguage = localStorage.getItem('currentLanguage');
    if (currentLanguage) {
        state.currentLanguage = currentLanguage;
        switchLanguage();
    }

    const showMnemonic = localStorage.getItem('showMnemonic');
    if (showMnemonic) {
        showMnemonic === 'true' ? showMnemonic() : hideMnemonic();
    }

    addEventListeners();
    checkIncomingMessages();
}

function addEventListeners() {
    document.getElementById('create-wallet-button').onclick = createWallet;
    document.getElementById('login-button').onclick = loginWallet;
    document.getElementById('send-button').onclick = sendMessage;
    document.getElementById('language-toggle').onclick = switchLanguage;
    document.getElementById('toggle-theme-button').onclick = toggleTheme;
    document.getElementById('show-mnemonic-button').onclick = showMnemonic;
    document.getElementById('hide-mnemonic-button').onclick = hideMnemonic;
    document.getElementById('logout-button').onclick = logout;
    document.getElementById('content').addEventListener('keypress', (event) => handleKeyPress(event, sendMessage));
}

function updateFileName() {
    const filename = this.files[0].name;
    document.querySelector('.btn').textContent = filename;
}

function saveState() {
    localStorage.setItem('appState', JSON.stringify(state));
    localStorage.setItem('activeDialog', state.activeDialog);
}

function loadState() {
    const storedState = localStorage.getItem('appState');
    if (storedState) {
        const parsedState = JSON.parse(storedState);
        state = { ...state, ...parsedState };

        updateUIBasedOnState();
    }
}

function updateUIBasedOnState() {
    if (state.userAddress) {
        toggleVisibility(['qr-code', 'send-message-section', 'chat-section', 'logout-button'], true);
        toggleVisibility(['wallet-section', 'create-wallet-container', 'login-wallet-container'], false);
    }

    if (state.theme === 'dark') {
        toggleTheme();
    }

    const lastActiveDialog = localStorage.getItem('lastActiveDialog');
    if (lastActiveDialog) {
        state.activeDialog = lastActiveDialog;
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

function toggleTheme() {
    document.body.classList.toggle('dark-theme');
    state.theme = document.body.classList.contains('dark-theme') ? 'dark' : 'light';
    saveState();
}

function logout() {
    hideMnemonic();
    state = { ...state, mnemonicPhrase: '', userAddress: '', activeDialog: '' };
    toggleVisibility(['mnemonic-login', 'wallet-section', 'login-wallet-container', 'create-wallet-container'], true);
    toggleVisibility(['qr-code', 'send-message-section', 'chat-section', 'logout-button'], false);
    localStorage.removeItem('mnemonicPhrase');
    localStorage.removeItem('appState');
    localStorage.removeItem('activeDialog');
}

function showMnemonic() {
    toggleVisibility(['qr-code', 'wallet-info', 'send-message-section', 'hide-mnemonic-button'], true);
    toggleVisibility(['show-mnemonic-button'], false);
    localStorage.setItem('showMnemonic', 'true');
    document.getElementById('wallet-info').innerHTML = `<label data-translate="address_label">Address:</label><span id="address-content">${state.userAddress}</span>`;
    document.getElementById('mnemonic-display').innerHTML = `<label for="mnemonic-display" data-translate="mnemonic_label">Mnemonic Phrase:</label><input type="text" id="mnemonic-display" value="${state.mnemonicPhrase}" readonly>`;
    generateQRCode(state.userAddress);
}

function hideMnemonic() {
    toggleVisibility(['qr-code', 'wallet-info', 'mnemonic-display', 'hide-mnemonic-button'], false);
    toggleVisibility(['show-mnemonic-button'], true);
    localStorage.setItem('showMnemonic', 'false');
}

function showAlert(message) {
    alert(message);
}

function switchLanguage() {
    state.currentLanguage = state.currentLanguage === 'en' ? 'ru' : 'en';
    document.getElementById('language-toggle').innerText = state.currentLanguage === 'en' ? 'Switch to Russian' : 'Переключить на английский';

    const translations = {
        en: {
            address_label: "Address:",
            logout_button: "Logout",
            upload_image_button: 'Upload Image',
            show_mnemonic_button: "Show Mnemonic Phrase",
            hide_mnemonic_button: "Hide Mnemonic",
            toggle_visibility_button: "Toggle Visibility",
            title: "Blockchain Messenger",
            toggle_theme: "Toggle Theme",
            create_wallet: "Create Wallet",
            login_button: "Login",
            send_message: "Send Message",
            get_messages: "Get Messages",
            wallet_section: "Create Wallet or Login",
            send_message_section: "Send Message",
            chat_section: "Chat",
            mnemonic_label: "Mnemonic Phrase:",
            recipient_label: "Recipient Address:",
            content_label: "Message:",
            send_button: "Send Message",
            save_image_button: "Save Image",
            get_messages_button: "Get Messages"
        },
        ru: {
            address_label: "Адрес:",
            logout_button: "Выход",
            upload_image_button: 'Загрузить изображение',
            show_mnemonic_button: "Показать мнемоническую фразу",
            hide_mnemonic_button: "Спрятать мнемоническую фразу",
            toggle_visibility_button: "Разблокировать/заблокировать",
            title: "Блокчейн Мессенджер",
            toggle_theme: "Переключить тему",
            create_wallet: "Создать кошелек",
            login_button: "Войти",
            send_message: "Отправить сообщение",
            get_messages: "Получить сообщения",
            wallet_section: "Создать кошелек или Войти",
            send_message_section: "Отправить сообщение",
            chat_section: "Чат",
            mnemonic_label: "Мнемоническая фраза:",
            recipient_label: "Адрес получателя:",
            content_label: "Сообщение:",
            send_button: "Отправить сообщение",
            get_messages_button: "Получить сообщения",
            save_image_button: "Сохранить изображение"
        }
    };

    const selectedTranslations = translations[state.currentLanguage];
    document.querySelectorAll('[data-translate]').forEach(element => {
        const translationKey = element.dataset.translate;
        if (translationKey) {
            element.innerText = selectedTranslations[translationKey];
        }
    });

    localStorage.setItem('currentLanguage', state.currentLanguage);
    saveState();
}

async function fetchData(url, options) {
    try {
        const response = await fetch(url, options);
        return await response.json();
    } catch (error) {
        console.error('Fetch Error:', error);
        throw error;
    }
}

async function createWallet() {
    try {
        const data = await fetchData(`/create_wallet?lang=${state.currentLanguage}`, { method: 'POST' });
        state.mnemonicPhrase = data.mnemonic_phrase;
        state.userAddress = data.address;
        document.getElementById('wallet-info').innerHTML = `Address: ${data.address}`;

        toggleVisibility(['wallet-section', 'create-wallet-container'], false);
        toggleVisibility(['send-message-section', 'chat-section', 'logout-button'], true);
        document.getElementById('mnemonic-login').value = state.mnemonicPhrase;
        localStorage.setItem('mnemonicPhrase', state.mnemonicPhrase);
        saveState();
        checkIncomingMessages();
        await getMessages();
    } catch (error) {
        showAlert('Error creating wallet');
    }
}

async function loginWallet() {
    try {
        const mnemonic = document.getElementById('mnemonic-login').value;
        const data = await fetchData(`/login_wallet?lang=${state.currentLanguage}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mnemonic })
        });
        state.mnemonicPhrase = mnemonic;
        state.userAddress = data.address;

        toggleVisibility(['wallet-section', 'create-wallet-container', 'login-wallet-container'], false);
        toggleVisibility(['send-message-section', 'chat-section', 'logout-button'], true);
        document.getElementById('wallet-info').innerHTML = `Address: ${data.address}`;
        localStorage.setItem('mnemonicPhrase', mnemonic);
        saveState();
        checkIncomingMessages();
        await getMessages();
    } catch (error) {
        showAlert('Error logging in');
    }
}

async function sendMessage() {
    try {
        const recipient = document.getElementById('recipient').value;
        const content = document.getElementById('content').value;
        await fetchData(`/send_message?lang=${state.currentLanguage}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ from: state.userAddress, to: recipient, message: content })
        });
        document.getElementById('content').value = '';
        await getMessages();
    } catch (error) {
        showAlert('Error sending message');
    }
}

async function getMessages() {
    try {
        const messages = await fetchData(`/get_messages?lang=${state.currentLanguage}&address=${state.userAddress}`, { method: 'GET' });
        displayMessages(messages);
    } catch (error) {
        showAlert('Error fetching messages');
    }
}

function displayMessages(messages) {
    const chatSection = document.getElementById('chat-section');
    chatSection.innerHTML = '';
    messages.forEach(message => {
        const messageElement = createMessageElement(message);
        chatSection.appendChild(messageElement);
    });
}

function createMessageElement(message) {
    const { sender, recipient, timestamp, content, image } = message;
    const formattedTimestamp = new Date(timestamp).toLocaleString(state.currentLanguage);
    const messageElement = document.createElement('div');
    messageElement.classList.add('message');
    messageElement.innerHTML = `
        <div class="message-content">${content}</div>
        ${image ? `<img src="${image}" class="message-image" alt="src" onclick="openModal('${image}', 'Image from ${shortenAddressForDisplay(sender)}')" />` : ''}
        <div class="message-sender">From: ${shortenAddressForDisplay(sender)}</div>
        <div class="message-recipient">To: ${shortenAddressForDisplay(recipient)}</div>
        <div class="message-timestamp">${formattedTimestamp}</div>
    `;
    return messageElement;
}

function highlightActiveDialog(activeButton) {
    const dialogTabs = document.getElementById('dialog-tabs').getElementsByTagName('button');
    for (const button of dialogTabs) {
        button.classList.remove('active');
    }
    activeButton.classList.add('active');
}

function shortenAddressForDisplay(address) {
    return `${address.slice(0, 6)}...${address.slice(-4)}`;
}

function copyRecipientAddress(recipient) {
    document.getElementById('recipient').value = recipient;
}

function handleKeyPress(event, callback) {
    if (event.key === 'Enter') {
        event.preventDefault();
        callback();
    }
}

function checkIncomingMessages() {
    setInterval(async () => {
        try {
            await getMessages();
        } catch (error) {
            console.error('Error fetching messages:', error);
        }
    }, 5000);
}

function openModal(src, alt) {
    const modal = createModal(src, alt, state.currentLanguage === 'en' ? 'Save Image' : 'Сохранить изображение');
    modal.onclick = () => document.body.removeChild(modal);
    document.body.appendChild(modal);
}

function createModal(src, alt, saveButtonText) {
    const modal = document.createElement('div');
    modal.classList.add('modal');

    const modalImg = document.createElement('img');
    modalImg.classList.add('modal-content');
    modalImg.src = src;

    const saveButton = document.createElement('button');
    saveButton.textContent = saveButtonText;
    saveButton.classList.add('save-button');
    saveButton.onclick = () => saveImage(src);

    const captionText = document.createElement('div');
    captionText.id = 'caption';
    captionText.innerHTML = alt;

    modal.append(modalImg, saveButton, captionText);
    return modal;
}

function saveImage(src) {
    const link = document.createElement('a');
    link.href = src;
    link.download = 'image';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function toggleVisibility(ids, visible) {
    ids.forEach(id => {
        document.getElementById(id).style.display = visible ? 'block' : 'none';
    });
}
