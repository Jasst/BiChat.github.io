// Assume there's a function renderQRCode(text) that renders QR code

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

function toggleTheme() {
    document.body.classList.toggle('dark-theme');
    state.theme = document.body.classList.contains('dark-theme') ? 'dark' : 'light';
    saveState();
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
    localStorage.setItem('showMnemonic', 'true');

    const walletInfo = document.getElementById('wallet-info');
    walletInfo.style.display = 'block';
    walletInfo.innerHTML = `<label data-translate="address_label">Address:</label>
                            <span id="address-content">${state.userAddress}</span>`;

    const mnemonicDisplay = document.getElementById('mnemonic-display');
    mnemonicDisplay.innerHTML = `<label for="mnemonic-display" data-translate="mnemonic_label">Mnemonic Phrase:</label>
                                 <input type="text" id="mnemonic-display" value="${state.mnemonicPhrase}" readonly>`;

    // Assuming renderQRCode(text) is the function to render QR code
    renderQRCode(state.userAddress); // Render QR code for the user address

    const sendMessageSection = document.getElementById('send-message-section');
    sendMessageSection.style.display = 'block';

    document.getElementById('hide-mnemonic-button').style.display = 'block';
    document.getElementById('show-mnemonic-button').style.display = 'none';
}

function hideMnemonic() {
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
