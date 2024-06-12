import pako from 'pako';

async function sendMessage() {
    try {
        const recipient = document.getElementById('recipient').value;
        const content = document.getElementById('content').value;
        const imageInput = document.getElementById('image-input');
        let compressedImageBase64 = null;

        if (imageInput.files.length > 0) {
            const imageFile = imageInput.files[0];
            const imageArrayBuffer = await fileToArrayBuffer(imageFile);
            const compressedImage = pako.deflate(imageArrayBuffer);
            compressedImageBase64 = arrayBufferToBase64(compressedImage);
        }

        const response = await fetch(`/send_message?lang=${state.currentLanguage}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mnemonic_phrase: state.mnemonicPhrase,
                recipient: recipient,
                content: content,
                image: compressedImageBase64
            })
        });
        const data = await response.json();

        const translations = {
            en: 'Message sent successfully',
            ru: 'Сообщение успешно отправлено'
        };

        const sendStatus = document.getElementById('send-status');
        sendStatus.innerHTML = data.message || translations[state.currentLanguage];
        sendStatus.style.display = 'block';

        setTimeout(() => {
            sendStatus.style.display = 'none';
        }, 3000);

        document.getElementById('content').value = '';
        document.getElementById('image-input').value = '';

        await getMessages();
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error sending message');
    }
}

function fileToArrayBuffer(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = function(event) {
            resolve(event.target.result);
        };
        reader.onerror = function(error) {
            reject(error);
        };
        reader.readAsArrayBuffer(file);
    });
}

function arrayBufferToBase64(buffer) {
    let binary = '';
    const bytes = new Uint8Array(buffer);
    const len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary);
}

function base64ToArrayBuffer(base64) {
    const binaryString = window.atob(base64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes.buffer;
}

async function displayDialog(messages, recipient) {
    const dialogContainer = document.getElementById('current-dialog');
    dialogContainer.innerHTML = '';

    for (const message of messages) {
        const { sender, recipient, content, timestamp, image } = message;
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
            ${image ? `<img src="${await decompressImage(image)}" class="message-image" alt="Image" />` : ''}
            <div class="message-sender">From: ${shortenAddressForDisplay(sender)}</div>
            <div class="message-recipient">To: ${shortenAddressForDisplay(recipient)}</div>
            <div class="message-timestamp">${formattedTimestamp}</div>
        `;
        dialogContainer.appendChild(messageElement);
    }
}

async function decompressImage(base64) {
    const compressedArrayBuffer = base64ToArrayBuffer(base64);
    const decompressedArrayBuffer = pako.inflate(compressedArrayBuffer);
    return `data:image/png;base64,${arrayBufferToBase64(decompressedArrayBuffer)}`;
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
                    highlightActiveDialog(tabButton); // Подсветка активного диалога
                };
                dialogTabs.appendChild(tabButton);

                // Подсветка активного диалога при инициализации
                if (dialogKey === state.activeDialog) {
                    highlightActiveDialog(tabButton);
                }
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
        showAlert('Error fetching messages');
    }
}

