
document.addEventListener('DOMContentLoaded', function() {
    
    if (localStorage.getItem('appState')) {
        loadState(); // Загрузка сохраненного состояния
        // Если требуется отправить сообщение после загрузки чатов
        sendMessage().then(r => {});
    }

    // Другие действия при загрузке страницы
    if (localStorage.getItem('currentLanguage')) {
        state.currentLanguage = localStorage.getItem('currentLanguage');
        switchLanguage();
    }
    switchLanguage();
    // Переключаем язык на сохраненный
    // Показываем или скрываем мнемоническую фразу в зависимости от сохраненного состояния
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

document.addEventListener('click', function(event) {
    const settingsMenu = document.getElementById('settings-menu');
    const settingsToggle = document.getElementById('settings-toggle');
    if (settingsMenu.style.display === 'block' && !settingsMenu.contains(event.target) && !settingsToggle.contains(event.target)) {
        settingsMenu.style.display = 'none';
    }
});





