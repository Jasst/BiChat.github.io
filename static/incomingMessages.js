import { getMessages } from './dialogs.js';

export function checkIncomingMessages() {
    setInterval(() => {
        try {
            getMessages().then(r => {});
        } catch (error) {
            console.error('Error fetching messages:', error);
        }
    }, 5000);
}
