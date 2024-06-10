function switchLanguage() {
    const languageToggle = document.getElementById('language-toggle');
    state.currentLanguage = state.currentLanguage === 'en' ? 'ru' : 'en';
    languageToggle.innerText = state.currentLanguage === 'en' ? 'Switch to Russian' : 'Переключить на английский';

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
            address_label: "Адрес:",
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

    const selectedTranslations = translations[state.currentLanguage];
    const elementsToTranslate = document.querySelectorAll('[data-translate]');
    elementsToTranslate.forEach(element => {
        const translationKey = element.dataset.translate;
        if (translationKey) {
            element.innerText = selectedTranslations[translationKey];
        }
    });

    localStorage.setItem('currentLanguage', state.currentLanguage); // Update stored language
    saveState(); // Save state after changing language
}