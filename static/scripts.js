document.addEventListener('DOMContentLoaded', function() {
    if (localStorage.getItem('appState')) {
        loadState(); // Load saved state on page load
        // Example: If you want to send a message after loading chats
        sendMessage().then(response => {
            // Handle response if needed
        }).catch(error => {
            console.error('Error sending message:', error);
        });
    }

    // Switch language based on saved state
    if (localStorage.getItem('currentLanguage')) {
        state.currentLanguage = localStorage.getItem('currentLanguage');
        switchLanguage();
    }

    // Show or hide mnemonic phrase based on saved state
    if (localStorage.getItem('showMnemonic')) {
        if (localStorage.getItem('showMnemonic') === 'true') {
            showMnemonic();
        } else {
            hideMnemonic();
        }
    }

    // Event listeners for various UI interactions
    document.getElementById('create-wallet-button').addEventListener('click', createWallet);
    document.getElementById('login-button').addEventListener('click', loginWallet);
    document.getElementById('send-button').addEventListener('click', sendMessage);
    document.getElementById('language-toggle').addEventListener('click', switchLanguage);
    document.getElementById('toggle-theme-button').addEventListener('click', toggleTheme);
    document.getElementById('show-mnemonic-button').addEventListener('click', showMnemonic);
    document.getElementById('hide-mnemonic-button').addEventListener('click', hideMnemonic);
    document.getElementById('logout-button').addEventListener('click', logout);

    // Event listener for handling keyboard events
    document.getElementById('content').addEventListener('keypress', function(event) {
        handleKeyPress(event, sendMessage);
    });

    // Close settings menu if clicked outside
    document.addEventListener('click', function(event) {
        const settingsMenu = document.getElementById('settings-menu');
        const settingsToggle = document.getElementById('settings-toggle');
        if (settingsMenu.style.display === 'block' && !settingsMenu.contains(event.target) && !settingsToggle.contains(event.target)) {
            settingsMenu.style.display = 'none';
        }
    });

    // Check for incoming messages or other periodic checks
    checkIncomingMessages();
});
