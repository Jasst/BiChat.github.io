        let mnemonicPhrase = '';
        let userAddress = '';
        let currentLanguage = 'en';

        function createWallet() {
            fetch(`/create_wallet?lang=${currentLanguage}`, {
                method: 'POST',
            })
            .then(response => response.json())
            .then(data => {
                mnemonicPhrase = data.mnemonic_phrase;
                userAddress = data.address;
                document.getElementById('wallet-info').innerHTML = `Address: ${data.address}`;

                document.getElementById('wallet-section').style.display = 'none';
                document.getElementById('mnemonic-login').value = mnemonicPhrase;
                document.getElementById('create-wallet-container').style.display = 'none';
                document.getElementById('send-message-section').style.display = 'block';
                document.getElementById('chat-section').style.display = 'block';
                document.getElementById('logout-button').style.display = 'block';

                checkIncomingMessages();
                getMessages();
            })
            .catch(error => {
                console.error('Error:', error);
                showAlert('Error creating wallet');
            });
        }

        function loginWallet() {
            const mnemonic = document.getElementById('mnemonic-login').value;

            fetch(`/login_wallet?lang=${currentLanguage}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ mnemonic_phrase: mnemonic }),
            })
            .then(response => response.json())
            .then(data => {
                mnemonicPhrase = mnemonic;
                userAddress = data.address;

                document.getElementById('wallet-info').innerHTML = `Address: ${data.address}`;

                document.getElementById('wallet-section').style.display = 'none';
                document.getElementById('create-wallet-container').style.display = 'none';
                document.getElementById('login-status').innerHTML = data.message;
                document.getElementById('login-wallet-container').style.display = 'none';
                document.getElementById('send-message-section').style.display = 'block';
                document.getElementById('chat-section').style.display = 'block';
                document.getElementById('logout-button').style.display = 'block';

                checkIncomingMessages();
                getMessages();
            })
            .catch(error => {
                console.error('Error:', error);
                showAlert('Error logging in');
            });
        }

        function sendMessage() {
            const recipient = document.getElementById('recipient').value;
            const content = document.getElementById('content').value;

            fetch(`/send_message?lang=${currentLanguage}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    mnemonic_phrase: mnemonicPhrase,
                    recipient: recipient,
                    content: content,
                }),
            })
            .then(response => response.json())
            .then(data => {
                document.getElementById('send-status').innerHTML = data.message || 'Message sent successfully';
                document.getElementById('content').value = '';
                getMessages();
            })
            .catch(error => {
                console.error('Error:', error);
                showAlert('Error sending message');
            });
        }

        function getMessages() {
            fetch(`/get_messages?lang=${currentLanguage}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ mnemonic_phrase: mnemonicPhrase }),
            })
            .then(response => response.json())
            .then(data => {
                const chatBox = document.getElementById('chat-box');
                chatBox.innerHTML = '';
                data.forEach(message => {
                    const messageElement = document.createElement('div');
                    messageElement.classList.add('message');
                    if (message.sender === userAddress) {
                        messageElement.classList.add('sent');
                    } else {
                        messageElement.classList.add('received');
                    }
                    const timestamp = new Date(message.timestamp * 1000).toLocaleString();
                    messageElement.innerHTML = `
                        <div class="message-content">${message.content}</div>
                        <div class="message-sender">From: ${message.sender}</div>
                        <div class="message-timestamp">${timestamp}</div>
                    `;
                    chatBox.appendChild(messageElement);
                });
            })
            .catch(error => {
                console.error('Error:', error);
                showAlert('Error fetching messages');
            });
        }

        function toggleTheme() {
            document.body.classList.toggle('dark-theme');
        }

        function toggleSettings() {
            const settingsMenu = document.getElementById('settings-menu');
            settingsMenu.style.display = settingsMenu.style.display === 'none' ? 'block' : 'none';
        }

        document.addEventListener('click', function(event) {
            const settingsMenu = document.getElementById('settings-menu');
            const settingsToggle = document.getElementById('settings-toggle');
            if (settingsMenu.style.display === 'block' && !settingsMenu.contains(event.target) && !settingsToggle.contains(event.target)) {
                settingsMenu.style.display = 'none';
            }
        });

        function showAlert(message) {
            alert(message);
        }

        function handleKeyPress(event, callback) {
            if (event.key === 'Enter') {
                event.preventDefault();
                callback();
            }
        }

        function checkIncomingMessages() {
            setInterval(() => {
                getMessages();
            }, 5000); // Check for new messages every 5 seconds
        }

        function logout() {
            location.reload(); // Reload the page on logout
        }

        function showMnemonic() {
            const walletInfo = document.getElementById('wallet-info');
            walletInfo.style.display = 'block';

            const mnemonicDisplay = document.getElementById('mnemonic-display');
            mnemonicDisplay.innerHTML = `<label for="mnemonic-display" data-translate="mnemonic_label">Mnemonic Phrase:</label>
                                          <input type="text" id="mnemonic-display" value="${mnemonicPhrase}" readonly>`;

            const sendMessageSection = document.getElementById('send-message-section');
            sendMessageSection.style.display = 'block';

            document.getElementById('hide-mnemonic-button').style.display = 'block';
            document.getElementById('show-mnemonic-button').style.display = 'none';
        }

        function hideMnemonic() {
            const walletInfo = document.getElementById('wallet-info');
            walletInfo.style.display = 'none';

            const mnemonicDisplay = document.getElementById('mnemonic-display');
            mnemonicDisplay.innerHTML = '';

            document.getElementById('hide-mnemonic-button').style.display = 'none';
            document.getElementById('show-mnemonic-button').style.display = 'block';
        }

        function switchLanguage() {
            const languageToggle = document.getElementById('language-toggle');
            currentLanguage = currentLanguage === 'en' ? 'ru' : 'en';
            languageToggle.innerText = currentLanguage === 'en' ? 'Switch to Russian' : 'Переключить на русский';

            const translations = {
                en: {
                    address_label: "Address:",
                    logout_button: "Logout",
                    show_mnemonic_button: "Show Mnemonic Phrase",
                    hide_mnemonic_button: "Hide Mnemonic",
                    toggle_visibility_button: "Toggle Visibility",
                    title: "Blockchain Messenger",
                    toggle_theme: "Toggle Theme",
                    create_wallet: "Create Wallet",
                    login_button: "Login",
                    send_message: "Send Message",
                    get_messages: "Get Messages",
                    wallet_section: "Create Wallet or Login",
                    send_message_section: "Send Message",
                    chat_section: "Chat",
                    mnemonic_label: "Mnemonic Phrase:",
                    recipient_label: "Recipient Address:",
                    content_label: "Message:",
                    send_button: "Send Message",
                    get_messages_button: "Get Messages"
                },
                ru: {
                    address_label: "Адресс:",
                    logout_button: "Выход",
                    show_mnemonic_button: "Показать мнемоническую фразу",
                    hide_mnemonic_button: "Спрятать мнемоническую фразу",
                    toggle_visibility_button: "Разблокировать/заблокировать",
                    title: "Блокчейн Мессенджер",
                    toggle_theme: "Переключить тему",
                    create_wallet: "Создать кошелек",
                    login_button: "Войти",
                    send_message: "Отправить сообщение",
                    get_messages: "Получить сообщения",
                    wallet_section: "Создать кошелек или Войти",
                    send_message_section: "Отправить сообщение",
                    chat_section: "Чат",
                    mnemonic_label: "Мнемоническая фраза:",
                    recipient_label: "Адрес получателя:",
                    content_label: "Сообщение:",
                    send_button: "Отправить сообщение",
                    get_messages_button: "Получить сообщения"
                }
            };

            const selectedTranslations = translations[currentLanguage];
            const elementsToTranslate = document.querySelectorAll('[data-translate]');
            elementsToTranslate.forEach(element => {
                const translationKey = element.dataset.translate;
                if (translationKey) {
                    element.innerText = selectedTranslations[translationKey];
                }
            });

            // Update the address label separately to retain the address content
            const walletInfoLabel = document.querySelector('#wallet-info [data-translate="address_label"]');
            if (walletInfoLabel) {
                walletInfoLabel.innerText = selectedTranslations.address_label;
            }
        }
