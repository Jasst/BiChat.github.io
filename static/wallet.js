import { state, saveState } from './state.js';
import { getMessages } from './dialogs.js';

export async function createWallet() {
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
        alert('Error creating wallet');
    }
}

export async function loginWallet() {
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
        alert('Error logging in');
    }
}
