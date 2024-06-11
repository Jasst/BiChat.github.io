import { state, saveState, clearState } from './state.js';

export function toggleTheme() {
    document.body.classList.toggle('dark-theme');
    state.theme = document.body.classList.contains('dark-theme') ? 'dark' : 'light';
    saveState();
}

export function showMnemonic() {
    localStorage.setItem('showMnemonic', 'true');

    const walletInfo = document.getElementById('wallet-info');
    walletInfo.style.display = 'block';
    walletInfo.innerHTML = `<label data-translate="address_label">Address:</label>
                            <span id="address-content">${state.userAddress}</span>`;

    const mnemonicDisplay = document.getElementById('mnemonic-display');
    mnemonicDisplay.innerHTML = `<label for="mnemonic-display" data-translate="mnemonic_label">Mnemonic Phrase:</label>
                                 <input type="text" id="mnemonic-display" value="${state.mnemonicPhrase}" readonly>`;
    mnemonicDisplay.style.display = 'block';

    document.getElementById('hide-mnemonic-button').style.display = 'block';
    document.getElementById('show-mnemonic-button').style.display = 'none';
}

export function hideMnemonic() {
    localStorage.setItem('showMnemonic', 'false');

    document.getElementById('wallet-info').style.display = 'none';
    document.getElementById('mnemonic-display').style.display = 'none';

    document.getElementById('hide-mnemonic-button').style.display = 'none';
    document.getElementById('show-mnemonic-button').style.display = 'block';
}

export function handleKeyPress(event) {
    if (event.key === 'Enter') {
        event.preventDefault();
        sendMessage();
    }
}

export function logout() {
    clearState();
    localStorage.removeItem('appState');
    localStorage.removeItem('showMnemonic');
    location.reload();
}
