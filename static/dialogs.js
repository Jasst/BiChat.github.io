import { state, saveState } from './state.js';

export async function getMessages(recipientAddress) {
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

        if (recipientAddress) {
            const dialogKey = `${state.userAddress}_${recipientAddress}`;
            if (dialogs.hasOwnProperty(dialogKey)) {
                state.activeDialog = dialogKey;
                displayDialog(dialogs[dialogKey], recipientAddress);
                saveState();
            }
        } else if (!state.activeDialog) {
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
    }
}

export function displayDialog(messages, recipient) {
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

export function copyRecipientAddress(recipient) {
    document.getElementById('recipient').value = recipient;
    getMessages().then(r => {});
}
