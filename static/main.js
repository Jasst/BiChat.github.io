import { loadState, saveState, state } from './state.js';
import { createWallet, loginWallet } from './wallet.js';
import { sendMessage } from './sendMessage.js';
import { toggleTheme, showMnemonic, hideMnemonic, handleKeyPress, switchLanguage } from './ui.js';
import { getMessages } from './dialogs.js';

document.addEventListener('DOMContentLoaded', function() {
    if (localStorage.getItem('appState')) {
        loadState();
        sendMessage().then(r => {});
    }

    document.getElementById('create-wallet-button').onclick = createWallet;
    document.getElementById('login-button').onclick = loginWallet;
    document.getElementById('send-button').onclick = sendMessage;
    document.getElementById('language-toggle').onclick = switchLanguage;
    document.getElementById('toggle-theme-button').onclick = toggleTheme;
    document.getElementById('show-mnemonic-button').onclick = showMnemonic;
    document.getElementById('hide-mnemonic-button').onclick = hideMnemonic;
    document.getElementById('logout-button').onclick = () => {
        localStorage.removeItem('appState');
        location.reload();
    };

    document.getElementById('content').addEventListener('keypress', handleKeyPress);

    setInterval(() => {
        getMessages().then(r => {});
    }, 5000);
});
