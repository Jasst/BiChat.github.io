import { state, saveState } from './state.js';

export async function getMessages() {
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

        data.dialogs.forEach(dialog => {
            const dialogTab = document.createElement('div');
            dialogTab.className = 'dialog-tab';
            dialogTab.innerText = dialog.address;
            dialogTab.onclick = () => {
                state.activeDialog = dialog.address;
                saveState();
                updateCurrentDialog();
            };

            dialogTabs.appendChild(dialogTab);
        });

        updateCurrentDialog();
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error fetching messages');
    }
}

function updateCurrentDialog() {
    const dialogContainer = document.getElementById('current-dialog');
    dialogContainer.innerHTML = '';

    const dialog = state.dialogs.find(d => d.address === state.activeDialog);

    if (dialog) {
        dialog.messages.forEach(message => {
            const messageElement = document.createElement('div');
            messageElement.className = 'message';
            messageElement.innerText = message.content;
            dialogContainer.appendChild(messageElement);
        });
    }
}
