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

        // Сохраняем мнемоническую фразу в localStorage
        localStorage.setItem('mnemonicPhrase', state.mnemonicPhrase);

        saveState();

        checkIncomingMessages();
        await getMessages();
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error creating wallet');
    }
}

function generateQRCode(address) {
    const qrCodeContainer = document.getElementById('qr-code');
    qrCodeContainer.innerHTML = ''; // Очищаем контейнер QR-кода перед генерацией нового

    // Используем qrcode.js для генерации QR-кода
    new QRCode(qrCodeContainer, {
        text: address,
        width: 128,
        height: 128
    });
}

function startQrCodeScanner() {
    document.getElementById('qr-reader').style.display = 'block';
    const qrReader = new Html5Qrcode("qr-reader");

    qrReader.start(
        { facingMode: "environment" },
        {
            fps: 10,
            qrbox: 250
        },
        (decodedText) => {
            document.getElementById('recipient').value = decodedText;
            qrReader.stop().then(ignore => {
                document.getElementById('qr-reader').style.display = 'none';
            }).catch(err => console.error(err));
        },
        (errorMessage) => {
            console.warn(`QR code scanning error: ${errorMessage}`);
        }
    ).catch(err => console.error(`Unable to start scanning, error: ${err}`));
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
        data.messages.forEach(message => { // Обращаемся к data.messages
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
        //showAlert('Error fetching messages');
    }
}

async function sendMessage() {
    try {
        const recipient = document.getElementById('recipient').value;
        const content = document.getElementById('content').value;
        const imageInput = document.getElementById('image-input');
        const originalImageInputValue = imageInput.value;
        let imageBase64 = null;

        if (imageInput.files.length > 0) {
            const imageFile = imageInput.files[0];
            imageBase64 = await convertFileToBase64(imageFile);
        }

        const response = await fetch(`/send_message?lang=${state.currentLanguage}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mnemonic_phrase: state.mnemonicPhrase,
                recipient: recipient,
                content: content,
                image: imageBase64
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
            imageInput.value = originalImageInputValue; //
            sendStatus.style.display = 'none';
            document.getElementById('content').value = '';
            imageInput.value = ''; // Очищаем поле загрузки изображения
        }, 2500);

        document.getElementById('content').value = '';
        document.getElementById('image-input').value = '';

        await getMessages();
    } catch (error) {
        console.error('Error:', error);
        //showAlert('Error sending message');
        document.getElementById('content').value = '';
        document.getElementById('image-input').value = '';
    }
}

async function convertFileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = function(event) {
            resolve(event.target.result);
        };
        reader.onerror = function(error) {
            reject(error);
        };
        reader.readAsDataURL(file);
    });
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
        generateQRCode(data.address);

        // Сохраняем мнемоническую фразу в localStorage
        localStorage.setItem('mnemonicPhrase', state.mnemonicPhrase);

        saveState();

        checkIncomingMessages();
        await getMessages();
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error logging in');
    }
}

function displayDialog(messages, recipient) {
    const dialogContainer = document.getElementById('current-dialog');
    dialogContainer.innerHTML = '';

    messages.forEach(message => {
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
            ${image ? `<img src="${image}" class="message-image" alt="src" onclick="openModal('${image}', 'Image from ${shortenAddressForDisplay(sender)}')" />` : ''}
            <div class="message-sender">From: ${shortenAddressForDisplay(sender)}</div>
            <div class="message-recipient">To: ${shortenAddressForDisplay(recipient)}</div>
            <div class="message-timestamp">${formattedTimestamp}</div>
        `;
        dialogContainer.appendChild(messageElement);
    });
}

function highlightActiveDialog(activeButton) {
    const dialogTabs = document.getElementById('dialog-tabs').getElementsByTagName('button');
    for (const button of dialogTabs) {
        button.classList.remove('active');
    }
    activeButton.classList.add('active');
}

function shortenAddressForDisplay(address) {
    return address.slice(0, 6) + '...' + address.slice(-4);
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
    }, 5000); // Проверяем новые сообщения каждые 10 секунд
}

function openModal(src, alt) {
    // Получаем текущий язык
    const currentLanguage = state.currentLanguage;

    // Переводы для кнопки сохранения изображения
    const translations = {
        en: 'Save Image',
        ru: 'Сохранить изображение'
    };

    // Создаем элементы модального окна
    const modal = document.createElement('div');
    modal.classList.add('modal');

    const modalImg = document.createElement('img');
    modalImg.classList.add('modal-content');
    modalImg.src = src;

    const saveButton = document.createElement('button');
    saveButton.textContent = translations[currentLanguage] || 'Save Image'; // Используем перевод в зависимости от языка
    saveButton.classList.add('save-button');
    saveButton.onclick = function() {
        saveImage(src);
    };

    const captionText = document.createElement('div');
    captionText.id = 'caption';
    captionText.innerHTML = alt;

    // Добавляем изображение, кнопку сохранения и текст к модальному окну
    modal.appendChild(modalImg);
    modal.appendChild(saveButton);
    modal.appendChild(captionText);

    // Закрываем модальное окно при клике на него
    modal.onclick = function() {
        document.body.removeChild(modal);
    };

    // Добавляем модальное окно в тело документа
    document.body.appendChild(modal);
}

function saveImage(src) {
    // Создаем ссылку для загрузки изображения
    const link = document.createElement('a');
    link.href = src;
    link.download = 'image'; // Устанавливаем имя файла для загрузки
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}



