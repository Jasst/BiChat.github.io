let state = {
    mnemonicPhrase: '',
    userAddress: '',
    currentLanguage: 'ru',
    activeDialog: '',
    theme: 'dark'
};

function saveState() {
    localStorage.setItem('appState', JSON.stringify(state));
    localStorage.setItem('appState', JSON.stringify(state));
    localStorage.setItem('activeDialog', state.activeDialog);
}

function loadState() {
    const storedState = localStorage.getItem('appState');
    if (storedState) {
        const parsedState = JSON.parse(storedState);
        state = { ...state, ...parsedState };

        // Восстанавливаем интерфейс и состояние в зависимости от загруженных данных
        if (state.userAddress) {
            document.getElementById('qr-code').style.display = 'block';
            document.getElementById('wallet-section').style.display = 'none';
            document.getElementById('create-wallet-container').style.display = 'none';
            document.getElementById('send-message-section').style.display = 'block';
            document.getElementById('chat-section').style.display = 'block';
            document.getElementById('logout-button').style.display = 'block';
        }

        // Восстанавливаем тему, если она была сохранена как темная
        if (state.theme === 'dark') {
            toggleTheme();
        }

        // Восстанавливаем последний активный диалог, если он был сохранен
        const lastActiveDialog = localStorage.getItem('lastActiveDialog');
        if (lastActiveDialog) {
            state.activeDialog = lastActiveDialog;
            // Здесь можете выполнить дополнительные действия для восстановления активного диалога
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

function toggleTheme() {
    document.body.classList.toggle('dark-theme');
    state.theme = document.body.classList.contains('dark-theme') ? 'dark' : 'light';
    saveState();
}


function logout() {
    hideMnemonic();

    // Очищаем состояние при выходе
    state.mnemonicPhrase = '';
    state.userAddress = '';
    state.activeDialog = '';

    // Скрываем необходимые элементы интерфейса
    document.getElementById('qr-code').style.display = 'none';
    document.getElementById('wallet-section').style.display = 'block';
    document.getElementById('create-wallet-container').style.display = 'block';
    document.getElementById('send-message-section').style.display = 'none';
    document.getElementById('chat-section').style.display = 'none';
    document.getElementById('logout-button').style.display = 'none';

    // Удаляем сохраненные данные из localStorage
    localStorage.removeItem('appState');
    localStorage.removeItem('activeDialog');
}


function showMnemonic() {
    const qrcode=document.getElementById('qr-code');
    qrcode.style.display='block';

    const Address = state.userAddress;
    generateQRCode(Address);
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
    const qrcode=document.getElementById('qr-code');
    qrcode.style.display='none';
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
