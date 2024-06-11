import { state, saveState } from './state.js';
import { getMessages } from './dialogs.js';

export async function sendMessage() {
    try {
        const recipient = document.getElementById('recipient').value;
        const content = document.getElementById('content').value;

        const response = await fetch(`/send_message?lang=${state.currentLanguage}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mnemonic_phrase: state.mnemonicPhrase,
                recipient: recipient,
                content: content,
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

        await getMessages();
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error sending message');
    }
}
