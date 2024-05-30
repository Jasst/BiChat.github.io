async function createWallet() {
    const response = await fetch('/create_wallet', { method: 'POST' });
    const data = await response.json();
    document.getElementById('wallet-info').innerText = `Mnemonic Phrase: ${data.mnemonic_phrase}\nAddress: ${data.address}`;
    localStorage.setItem('mnemonic', data.mnemonic_phrase);
    localStorage.setItem('address', data.address);
}

async function sendMessage() {
    const mnemonic = document.getElementById('mnemonic').value;
    const recipient = document.getElementById('recipient').value;
    const content = document.getElementById('content').value;

    if (!mnemonic || !recipient || !content) {
        document.getElementById('send-status').innerText = 'All fields are required.';
        return;
    }

    const response = await fetch('/send_message', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ mnemonic_phrase: mnemonic, recipient: recipient, content: content })
    });

    const data = await response.json();
    if (response.status === 201) {
        document.getElementById('send-status').innerText = 'Message sent successfully.';
    } else {
        document.getElementById('send-status').innerText = `Error: ${data.error}`;
    }
}

async function getMessages() {
    const mnemonic = document.getElementById('mnemonic-get').value;

    if (!mnemonic) {
        document.getElementById('messages').innerText = 'Mnemonic phrase is required.';
        return;
    }

    const response = await fetch('/get_messages', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ mnemonic_phrase: mnemonic })
    });

    const messages = await response.json();
    let output = '<ul>';
    messages.forEach(message => {
        output += `<li>Sender: ${message.sender}, Content: ${message.content}</li>`;
    });
    output += '</ul>';

    document.getElementById('messages').innerHTML = output;
}

function toggleTheme() {
    // Получаем тело документа
    var body = document.body;
    // Если текущая тема — светлая, то переключаем на темную и наоборот
    if (body.classList.contains('light-theme')) {
        body.classList.remove('light-theme');
        body.classList.add('dark-theme');
    } else {
        body.classList.remove('dark-theme');
        body.classList.add('light-theme');
    }
}
