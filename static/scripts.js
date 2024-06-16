
document.addEventListener('click', function(event) {
    const settingsMenu = document.getElementById('settings-menu');
    const settingsToggle = document.getElementById('settings-toggle');
    if (settingsMenu.style.display === 'block' && !settingsMenu.contains(event.target) && !settingsToggle.contains(event.target)) {
        settingsMenu.style.display = 'none';
    }
});


document.addEventListener('DOMContentLoaded', function() {
    // Автоматический логин при загрузке страницы
    const savedMnemonic = localStorage.getItem('mnemonicPhrase');
    if (savedMnemonic) {
        document.getElementById('mnemonic-login').value = savedMnemonic;
        loginWallet(); // Автоматический логин с использованием сохраненной мнемонической фразы
    }

    if (localStorage.getItem('appState')) {
        loadState(); // Загрузка сохраненного состояния
    }

    // Другие действия при загрузке страницы
    if (localStorage.getItem('currentLanguage')) {
        state.currentLanguage = localStorage.getItem('currentLanguage');
        switchLanguage();
    }
    switchLanguage();

    if (localStorage.getItem('showMnemonic')) {
        if (localStorage.getItem('showMnemonic') === 'true') {
            showMnemonic();
        } else {
            hideMnemonic();
        }
    }

    document.getElementById('create-wallet-button').onclick = createWallet;
    document.getElementById('login-button').onclick = loginWallet;
    document.getElementById('send-button').onclick = sendMessage;
    document.getElementById('language-toggle').onclick = switchLanguage;
    document.getElementById('toggle-theme-button').onclick = toggleTheme;
    document.getElementById('show-mnemonic-button').onclick = showMnemonic;
    document.getElementById('hide-mnemonic-button').onclick = hideMnemonic;
    document.getElementById('logout-button').onclick = logout;

    document.getElementById('content').addEventListener('keypress', function(event) {
        handleKeyPress(event, sendMessage);
    });

    checkIncomingMessages();
});

document.getElementById('image-input').addEventListener('change', function() {
    const filename = this.files[0].name;
    const btnText = document.querySelector('.btn');
    btnText.textContent = filename;
});




